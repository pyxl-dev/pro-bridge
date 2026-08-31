"""MCP server exposing an authenticated ChatGPT web session as tools."""
import asyncio
import logging

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import config
from .browser_guard import launch_local_browser
from .chatgpt import ChatGPTDriver
from .conversations import resolve_conversation_reference
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
_browser_guard_lock = asyncio.Lock()


async def _ensure_browser_available() -> None:
    """Best-effort auto-start for the dedicated local CDP browser."""
    if not config.AUTO_START_BROWSER:
        return

    async with _browser_guard_lock:
        available = await launch_local_browser(
            config.CDP_URL,
            timeout=config.BROWSER_START_TIMEOUT,
            custom_command=config.BROWSER_START_COMMAND or None,
        )
        if available:
            return

        # A False result means the configured CDP endpoint is remote/non-local.
        # Never attempt to launch a local browser for a remote browser config.
        log.debug("Browser auto-start skipped for non-local CDP URL %s", config.CDP_URL)


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
    session: str | None = None,
    conversation_id: str | None = None,
    conversation_url: str | None = None,
) -> dict:
    """Ask ChatGPT through the logged-in web UI and return the complete reply.

    With Hermes, caller identity is normally automatic: configure the MCP server
    with an identity header sourced from the active Hermes profile. The bridge
    reads that header and persistently maps the profile name to its own ChatGPT
    conversation, so each Hermes profile keeps independent context without the
    model having to pass a session name.

    To hand an existing ChatGPT thread to an agent, pass its normal authenticated
    URL as `conversation_url`, for example
    `https://chatgpt.com/c/<conversation-id>`. The bridge extracts the UUID and,
    after a successful answer, rebinds the calling Hermes profile to that thread.
    Later calls from that profile continue it automatically without the URL.

    `conversation_id` remains available as the lower-level equivalent. If both
    `conversation_id` and `conversation_url` are supplied, they must identify the
    same thread or the call fails explicitly.

    `session` is only a fallback for clients that do not send the identity
    header. When the header is present it wins, preventing an agent from routing
    itself into another profile's thread by passing the wrong session value.

    If no profile mapping, conversation_id, or conversation_url is available,
    the call starts a new ChatGPT conversation.

    If the dedicated local browser was closed, the bridge attempts to relaunch
    it automatically before performing the call.

    Returns {text, model, conversation_id, session, session_source,
    conversation_source}.
    """
    effective_session, session_source = _effective_session(session, ctx)
    explicit_conversation, explicit_source = resolve_conversation_reference(
        conversation_id,
        conversation_url,
    )

    await _ensure_browser_available()

    async with _session_lock:
        mapped_conversation = None
        if effective_session:
            mapped_conversation = _sessions.get(effective_session)

        resolved_conversation = explicit_conversation or mapped_conversation
        if explicit_conversation:
            conversation_source = explicit_source
        elif mapped_conversation:
            conversation_source = "mapped"
        else:
            conversation_source = "new"

        log.info(
            "chatgpt_ask: %d chars, session=%s source=%s conv=%s conv_source=%s",
            len(prompt),
            effective_session,
            session_source,
            resolved_conversation,
            conversation_source,
        )

        result = await _driver.ask(prompt, resolved_conversation)

        if effective_session:
            _sessions.set(effective_session, result["conversation_id"])

        result["session"] = effective_session
        result["session_source"] = session_source
        result["conversation_source"] = conversation_source
        log.info(
            "chatgpt_ask done: model=%s session=%s conv=%s, %d chars",
            result.get("model"),
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
    await _ensure_browser_available()

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
    await _ensure_browser_available()

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
        "(token=%s, model_slug=%s, sessions=%s, identity_header=%s, "
        "browser_autostart=%s)",
        config.HOST,
        config.PORT,
        "set" if config.TOKEN else "NONE",
        config.MODEL_SLUG or "default/current",
        config.SESSION_FILE,
        config.IDENTITY_HEADER,
        "on" if config.AUTO_START_BROWSER else "off",
    )
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
