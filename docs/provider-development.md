**English** | [简体中文](provider-development.zh-CN.md)

# Provider Development

A provider maps the common session operations onto a website that the user has
already authenticated in the browser. Before adding one, confirm that the
website permits the intended automation and that the user has explicitly
authorized it.

## Non-negotiable boundaries

### Python: static definition only

Python providers are immutable `ProviderDefinition` values. They contain:

- a unique `id`;
- an HTTPS `default_url`;
- an allowed `hosts` set; and
- a read-only `capabilities` mapping.

The base `normalize_url()` strips surrounding whitespace, requires HTTPS and an
allowed hostname, drops query and fragment data, removes trailing path slashes,
and preserves `/` for the root URL. Invalid types produce `INVALID_ARGUMENT`;
unsupported URLs produce `INVALID_URL`.

A Python provider does **not** implement `open`, `chat`, `get_messages`, or
`close`. It must not contain selectors, DOM parsing, CLI formatting, credentials,
or runtime connection state. `SessionManager` owns these operations and calls
the one shared `ExtensionTransport` with the provider ID.

### Session: durable binding and policy

Session code owns record selection, the global operation lock, metadata
persistence, sequence increments, and the explicit `reopen_on_closed` policy.
It does not know prompt selectors or how a site represents messages.

Recovery must respect side effects. `get_messages` may rebind and retry once
after a pre-dispatch `TAB_CLOSED` when the policy is enabled. `chat` may prepare
a new binding for later calls but must never replay the original prompt after an
error.

### Transport: one connection owner

`ExtensionTransport` owns the only extension listener, connection handshake,
internal request IDs, pending futures, accepted progress phases, and timeouts.
No provider may create another transport or listen on the extension port.

The service worker verifies that the requested provider exists and matches the
actual tab URL before forwarding an operation. A provider mismatch is
`INVALID_URL`, not a reason to run the wrong adapter.

### Extension: DOM behavior

Only the extension provider profile and adapter know site DOM details. Generic
extension core owns the reusable input, submission, completion, history, and
Markdown algorithms and calls the registered adapter for site-specific facts.

## Provider contract

Each provider must satisfy both halves of this contract.

### Python definition contract

| Item | Requirement |
| --- | --- |
| Identity | `id` is unique in `ProviderRegistry` and matches the extension profile ID exactly. |
| Default URL | HTTPS and accepted by both Python and extension URL matching. |
| Hosts | Explicit allowlist; do not accept suffix matches or arbitrary redirects. |
| Capabilities | Boolean, read-only declarations of behavior actually implemented and tested. |
| Runtime state | None. Definitions remain frozen and transport-independent. |

Register the definition in `web_llm_bridge/providers/registry.py`. Duplicate IDs
must fail rather than silently replace an existing provider.

### Extension profile contract

The profile registered with `registerProvider()` must expose:

| Member | Requirement |
| --- | --- |
| `id` | Same unique ID as Python. |
| `defaultUrl`, `hosts`, `capabilities` | Semantically match the Python definition. |
| `matchesUrl(value)` | Return true only for supported HTTPS pages. |
| `normalizeUrl(value)` | Produce the same stable URL class as Python normalization. |
| `timing` | Explicit page-ready, polling, submission, completion, response-idle, progress, and history timeouts required by the generic runtime. |
| `selectors` | Centralized prompt, send, generation, completion, message, role, tool, and status selectors. |
| `adapter` | Implement the runtime methods below. |

Keep Python and JavaScript URL normalization equivalent. Query, fragment,
trailing-slash, alternate-host, and invalid-scheme cases need paired tests.

### Extension adapter contract

| Member | Behavior |
| --- | --- |
| `findPrompt()` | Return a visible usable prompt element, or null while unavailable. |
| `findSendButton()` | Return a visible send control. Generic core checks enabled state. |
| `isEnabled(button)` | Reject disabled and `aria-disabled` controls. |
| `isGenerating()` | Report active generation. A permanently present control must not make this permanently true. |
| `getMessages()` | Return currently rendered message nodes in DOM order. |
| `getUsers()`, `getLastAssistant()` | Support submission evidence and final-response selection. |
| `getRole(node)` | Return only roles understood by history (`user` or `assistant`). |
| `findTurnContainer(node)`, `turnAttributes` | Provide stable turn identity for deduplication; the generic runtime has only a per-node fallback. |
| `hasCompletionMarker(node)` | Detect site completion UI used as an activity/confirmation signal. It is not, by itself, proof of final content. |
| `activitySnapshot()` | Return a stable `signature` and `toolCall` boolean so actual tool/status changes count as activity. |
| `isActivityNode()`, `isActivitySubtree()` | Limit MutationObserver activity to relevant page areas; unrelated DOM animation must not reset response idle time. |
| `serializer.serializeElement(element)` | Optionally serialize provider-specific structures; return `undefined` to fall back to generic Markdown traversal. |

## Behavioral requirements

### Prompt entry and send

Generic core supports content-editable controls and native value controls. It
dispatches input events, verifies the normalized written text, waits for an
enabled send button, and clicks it. A provider must not use the clipboard,
DevTools/CDP, private APIs, or authentication data as a shortcut.

