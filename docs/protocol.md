**English** | [简体中文](protocol.zh-CN.md)

# Protocol

Web LLM Bridge has two local protocols:

- CLI/agent to Broker: NDJSON over TCP at `127.0.0.1:8766`;
- extension to Broker: JSON messages over WebSocket at
  `ws://127.0.0.1:8765`.

Both are loopback-only IPC. Neither is a public remote API. The current
extension protocol version is `2`, and both transports cap a message at 8 MiB.
Version 2 adds Session lifecycle RPCs and bounded Artifact transfer events;
older Extensions are rejected during the handshake.

## Broker NDJSON

Each request, progress event, and final response is one UTF-8 JSON object
terminated by a newline. A connection may contain multiple requests. The
Broker processes lines as tasks, so callers that pipeline requests must
correlate every event and response by `id` rather than assume response order.

### Request envelope

```json
{"id":"req-123","method":"chat","params":{"text":"Hello"}}
```

| Field | Requirement |
| --- | --- |
| `id` | Required non-empty string, chosen by the caller. |
| `method` | Required string naming a method below. |
| `params` | JSON object; omitted means `{}`. |

The Broker NDJSON ID remains stable for that local RPC. The Broker-to-extension
transport creates a separate internal ID, so IDs are not end-to-end identical
across both protocol layers.

### Final responses

A successful final response is:

```json
{"id":"req-123","ok":true,"result":{"text":"Hello. How can I help?"}}
```

A failed final response is:

```json
{"id":"req-123","ok":false,"error":{"code":"RESPONSE_TIMEOUT","message":"No effective page update was detected for five minutes","safe_to_retry":false}}
```

Exactly one final response is sent for a valid request task. `result` is always
an object but is method-specific; it is not an OpenAI API response shape.
Clients should ignore unknown additive fields.

### Methods

#### `open`

Parameters:

| Field | Type and behavior |
| --- | --- |
| `provider` | Non-empty string; defaults to `chatgpt`. |
| `new` | Boolean; defaults to `false`. If true, `url` and `session_id` must be absent. |
| `url` | Optional provider HTTPS URL. Mutually exclusive with `session_id`. |
| `session_id` | Optional existing session ID. |
| `reopen_on_closed` | Optional boolean. `null`/omitted preserves a stored policy; otherwise it replaces it. |

When no explicit target is supplied, the active record for the provider is
used if present; otherwise the provider default URL is opened. `new: true`
creates a new tab and a new session record. Other opens may reattach to the
recorded tab or reuse a matching provider tab.

Result fields:

```json
{
  "session_id": "3d1f...",
  "provider": "chatgpt",
  "tab_id": 42,
  "conversation_url": "https://chatgpt.com/c/example",
  "sequence": 0,
  "reopen_on_closed": false
}
```

#### `chat`

Parameters are `provider` (default `chatgpt`), optional `session_id`, and a
non-empty string `text`. If no session is selected, the manager creates one at
the provider default URL. The result is the session descriptor above plus a
non-empty string `text` containing the final serialized assistant response.

`sequence` is incremented before browser dispatch, even if the operation later
fails. Callers must not use it as submission proof.

#### `get_messages`

Parameters are `provider`, optional `session_id`, `full`, and `limit`:

- `full` must be boolean and defaults to `false`.
- When `full` is false, `limit` may be `null` or an integer from 1 through 1000.
- A raw Broker request that omits `limit` defaults to 5.
- The public `WebLLMSession.get_messages()` method explicitly sends
  `limit: null`; this returns the currently captured/visible history without
  requesting a target count.
- `full: true` ignores `limit` and attempts to scroll through all available
  history.

Result fields are the session descriptor plus:

```json
{
  "messages": [
    {"role":"user","content":"Question"},
    {"role":"assistant","content":"Answer"}
  ],
  "truncated": false
}
```

Messages are ordered oldest to newest. `truncated: true` means the history load
deadline was reached; `false` does not guarantee that the website exposed every
historical turn.

#### `list_sessions`

