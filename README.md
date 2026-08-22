# Web LLM Bridge

**English** | [简体中文](README.zh-CN.md)

![AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue.svg) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg) ![Alpha](https://img.shields.io/badge/status-alpha-orange.svg)

Web LLM Bridge turns authenticated LLM web applications into a simple local CLI interface that agents can call directly.

It handles browser-specific interaction such as DOM parsing, prompt submission, thinking and tool activity, streaming completion, response extraction, and persistent browser sessions. Codex, Claude Code, OpenClaw, Hermes, and custom agents can use the bridge without implementing site-specific browser logic. The current provider is **ChatGPT Web**.

## Why Web LLM Bridge?

Traditional shell agents are good at calling CLI tools, but interacting directly with LLM web applications is fragile. Without a bridge, an agent would need to understand changing DOM structures, locate editors and buttons, confirm submission, wait through thinking, tool calls, and streaming, detect final completion, extract Markdown or LaTeX, and recover tabs and conversations.

Web LLM Bridge moves that browser-specific complexity behind a small local interface. Agents only need to call:

```text
open
chat
get-messages
```

The web application keeps the conversation context. The bridge itself does not need a Provider API key because it uses the user's authenticated browser session; it does not bypass quotas, access controls, or verification.

## How It Works

```text
Local Agent / CLI
       |
       | NDJSON 127.0.0.1:8766
       v
Persistent Broker
       |
       | WebSocket 127.0.0.1:8765
       v
Browser Extension
       |
       v
Authenticated ChatGPT Web Tab
```

- The Broker maintains persistent sessions.
- The Extension handles browser DOM interaction.
- ChatGPT Web keeps the conversation context.

See [architecture.md](docs/architecture.md) for component boundaries and repository details.

## Quick Start

### Requirements

- Python 3.11+
- Chrome or Edge 120+

### Install

```console
git clone https://github.com/Tuzfucius/web-llm-bridge.git
cd web-llm-bridge
python -m pip install -e .
```

### Load the Extension

1. Open `chrome://extensions` or `edge://extensions`.
2. Enable Developer mode.
3. Choose **Load unpacked** and select [`extension/`](extension/).
4. Log in to ChatGPT normally in that browser profile.

### Start the Broker

```console
web-llm-broker serve
```

The installed `web-llm-agent` launcher can also start or reuse a local Broker when needed. The module fallback is `python -m web_llm_bridge.broker.server serve`.

### Scripts

The [`scripts/`](scripts/) directory provides cross-platform Python launchers:

- `python scripts/agent_cli.py ...` runs one Agent CLI command for an agent and starts or reuses the local Broker.
- `python scripts/manual_console.py` starts or reuses the Broker and opens a human-facing interactive console for directly selecting sessions, sending messages, and reading history.

For example:

```console
python scripts/agent_cli.py chat --text "Review this implementation" --json
python scripts/manual_console.py
```

### Chat

```console
web-llm-agent open --new --json
web-llm-agent chat --text "Reply with exactly: Hello from Web LLM Bridge" --json
cat prompt.md | web-llm-agent chat --stdin --json
```

Use `--session-id SESSION_ID` when an explicit persisted session is preferred.

## Agent Usage

Any local agent that can execute shell commands, write stdin, and read stdout can use Web LLM Bridge, including Codex, Claude Code, OpenClaw, Hermes, and custom agents.

Open a new conversation:

```console
web-llm-agent open --new --json
```

Open an existing conversation:

```console
web-llm-agent open --url "https://chatgpt.com/c/CONVERSATION_ID" --json
```

Send a prompt or a long prompt from stdin:

```console
web-llm-agent chat --text "Review this implementation" --json
cat prompt.md | web-llm-agent chat --stdin --json
```

Read recent messages or list persisted sessions:

```console
web-llm-agent get-messages --limit 5 --json
web-llm-agent list-sessions --json
```

With `--json`, stdout is one machine-readable JSON object and progress or diagnostics go to stderr.

```json
{"ok":true,"result":{"text":"..."}}
```

```json
{"ok":false,"error":{"code":"CHAT_STATE_UNKNOWN","message":"...","safe_to_retry":false}}
```

The bridge avoids automatically resending prompts when submission state is uncertain. See [protocol.md](docs/protocol.md) for error and retry semantics.

## Agent Skill

Web LLM Bridge ships a repository-maintained Agent Skill that teaches compatible local agents when and how to consult a Web LLM through the bridge. See [skills/web-llm-bridge/SKILL.md](skills/web-llm-bridge/SKILL.md).

## Supported Providers

- [x] ChatGPT Web — Alpha
- [ ] Grok Cloud — Planned
- [ ] Kimi — Planned
- [ ] DeepSeek — Planned
- [ ] Doubao — Planned
- [ ] Gemini — Planned
- [ ] Google AI Studio — Planned

The current release focuses on stabilizing the ChatGPT adapter before additional providers are added.

## Python API

```python
from web_llm_bridge import WebLLMSession

async with await WebLLMSession.open(new=True) as session:
    answer = await session.chat("Reply with 123")
```

## Documentation

- [Architecture](docs/architecture.md)
- [Protocol](docs/protocol.md)
- [Provider Development](docs/provider-development.md)
- [ChatGPT Provider](docs/providers/chatgpt.md)

## Limitations

- ChatGPT Web is currently the only supported provider.
- Browser DOM changes can break adapters.
- The bridge depends on an authenticated local Chrome or Edge session.
- Authentication remains in the user's browser. The bridge does not extract passwords, cookies, or tokens and does not use private Provider APIs, Playwright, Selenium, or CDP.
- This is an Alpha project.

## License

Web LLM Bridge is licensed under AGPL-3.0-only. See [LICENSE](LICENSE) for the full terms.
