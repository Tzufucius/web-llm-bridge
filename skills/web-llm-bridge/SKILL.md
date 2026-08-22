---
name: web-llm-bridge
description: >
  Use Web LLM Bridge when the user explicitly asks to consult a web LLM,
  when an independent second opinion or cross-model review would materially
  help, when work should be delegated to a supported Web LLM, or when an
  existing Web LLM conversation should be continued.
---

# Web LLM Bridge

Use `web-llm-agent` to consult an LLM running in the user's authenticated
browser session. The current supported provider is ChatGPT Web.

## When to Use

Use this Skill when:

- the user asks to ask ChatGPT or another supported Web LLM;
- an independent review, second opinion, or cross-model comparison has material value;
- a bounded analysis should be delegated to the Web LLM;
- an existing Web LLM Conversation should be continued.

Do not invoke the Web LLM routinely for trivial work. The user must ask for it,
or the additional model must provide a concrete benefit to the task.

## Responsibility Boundary

The local Agent owns the local task, repository, terminal state, and final
decision. The Web LLM only knows the context already present in its browser
Conversation. Web LLM Bridge does not synchronize local files, hidden reasoning,
or terminal state automatically.

Before calling the Web LLM, select and provide only the relevant context. Treat
the response as external analysis: verify useful claims against local code,
tests, documentation, or other primary evidence before acting on them.

## Session Policy

Reuse the active persistent Session when continuing the same line of work. Do
not create a new Session for every message. The usual continuation is:

```bash
web-llm-agent chat --stdin --json
```

Create a new Session only when the user requests a fresh conversation, the task
is unrelated, an experiment needs isolation, or an independent review should
not inherit the current Conversation's context:

```bash
web-llm-agent open --new --json
```

Record the returned `session_id`. When a known Session ID is available, use it
explicitly. Use `list-sessions` when the active Session is unclear. Read the
full command details in [references/cli.md](references/cli.md).

## Prompt and Input Policy

Construct a self-contained prompt with the following information as applicable:

```text
Task:
Goal:
Constraints:
Current implementation or conclusion:
Relevant code, logs, diff, or data:
Questions for independent review:
```

Do not assume the Web LLM can see the local working directory. For reviews,
ask for an independent assessment rather than confirmation of the local Agent's
conclusion.

Prefer `--stdin` for multiline prompts, source code, JSON, Markdown, diffs, and
logs. Use `--text` only for short, simple prompts.

## Result and Error Safety

With `--json`, parse stdout as JSON. A successful call has `ok: true` and its
payload is in `result`; a failed call has `ok: false` and an `error` object.
Progress and diagnostics are on stderr. Do not use natural-language stderr as
the business result.

If `error.safe_to_retry` is `true`, a finite retry is allowed only after the
local Agent confirms that repeating the operation is appropriate. If it is
`false`, the local Agent **MUST NOT** automatically resend the original Prompt.

For `CHAT_STATE_UNKNOWN`, the local Agent **MUST NOT** call `chat` again with
the original Prompt before inspecting the Conversation:

```bash
web-llm-agent get-messages --limit 5 --json
```

Determine whether the Prompt or response already exists, then decide the next
action. Never turn an uncertain submission into an unbounded retry loop.
