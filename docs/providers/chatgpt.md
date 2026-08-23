**English** | [简体中文](chatgpt.zh-CN.md)

# ChatGPT Web Provider

This provider exposes an already authenticated ChatGPT web tab through the
common Web LLM Bridge session model. The generic provider contract is documented
in [Provider Development](../provider-development.md); wire details are in
[Protocol](../protocol.md).

## Authentication and security boundary

The user signs in to ChatGPT in Chrome or Edge. The provider reuses that visible
browser session but does not read passwords, cookies, tokens, Local Storage, or
private conversation APIs. It does not use Playwright, Selenium, DevTools/CDP,
or clipboard access, and the extension manifest requests no clipboard
permission.

Do not place real conversation URLs, prompts, replies, or account data in test
fixtures or logs.

## Declared support

Python and extension definitions use provider ID `chatgpt`, default URL
`https://chatgpt.com/`, and hosts `chatgpt.com` and `www.chatgpt.com`.
The manifest declares Chrome 120 as its minimum version; current manual support
targets Chrome or Edge 120 and later with Manifest V3 enabled.

Declared capabilities are:

| Capability | Value |
| --- | --- |
| `chat` | `true` |
| `getMessages` | `true` |
| `history` | `true` |
| `fullHistory` | `true` |
| `markdown` | `true` |
| `latex` | `true` |
| `persistentConversation` | `true` |
| `artifacts` | `true` |
| `images` | `true` |

These capabilities describe browser-DOM behavior. They do not imply API-level
delivery guarantees or perfect reconstruction of virtualized history.

## URL and tab behavior

Only HTTPS URLs on the two allowed hosts match. Normalization removes query and
fragment components, removes trailing slashes from a non-root path, and keeps
the root as `/`. The `www` host is preserved rather than redirected in metadata.

Ordinary ChatGPT URLs do not contain an explicit port and callers should not
add one. The current Python normalizer reconstructs a URL without a port, while
the JavaScript normalizer uses `URL.origin`; behavior for an explicit port is
therefore not a supported parity case.

For an open operation, the extension attempts, in order:

1. the recorded tab, if its provider and normalized URL still match;
2. another existing tab with the same normalized URL; or
3. a newly created active tab.

`new: true` skips reuse and creates a new tab. The extension waits up to 30
seconds for the content script to answer `ping` before returning
`PAGE_NOT_READY`.

A persistent session record stores only the provider, session/tab IDs, current
URL, timestamps, sequence, and active flag. After a successful chat or history
read, the current tab URL is written back so navigation from the home page to
`/c/...` can be recovered later. Stale tabs are rebound before the next
operation; a chat is never replayed. If messaging fails after dispatch begins,
the provider returns `CHAT_STATE_UNKNOWN` and retry is unsafe.

## DOM profile

The current profile uses these signals:

| Purpose | Primary signals |
| --- | --- |
| Prompt | `#prompt-textarea`; visible content-editable textbox fallback |
| Send | `#composer-submit-button`, `data-testid=send-button`, or English `Send prompt` aria-label |
| Generation | Visible Stop button/test ID |
| Messages | `data-message-author-role` with `user` or `assistant` |
| Turn identity | `data-turn-id`, conversation-turn `data-testid`, then `data-turn`; per-node fallback last |
| Completion activity | Copy/message-action controls in English or Chinese |
| Tool/status activity | Tool, function, browser, search, code, thinking, live/status/log/busy selectors and status text |

Selectors are centralized in `extension/providers/chatgpt/profile.js`. A site
DOM release may invalidate them without changing any Python API.

### Prompt entry and submission

The content runtime first rejects a send while a visible Stop control indicates
generation. It then waits up to 30 seconds for a prompt and enabled Send control,
writes through DOM/native value semantics, dispatches an input event, and
verifies the normalized text before clicking.

After the click it waits up to 60 seconds for at least one submission signal:
a new user message, an empty prompt, active generation, or a changed assistant
node. Without evidence it returns `SEND_FAILED`. The `submitted` progress phase
is emitted only after this check.

### Activity, progress, and completion

The runtime observes relevant mutations under the main/message/tool/status
areas. Assistant text changes, activity snapshot changes, and completion-marker
changes also count as effective activity. Static Stop, tool, or status elements
do not repeatedly reset activity unless their relevant state changes.

Current timing values are:

| Setting | Value |
| --- | --- |
| Poll interval | 200 ms |
| Progress interval | 1,500 ms |
| Raw-text stability | 1,500 ms |
| Serialized completion confirmation | 3,000 ms |
| Page/send readiness | 30,000 ms |
| Submission confirmation | 60,000 ms |
| Response idle timeout | 300,000 ms |

Progress can report `working` before submission, then `submitted`, and while
waiting may report `thinking`, `working`, `tool_call`, or `streaming`. Progress
includes elapsed and idle milliseconds and is never a completion signal.

A response completes only when all of the following hold:

- the latest assistant has non-empty text or at least one ready Artifact;
- no active generation is detected;
- assistant text, Artifact signature, and effective page activity are stable for
  1.5 seconds;
- the serialized candidate remains unchanged for 3 seconds; and
- a final serialization of the current assistant node equals that candidate.

Completion-marker changes reset the candidate confirmation, but the marker is
not required to exist and its presence alone is not sufficient. If no effective
page activity occurs for five consecutive minutes, the runtime returns
`RESPONSE_TIMEOUT`, never partial text as success.

## Artifact extraction and materialization

