"""MCP server exposing an authenticated ChatGPT web session as tools."""
import logging

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from . import config
from .chatgpt import ChatGPTDriver

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


@mcp.tool()
async def chatgpt_ask(prompt: str, conversation_id: str | None = None) -> dict:
    """Ask ChatGPT through the logged-in web UI and return the complete reply.

    Omit conversation_id to start a NEW ChatGPT conversation.
    Pass a conversation_id returned by an earlier call to continue that exact
    thread. Calls are serialized so multiple agents cannot interleave browser
    input.

    Returns {text, model, conversation_id}.
    """
    log.info("chatgpt_ask: %d chars, conv=%s", len(prompt), conversation_id)
    result = await _driver.ask(prompt, conversation_id)
    log.info(
        "chatgpt_ask done: model=%s conv=%s, %d chars",
        result.get("model"),
        result.get("conversation_id"),
        len(result.get("text", "")),
    )
    return result


@mcp.tool()
async def chatgpt_new_chat() -> dict:
    """Navigate the bridge browser to a fresh ChatGPT conversation."""
    return await _driver.new_chat()


@mcp.tool()
async def chatgpt_status() -> dict:
    """Return bridge connection, current URL, model (if known), and chat id."""
    return await _driver.status()


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
        "ChatGPT web MCP listening on http://%s:%s/mcp (token=%s, model_slug=%s)",
        config.HOST,
        config.PORT,
        "set" if config.TOKEN else "NONE",
        config.MODEL_SLUG or "default/current",
    )
    uvicorn.run(app, host=config.HOST, port=config.PORT)


if __name__ == "__main__":
    main()
