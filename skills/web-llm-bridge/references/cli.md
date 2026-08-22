# Web LLM Bridge CLI Reference

Use this reference after the Skill's core workflow indicates that a Web LLM
call is appropriate. The source of truth for command parsing is
`web_llm_bridge/cli/agent.py`.

## Entry Points

The installed Agent command is:

```bash
web-llm-agent <command> [options]
```

The launcher starts or reuses the local Broker before running the command. The
repository script is equivalent:

```bash
python scripts/agent_cli.py <command> [options]
```

To start the Broker explicitly:

```bash
web-llm-broker serve
```

The module fallback is `python -m web_llm_bridge.broker.server serve`.

## Commands

### `open`

Open, create, or restore a browser Session:

```bash
web-llm-agent open --new --json
web-llm-agent open --url "https://chatgpt.com/c/CONVERSATION_ID" --json
web-llm-agent open --session-id SESSION_ID --json
```

Options:

- `--new`: create a new Conversation and Session;
- `--url URL`: open or restore a Conversation URL;
- `--session-id SESSION_ID`: restore an existing persisted Session;
- `--provider PROVIDER`: Provider ID, default `chatgpt`;
- `--reopen-on-closed`: enable reopening a closed browser tab when possible;
- `--json`: emit the machine-readable result envelope.

`--new`, `--url`, and `--session-id` are mutually exclusive. Without an
explicit target, `open` uses the active Session for the Provider when one
exists, otherwise it opens the Provider's default URL. A successful response
contains the `session_id` to use for later explicit calls.

### `chat`

Send one Prompt and wait for the final response:

```bash
web-llm-agent chat --stdin --json < prompt.md
web-llm-agent chat --session-id SESSION_ID --stdin --json < prompt.md
web-llm-agent chat --text "Review this implementation" --json
```

Exactly one of `--text` and `--stdin` is required. `--stdin` reads until EOF
and is preferred for multiline content. `--session-id` is optional; when it is
omitted, the active Session is used. `--provider` defaults to `chatgpt`.

Only progress is written to stderr while the call is running. The final
response is written to stdout when `--json` is selected.

### `get-messages`

Read messages from the selected browser Conversation:

```bash
web-llm-agent get-messages --limit 5 --json
web-llm-agent get-messages --session-id SESSION_ID --limit 5 --json
web-llm-agent get-messages --all --json
```

`--limit` defaults to `5` and accepts an integer from `1` through `1000`,
validated by the Broker. `--all` requests the complete collected history and
ignores the limit.
`--session-id` is optional and otherwise uses the active Session.

### `list-sessions`

List persisted Sessions:

```bash
web-llm-agent list-sessions --json
web-llm-agent list-sessions --provider chatgpt --json
```

Use this command when the active Session is unknown or when a specific persisted
Session must be selected. The list contains metadata, including `session_id`
and the current URL; it does not contain the full Conversation body.

## JSON and Exit Codes

With `--json`, stdout contains one complete JSON object. Parse it with
`json.loads`; do not parse stderr to determine business success.

Success has exit code `0`:

```json
{"ok":true,"result":{"text":"..."}}
```

Failure has a non-zero exit code (`1` for Broker or business errors):

```json
{"ok":false,"error":{"code":"CHAT_STATE_UNKNOWN","message":"...","safe_to_retry":false}}
```

Argument parsing failures keep argparse's exit code `2`. Progress, diagnostics,
warnings, and human-readable non-JSON errors are written to stderr.

For the complete Broker error table and retry semantics, read
[`docs/protocol.md`](../../../docs/protocol.md).

## Result Shapes

The CLI wraps the Broker result without changing its method-specific fields:

- `open`: `session_id`, `provider`, `tab_id`, `conversation_url`, `sequence`, and `reopen_on_closed`;
- `chat`: the Session fields plus non-empty `text`;
- `get-messages`: the Session fields plus `messages` and `truncated`;
- `list-sessions`: a `sessions` list containing persisted Session metadata.

The `result` object is not an OpenAI-compatible API response. Use only the
fields needed for the current task and ignore additive fields.

## Common Errors and Troubleshooting

- `SESSION_NOT_FOUND`: run `list-sessions --json` and select a persisted `session_id`.
- `INVALID_URL`: verify that the URL belongs to the currently supported ChatGPT Web host.
- `EXTENSION_NOT_CONNECTED` or `PAGE_NOT_READY`: load `extension/` as an unpacked extension, sign in to ChatGPT in that browser profile, and keep a supported ChatGPT tab available.
- `TAB_CLOSED`: inspect `safe_to_retry`; reopening is controlled by the Session policy and does not make an uncertain chat safe to replay.
- `RESPONSE_TIMEOUT`: treat the call as a failure and inspect the Conversation before deciding what to do next.
- `CHAT_STATE_UNKNOWN`: follow the mandatory message inspection flow below; do not resend the original Prompt.

The Agent-to-Broker connection uses `127.0.0.1:8766`; the Extension-to-Broker
WebSocket uses `127.0.0.1:8765`. If the launcher cannot start the Broker,
inspect `runtime/broker.stderr.log` under `WEB_LLM_BRIDGE_HOME` or the default
`~/.web-llm-bridge` directory. For provider-specific DOM assumptions, read
[`docs/providers/chatgpt.md`](../../../docs/providers/chatgpt.md).

## Session Selection Workflow

1. Continue the current line of work with `chat --stdin --json` and the active
   Session.
2. Use `list-sessions --json` when the active Session is unclear.
3. Use `open --new --json` only for a new, unrelated, isolated, or deliberately
   independent Conversation; retain its returned `session_id`.
4. Use `--session-id SESSION_ID` when the local Agent already knows the target.

Do not call `open --new` before every Prompt; doing so discards the value of the
persistent Web Conversation context.

## Prompt Template

Build a prompt that gives the Web LLM enough context to reason independently:

```text
Task:
We are working on ...

Goal:
...

Constraints:
...

Current implementation or conclusion:
...

Relevant code, logs, diff, or data:
...

Questions:
1. ...
2. ...

Please review this independently and identify assumptions, risks, and alternatives.
```

The local Agent chooses what to share. Do not claim that the Web LLM inspected
files or repository state unless that content was included in the Prompt.

## Retry Safety

If a JSON failure has `safe_to_retry: true`, a finite deliberate retry may be
considered after checking that the operation is safe to repeat. If the value is
`false`, the local Agent **MUST NOT** automatically resend the original Prompt.

For `CHAT_STATE_UNKNOWN`, submission may already have happened. First inspect
recent messages:

```bash
web-llm-agent get-messages --limit 5 --json
```

Only after checking the Conversation may the local Agent decide whether a new,
distinct Prompt is appropriate. Never blindly replay the original Prompt.
