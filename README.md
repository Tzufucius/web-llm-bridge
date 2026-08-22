# Web LLM Bridge

**English** | [简体中文](README.zh-CN.md)

![AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue.svg) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg) ![Alpha](https://img.shields.io/badge/status-alpha-orange.svg)

`web-llm-bridge` exposes an already authenticated supported LLM web page to local Python, shells, and agents. ChatGPT Web is the only implemented provider.

## Why Web LLM Bridge?

It gives an existing browser session a local control plane: the extension owns page DOM work and the Broker owns local sessions and NDJSON RPC. It is not a general gateway, OpenAI-compatible API, or login replacement.
The Bridge itself does not require a Provider API key because interaction stays
inside the user's existing authenticated browser session; it does not bypass
Provider quotas, limits, access controls, or verification.

## Architecture Diagram

```text
Local CLI / Python application / shell agent
                 | NDJSON over TCP, 127.0.0.1:8766
                 v
Persistent Broker -------- SessionStore (metadata only)
                 | WebSocket, 127.0.0.1:8765
                 v
Manifest V3 Extension -> authenticated ChatGPT Web tab
```

## Features

- NDJSON RPC, JSON output, stdin prompts; `open`, `chat`, `get_messages`; persistent registry, URL recovery, tab attach and optional reopen.
- Full progress phases (`submitted`, `thinking`, `working`, `tool_call`, `streaming`); idle timeout; Markdown/LaTeX and virtualized-history capture.
- At-most-once Broker delivery for `chat`: uncertain submission returns `CHAT_STATE_UNKNOWN` and is never automatically resent.

## Project Status

Alpha. Browser DOM is an external, changing dependency; callers must handle structured failures.

## Supported Providers

| Provider | Status | Persistent Session | History | Markdown/LaTeX |
| --- | --- | --- | --- | --- |
| ChatGPT Web | Supported / Alpha | Yes | Yes | Yes |
| Second provider validation | v0.2 planned | — | — | — |
| Gemini, Grok, DeepSeek, Kimi, Doubao, AI Studio | Planned / not implemented | — | — | — |

Planned Providers have no delivery date or compatibility commitment.

## Quick Start

### Install
```console
git clone https://github.com/Tuzfucius/web-llm-bridge.git
cd web-llm-bridge
python -m venv .venv
```
Windows PowerShell: `.venv\Scripts\Activate.ps1`
Linux/macOS: `source .venv/bin/activate`
```console
python -m pip install -U pip
python -m pip install -e .
```

### Load The Extension
1. Open `chrome://extensions` or `edge://extensions` and enable Developer mode.
2. Choose **Load unpacked**, select [`extension/`](extension/), then authenticate to ChatGPT yourself in that browser profile.

### First Session And Chat
```console
web-llm-broker serve
```

Keep that terminal open. If the installed console script is unavailable, use
`python -m web_llm_bridge.broker.server serve`. In a second terminal:

```console
web-llm-agent open --new --json
```
```json
{"session_id":"SESSION_ID","provider":"chatgpt","conversation_url":"https://chatgpt.com/c/CONVERSATION_ID","sequence":0}
```
```console
web-llm-agent chat --session-id SESSION_ID --text "Reply with exactly: Hello from Web LLM Bridge" --json
cat prompt.md | web-llm-agent chat --session-id SESSION_ID --stdin --json
```

For multiline prompts, source code, JSON, Markdown, and long Agent instructions,
stdin is recommended because it avoids shell quoting and command-line length limits.

## Using With Agents

`web-llm-agent` runs one `open`, `chat`, `get-messages`, or `list-sessions` action. It fits Codex, Claude Code, OpenClaw, Hermes, custom agents, and CI when they can invoke a shell command, supply stdin, and consume stdout. Successful `--json` output is one final result JSON object on stdout; progress is stderr. Failure is a human-readable `Error: ...` on stderr, not guaranteed JSON stdout. Raw Broker errors are structured NDJSON with `code`, `message`, and `safe_to_retry`; progress and the final response share `id`.

```json
{"id":"req-123","ok":false,"error":{"code":"CHAT_STATE_UNKNOWN","message":"...","safe_to_retry":false}}
```

### At-most-once prompt submission

If the Extension, tab, or browser becomes unreachable after sending and the system cannot prove that the prompt was not submitted, the call returns `CHAT_STATE_UNKNOWN` instead of resending. `safe_to_retry: false` means an agent must not automatically repeat the original prompt. Inspect the Conversation or call `get-messages` before deciding whether another prompt is appropriate.

## Persistent Session Model

Session ID is the stable local handle; tab ID identifies the current browser runtime tab; Conversation URL is the persistent recovery identity. A tab can change while the Conversation remains the same. Context is maintained by the ChatGPT Web Conversation itself: the Bridge does not reconstruct and resend the full history for every request. Registry data excludes prompts, replies, cookies, tokens, and passwords; deleting it does not delete browser conversations.

## CLI Reference
```console
web-llm-agent open --new --json
web-llm-agent open --url https://chatgpt.com/c/CONVERSATION_ID --json
web-llm-agent list-sessions --json
web-llm-agent get-messages --session-id SESSION_ID --limit 5 --json
web-llm-bridge
```

## Python API
```python
from web_llm_bridge import WebLLMSession

async with await WebLLMSession.open(new=True) as session:
    answer = await session.chat("Reply with 123")
    history = await session.get_messages(limit=5)
```

## Architecture

The extension owns selectors, input, submission evidence, completion, and serialization. The Broker owns its one extension connection, session serialization, errors, and metadata persistence. Python providers remain DOM-free. See [architecture](docs/architecture.md) and [protocol](docs/protocol.md).

### Repository Layout

```text
web_llm_bridge/              Python transport, session, Broker, client, and CLI
extension/core/              Provider-independent browser runtime
extension/providers/chatgpt/ ChatGPT DOM adapter and serializer
scripts/                     Cross-platform manual and Agent launchers
tests/                       Protocol, session, CLI, and browser-runtime regressions
docs/                        Architecture, protocol, and Provider documentation
examples/                    Minimal Python and Agent CLI examples
```

## Security Model

No password, cookie, token, clipboard data, private API, Playwright, Selenium, CDP, CAPTCHA bypass, or quota/access-limit bypass is used. Authentication remains in the browser. Broker uses `127.0.0.1:8766`; extension transport uses `127.0.0.1:8765`; neither is a remote service or authorization boundary.

## Runtime Data

Home is `~/.web-llm-bridge` or `WEB_LLM_BRIDGE_HOME`. `sessions/` contains recovery metadata, while `runtime/` contains `broker.pid`, `broker.stdout.log`, and `broker.stderr.log`. The Bridge does not store full Conversation text there. Treat this as sensitive local state because Session records include Conversation URLs.

## Limitations

One registered extension is active at a time. Lines are limited to 8 MiB. DOM changes, closed tabs, unavailable extensions, and timeouts are expected failures. Open has 30 seconds, history 70 seconds, and chat five minutes of continuous inactivity, reset by progress.

## Contributing

Contributions are welcome. Before changing browser adapters or adding a Provider, read [CONTRIBUTING.md](CONTRIBUTING.md), [architecture](docs/architecture.md), and [Provider development](docs/provider-development.md). Chinese documentation is available in [CONTRIBUTING.zh-CN.md](CONTRIBUTING.zh-CN.md), [架构](docs/architecture.zh-CN.md), and [Provider 开发](docs/provider-development.zh-CN.md).

## Roadmap
1. Stabilize ChatGPT capabilities, errors, and protocol behavior for v0.1.
2. Validate a second-provider adapter contract in v0.2, without promising an implementation.
3. Improve redacted diagnostics and protocol negotiation while retaining local defaults.

## License

Web LLM Bridge is licensed under the GNU Affero General Public License v3.0 only (`AGPL-3.0-only`). When distributing a modified covered version, you must provide Corresponding Source as required by the AGPL. When a modified covered program offers interaction to users over a network, Section 13 requires an opportunity to receive that version's Corresponding Source. Whether a separate program forms a covered combination or derivative work depends on the license text, applicable law, and the relevant facts. The [LICENSE](LICENSE) file is the authoritative legal text.
