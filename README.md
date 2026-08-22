# Web LLM Bridge

`web-llm-bridge` 是一个本地 WebSocket/NDJSON bridge：它把用户已经在 Chrome 或
Edge 中完成认证的 ChatGPT 页面，提供给本机 CLI 或 Agent 使用。项目当前只支持
ChatGPT Web，不是通用的 LLM 网关，也不替代用户的登录流程。

```text
已认证的 Chrome/Edge ChatGPT 页面
            |
        Manifest V3 Extension
            | ws://127.0.0.1:8765
        Persistent Broker
            | NDJSON 127.0.0.1:8766
        Human CLI / Agent CLI
```

## 安全边界

- 登录、验证码和多因素认证只在用户自己的浏览器中完成；项目不接收密码。
- Extension 不读取、保存或转发 Cookie、Token、密码或系统剪贴板，也不调用 ChatGPT
  私有 Conversation API。
- Broker 和 Agent endpoint 默认只绑定 `127.0.0.1`。它们不是远程服务，不能替代
  网络边界、主机权限或浏览器自身的安全策略。
- Session registry 只记录 Session ID、Conversation URL、时间、序号和 active 状态，
  不记录 Prompt、回复正文或完整对话历史。请把运行目录视为本机敏感状态，不要共享
  其中的 URL。
- 页面 DOM 和 selector 属于 ChatGPT Web 的可变实现。页面结构变化、页面未就绪、会话
  关闭和响应空闲超时会返回结构化错误；调用方必须处理失败，不应假定每次请求都成功。
- 请遵守 ChatGPT、浏览器和所在组织的使用政策。不要把本项目用于绕过访问控制、限制
  或安全验证。

## Supported providers

- ✅ **ChatGPT Web**：v0.1 的唯一实现，使用用户已经认证的 Chrome/Edge 浏览器会话。
- ⏳ **Second provider validation**：v0.2 规划中的验证目标，尚未实现。
- 🧪 **Gemini、Grok、DeepSeek、Kimi、Doubao、AI Studio**：future planned/experimental，
  不承诺版本或交付时间。

Provider 接口、Broker 和协议的抽象用于隔离站点差异，但当前可运行能力仍只有
ChatGPT Web。

## 安装

要求 Python 3.11 或更高版本。请在当前操作系统选定的虚拟环境中执行：

```console
python -m pip install -U pip
python -m pip install -e .
```

也可以只安装运行依赖：

```console
python -m pip install -r requirements.txt
```

安装后可使用三个 console script：`web-llm-broker`、`web-llm-agent` 和
`web-llm-bridge`。直接从源码运行时，请使用同一个 Python 解释器安装和启动，避免
`websockets` 被安装到另一个环境。

## 浏览器扩展

1. 在 Chrome 打开 `chrome://extensions`，或在 Edge 打开 `edge://extensions`。
2. 开启“开发者模式”。
3. 选择“加载已解压的扩展程序”，指向本仓库的 `extension/` 目录。
4. 在同一个浏览器配置中打开 ChatGPT，并按站点要求完成认证。

扩展没有独立的登录页，也不会保存登录材料。点击扩展图标会尝试连接本机 bridge，
Broker 未启动时会自动重连。扩展最低要求 Chrome/Edge 120。

## 启动与使用

### 跨平台 Python 启动入口

人工交互控制台会自动启动或复用 Broker：

```bash
python scripts/manual_console.py
```

智能体通过第二个入口执行单次 CLI 命令：

```bash
python scripts/agent_cli.py list-sessions --json
python scripts/agent_cli.py open --new --json
python scripts/agent_cli.py chat --text "Reply with 123" --json
```

两个脚本只依赖 Python，适用于 Windows、macOS 和 Linux。Broker 日志和 PID 写入
`${WEB_LLM_BRIDGE_HOME:-~/.web-llm-bridge}/runtime`。浏览器扩展仍需由用户在
Chrome/Edge 中加载并完成登录；脚本不会读取认证信息，也不会自动操作浏览器。

### 分步启动

先启动唯一持有 Extension WebSocket 的 Broker：

```console
web-llm-broker serve
```

再打开交互式终端：

```console
web-llm-bridge
```

交互式终端会引导你创建新 Conversation 或恢复已登记的 Conversation URL。输入
`/history`、`/history N` 或 `/history all` 可读取页面已捕获的消息；输入 `/exit`
或 `/quit` 只关闭本地 bridge，不关闭浏览器标签页。

### Agent CLI 与 stdin

Agent CLI 面向脚本和 Shell Agent，默认输出适合人读的文本；加 `--json` 输出一行
一个 JSON 对象（NDJSON）：

```console
web-llm-agent list-sessions --json
web-llm-agent open --new --json
web-llm-agent chat --text "请用三句话总结今天的工作"
```

长文本从 stdin 传入，不需要把内容拼接到命令行参数：

```console
web-llm-agent chat --stdin --json
```

Broker 的 NDJSON 请求至少包含 `id`、`method` 和 `params`；响应包含同一个 `id`、
`ok`，成功时带 `result`，失败时带 `error.code`、`error.message` 和
`error.safe_to_retry`。进度消息使用 `type: "progress"`，调用方应按 `id` 过滤，
不要把进度事件误当成最终响应。协议细节见 [docs/protocol.md](docs/protocol.md)。

## 私有 submodule 认证

本仓库将作为 `Tuzfucius/math-modeling` 的 private submodule 使用；它自身不包含
provider submodule。首次获取父仓库时，需要通过 GitHub HTTPS authentication 访问
父仓库及其 submodule：

```console
git clone --recurse-submodules https://github.com/Tuzfucius/math-modeling.git
cd math-modeling
git submodule update --init --recursive
```

请按 GitHub 的组织策略配置 HTTPS credential manager 或 PAT。不要把 PAT、SSH 私钥、
Cookie 或会话 URL 写进 `pyproject.toml`、`.env`、示例、日志或提交记录。submodule
访问授权属于 GitHub/Git 配置，不属于 bridge 协议；权限不足时应修复 Git 认证，而
不是把凭据传给浏览器扩展。

## 文档

- [架构](docs/architecture.md)：进程、provider 和 session 生命周期。
- [协议](docs/protocol.md)：Extension WebSocket 与 Broker NDJSON 约定。
- [Provider 开发](docs/provider-development.md)：新增 provider 时的边界和测试要求。
- [ChatGPT provider](docs/providers/chatgpt.md)：现有认证浏览器会话的实现约束。
- [基础示例](examples/basic_chat.py)：最小异步调用示例。
- [Agent CLI 示例](examples/agent_cli.md)：stdin、JSON 和错误处理。

## Roadmap

以下版本标签是规划状态，不承诺时间：

1. **v0.1 ChatGPT**：稳定 ChatGPT provider 的 capability、错误码和协议行为。
2. **v0.2 second provider validation**：验证第二个 provider 的 Adapter Contract，
   不表示已提供可用实现。
3. **Future**：Gemini、Grok、DeepSeek、Kimi、Doubao、AI Studio planned/experimental；
   在符合服务条款和用户显式授权前提下评估，不承诺时间或兼容性。
4. 持续增加脱敏诊断和协议版本协商，同时保持本机默认绑定和最小权限。

## 许可证

本项目采用 [MIT License](LICENSE)。
