"""MCP server exposing an authenticated ChatGPT web session as tools."""
import asyncio
import logging

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import config
from .chatgpt import ChatGPTDriver
from .sessions import SessionStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pro_bridge")

# MCP streamable-HTTP has DNS-rebinding protection that only allows localhost
# Host headers. For explicitly configured remote/private-network deployments,
# preserve the upstream compatibility fallback.
try:
    from mcp.server.transport_security import TransportSecuritySettings

    _SEC = TransportSecuritySettings(enable_dns_rebinding_protection=False)
except Exception:
    _SEC = None

try:
    mcp = (
        FastMCP("chatgpt-web", transport_security=_SEC)
        if _SEC
        else FastMCP("chatgpt-web")
    )
except TypeError:
    mcp = FastMCP("chatgpt-web")

_driver = ChatGPTDriver()
_sessions = SessionStore(config.SESSION_FILE)

# Session lookup + browser ask + mapping update must be one logical operation.
# The browser driver already serializes its own work; this outer lock prevents a
# concurrent reset/rebind from racing between lookup and persistence.
_session_lock = asyncio.Lock()


@mcp.tool()
async def chatgpt_ask(
    prompt: str,
    session: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Ask ChatGPT through the logged-in web UI and return the complete reply.

    Recommended multi-agent usage: pass a stable `session` name for the caller
    (for example the Hermes profile name). The bridge remembers the ChatGPT
    conversation id for that session and automatically resumes it on later
    calls. If the session has no mapping yet, a new ChatGPT conversation is
    created and then persisted.

    `conversation_id` remains available as an advanced/manual override. If both
    `session` and `conversation_id` are supplied, that exact conversation is
    continued and the session is rebound to it after a successful answer.

    If neither `session` nor `conversation_id` is supplied, every call starts a
    new ChatGPT conversation (legacy/stateless behavior).

    Returns {text, model, conversation_id, session}.
    """
    async with _session_lock:
        mapped_conversation = None
        if session:
            mapped_conversation = _sessions.get(session)

        resolved_conversation = conversation_id or mapped_conversation
        log.info(
            "chatgpt_ask: %d chars, session=%s, conv=%s%s",
            len(prompt),
            session,
            resolved_conversation,
            " (mapped)" if mapped_conversation and not conversation_id else "",
        )

        result = await _driver.ask(prompt, resolved_conversation)

        if session:
            _sessions.set(session, result["conversation_id"])

        result["session"] = session
        log.info(
            "chatgpt_ask done: model=%s session=%s conv=%s, %d chars",
            result.get("model"),
            session,
            result.get("conversation_id"),
            len(result.get("text", "")),
        )
        return result


@mcp.tool()
async def chatgpt_new_chat(session: str | None = None) -> dict:
    """Start fresh, optionally resetting one named agent session.

    Pass the caller's stable `session` name to forget its previous ChatGPT
    conversation. The old ChatGPT thread is not deleted; it is simply detached
    from this session. The next `chatgpt_ask(..., session=...)` starts a new
    conversation and stores its new id automatically.

    With no session, this only navigates the bridge browser to ChatGPT's generic
    new-chat page and does not alter any named mappings.
    """
    async with _session_lock:
        previous = _sessions.reset(session) if session else None
        result = await _driver.new_chat()
        result.update(
            {
                "session": session,
                "previous_conversation_id": previous,
                "reset": bool(session),
            }
        )
        log.info(
            "chatgpt_new_chat: session=%s previous=%s",
            session,
            previous,
        )
        return result


@mcp.tool()
async def chatgpt_status(session: str | None = None) -> dict:
    """Return bridge status and, optionally, one named session's mapped chat id."""
    async with _session_lock:
        result = await _driver.status()
        result["session"] = session
        result["session_conversation_id"] = _sessions.get(session) if session else None
        result["session_count"] = len(_sessions.snapshot())
        return result


class TokenAuth(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if (
            config.TOKEN
            and request.headers.get("authorization", "")
            != f"Bearer {config.TOKEN}"
        ):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


class RewriteHost:
    """Present a localhost Host header to the inner MCP app.

    This keeps compatibility with MCP SDK versions whose DNS-rebinding guard
    does not accept private-network hostnames even when the bridge is protected
    by a bearer token.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            host = f"localhost:{config.PORT}".encode()
            headers = [
                (key, value)
                for (key, value) in scope["headers"]
                if key.lower() != b"host"
            ]
            headers.append((b"host", host))
            scope = dict(scope, headers=headers)
        await self.app(scope, receive, send)


def main():
    app = mcp.streamable_http_app()
    app.add_middleware(TokenAuth)
    app = RewriteHost(app)
    log.info(
        "ChatGPT web MCP listening on http://%s:%s/mcp "
        "(token=%s, model_slug=%s, sessions=%s)",
        config.HOST,
        config.PORT,
        "set" if config.TOKEN else "NONE",
        config.MODEL_SLUG or "default/current",
        config.SESSION_FILE,
    )
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