The optional `provider` string filters records. The result is
`{"sessions":[...]}`. Each record contains `version`, `provider`, `session_id`,
`tab_id`, `current_url`, `created_at`, `updated_at`, `sequence`, `active`, and
`reopen_on_closed`. This method returns store records, so the URL field is
`current_url`, not `conversation_url`.

#### `close_session`

Requires `session_id`. The Broker closes only the Tab currently bound to that
Session, treats an already closed Tab as an idempotent success, preserves the
Conversation URL and sequence, and marks the local record inactive.

#### `forget_session`

Requires `session_id`. The Broker closes the bound Tab and removes local Session
metadata. It does not delete or archive the provider Conversation.

#### `get_artifact`

Requires an Artifact `artifact_id` and optionally accepts an output path. The
caller cannot provide an arbitrary URL. The result contains an absolute local
path, MIME type, byte size, SHA-256, and quality.

Chat and history responses may contain an additive `artifacts` array. An image
descriptor contains `id`, `kind`, `provider`, `turn_id`, `index`, `mime_type`,
`width`, `height`, `alt`, and `quality`; source URLs and DOM selectors are
never part of the public result. A pure image reply may have `text: ""`.

#### `debug_snapshot`

Returns a sanitized DOM/Artifact snapshot for the bound tab. The result contains
only the page origin/path, prompt presence/visibility/text length, message
counts, the last assistant turn ID and text hash, generation/completion state,
revision, and Artifact readiness, dimensions, source kind, and source hash. It
never returns full HTML, prompt text, cookies, tokens, signed URLs, data URIs,
or blob contents. It uses the same Browser Bootstrap and Session rebind path as
other browser operations.

#### `debug_trace`

Parameters are `provider`, optional `session_id`, and required `request_id`.
The result reads the in-memory bounded trace for that chat request. Events are
`before_send`, `submitted`, `assistant_node_seen`, `artifact_seen`,
`artifact_ready`, `completion_candidate`, `completed`, or
`chat_state_unknown`. Traces are not persisted and are cleared when the
Extension is reloaded.

#### `wait_artifact`

Parameters are a required `artifact_id` and optional `timeout_ms` from 1000
through 300000 (default 60000). It only waits for an existing Artifact
descriptor to become ready and never resubmits the Prompt. A closed Session is
temporarily restored and closed again afterward, preserving `active: false`.
Timeout returns `ARTIFACT_NOT_READY`.

## Broker progress

Only `chat` currently emits progress. Events precede the final response:

```json
{
  "type": "progress",
  "id": "req-123",
  "provider": "chatgpt",
  "session_id": "3d1f...",
  "tab_id": 42,
  "url": "https://chatgpt.com/c/example",
  "phase": "streaming",
  "elapsed_ms": 12400,
  "idle_ms": 180
}
```

Current `phase` values are `submitted`, `thinking`, `working`, `tool_call`, and
`streaming`. The extension transport drops phases outside this set. Consumers
should still treat a future unknown phase as observational data, never as a
final result.

`elapsed_ms` is time since the content runtime started the chat operation;
`idle_ms` is time since its most recent effective page activity. Both are
non-negative numbers, and the Broker supplies `0` when an extension event omits
them. `session_id` reflects the caller's parameter and may be null when the
manager implicitly creates a session; it is not a replacement for the final
session descriptor.

The first progress may be `working` before submission. `submitted` is emitted
only after submission evidence is observed, but it still does not prove that a
final answer will be produced. The caller must continue reading until the final
response with the same Broker `id`.

## Extension WebSocket

### Connection and handshake

The Broker accepts one active client whose Origin matches a Chrome extension
origin. Origin rejection may occur at the WebSocket handshake and is not
guaranteed to arrive as a JSON error.

The extension starts with:

```json
{"type":"hello","protocol_version":2}
```

The Broker responds with `{"type":"hello_ack","protocol_version":2}`. An
incompatible hello receives an `error` message with code
`INCOMPATIBLE_PROTOCOL`; a second active extension receives
`EXTENSION_ALREADY_CONNECTED`. The extension also sends `ping`, to which the
Broker replies with `pong`.

### Requests, responses, and progress

The Broker sends:

