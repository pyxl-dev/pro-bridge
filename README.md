# pro-bridge — ChatGPT Web as an MCP tool

`pro-bridge` exposes the normal **ChatGPT web app** to Hermes and other MCP
clients through a real browser session you are already logged into.

It does not use the OpenAI API and does not depend on a particular ChatGPT
model. The bridge drives `chatgpt.com` over Chrome DevTools Protocol (CDP),
waits for the visible assistant turn to finish, and returns the reply together
with its `conversation_id`.

## Current V1

The MCP server exposes three tools:

| Tool | Purpose |
|---|---|
| `chatgpt_ask(prompt, conversation_id?)` | Ask ChatGPT. No id = **new chat**; passing an id continues that exact thread. |
| `chatgpt_new_chat()` | Explicitly navigate the bridge browser to a fresh chat. |
| `chatgpt_status()` | Check browser connection, current URL, model (when known), and conversation id. |

File upload and image generation are intentionally left for the next milestone,
after the text round-trip is validated against the current ChatGPT UI.

## Why this fork differs from upstream

The original project was centered on GPT Pro. This fork generalizes the bridge
for ordinary ChatGPT usage:

- no GPT Pro requirement or strict-model rejection;
- no model-specific MCP tool name;
- `conversation_id=None` now **always starts a new conversation** instead of
  accidentally reusing whichever `/c/...` tab happened to be open;
- browser actions remain serialized with a lock so multiple agents cannot type
  into the composer at the same time;
- completion detection combines the latest turn's Copy action, visible Stop
  state, and conservative text stability;
- timeouts now fail explicitly instead of returning a potentially partial
  answer;
- generic `CHATGPT_BRIDGE_*` configuration names, with legacy upstream names
  still accepted.

## Architecture

```text
Hermes / MCP client
        |
        | Streamable HTTP MCP
        v
   pro-bridge
        |
        | Playwright over CDP
        v
Chrome / Brave / Edge
(logged into chatgpt.com)
        |
        v
      ChatGPT
```

The browser should be a dedicated profile. Login, cookies, challenges, and the
normal ChatGPT frontend remain handled by the real browser.

## Quick start

Python 3.10+ is required.

```bash
git clone https://github.com/pyxl-dev/pro-bridge
cd pro-bridge
pip install -r requirements.txt
cp .env.example .env
```

Start the dedicated debug browser:

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File scripts\start-chrome-debug.ps1
```

```bash
# macOS / Linux — auto-detects Chrome/Chromium/Brave/Edge
./scripts/start-chrome-debug.sh
```

Log into `chatgpt.com` in that browser once and leave the browser open.

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

## Hermes

Hermes supports HTTP MCP servers natively. A minimal local configuration is:

```yaml
mcp_servers:
  chatgpt_web:
    url: "http://127.0.0.1:8765/mcp"
```

If the bridge is on another machine, bind it to a private interface/network,
set `CHATGPT_BRIDGE_TOKEN`, and send the matching bearer token in the MCP
headers.

The important tool contract for orchestration is:

```text
chatgpt_ask(prompt)
  -> {text, model, conversation_id}

chatgpt_ask(follow_up, conversation_id=<previous id>)
  -> same ChatGPT thread
```

Each no-id call starts a fresh ChatGPT conversation. This makes the bridge safe
to use from an orchestrator that may maintain several independent ChatGPT
threads.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CHATGPT_BRIDGE_CDP_URL` | `http://localhost:9222` | CDP endpoint |
| `CHATGPT_BRIDGE_HOST` | `127.0.0.1` | MCP bind address |
| `CHATGPT_BRIDGE_PORT` | `8765` | MCP port |
| `CHATGPT_BRIDGE_TOKEN` | _(none)_ | optional bearer token |
| `CHATGPT_MODEL_SLUG` | _(empty)_ | optional model slug for new chats |
| `CHATGPT_BRIDGE_TIMEOUT` | `1800` | max seconds per answer |

Legacy `PRO_BRIDGE_*`, `PRO_BRIDGE_TIMEOUT`, and `GPT_PRO_MODEL_SLUG` variables
are accepted as fallbacks so existing upstream launch scripts/configurations do
not break immediately.

## Completion and response extraction

The bridge deliberately avoids parsing ChatGPT's private streaming protocol.

It waits for a new semantic assistant turn:

```css
[data-message-author-role="assistant"]
```

Then it extracts rendered `.markdown` when available, falling back to the full
assistant turn.

Completion uses two paths:

1. **High confidence:** the latest conversation turn exposes
   `copy-turn-action-button` and the answer text is stable.
2. **UI-drift fallback:** no visible Stop control and the answer text remains
   unchanged for roughly 15 seconds.

If neither condition is reached before the configured timeout, the call raises a
timeout error rather than silently returning partial output.

## Multi-agent behavior

The browser is a single mutable UI, so all bridge operations are guarded by an
`asyncio.Lock`.

That means Hermes can issue calls from different agents without prompt text
interleaving. They are executed sequentially, while each agent can preserve its
own ChatGPT context by keeping the returned `conversation_id`.

## Diagnostics

```bash
python selftest.py
python debug_ask.py "Reply with one word: PONG"
python probe_dom.py
```

`probe_dom.py` sends nothing and is useful when ChatGPT changes DOM attributes.

## Next milestone

- [ ] upload files through the hidden `input[type=file]`;
- [ ] generate images through ChatGPT and download the resulting file;
- [ ] optional reference-image support;
- [ ] automated DOM smoke test / CI fixtures;
- [ ] improve multi-tab isolation if parallel browser workers are later needed.

## Security and operational notes

- Keep the debug browser profile private: it contains an authenticated ChatGPT
  session.
- Keep the MCP server on localhost unless remote access is genuinely needed.
- If remote access is needed, use a private network plus a bearer token.
- UI automation can break when ChatGPT changes its frontend; the semantic
  selectors are intentionally kept few and centralized in `pro_bridge/chatgpt.py`.
- This is an independent project and is not affiliated with OpenAI.

## License

MIT.