Images are extracted only from assistant turns. Avatars, favicons, icons, tool
icons, decorative elements, loading placeholders, and user-uploaded images are
filtered. Sources are selected in this order: original/download resource,
original link, largest `srcset`, `currentSrc`, `src`, `data:`, then `blob:`;
quality is `unknown` when the original cannot be confirmed.

The adapter returns only the minimal descriptor plus private source fields. The
Broker creates the stable Artifact ID from `(provider, turn_id, index)`. A
`get-artifact` call resolves the turn/index again, polls readiness with a fixed
internal bound, refreshes an expired source, and then materializes through the
data/blob/HTTPS transfer path. Arbitrary URLs are never accepted.

## History behavior

The content runtime continuously captures rendered `user` and `assistant`
messages and caches `{role, content}` by turn identity. A longer rendering may
replace a shorter cached record. The cache resets when the page origin/path
changes, preventing turns from one conversation from leaking into another.

For a full or sufficiently large request, the runtime locates the nearest
scrollable message ancestor, scrolls upward in overlapping increments, captures
and deduplicates turns, then restores the original position (or follows the
bottom when the user was already near it). The history load deadline is 60
seconds and the poll interval is 250 ms.

Results are oldest to newest. `limit=N` returns the most recent N captured
messages. `full=true` attempts all history. `truncated=true` means the deadline
was reached. Virtualization, lazy loading, page visibility, and network speed can
still make a non-truncated result incomplete.

## Markdown and LaTeX

Generic serialization preserves readable text and supports headings,
paragraphs, bold/italic text, lists, block quotes, fenced preformatted text,
inline code, links, tables, horizontal rules, and line breaks.

The ChatGPT serializer reads `application/x-tex` annotations from Math/KaTeX
content and emits `$...$` or a `$$` block. It suppresses duplicate KaTeX HTML,
MathML, and MathJax presentation wrappers after extracting the TeX annotation.
It never clicks ChatGPT's Copy button.

### Known limitations

Known fidelity limits include images and non-text attachments, syntax-language
labels on code fences, code containing Markdown fence delimiters, complex nested
lists, row/column spans, interactive citations, MathJax structures without a
usable TeX annotation, and content not currently exposed in the DOM. Unknown
elements fall back to readable descendant text where possible.

## Errors and retry behavior

Callers should handle `PAGE_NOT_READY`, `INPUT_FAILED`, `BUSY`, `SEND_FAILED`,
`TAB_CLOSED`, `CHAT_STATE_UNKNOWN`, `RPC_TIMEOUT`, `RESPONSE_TIMEOUT`,
`CONTENT_SCRIPT_UNAVAILABLE`, `INVALID_URL`, and `INTERNAL_ERROR`.

`PROMPT_NOT_FOUND` and `SEND_BUTTON_NOT_FOUND` are internal retry diagnostics,
not stable Broker errors. `DOM_CHANGED` is not currently emitted. DOM breakage
normally appears as `PAGE_NOT_READY`, `SEND_FAILED`, `RESPONSE_TIMEOUT`, or an
incomplete best-effort history result.

Treat `safe_to_retry` as authoritative over message text. In particular:

- pre-dispatch `TAB_CLOSED` is marked true by tab lookup;
- post-dispatch tab/content-script/extension loss becomes
  `CHAT_STATE_UNKNOWN` with false; and
- all other errors default to false unless a future implementation explicitly
  proves retry safety.

## Manual authenticated-browser test

Use non-sensitive content and record Chrome/Edge version, extension commit,
ChatGPT locale, account/feature tier relevant to the run, page URL class, and
date.

1. Load the unpacked Manifest V3 extension, start the Broker, and confirm the
   extension completes protocol version 2 handshake.
2. Open `https://chatgpt.com/`; call `open`, then send a short prompt. Confirm the
   URL updates when ChatGPT navigates to `/c/...` and only one final response is
   returned.
3. Send a response long enough to stream. Verify `streaming` progress appears
   and the final result is not returned while text is still changing.
4. Run a prompt that invokes an available ChatGPT tool. Verify relevant DOM
   changes produce `tool_call`/`working` and a static completed tool card does
   not keep the request alive forever.
5. Test headings, emphasis, lists, quote, link, code, table, inline TeX, and block
   TeX. Compare returned Markdown to the visible answer without using Copy.
6. Call history with `limit`, with the public no-limit default, and with
   `full=true` in a long conversation. Verify order, deduplication, scroll
   restoration, and `truncated` behavior.
7. Open the same conversation in another tab and verify normalized-URL reuse.
   Then use `new=true` and verify a distinct tab/session is created.
8. Close a tab before `get_messages` and confirm the manager rebinds the stale
   tab before the read without exposing tab state in the result.
9. During a chat, close the tab or reload/disable the extension. Confirm the
   prompt is not automatically replayed and ambiguous dispatch is reported as
   `CHAT_STATE_UNKNOWN` with `safe_to_retry: false`.
10. Inspect `${WEB_LLM_BRIDGE_HOME:-~/.web-llm-bridge}/sessions` and process output; confirm
    no prompt, response, cookie, token, or password was stored or logged.

Last synthetic verification: 2026-08-22, Chrome/Edge Manifest V3 DOM smoke
fixtures. A real signed-in end-to-end pass is still required before claiming a
specific current ChatGPT page release as verified.

Assistant images are collected only from the Assistant turn. Avatars, icons,
loading placeholders, and user-uploaded images are ignored. Source selection
prefers an explicit original/download resource, then an original link, the
largest `srcset` candidate, `currentSrc`, `src`, `data:`, and finally `blob:`.
The adapter returns stable `(turn_id, index)` references and reports image
readiness in its internal signature so image-only replies can complete safely.
