"""Helpers for resolving ChatGPT conversation references."""
from __future__ import annotations

import re
from urllib.parse import urlparse

CONVERSATION_ID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_ALLOWED_HOSTS = {"chatgpt.com", "www.chatgpt.com", "chat.openai.com"}


def normalize_conversation_id(conversation_id: str | None) -> str | None:
    """Validate and normalize a ChatGPT conversation UUID."""
    if conversation_id is None:
        return None
    value = conversation_id.strip()
    if not value:
        raise ValueError("conversation_id must not be blank")
    if not CONVERSATION_ID_RE.fullmatch(value):
        raise ValueError("conversation_id must be a ChatGPT conversation UUID")
    return value.lower()


def conversation_id_from_url(conversation_url: str | None) -> str | None:
    """Extract a conversation UUID from a normal authenticated ChatGPT chat URL."""
    if conversation_url is None:
        return None

    value = conversation_url.strip()
    if not value:
        raise ValueError("conversation_url must not be blank")

    parsed = urlparse(value)
    if parsed.scheme.lower() != "https":
        raise ValueError("conversation_url must use https")

    host = (parsed.hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise ValueError(
            "conversation_url must point to chatgpt.com or chat.openai.com"
        )

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) != 2 or parts[0] != "c":
        raise ValueError(
            "conversation_url must be a normal ChatGPT /c/<conversation_id> URL"
        )

    return normalize_conversation_id(parts[1])


def resolve_conversation_reference(
    conversation_id: str | None,
    conversation_url: str | None,
) -> tuple[str | None, str]:
    """Resolve explicit id/url input into one conversation id and source label."""
    explicit_id = normalize_conversation_id(conversation_id)
    url_id = conversation_id_from_url(conversation_url)

    if explicit_id and url_id and explicit_id != url_id:
        raise ValueError(
            "conversation_id and conversation_url refer to different ChatGPT threads"
        )

    if url_id:
        return url_id, "url"
    if explicit_id:
        return explicit_id, "id"
    return None, "mapped"
