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

## Preflight

Before the first Web LLM call in a task, verify that the CLI is available:

```bash
web-llm-agent --help
```

If the command is unavailable, report exactly:

```text
Web LLM Bridge CLI is not installed or not available in the current environment.
```

Do not automatically install packages, clone repositories, or replace the
bridge with Playwright, Selenium, CDP, private APIs, cookies, or tokens. The
normal Agent launcher starts or reuses the local Broker automatically. When a
browser operation is needed, the Broker also starts or wakes the configured
daily browser, waits for the Extension handshake, and restores the selected
Session tab. Authentication remains the user's responsibility.

## Tool Boundary

When this Skill is active, use `web-llm-agent` for supported Web LLM access.
Do not independently automate the provider website with browser JavaScript,
Playwright, Selenium, CDP, private provider APIs, cookies, or tokens. Browser
interaction belongs to the Bridge runtime, not to this Skill.

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

When a successful `chat` or `get-messages` result contains `artifacts`, use
`get-artifact --id ARTIFACT_ID` to materialize the requested image. Do not parse
ChatGPT DOM, copy data URIs, fetch `blob:` URLs directly, or invoke arbitrary
download URLs.

The formal Agent surface is limited to `open`, `chat`, `get-messages`,
`list-sessions`, `close-session`, `forget-session`, and `get-artifact`. There is
no public debugging or artifact-wait command. `get-artifact` performs internal
turn/index resolution, readiness polling, source refresh, and bounded transfer.
If `CHAT_STATE_UNKNOWN` is returned, inspect messages and do not call `chat`
again automatically.

To release a browser tab while keeping the Conversation recoverable, use
`close-session`. Use `forget-session` only when the local Bridge should stop
maintaining that Session. Never close all ChatGPT tabs or call `chrome.tabs`
directly.

For detailed operational guidance, load only the reference needed:

- [CLI](references/cli.md) for commands, parameters, output, and exit codes;
- [Session management](references/session-management.md) for active, named,
  new, URL, and history workflows;
- [Error handling](references/error-handling.md) for error codes and retry
  safety;
- [Agent workflows](references/agent-workflows.md) for consultation and review
  patterns.
