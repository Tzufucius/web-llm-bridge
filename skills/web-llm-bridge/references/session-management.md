# Session Management

Sessions bind independent CLI calls to the same browser Conversation. The
Conversation itself keeps context; the Bridge does not reconstruct and resend
the full history for every prompt.

## Choose a Session

1. Continue the current line of work with the active Session:

   ```bash
   web-llm-agent chat --stdin --json < prompt.md
   ```

2. If the active Session is unclear, inspect persisted sessions:

   ```bash
   web-llm-agent list-sessions --json
   ```

3. If the target is known, pass its ID explicitly:

   ```bash
   web-llm-agent chat --session-id SESSION_ID --stdin --json < prompt.md
   ```

4. To continue a known browser Conversation URL:

   ```bash
   web-llm-agent open --url "https://chatgpt.com/c/CONVERSATION_ID" --json
   ```

Do not call `open --new` before every prompt. That discards useful persistent
context.

## Create a New Session

Create a new Session only when the user requests a fresh Conversation, the
task is unrelated, an experiment needs isolation, or an independent review
must avoid existing context:

```bash
web-llm-agent open --new --json
```

Record the returned `session_id` when later calls must be unambiguous.

## Read History

Use a bounded recent view by default:

```bash
web-llm-agent get-messages --limit 5 --json
```

Use `--session-id` when the target is explicit. Use `--all` only when the user
or task explicitly requires complete history; do not use full history to
rebuild context automatically.
