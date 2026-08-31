# pro-bridge — ChatGPT Web as an MCP tool

`pro-bridge` exposes the normal **ChatGPT web app** to Hermes and other MCP
clients through a real browser session you are already logged into.

It does not use the OpenAI API and does not depend on a particular ChatGPT
model. The bridge drives `chatgpt.com` over Chrome DevTools Protocol (CDP),
waits for the visible assistant turn to finish, and returns the reply together
with its `conversation_id`.

## Current V0.4

The MCP server exposes three tools:

| Tool | Purpose |
|---|---|
| `chatgpt_ask(prompt, files?, session?, conversation_id?)` | Ask ChatGPT, optionally attaching local files to the same message. Hermes profiles are automatically routed to their own persistent ChatGPT thread. |
| `chatgpt_new_chat(session?)` | Detach the caller profile from its current thread so its next message starts fresh. |
| `chatgpt_status(session?)` | Check browser state and the caller profile's mapped conversation. |

Image generation/download remains deferred to the next milestone.

## File attachments

Agents can attach one or more local files directly to a ChatGPT message:

```text
chatgpt_ask(
  prompt="Analyse ces documents et compare leurs conclusions.",
  files=[
    "/absolute/path/report.pdf",
    "/absolute/path/notes.docx"
  ]
)
```

`files` contains filesystem paths on the machine running `pro-bridge`.
Absolute paths are strongly recommended; relative paths are resolved against the
bridge process working directory.

Before touching the browser, the bridge:

1. expands `~` and resolves each path to an absolute path;
2. rejects missing paths and directories;
3. removes duplicate paths while preserving order;
4. fills the prompt;
5. selects the files through ChatGPT's real `input[type=file]` composer control;
6. waits for the attachment chips to appear and settle before sending;
7. returns the uploaded basenames in `attached_files`.

Example result shape:

```json
{
  "text": "...",
  "model": "gpt-5-6-thinking",
  "conversation_id": "...",
  "attached_files": ["report.pdf", "notes.docx"],
  "session": "developer",
  "session_source": "header"
}
```

Uploads are covered by the same browser/session lock as normal messages, so a
second Hermes agent cannot navigate or type over another agent while its files
are being attached.

If attachment preparation fails before send, the bridge reloads the current
ChatGPT thread before returning the error so stale prompt text or partially
attached files do not contaminate the next call.

The bridge does not bypass ChatGPT's own file type, size, account, or quota
limits. If ChatGPT rejects a file, the tool call fails rather than pretending it
was attached.

## Automatic Hermes profile sessions

Hermes can attach its active profile name to every HTTP MCP request with an
`identity_header` configuration. `pro-bridge` reads that header directly from
the MCP request context, so the model does **not** need to know, remember, or
pass its own session name.

Recommended Hermes configuration:

```json
{
  "mcpServers": {
    "chatgpt-web": {
      "url": "http://127.0.0.1:8765/mcp",
      "identity_header": {
        "name": "X-Hermes-Profile",
        "value_from": "profile"
      }
    }
  }
}
```

If the active Hermes profile is `developer`, Hermes sends:

```text
X-Hermes-Profile: developer
```

The bridge then resolves:

```text
developer -> no mapping yet -> NEW ChatGPT conversation -> id AAA
```

Later tool calls from the same Hermes profile automatically resolve:

```text
developer -> AAA -> continue the same ChatGPT conversation
```

A different profile remains isolated:

```text
business -> NEW ChatGPT conversation -> id BBB
```

The mapping is persisted by default in:

```text
~/.pro-bridge/sessions.json
```

so continuity survives Hermes and bridge restarts.

To deliberately start a new topic, the agent only needs to call:

```text
chatgpt_new_chat()
```

The caller is identified from `X-Hermes-Profile`, so only that profile's mapping
is reset. The previous ChatGPT conversation is **not deleted**; it is simply no
longer attached to that Hermes profile. Its next `chatgpt_ask(...)` creates a
fresh ChatGPT conversation and stores the new id automatically.

### Manual fallback / advanced override

The `session` argument remains available for MCP clients that do not send an
identity header. When `X-Hermes-Profile` is present, the header always wins over
the explicit argument; this prevents an LLM from accidentally routing itself
into another agent's thread.

`conversation_id` remains an advanced manual override for continuing a specific
ChatGPT thread. If a caller profile is resolved, a successful explicit
continuation rebinds that profile to the resulting conversation id.

