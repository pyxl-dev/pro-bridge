---
description: High-stakes debate with ChatGPT Web via pro-bridge MCP
argument-hint: [question or decision; defaults to current context/selection]
allowed-tools: mcp__chatgpt-web__chatgpt_ask, Read, Grep, Glob, Bash
---

You are running a high-stakes debate between yourself and ChatGPT through the
`mcp__chatgpt-web__chatgpt_ask` tool.

## Topic
$ARGUMENTS

If empty, infer it from the current conversation, the user's IDE selection, and
the open files. State the topic explicitly before starting.

## Protocol
1. Frame the question and what a good answer must satisfy. Take your own reasoned
   position first.
2. Call `chatgpt_ask` with the framing, all concrete context ChatGPT needs, your
   position, and a request for its strongest objection.
3. Rebut critically. If another ChatGPT turn is useful, call `chatgpt_ask` again.
   With Hermes identity-header routing enabled, the bridge automatically keeps
   this profile on its own ChatGPT conversation; no session id needs to be
   supplied manually.
4. Default to two rounds. Add a third only if a genuine crux remains unresolved.
5. Synthesize agreement, disagreement, and your recommendation.

## Rules
- Do not manually invent or switch `session` names when Hermes profile identity
  routing is enabled. The bridge derives the caller profile from the MCP request.
- Use `chatgpt_new_chat()` first only when the debate genuinely needs a clean
  ChatGPT context rather than the profile's existing conversation.
- If the MCP tool is unavailable, surface that the bridge server/browser may not
  be running instead of retrying blindly.
- Do not relay ChatGPT verbatim without analysis; engage critically with it.
