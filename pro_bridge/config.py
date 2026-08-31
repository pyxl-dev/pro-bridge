"""Configuration for pro-bridge, read from environment / a local .env file."""
import os


def _load_dotenv():
    # Minimal .env loader so we don't add a dependency.
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _env(primary, legacy, default=""):
    """Read the new generic name first, then the legacy pro-bridge name."""
    return os.environ.get(primary, os.environ.get(legacy, default))


_load_dotenv()

# CDP endpoint of the debug browser — local to this machine, never exposed.
CDP_URL = _env(
    "CHATGPT_BRIDGE_CDP_URL",
    "PRO_BRIDGE_CDP_URL",
    "http://localhost:9222",
)

# Where the MCP server listens.
HOST = _env("CHATGPT_BRIDGE_HOST", "PRO_BRIDGE_HOST", "127.0.0.1")
PORT = int(_env("CHATGPT_BRIDGE_PORT", "PRO_BRIDGE_PORT", "8765"))

# Shared secret. If set, callers must send Authorization: Bearer <TOKEN>.
TOKEN = _env("CHATGPT_BRIDGE_TOKEN", "PRO_BRIDGE_TOKEN", "")

# Optional: force a model slug on NEW chats. Empty means use ChatGPT's current
# account/default behavior. The driver still reports the model that answered
# when ChatGPT exposes data-message-model-slug.
MODEL_SLUG = os.environ.get(
    "CHATGPT_MODEL_SLUG",
    os.environ.get("GPT_PRO_MODEL_SLUG", ""),
)

# Max seconds to wait for one answer.
ANSWER_TIMEOUT = int(
    os.environ.get(
        "CHATGPT_BRIDGE_TIMEOUT",
        os.environ.get("PRO_BRIDGE_TIMEOUT", "1800"),
    )
)