If no profile header, `session`, or `conversation_id` is available, the bridge
keeps stateless behavior: every call starts a new ChatGPT conversation.

## Why this fork differs from upstream

The original project was centered on GPT Pro. This fork generalizes the bridge
for ordinary ChatGPT usage:

- no GPT Pro requirement or strict-model rejection;
- prompt + local file attachments in the same MCP call;
- automatic Hermes profile identity via HTTP MCP header;
- persistent `profile -> conversation_id` routing for multi-agent Hermes;
- `conversation_id=None` starts a new conversation when no named mapping exists;
- browser actions and uploads are serialized so multiple agents cannot type or
  attach files into the same composer simultaneously;
- completion detection combines semantic assistant turns, Copy/Stop state, and
  conservative text stability;
- timeouts fail explicitly rather than returning potentially partial output;
- generic `CHATGPT_BRIDGE_*` configuration names, with legacy upstream names
  still accepted;
- on macOS, the default launcher uses a genuine headed browser hidden in the
  background because ChatGPT currently challenges native Chromium headless.

## Architecture

```text
Hermes profile: developer ─┐
Hermes profile: business  ─┼─ X-Hermes-Profile
Hermes profile: research  ─┘
             |
             | Streamable HTTP MCP
             v
        pro-bridge
   persistent session registry
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

Manual file-upload smoke test:

```bash
python debug_ask.py --file /absolute/path/test.txt "Tell me the first line of the attached file."
```

Repeat `--file` to attach multiple files.

Start the MCP server:

```bash
python -m pro_bridge.server
# http://127.0.0.1:8765/mcp by default
```

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CHATGPT_BRIDGE_CDP_URL` | `http://localhost:9222` | CDP endpoint |
| `CHATGPT_BRIDGE_HOST` | `127.0.0.1` | MCP bind address |
| `CHATGPT_BRIDGE_PORT` | `8765` | MCP port |
| `CHATGPT_BRIDGE_TOKEN` | _(none)_ | optional bearer token |
| `CHATGPT_BRIDGE_IDENTITY_HEADER` | `X-Hermes-Profile` | HTTP header containing caller profile identity |
| `CHATGPT_MODEL_SLUG` | _(empty)_ | optional model slug for new chats |
| `CHATGPT_BRIDGE_SESSION_FILE` | `~/.pro-bridge/sessions.json` | persistent profile/session registry |
| `CHATGPT_BRIDGE_UPLOAD_TIMEOUT` | `180` | max seconds for attachments to become ready |
| `CHATGPT_BRIDGE_TIMEOUT` | `1800` | max seconds per answer |

Legacy `PRO_BRIDGE_*`, `PRO_BRIDGE_TIMEOUT`, and `GPT_PRO_MODEL_SLUG` variables
are accepted as fallbacks.

## Concurrency

The browser is a single mutable UI. The bridge serializes calls with locks so
separate Hermes agents cannot navigate, type, or upload over one another.
Profile sessions provide logical conversation isolation; calls are still
executed sequentially through the single browser worker.

## Diagnostics

```bash
python -m unittest discover -s tests
python selftest.py
python debug_ask.py "Reply with one word: PONG"
python debug_ask.py --file /absolute/path/test.txt "Read the attached file."
python probe_dom.py
```

`probe_dom.py` sends nothing and is useful when ChatGPT changes DOM attributes.

## Next milestone

- [x] upload files through ChatGPT;
- [ ] generate/download images;
- [ ] optional reference-image support;
- [ ] automated DOM smoke tests;
- [ ] optional multi-browser workers if true parallel execution is later needed.

## Security and operational notes

- Keep the dedicated browser profile private: it contains an authenticated
  ChatGPT session.
- File paths are read with the bridge process permissions. Only expose this MCP
  tool to agents you trust with the files accessible to that process.
- Keep the MCP server on localhost unless remote access is genuinely needed.
- If remote access is needed, use a private network plus a bearer token.
- Treat identity headers as routing hints, not authentication. For remote access,
  protect the bridge separately with its bearer token/private network.
- UI automation can break when ChatGPT changes its frontend; semantic selectors
  are intentionally kept few and centralized in `pro_bridge/chatgpt.py`.
- This is an independent project and is not affiliated with OpenAI.

## License

MIT.
