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


def _env_bool(primary, legacy, default="1"):
    value = _env(primary, legacy, default).strip().lower()
    return value not in {"0", "false", "no", "off"}


_load_dotenv()

# CDP endpoint of the debug browser — local to this machine, never exposed.
CDP_URL = _env(
    "CHATGPT_BRIDGE_CDP_URL",
    "PRO_BRIDGE_CDP_URL",
    "http://localhost:9222",
)

# Automatically relaunch the dedicated browser if a local CDP endpoint is down.
# Remote CDP endpoints are never auto-started.
AUTO_START_BROWSER = _env_bool(
    "CHATGPT_BRIDGE_AUTO_START_BROWSER",
    "PRO_BRIDGE_AUTO_START_BROWSER",
    "1",
)
BROWSER_START_TIMEOUT = float(
    _env(
        "CHATGPT_BRIDGE_BROWSER_START_TIMEOUT",
        "PRO_BRIDGE_BROWSER_START_TIMEOUT",
        "20",
    )
)
BROWSER_START_COMMAND = _env(
    "CHATGPT_BRIDGE_BROWSER_START_COMMAND",
    "PRO_BRIDGE_BROWSER_START_COMMAND",
    "",
).strip()

# Where the MCP server listens.
HOST = _env("CHATGPT_BRIDGE_HOST", "PRO_BRIDGE_HOST", "127.0.0.1")
PORT = int(_env("CHATGPT_BRIDGE_PORT", "PRO_BRIDGE_PORT", "8765"))

# Shared secret. If set, callers must send Authorization: Bearer <TOKEN>.
TOKEN = _env("CHATGPT_BRIDGE_TOKEN", "PRO_BRIDGE_TOKEN", "")

# HTTP header carrying the MCP caller identity. Hermes can populate this
# automatically from its active profile with identity_header.value_from=profile.
IDENTITY_HEADER = os.environ.get(
    "CHATGPT_BRIDGE_IDENTITY_HEADER",
    "X-Hermes-Profile",
).strip() or "X-Hermes-Profile"

# Optional: force a model slug on NEW chats. Empty means use ChatGPT's current
# account/default behavior. The driver still reports the model that answered
# when ChatGPT exposes data-message-model-slug.
MODEL_SLUG = os.environ.get(
    "CHATGPT_MODEL_SLUG",
    os.environ.get("GPT_PRO_MODEL_SLUG", ""),
)

# Persistent mapping of named caller sessions (for example Hermes profiles) to
# ChatGPT conversation ids. This deliberately lives outside the repository so
# git pulls/checkouts never erase agent continuity.
SESSION_FILE = os.path.expanduser(
    _env(
        "CHATGPT_BRIDGE_SESSION_FILE",
        "PRO_BRIDGE_SESSION_FILE",
        "~/.pro-bridge/sessions.json",
    )
)

# Max seconds to wait for one answer.
ANSWER_TIMEOUT = int(
    os.environ.get(
        "CHATGPT_BRIDGE_TIMEOUT",
        os.environ.get("PRO_BRIDGE_TIMEOUT", "1800"),
    )
)
