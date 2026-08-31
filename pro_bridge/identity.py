"""Request identity helpers for named ChatGPT sessions."""

from __future__ import annotations

from typing import Any


def profile_from_context(ctx: Any, header_name: str) -> str | None:
    """Read a non-empty profile identity from the current MCP HTTP request.

    FastMCP injects ``Context`` into tool functions without exposing it to the
    model. On Streamable HTTP, ``ctx.request_context.request`` is the Starlette
    request that carried the MCP call, so client-provided identity headers are
    available here. On stdio or older/partial contexts this safely returns None.
    """
    try:
        request = ctx.request_context.request
        headers = getattr(request, "headers", None)
        if headers is None:
            return None
        value = headers.get(header_name)
    except Exception:
        return None

    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def resolve_session(
    explicit_session: str | None,
    ctx: Any,
    header_name: str,
) -> tuple[str | None, str]:
    """Resolve the effective session, preferring transport identity.

    A profile identity supplied by Hermes in the configured HTTP header always
    wins. This prevents an LLM from accidentally routing itself into another
    agent's ChatGPT thread by inventing or misremembering ``session``.

    The explicit tool argument remains a fallback for non-Hermes clients and
    manual testing where no identity header is present.
    """
    profile = profile_from_context(ctx, header_name)
    if profile:
        return profile, "header"

    if isinstance(explicit_session, str):
        explicit_session = explicit_session.strip()
        if explicit_session:
            return explicit_session, "argument"

    return None, "none"
