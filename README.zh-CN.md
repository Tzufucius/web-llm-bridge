# Web LLM Bridge

[English](README.md) | **简体中文**

![AGPL-3.0-only](https://img.shields.io/badge/license-AGPL--3.0--only-blue.svg) ![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg) ![Alpha](https://img.shields.io/badge/status-alpha-orange.svg)

`web-llm-bridge` 将已在受支持 LLM 网页中认证的页面提供给本机 Python、Shell 和 Agent 使用。当前唯一已实现的 Provider 是 ChatGPT Web。

## 为什么使用 Web LLM Bridge？

它为现有浏览器会话提供本地控制面：扩展负责页面 DOM 工作，Broker 负责本地会话和 NDJSON RPC。本项目不是通用网关、OpenAI 兼容 API 或登录流程替代品。
Bridge 本身不需要 Provider API key，因为交互始终位于用户现有的已认证浏览器会话中；
它不会绕过 Provider 的配额、限制、访问控制或验证。

## 架构图

```text
本地 CLI / Python 应用 / Shell Agent
                 | NDJSON over TCP，127.0.0.1:8766
                 v
常驻 Broker ---------------------- SessionStore（仅元数据）
                 | WebSocket，127.0.0.1:8765
                 v
Manifest V3 Extension -> 已认证的 ChatGPT Web 标签页
```

## 功能

- NDJSON RPC、JSON 输出、stdin 提示词；`open`、`chat`、`get_messages`；持久化 registry、URL 恢复、标签页附加和可选重开。
- 完整进度阶段（`submitted`、`thinking`、`working`、`tool_call`、`streaming`）；空闲超时；Markdown/LaTeX 与虚拟化历史捕获。
- `chat` 在 Broker 视角为至多一次投递：提交状态不确定时返回 `CHAT_STATE_UNKNOWN`，绝不自动重发。

## 项目状态

项目处于 alpha 阶段。浏览器 DOM 是会变化的外部依赖，调用方必须处理结构化失败。

## 支持的 Provider

| Provider | 状态 | 持久会话 | 历史 | Markdown/LaTeX |
| --- | --- | --- | --- | --- |
| ChatGPT Web | Supported / Alpha | 是 | 是 | 是 |
| 第二 Provider 验证 | 计划于 v0.2 | — | — | — |
| Gemini、Grok、DeepSeek、Kimi、Doubao、AI Studio | 已规划 / 尚未实现 | — | — | — |

未来 Provider 不承诺交付时间或兼容性。

## 快速开始

### 安装
```console
git clone https://github.com/Tuzfucius/web-llm-bridge.git
cd web-llm-bridge
python -m venv .venv
```
Windows PowerShell：`.venv\Scripts\Activate.ps1`

Linux/macOS：`source .venv/bin/activate`
```console
python -m pip install -U pip
python -m pip install -e .
```

### 加载扩展
1. 打开 `chrome://extensions` 或 `edge://extensions`，并开启开发者模式。
2. 选择**加载已解压的扩展程序**，选择 [`extension/`](extension/)，然后在该浏览器配置中自行登录 ChatGPT。

### 创建首个会话并对话
```console
web-llm-broker serve
```

保持该终端运行。如果安装后的命令暂不可用，可执行
`python -m web_llm_bridge.broker.server serve`。在第二个终端中执行：

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

多行 Prompt、源代码、JSON、Markdown 和较长的 Agent 指令建议使用 stdin，以避免 Shell
引号和命令行长度限制。

## 与 Agent 配合使用

`web-llm-agent` 每个进程执行一次 `open`、`chat`、`get-messages` 或 `list-sessions`。适用于能调用 Shell 命令、提供 stdin 并读取 stdout 的 Codex、Claude Code、OpenClaw、Hermes、自定义 Agent 和 CI。成功使用 `--json` 时，stdout 输出一个最终结果 JSON 对象；进度输出到 stderr。失败时 CLI 在 stderr 写入人类可读的 `Error: ...`，不保证 stdout 为 JSON。原始 Broker 错误是包含 `code`、`message`、`safe_to_retry` 的结构化 NDJSON；进度与最终响应共享 `id`。

```json
{"id":"req-123","ok":false,"error":{"code":"CHAT_STATE_UNKNOWN","message":"...","safe_to_retry":false}}
```

### 至多一次提示词提交

发送后如果 Extension、标签页或浏览器失联，而系统无法证明 Prompt 尚未提交，调用会返回 `CHAT_STATE_UNKNOWN`，而不是重新发送。`safe_to_retry: false` 表示 Agent 不得自动重复原 Prompt。请先检查 Conversation 或调用 `get-messages`，再决定是否发送另一条提示词。

## 持久会话模型

Session ID 是稳定的本地句柄；tab ID 标识当前浏览器运行时标签页；Conversation URL 是持久恢复标识。标签页可以变化，而 Conversation 保持不变。上下文由 ChatGPT Web Conversation 本身维护，Bridge 不会为每次请求重建并重发完整历史。Registry 不包含 Prompt、回复、Cookie、Token 或密码；删除 Registry 不会删除浏览器 Conversation。

## CLI 参考
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

## 架构

扩展负责 selector、输入、提交证据、完成判断和序列化。Broker 负责唯一扩展连接、会话串行化、错误和元数据持久化。Python Provider 保持无 DOM。详见[架构](docs/architecture.zh-CN.md)和[协议](docs/protocol.zh-CN.md)。

### 仓库结构

```text
web_llm_bridge/              Python Transport、Session、Broker、Client 和 CLI
extension/core/              与 Provider 无关的浏览器运行时
extension/providers/chatgpt/ ChatGPT DOM Adapter 和 Serializer
scripts/                     跨平台人工与 Agent 启动入口
tests/                       协议、Session、CLI 和浏览器运行时回归测试
docs/                        架构、协议和 Provider 文档
examples/                    最小 Python 与 Agent CLI 示例
```

## 安全模型

不读取、保存或转发密码、Cookie、Token、剪贴板数据或私有 API；不使用 Playwright、Selenium、CDP、CAPTCHA 绕过或配额/访问限制绕过。认证留在浏览器中。Broker 使用 `127.0.0.1:8766`，扩展传输使用 `127.0.0.1:8765`；两者均不是远程服务或授权边界。

## 运行时数据

home 默认为 `~/.web-llm-bridge`，也可由 `WEB_LLM_BRIDGE_HOME` 指定。`sessions/` 保存恢复元数据，`runtime/` 保存 `broker.pid`、`broker.stdout.log` 和 `broker.stderr.log`；Bridge 不会在其中保存完整 Conversation 正文。Session 记录包含 Conversation URL，应将这些目录视为敏感本机状态。

## 限制

同一时间只能有一个已登记的活动扩展。单行上限为 8 MiB。DOM 变化、标签页关闭、扩展不可用和超时均是预期失败。打开请求为 30 秒、历史为 70 秒、`chat` 为连续 5 分钟无活动，进度会重置该窗口。

## 贡献

欢迎参与贡献。修改浏览器 Adapter 或新增 Provider 前，请阅读[中文贡献指南](CONTRIBUTING.zh-CN.md)、[架构](docs/architecture.zh-CN.md)和 [Provider 开发](docs/provider-development.zh-CN.md)。英文文档见 [CONTRIBUTING.md](CONTRIBUTING.md)、[Architecture](docs/architecture.md)和 [Provider development](docs/provider-development.md)。

## 路线图
1. 在 v0.1 稳定 ChatGPT capability、错误和协议行为。
2. 在 v0.2 验证第二 Provider 的适配器契约，不承诺提供实现。
3. 在保持本地默认值的前提下完善脱敏诊断与协议协商。

## 许可证

Web LLM Bridge 采用 GNU Affero General Public License v3.0 only（`AGPL-3.0-only`）。修改并分发受覆盖版本时，必须按照 AGPL 的要求提供对应源码。修改后的受覆盖程序通过网络向用户提供交互时，第 13 节要求向用户提供获取该版本对应源码的机会。独立程序是否构成受覆盖的组合或衍生作品，应根据许可证正文、适用法律和具体事实判断。[LICENSE](LICENSE) 文件是权威法律文本。
