# Web LLM Bridge

[English](README.md) | **简体中文**

![AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue.svg) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg) ![Alpha](https://img.shields.io/badge/status-alpha-orange.svg)

Web LLM Bridge 将已登录的大语言模型 Web 页面桥接为可由 Agent 直接调用的简单本地 CLI 接口。

它在内部处理浏览器 DOM、Prompt 提交、Thinking 与 Tool Call、流式完成、回复提取和持久化浏览器 Session。Codex、Claude Code、OpenClaw、Hermes 以及自定义 Agent 无需自行实现站点相关的浏览器逻辑。当前支持的 Provider 是 **ChatGPT Web**。

## 为什么使用 Web LLM Bridge？

传统 Shell Agent 擅长调用 CLI，但直接操作 LLM Web 页面很脆弱。没有 Bridge 时，Agent 需要自行理解不断变化的 DOM，定位编辑器和按钮，确认提交，等待 Thinking、Tool Call 和 Streaming，判断最终完成，提取 Markdown 或 LaTeX，并恢复标签页和 Conversation。

Web LLM Bridge 将这些网页细节封装在简单的本地接口之后。Agent 只需要调用：

```text
open
chat
get-messages
```

对话上下文继续由 Web 应用自身维护。Bridge 不需要 Provider API key，而是使用用户已认证的浏览器 Session；它不会绕过 Provider 的配额、访问控制或验证。

## 工作方式

```text
本地 Agent / CLI
       |
       | NDJSON 127.0.0.1:8766
       v
持久化 Broker
       |
       | WebSocket 127.0.0.1:8765
       v
浏览器扩展
       |
       v
已认证的 ChatGPT Web 标签页
```

- Broker 维护持久化 Session。
- Extension 处理浏览器 DOM 交互。
- ChatGPT Web 保存 Conversation 上下文。

组件边界和仓库结构见[架构文档](docs/architecture.zh-CN.md)。

## 快速开始

### 环境要求

- Python 3.11+
- Chrome 或 Edge 120+

### 安装

```console
git clone https://github.com/Tuzfucius/web-llm-bridge.git
cd web-llm-bridge
python -m pip install -e .
```

### 加载扩展

1. 打开 `chrome://extensions` 或 `edge://extensions`。
2. 开启开发者模式。
3. 选择**加载已解压的扩展程序**，并选择 [`extension/`](extension/)。
4. 在该浏览器配置中正常登录 ChatGPT。

### 启动 Broker

```console
web-llm-broker serve
```

安装后的 `web-llm-agent` 入口在需要时也会启动或复用本机 Broker。模块备用命令是 `python -m web_llm_bridge.broker.server serve`。

需要浏览器 RPC 时，Broker 可以启动或唤醒配置的日常浏览器，并等待 Extension 握手。持久化 Session 可以关闭和恢复，图片 Artifact 可以获取为本地文件。

### Scripts

[`scripts/`](scripts/) 目录提供跨平台 Python 启动脚本：

- `python scripts/agent_cli.py ...` 面向 Agent 执行一次 CLI 命令，并启动或复用本机 Broker。
- `python scripts/manual_console.py` 启动或复用 Broker，然后进入面向人类用户的交互式控制台，可直接选择 Session、发送消息和读取历史。

例如：

```console
python scripts/agent_cli.py chat --text "Review this implementation" --json
python scripts/manual_console.py
```

### 对话

```console
web-llm-agent open --new --json
web-llm-agent chat --text "Reply with exactly: Hello from Web LLM Bridge" --json
cat prompt.md | web-llm-agent chat --stdin --json
```

需要明确指定持久化 Session 时，可使用 `--session-id SESSION_ID`。

## Agent 使用方式

任何能够执行 Shell 命令、写入 stdin 并读取 stdout 的本地 Agent 都可以使用 Web LLM Bridge，包括 Codex、Claude Code、OpenClaw、Hermes 和自定义 Agent。

新建 Conversation：

```console
web-llm-agent open --new --json
```

打开已有 Conversation：

```console
web-llm-agent open --url "https://chatgpt.com/c/CONVERSATION_ID" --json
```

发送 Prompt 或通过 stdin 发送长 Prompt：

```console
web-llm-agent chat --text "Review this implementation" --json
cat prompt.md | web-llm-agent chat --stdin --json
```

读取最近消息或列出持久化 Session：

```console
web-llm-agent get-messages --limit 5 --json
web-llm-agent list-sessions --json
```

关闭或遗忘持久化 Session，或获取 ChatGPT 回复中的图片 Artifact：

```console
web-llm-agent close-session --session-id SESSION_ID --json
web-llm-agent forget-session --session-id SESSION_ID --json
web-llm-agent get-artifact --id ARTIFACT_ID --json
```

指定 `--json` 后，stdout 始终输出一个可供机器解析的 JSON 对象，进度和诊断信息输出到 stderr。

```json
{"ok":true,"result":{"text":"..."}}
```

```json
{"ok":false,"error":{"code":"CHAT_STATE_UNKNOWN","message":"...","safe_to_retry":false}}
```

当提交状态不确定时，Bridge 不会自动重发 Prompt。错误和重试语义见[协议文档](docs/protocol.zh-CN.md)。

## Agent Skill

Web LLM Bridge 附带可选的 Agent Skill，用于指导兼容的本地 Agent 何时以及如何通过 `web-llm-agent` 咨询 Web LLM。不安装 Skill 也不影响 CLI 使用。

可为当前项目或当前用户安装：

```console
web-llm-bridge install --skills
web-llm-bridge install --skills -g
```

canonical 源码位于 [`skills/`](skills/)。修改后运行 `python scripts/sync_skill_bundle.py` 重新生成打包镜像。详见 [skills/web-llm-bridge/SKILL.md](skills/web-llm-bridge/SKILL.md)。

## 支持的 Provider

- [x] ChatGPT Web — Alpha
- [ ] Grok Cloud — Planned
- [ ] Kimi — Planned
- [ ] DeepSeek — Planned
- [ ] 豆包 — Planned
- [ ] Gemini — Planned
- [ ] Google AI Studio — Planned

当前版本将优先稳定 ChatGPT Adapter，再增加其他 Provider。

## Python API

```python
from web_llm_bridge import WebLLMSession

async with await WebLLMSession.open(new=True) as session:
    answer = await session.chat("Reply with 123")
```

## 文档

- [架构](docs/architecture.zh-CN.md)
- [协议](docs/protocol.zh-CN.md)
- [Provider 开发](docs/provider-development.zh-CN.md)
- [ChatGPT Provider](docs/providers/chatgpt.zh-CN.md)

## 限制

- 当前仅支持 ChatGPT Web。
- 浏览器 DOM 变化可能导致 Adapter 失效。
- Bridge 依赖已认证的本机 Chrome 或 Edge Session。
- 认证始终保留在用户浏览器中。Bridge 不提取密码、Cookie 或 Token，不使用 Provider 私有 API、Playwright、Selenium 或 CDP。
- 项目处于 Alpha 阶段。

## 许可证

Web LLM Bridge 采用 AGPL-3.0-only。完整条款见 [LICENSE](LICENSE)。
