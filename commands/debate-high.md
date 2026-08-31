---
description: Structured debate with ChatGPT web through pro-bridge
argument-hint: [question or decision; defaults to current context/selection]
allowed-tools: mcp__chatgpt-web__chatgpt_ask, Read, Grep, Glob, Bash
---

Run a focused multi-round debate between yourself and ChatGPT through
`mcp__chatgpt-web__chatgpt_ask`.

## Topic
$ARGUMENTS

1. Frame the question and take an initial position.
2. Call `chatgpt_ask` with a self-contained prompt. Save the returned
   `conversation_id`.
3. Critique the answer, then call `chatgpt_ask` again with that same
   `conversation_id` for a rebuttal.
4. Default to two rounds. Add a third only when a material crux remains.
5. Synthesize agreements, disagreements, and the final recommendation.

Rules:
- A call without `conversation_id` starts a new ChatGPT thread.
- Always pass the same id for follow-ups in one debate.
- Treat the ChatGPT answer as another model's evidence/argument, not authority.
- If the MCP tool is unavailable, check that the bridge server and dedicated
  browser are running.