```json
{"type":"request","id":"transport-id","method":"chat","params":{"provider":"chatgpt","tab_id":42,"text":"Hello"}}
```

Supported internal methods are `open`, `chat`, `get_messages`, `debug_snapshot`,
`debug_trace`, `wait_artifact`, `close_tab`, `resolve_artifact`, and
`get_artifact`. A response is
either:

```json
{"type":"response","id":"transport-id","ok":true,"result":{}}
```

or:

```json
{"type":"response","id":"transport-id","ok":false,"error":{"code":"PAGE_NOT_READY","message":"...","safe_to_retry":false}}
```

Progress uses the same transport ID and includes `tab_id`, `url`, `provider`,
`phase`, `elapsed_ms`, and `idle_ms`. This WebSocket contract is internal: a
provider change may update it together with extension and protocol tests.

For blob Artifacts, the Extension emits `artifact_start`, ordered
`artifact_chunk` messages containing base64-encoded 256 KiB raw chunks, and an
`artifact_end`, all correlated by the request ID. The Broker rejects duplicate
or missing sequences, invalid base64, size mismatches, and transfers above the
50 MiB Artifact limit before writing the file.

## Errors and retry safety

Every Broker failure contains machine-readable `code`, diagnostic `message`,
and boolean `safe_to_retry`. Do not infer behavior from localized message text.

`safe_to_retry` has a narrow meaning: repeating the same RPC is known not to
duplicate a page-side effect at the point where the error was produced. It does
not mean the retry will succeed. `false` means a blind retry is not proven safe,
not necessarily that the failure is permanent.

The current implementation defaults this field to `false`. The notable explicit
safe case is a pre-dispatch `TAB_CLOSED`, which the extension marks true.
`CHAT_STATE_UNKNOWN` is always false: dispatch began, and tab or messaging loss
made it impossible to determine whether the prompt was submitted. Never
automatically replay that prompt.

Current Broker-facing error codes include:

| Area | Codes |
| --- | --- |
| Envelope and arguments | `INVALID_JSON`, `INVALID_REQUEST`, `INVALID_ARGUMENT`, `UNKNOWN_METHOD` |
| Provider/session selection | `PROVIDER_NOT_FOUND`, `SESSION_NOT_FOUND`, `INVALID_URL` |
| Extension availability | `EXTENSION_NOT_CONNECTED`, `BROWSER_LAUNCH_FAILED`, `BROWSER_EXTENSION_NOT_CONNECTED`, `TAB_CLOSED`, `CONTENT_SCRIPT_UNAVAILABLE` |
| Page operation | `PAGE_NOT_READY`, `INPUT_FAILED`, `BUSY`, `SEND_FAILED` |
| Ambiguous chat | `CHAT_STATE_UNKNOWN` |
| Time and size | `RPC_TIMEOUT`, `RESPONSE_TIMEOUT`, `RESPONSE_TOO_LARGE`, `ARTIFACT_TOO_LARGE` |
| Artifact | `ARTIFACT_NOT_FOUND`, `ARTIFACT_NOT_READY`, `ARTIFACT_UNAVAILABLE`, `ARTIFACT_TRANSFER_FAILED`, `ARTIFACT_INVALID_TYPE`, `ARTIFACT_SOURCE_EXPIRED`, `ARTIFACT_WRITE_FAILED` |
| Debugging | `DEBUG_TRACE_NOT_FOUND` |
| Fallback | `INTERNAL_ERROR` |

`PROMPT_NOT_FOUND` and `SEND_BUTTON_NOT_FOUND` are internal content-runtime
diagnostics currently retried and collapsed into `PAGE_NOT_READY` at the stable
Broker boundary. `DOM_CHANGED` is not a current stable error code.

Handshake conditions also use `INCOMPATIBLE_PROTOCOL` and
`EXTENSION_ALREADY_CONNECTED`; an invalid Origin is rejected by the WebSocket
server. The Python client may raise client-side `INVALID_RESPONSE` for malformed,
oversized, or non-object Broker results. A connection closing before a final
response is also a client-side transport failure and must not be treated as
success.
