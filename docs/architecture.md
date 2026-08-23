**English** | [简体中文](architecture.zh-CN.md)

# Architecture

## Goal

Web LLM Bridge uses an already authenticated browser page as the execution
surface and a local Python process as the control plane. Python does not start
the browser, attach a debugging protocol, or inject credentials. All page
interaction runs in the Manifest V3 extension on a tab opened by the user or by
the extension.

The public abstraction is a provider-neutral browser session, not an OpenAI API
emulator. Site-specific DOM knowledge stays in the extension.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `web_llm_bridge/` | Python protocol, transport, Provider metadata, Session management, Broker, Client, and CLI. |
| `extension/core/` | Provider-independent browser runtime, routing, history, Markdown, RPC, and tab mechanics. |
| `extension/providers/` | Site-specific profiles, DOM Adapters, and serializers. |
| `tests/` | Python architecture/protocol regressions and synthetic Extension smoke tests. |
| `docs/` | Architecture, protocol, Provider contracts, and implementation assumptions. |
| `examples/` | Minimal Python and Agent CLI usage. |
| `scripts/` | Cross-platform manual-console and Agent CLI launchers. |

## Process topology

```text
CLI / local agent / WebLLMSession
              |
              | NDJSON over TCP, 127.0.0.1:8766
              v
Persistent Broker
  SessionManager ---- SessionStore (metadata only)
        |
        | one ExtensionTransport
        | WebSocket, 127.0.0.1:8765
        v
Manifest V3 extension
  service worker ---- provider registry / tab routing
        |
        v
content runtime ---- provider adapter ---- authenticated web page
```

Both listeners bind to the loopback interface. They are local IPC boundaries,
not remotely exposed service APIs.

## Ownership boundaries

### Client and session handle

`WebLLMClient` sends one Broker RPC per connection. `WebLLMSession` is a small,
Broker-backed handle containing `provider`, `session_id`, and
`conversation_url`. It does not own a tab, a WebSocket, the Broker process, or
credentials. Leaving its async context does not close any shared resource.

`close_session` closes only the Tab bound to a persisted Session and keeps its
Conversation URL and sequence. `forget_session` additionally removes local
metadata; neither operation deletes a cloud Conversation. `SessionManager.close()`
still exists only to shut down the Broker-owned transport during Broker teardown.

Browser bootstrap is deliberately below the CLI. Before a browser RPC the
manager starts the Extension listener, waits through a short reconnect grace,
and, under one async launch lock, opens the configured daily browser only when
the Extension has not completed its WebSocket handshake. Browser process
presence is never used as a readiness signal. A Session is rebound by its
Conversation URL before a new prompt is dispatched, while post-dispatch errors
remain at-most-once and are never replayed automatically.

### Broker and SessionManager

The Broker is the only Python process that listens for the extension. It:

- validates and dispatches local NDJSON requests;
- owns one `SessionManager`, one provider registry, one `SessionStore`, and one
  `ExtensionTransport`;
- rewrites extension progress into Broker progress correlated to the caller's
  request ID;
- converts typed failures into stable error objects; and
- rejects responses that would exceed the 8 MiB NDJSON line limit.

`SessionManager` owns orchestration and recovery policy. Its current single
`asyncio.Lock` serializes all `open`, `chat`, and `get_messages` operations for
the manager, including operations for different sessions or providers.
`list_sessions` only reads metadata and does not acquire that lock.

The Broker does not intentionally persist prompts or response bodies and is not
a remote proxy.

### Session and SessionStore

A session is a durable binding record, not a copy of a web conversation. The
store persists schema version, provider ID, session ID, tab ID, current URL,
creation/update timestamps, sequence, and active status. Legacy JSON is
normalized to this reduced structure when read. Only one stored record per
provider is active.

`sequence` is incremented and persisted before each chat dispatch. It therefore
counts chat attempts, including attempts that later fail; it is not proof that a
message was accepted by the page. Public results do not expose `tab_id`,
`active`, transport `request_id`, or private Artifact sources.

The store contains neither message bodies nor authentication material. Removing
the local registry does not delete a conversation on the provider website.

### Python provider definition

