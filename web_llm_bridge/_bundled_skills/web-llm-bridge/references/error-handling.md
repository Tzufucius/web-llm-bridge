# Error Handling and Retry Safety

Always parse the JSON envelope from stdout when `--json` is used. Progress and
diagnostics belong to stderr.

Success:

```json
{"ok":true,"result":{}}
```

Failure:

```json
{"ok":false,"error":{"code":"...","message":"...","safe_to_retry":false}}
```

If `safe_to_retry` is `false`, the local Agent **MUST NOT** automatically
resend the original Prompt. A `true` value permits only a finite retry after
checking that repeating the operation is appropriate.

## Important Codes

- `CHAT_STATE_UNKNOWN`: submission may already have happened. First inspect
  recent messages, then decide what to do.
- `EXTENSION_NOT_CONNECTED`: the extension is not connected to the Broker.
- `PAGE_NOT_READY`: the provider page is not ready for interaction.
- `SESSION_NOT_FOUND`: the requested persisted Session does not exist.
- `TAB_CLOSED`: the bound browser tab is closed; reopening does not make an
  uncertain prompt safe to replay.
- `RESPONSE_TIMEOUT`: the final response was not observed within the runtime
  window; inspect the Conversation before retrying.
- `BROWSER_LAUNCH_FAILED`: the configured browser could not be started.
- `BROWSER_EXTENSION_NOT_CONNECTED`: the browser started but the Extension did
  not complete its handshake within the configured window.
- `ARTIFACT_NOT_FOUND`: the local Artifact descriptor is unavailable, commonly
  after `forget-session`.
- `ARTIFACT_TOO_LARGE`, `ARTIFACT_INVALID_TYPE`, `ARTIFACT_TRANSFER_FAILED`,
  `ARTIFACT_WRITE_FAILED`: Artifact materialization was rejected or failed;
  do not replace it with an arbitrary URL downloader.

For `CHAT_STATE_UNKNOWN`, the local Agent **MUST NOT** call `chat` again with
the original Prompt before running:

```bash
web-llm-agent get-messages --limit 5 --json
```

Check whether the Prompt or response is already present. Never turn an
uncertain submission into an unbounded retry loop.

The full wire-level error semantics remain in the project's
[protocol documentation](https://github.com/Tuzfucius/web-llm-bridge/blob/main/docs/protocol.md).
