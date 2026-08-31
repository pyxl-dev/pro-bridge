# pro-bridge — ChatGPT Web as an MCP tool

`pro-bridge` exposes the normal **ChatGPT web app** to Hermes and other MCP
clients through a real browser session you are already logged into.

It does not use the OpenAI API and does not depend on a particular ChatGPT
model. The bridge drives `chatgpt.com` over Chrome DevTools Protocol (CDP),
waits for the visible assistant turn to finish, and returns the reply together
with its `conversation_id`.

## Current V0.3

The MCP server exposes three tools:

| Tool | Purpose |
|---|---|
| `chatgpt_ask(prompt, session?, conversation_id?)` | Ask ChatGPT. A named session automatically resumes its own mapped ChatGPT thread. |
| `chatgpt_new_chat(session?)` | Reset one named session so its next message starts a new ChatGPT thread. |
| `chatgpt_status(session?)` | Check browser state and optionally inspect the conversation mapped to one session. |

File upload and image generation are intentionally left for the next milestone.

## Named sessions for Hermes agents

The recommended multi-agent contract is to use the **stable Hermes profile/bot
name** as `session`.

Example:

```text
chatgpt_ask(
  prompt="Analyse ce bug et propose un correctif.",
  session="developer"
)
```

First call for `developer`:

```text
developer -> no mapping yet -> NEW ChatGPT conversation -> id AAA
```

Later calls:

```text
developer -> AAA -> continue the same ChatGPT conversation
```

Another profile stays isolated:

```text
business -> NEW ChatGPT conversation -> id BBB
```

The mapping is persisted by default in:

```text
~/.pro-bridge/sessions.json
```

so continuity survives Hermes and bridge restarts.

To deliberately start a new topic for one profile:

```text
chatgpt_new_chat(session="developer")
```

This **does not delete** the previous ChatGPT conversation. It only removes the
`developer -> AAA` mapping. The next `chatgpt_ask(..., session="developer")`
creates a fresh ChatGPT conversation and stores the new id automatically.

### Advanced/manual conversation id

`conversation_id` remains available as an override:

```text
chatgpt_ask(
  prompt="Continue ce thread précis.",
  session="developer",
  conversation_id="6a95826b-..."
)
```

After a successful answer, `developer` becomes mapped to that explicit
conversation id.

If neither `session` nor `conversation_id` is passed, the bridge keeps the old
stateless behavior: every call starts a new ChatGPT conversation.

## Why this fork differs from upstream

The original project was centered on GPT Pro. This fork generalizes the bridge
for ordinary ChatGPT usage:

- no GPT Pro requirement or strict-model rejection;
- named persistent `session -> conversation_id` routing for multi-agent Hermes;
- `conversation_id=None` starts a new conversation when no named mapping exists;
- browser actions are serialized so multiple agents cannot type into the same
  composer simultaneously;
- completion detection combines semantic assistant turns, Copy/Stop state, and
  conservative text stability;
- timeouts fail explicitly rather than returning potentially partial output;
- generic `CHATGPT_BRIDGE_*` configuration names, with legacy upstream names
  still accepted;
- on macOS, the default launcher uses a genuine headed browser hidden in the
  background because ChatGPT currently challenges native Chromium headless.

## Architecture

```text
Hermes agents
 developer ─┐
 business  ─┼─ session names
 research  ─┘
        |
        | Streamable HTTP MCP
        v
   pro-bridge
   session registry
        |
        | Playwright over CDP
        v
Chrome / Brave / Edge
(dedicated authenticated profile)
        |
        v
      ChatGPT
```

## Quick start

Python 3.10+ is required. A virtual environment is recommended.

```bash
git clone https://github.com/pyxl-dev/pro-bridge
cd pro-bridge
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

### Browser

On macOS/Linux:

```bash
# Normal operation. On macOS this runs a genuine browser hidden in background.
./scripts/start-chrome-debug.sh

# Visible mode for login/account maintenance.
./scripts/start-chrome-debug.sh --login

# Stop the dedicated bridge browser.
./scripts/start-chrome-debug.sh --stop
```

Both normal and login mode use the same persistent browser profile.

Native `--headless` remains available only as an experimental diagnostic mode;
ChatGPT currently serves a challenge page to `HeadlessChrome` on tested builds.

Check the connection without sending anything:

```bash
python selftest.py
```

Full text round-trip:

```bash
python selftest.py "Reply with exactly one word: PONG"
```

Start the MCP server:

```bash
python -m pro_bridge.server
# http://127.0.0.1:8765/mcp by default
```

## Hermes MCP configuration

For Hermes installations using JSON MCP config:

```json
{
  "mcpServers": {
    "chatgpt-web": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

Each Hermes profile should pass its own stable profile/bot name as the `session`
argument whenever it uses `chatgpt_ask`, `chatgpt_new_chat`, or session-specific
`chatgpt_status`.

A useful agent instruction is:

```text
When using chatgpt-web, always pass your own stable Hermes profile name as
`session`. Reuse that session for the same topic. When a genuinely new topic
needs a clean ChatGPT context, call chatgpt_new_chat with that same session
before the next chatgpt_ask.
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CHATGPT_BRIDGE_CDP_URL` | `http://localhost:9222` | CDP endpoint |
| `CHATGPT_BRIDGE_HOST` | `127.0.0.1` | MCP bind address |
| `CHATGPT_BRIDGE_PORT` | `8765` | MCP port |
| `CHATGPT_BRIDGE_TOKEN` | _(none)_ | optional bearer token |
| `CHATGPT_MODEL_SLUG` | _(empty)_ | optional model slug for new chats |
| `CHATGPT_BRIDGE_SESSION_FILE` | `~/.pro-bridge/sessions.json` | persistent named-session registry |
| `CHATGPT_BRIDGE_TIMEOUT` | `1800` | max seconds per answer |

Legacy `PRO_BRIDGE_*`, `PRO_BRIDGE_TIMEOUT`, and `GPT_PRO_MODEL_SLUG` variables
are accepted as fallbacks.

## Concurrency

The browser is a single mutable UI. The bridge serializes calls with locks so
separate Hermes agents cannot navigate/type over one another. Named sessions
provide logical conversation isolation; calls are still executed sequentially
through the single browser worker.

## Diagnostics

```bash
python selftest.py
python debug_ask.py "Reply with one word: PONG"
python probe_dom.py
```

`probe_dom.py` sends nothing and is useful when ChatGPT changes DOM attributes.

## Next milestone

- [ ] upload files through ChatGPT;
- [ ] generate/download images;
- [ ] optional reference-image support;
- [ ] automated DOM smoke tests;
- [ ] optional multi-browser workers if true parallel execution is later needed.

## Security and operational notes

- Keep the dedicated browser profile private: it contains an authenticated
  ChatGPT session.
- Keep the MCP server on localhost unless remote access is genuinely needed.
- If remote access is needed, use a private network plus a bearer token.
- UI automation can break when ChatGPT changes its frontend; semantic selectors
  are intentionally kept few and centralized in `pro_bridge/chatgpt.py`.
- This is an independent project and is not affiliated with OpenAI.

## License

MIT.