Missing prompt/send elements and input failures are retried during the page-ready
window. Exhaustion is exposed as `PAGE_NOT_READY`; selector-specific
`PROMPT_NOT_FOUND` and `SEND_BUTTON_NOT_FOUND` remain internal diagnostics.

### Submission detection

Clicking Send is not submission proof. Within the submission window, at least
one of these must be observed: a new user message, an emptied prompt, active
generation, or a changed assistant node. Otherwise return `SEND_FAILED`.

Do not emit `submitted` until this confirmation succeeds.

### Generation, progress, and completion

Activity must be based on relevant DOM mutation, assistant text, tool/status
snapshot change, or completion-marker change. Emit only `submitted`, `thinking`,
`working`, `tool_call`, or `streaming`. Progress is observational and must never
be treated as the result.

Completion requires non-empty assistant content, no active generation, stable
raw text, a stable serialized candidate, and a final re-read that matches that
candidate. A completion marker may reset confirmation when it changes, but its
mere presence is insufficient. On response-idle timeout, return
`RESPONSE_TIMEOUT`, never a partial success.

### History and turn identity

History capture returns `{role, content}` ordered oldest to newest. It caches by
stable turn identity, updates a record only when content grows, resets on an
origin/path change, and restores the original scroll position after collection.

Full history is best effort. The adapter must support incremental upward
scrolling of virtualized lists and overlap deduplication. Set `truncated: true`
when the load deadline is reached. A false value cannot promise the website made
all history available.

### Serialization

Generic serialization covers headings, paragraphs, emphasis, lists, quotes,
preformatted/code text, links, tables, horizontal rules, and line breaks. A
provider serializer should add only site-specific structures such as TeX.
Unknown structures should retain readable text rather than trigger Copy buttons
or clipboard writes.

## Error and retry contract

Every error crossing the extension boundary includes `code`, `message`, and
`safe_to_retry`. The default is false. Only mark true when repeating the exact
RPC is known not to duplicate a side effect.

For `chat`, failures after dispatch involving a closed tab, unavailable content
script, or lost extension messaging must become `CHAT_STATE_UNKNOWN` with
`safe_to_retry: false`. Do not leak the lower-level transport error in a way that
encourages automatic resubmission.

Pre-dispatch `TAB_CLOSED` may be marked safe. Read-only recovery remains a
SessionManager policy; the provider adapter must not reopen or retry tabs on its
own.

## Wiring a new provider

1. Add and register the Python `ProviderDefinition`.
2. Add an extension profile, special serializer if needed, and adapter.
3. Load the profile and adapter in both `service_worker.js` and the manifest
   content-script list, in dependency order.
4. Add the provider hosts to `host_permissions` and content-script `matches`.
5. Keep Python and extension metadata, URL behavior, capabilities, and IDs in
   sync.
6. Add provider documentation and focused tests without weakening security
   boundaries.

## Verification checklist

- Python tests cover immutable metadata, duplicate registration, URL
  normalization/rejection, and capability parity.
- Fake-transport tests cover open, chat, history, active-session selection,
  global serialization, sequence behavior, and recovery policy.
- DOM fixtures cover prompt discovery, native/content-editable input, send
  readiness, submission evidence, and `SEND_FAILED`.
- DOM fixtures cover long thinking, tools, streaming, completion confirmation,
  idle timeout, and every progress phase used by the provider.
- History fixtures cover stable IDs, overlapping virtualized windows, URL reset,
  limits, full history, truncation, and scroll restoration.
- Serializer fixtures cover every declared format and readable fallback.
- Tab-routing tests distinguish safe pre-dispatch `TAB_CLOSED` from unsafe
  post-dispatch `CHAT_STATE_UNKNOWN`.
- Logs, fixtures, and session files contain no credentials, real conversation
  URLs, prompts, or response bodies.
- Broker network tests remain independent of provider DOM fixtures.

## Manual browser test

Record the browser version, extension version/commit, provider account state,
page URL class, locale, and date. Use non-sensitive test text.

1. Load the unpacked extension and start the Broker; confirm exactly one
   extension connects.
2. Open the provider home page and an existing conversation; verify URL
   normalization and tab reuse/new-tab behavior.
3. Send a short prompt and observe submission, progress, and one complete final
   response.
4. Exercise a long response and, if supported, a tool call; verify the operation
   does not finish on partial streaming text or a static status element.
5. Read current, limited, and full history; inspect ordering, deduplication,
   truncation, scroll restoration, Markdown, and special serialization.
6. Close the tab before a read, then during a chat. Confirm recovery policy for
   the read and confirm the chat prompt is never automatically replayed.
7. Disable or reload the extension during chat and verify the resulting error
   communicates unknown chat state rather than retry safety.
8. Inspect the session registry and logs for prompts, responses, cookies, tokens,
   and other secrets.

Synthetic DOM tests do not replace this manual authenticated-browser pass.

## Release constraints

Update capability lists, protocol documentation, provider directory docs, and
security boundaries when adding a provider. If code lives in a private
submodule, pin a reproducible commit and test submodule availability in CI.
Credentials belong in Git configuration, never Python configuration or the
browser extension.
