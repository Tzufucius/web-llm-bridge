# Web LLM Bridge CLI

Use this reference for exact `web-llm-agent` commands and machine output. The
installed launcher starts or reuses the local Broker before running a command.
The repository equivalent is `python scripts/agent_cli.py` with the same
arguments. No command here requires the Skill to be installed.

## Entry points

```bash
web-llm-agent <command> [options]
python scripts/agent_cli.py <command> [options]
```

The explicit Broker command is only for setup or troubleshooting:

```bash
web-llm-broker serve
python -m web_llm_bridge.broker.server serve
```

## Commands

### `open`

```bash
web-llm-agent open --new --json
web-llm-agent open --url "https://chatgpt.com/c/CONVERSATION_ID" --json
web-llm-agent open --session-id SESSION_ID --json
```

Options:

- `--new`, `--url URL`, and `--session-id SESSION_ID` are mutually exclusive;
- `--provider PROVIDER` defaults to `chatgpt`;
- `--reopen-on-closed` asks the runtime to reopen a closed tab when possible;
- `--json` writes one machine-readable result to stdout.

Without a target, `open` uses the provider's active Session when available.

### `chat`

```bash
web-llm-agent chat --text "Review this implementation" --json
web-llm-agent chat --stdin --json < prompt.md
web-llm-agent chat --session-id SESSION_ID --stdin --json < prompt.md
```

Exactly one of `--text` and `--stdin` is required. `--stdin` reads until EOF
and is preferred for code, Markdown, JSON, diffs, logs, and other multiline
content. `--session-id` is optional and otherwise selects the active Session.
`--provider` defaults to `chatgpt`.

### `get-messages`

```bash
web-llm-agent get-messages --limit 5 --json
web-llm-agent get-messages --session-id SESSION_ID --limit 5 --json
web-llm-agent get-messages --all --json
```

`--limit` defaults to `5` and accepts `1` through `1000`. `--all` requests the
complete collected history and takes precedence over `--limit`.

### `list-sessions`

```bash
web-llm-agent list-sessions --json
web-llm-agent list-sessions --provider chatgpt --json
```

Use this when the active Session is unclear or a persisted `session_id` must
be selected. It returns Session metadata, not the full Conversation body.

## JSON and exit codes

With `--json`, stdout contains exactly one complete JSON object. Parse stdout
with `json.loads`; never parse stderr for business success.

Success exits `0`:

```json
{"ok":true,"result":{"text":"..."}}
```

Broker or business failures exit `1`:

```json
{"ok":false,"error":{"code":"CHAT_STATE_UNKNOWN","message":"...","safe_to_retry":false}}
```

Argument parsing failures retain argparse exit code `2`. Progress, warnings,
diagnostics, and human-readable non-JSON errors go to stderr.

The result object keeps method-specific fields. It is not an
OpenAI-compatible API response.

For the complete protocol reference, see the project's
[protocol documentation](https://github.com/Tuzfucius/web-llm-bridge/blob/main/docs/protocol.md).