A Python `ProviderDefinition` is immutable, static metadata: `id`,
`default_url`, allowed `hosts`, `capabilities`, and HTTPS URL normalization. It
has no DOM selectors, connection state, or `open`/`chat`/`get_messages` methods.

`SessionManager`, rather than a provider instance, invokes the shared
`ExtensionTransport`. This keeps provider registration separate from transport
ownership and prevents each provider from opening another listener.

### ExtensionTransport

The Broker-owned transport is the only listener on `127.0.0.1:8765`. It accepts
one active extension connection, checks the Chrome-extension Origin and protocol
version, correlates requests and responses, filters progress phases, and manages
timeouts. Its request IDs are internal transport IDs; they are not required to
equal the caller's NDJSON request IDs.

For chat, accepted progress resets the transport wait deadline. The content
runtime independently enforces the five-minute effective-page-activity timeout,
so heartbeat-style progress cannot turn an inactive page into a successful
completion.

### Extension core and provider adapter

The service worker owns the Broker connection and tab routing. The content
runtime owns generic input, submission confirmation, progress production,
completion waiting, history capture, and Markdown traversal.

The extension provider supplies site-specific metadata and behavior:

- URL matching and normalization;
- selectors and prompt/send/generation discovery;
- message roles, turn identity, completion markers, and activity snapshots; and
- special serialization such as ChatGPT KaTeX extraction.

The extension never needs passwords, cookies, tokens, private conversation
APIs, DevTools/CDP, or clipboard access.

### Artifact layer

Provider adapters expose image Artifacts as stable descriptors. The Broker
stores private source metadata locally and returns only provider-neutral fields
such as `id`, `kind`, `turn_id`, dimensions, MIME type, and quality. Bytes are
materialized only by `get-artifact`: public HTTPS sources use stdlib download,
`data:` sources are decoded locally, and `blob:` sources are transferred from
the content script in bounded 256 KiB chunks. Transfers are size- and MIME-
checked, hashed with SHA-256, and atomically renamed into the Artifact store.

## Dependency direction

```text
CLI / WebLLMSession -> Broker client -> Broker server -> SessionManager
                                                   |-> SessionStore
                                                   |-> ProviderRegistry
                                                   `-> ExtensionTransport
                                                          |
                                                          v
extension core -> extension provider adapter -> page DOM
```

CLI formatting must not leak into providers. Python provider definitions must
not depend on the CLI or extension DOM modules. Generic extension core may call
the registered adapter, but an adapter must not own the Broker transport.

## Chat request lifecycle

1. The client creates a non-empty string `id` and sends one UTF-8 JSON object as
   an NDJSON line to `127.0.0.1:8766`.
2. The Broker validates the envelope, then `SessionManager` acquires the global
   operation lock and resolves or creates a session record.
3. Before dispatch, the manager increments the stored session `sequence`.
4. `ExtensionTransport` creates its own request ID and sends the operation to
   the service worker, which verifies the requested provider against the tab URL
   and forwards it to the content script.
5. The content runtime writes the prompt, clicks Send, and waits for submission
   evidence. Only then does it emit `submitted`.
6. While waiting for final content, the extension emits allowed progress phases.
   The transport correlates them to its pending call; the Broker re-emits them
   with the original NDJSON `id`.
7. After stable final content, the response travels back through the same
   layers. The manager updates the URL and session metadata, releases the lock,
   and the Broker sends exactly one final response.

Progress is observational. It never constitutes success and never replaces the
final response.

## Failure and retry invariants

Chat is a side-effecting operation. Once dispatch to the content script has
started, a tab closure or messaging failure may leave submission state unknown.
The extension maps that ambiguity to `CHAT_STATE_UNKNOWN` with
`safe_to_retry: false`. Neither `SessionManager` nor the client resends the
prompt automatically.

If a closed tab is known before content dispatch, the extension can report
`TAB_CLOSED` with `safe_to_retry: true`. The manager rebinds stale tabs before
the next operation. For `chat`, a failure after dispatch still raises the
original ambiguity and never replays the prompt.

All errors are failures, even when `safe_to_retry` is true. The flag only states
whether repeating that same RPC is known not to duplicate a page-side effect at
the boundary where the error was produced.
