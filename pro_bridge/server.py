"""MCP server exposing an authenticated ChatGPT web session as tools."""
import asyncio
import logging

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import config
from .chatgpt import ChatGPTDriver
from .identity import resolve_session
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


def _effective_session(session: str | None, ctx: Context) -> tuple[str | None, str]:
    """Resolve caller identity from Hermes HTTP header, then argument fallback."""
    resolved, source = resolve_session(session, ctx, config.IDENTITY_HEADER)
    if source == "header" and session and session.strip() != resolved:
        log.warning(
            "Ignoring explicit session=%r because %s identifies caller as %r",
            session,
            config.IDENTITY_HEADER,
            resolved,
        )
    return resolved, source


@mcp.tool()
async def chatgpt_ask(
    prompt: str,
    ctx: Context,
    files: list[str] | None = None,
    session: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Ask ChatGPT through the logged-in web UI and return the complete reply.

    `files` optionally attaches local files to the SAME ChatGPT message as the
    prompt. Supply filesystem paths visible to the machine running pro-bridge;
    absolute paths are strongly recommended. The bridge validates each path,
    uploads all files through ChatGPT's composer, waits for them to become ready,
    then sends the prompt. The result includes `attached_files` with the uploaded
    basenames.

    With Hermes, caller identity is normally automatic: configure the MCP server
    with an identity header sourced from the active Hermes profile. The bridge
    reads that header and persistently maps the profile name to its own ChatGPT
    conversation, so each Hermes profile keeps independent context without the
    model having to pass a session name.

    `session` is only a fallback for clients that do not send the identity
    header. When the header is present it wins, preventing an agent from routing
    itself into another profile's thread by passing the wrong session value.

    `conversation_id` remains an advanced/manual override. When a named profile
    or fallback session is resolved, a successful explicit continuation rebinds
    that session to the resulting conversation id.

    If no profile header, session, or conversation_id is available, the call is
    stateless and starts a new ChatGPT conversation.

    Returns {text, model, conversation_id, attached_files, session, session_source}.
    """
    effective_session, session_source = _effective_session(session, ctx)
    file_count = len(files or [])

    async with _session_lock:
        mapped_conversation = None
        if effective_session:
            mapped_conversation = _sessions.get(effective_session)

        resolved_conversation = conversation_id or mapped_conversation
        log.info(
            "chatgpt_ask: %d chars, files=%d, session=%s source=%s conv=%s%s",
            len(prompt),
            file_count,
            effective_session,
            session_source,
            resolved_conversation,
            " (mapped)" if mapped_conversation and not conversation_id else "",
        )

        result = await _driver.ask(prompt, resolved_conversation, files=files)

        if effective_session:
            _sessions.set(effective_session, result["conversation_id"])

        result["session"] = effective_session
        result["session_source"] = session_source
        log.info(
            "chatgpt_ask done: model=%s files=%d session=%s conv=%s, %d chars",
            result.get("model"),
            len(result.get("attached_files", [])),
            effective_session,
            result.get("conversation_id"),
            len(result.get("text", "")),
        )
        return result


@mcp.tool()
async def chatgpt_new_chat(
    ctx: Context,
    session: str | None = None,
) -> dict:
    """Detach the caller's current ChatGPT thread so the next ask starts fresh.

    Hermes profiles are identified automatically from the configured identity
    header. Therefore a normal Hermes caller can invoke this tool with no
    arguments and only its own profile mapping is reset.

    `session` is a fallback for clients without an identity header. The old
    ChatGPT thread is not deleted; it is simply detached from the resolved
    session. The next chatgpt_ask starts a new conversation and stores its id.
    """
    effective_session, session_source = _effective_session(session, ctx)

    async with _session_lock:
        previous = _sessions.reset(effective_session) if effective_session else None
        result = await _driver.new_chat()
        result.update(
            {
                "session": effective_session,
                "session_source": session_source,
                "previous_conversation_id": previous,
                "reset": bool(effective_session),
            }
        )
        log.info(
            "chatgpt_new_chat: session=%s source=%s previous=%s",
            effective_session,
            session_source,
            previous,
        )
        return result


@mcp.tool()
async def chatgpt_status(
    ctx: Context,
    session: str | None = None,
) -> dict:
    """Return bridge status and the caller profile's mapped ChatGPT thread."""
    effective_session, session_source = _effective_session(session, ctx)

    async with _session_lock:
        result = await _driver.status()
        result["session"] = effective_session
        result["session_source"] = session_source
        result["session_conversation_id"] = (
            _sessions.get(effective_session) if effective_session else None
        )
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
    by a bearer token. All other request headers, including the Hermes profile
    identity header, are preserved unchanged.
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
        "(token=%s, model_slug=%s, sessions=%s, identity_header=%s)",
        config.HOST,
        config.PORT,
        "set" if config.TOKEN else "NONE",
        config.MODEL_SLUG or "default/current",
        config.SESSION_FILE,
        config.IDENTITY_HEADER,
    )
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
