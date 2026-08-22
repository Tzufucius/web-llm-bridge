# 参与贡献 Web LLM Bridge

[English](CONTRIBUTING.md) | **简体中文**

感谢参与改进 Web LLM Bridge。本项目是连接已由用户完成认证的浏览器页面与本地 CLI 或
Agent 进程的本地 bridge；它不是通用 LLM 网关、浏览器登录工具，也不是远程代理。

## 参与方式

- 报告可复现的缺陷或文档问题，但不得分享私有会话数据。
- 改进 Python Broker、会话、Transport、协议、CLI 或测试覆盖。
- 改进 Manifest V3 扩展的共享运行时或已支持的 ChatGPT 适配器。
- 仅在确认网站条款允许且用户明确授权后，新增或验证 Provider。
- 改进示例、架构、协议、Provider 和目录说明文档。

目前唯一可运行的 Provider 是 ChatGPT Web。README 中列出的其他 Provider 只是规划或
实验，不是已支持的集成。

## 开发环境

使用 Python 3.11 或更高版本；运行 Extension smoke 测试还需要受支持的 Node.js 运行时：

```console
git clone https://github.com/Tuzfucius/web-llm-bridge.git
cd web-llm-bridge
python -m venv .venv
```

Windows PowerShell 使用 `.venv\Scripts\Activate.ps1` 激活环境，Linux 和 macOS 使用
`source .venv/bin/activate`，然后安装项目：

```console
python -m pip install -U pip
python -m pip install -e .
```

只有在手动浏览器检查时，才将 `extension/` 作为未打包扩展加载到 Chrome 或 Edge。请在
该浏览器配置中自行完成网站认证。项目不得接收或自动操作凭据。

修改不熟悉的区域前，先阅读最近的 `README.md`，再查阅以下文档：

- [架构](docs/architecture.zh-CN.md)：进程所有权和依赖方向。
- [协议](docs/protocol.zh-CN.md)：Extension WebSocket 与 Broker NDJSON 契约。
- [Provider 开发](docs/provider-development.zh-CN.md)：Adapter Contract。

## 架构边界

预期的请求路径如下：

```text
CLI / 本地 Agent -> Client -> Broker -> Session Manager -> Transport -> Extension Adapter -> 页面 DOM
```

- CLI 必须使用 Broker 协议，不得直接访问 Extension。
- Broker 持有唯一的 Extension WebSocket，负责 Session 串行化、稳定错误和仅元数据的
  Session 持久化。它默认只监听回环地址，不是远程服务。
- Python Provider 只包含不可变 metadata、URL 规范化、host 和 capabilities；不得持有
  Transport、解析 DOM、保存 selector 或包含认证状态。
- Extension adapter 负责网站特有的 selector、DOM 输入与提交、页面活动、完成判断、turn
  identity、历史滚动和序列化。
- `SessionStore` 仅保存恢复所需的 metadata；不得持久化 Prompt、回复正文、Cookie、Token、
  密码或完整对话历史。

不要为了方便小改动而反转这些依赖方向。

## 修改位置

| 修改内容 | 主要位置 | 必须配套的工作 |
| --- | --- | --- |
| 公共 Python API、错误或 NDJSON schema | `web_llm_bridge/`、`docs/protocol.md` | 更新聚焦的 protocol/broker 测试。 |
| Broker 请求生命周期或锁 | `web_llm_bridge/broker/`、`web_llm_bridge/session/` | 覆盖顺序、错误、恢复和并发。 |
| CLI 行为 | `web_llm_bridge/cli/`、`scripts/` | 保持 Broker 边界，更新 CLI 测试/示例。 |
| 与网站无关的 Provider metadata | `web_llm_bridge/providers/` | 增加 URL/capability 测试和 registry 覆盖。 |
| 网站 DOM 行为 | `extension/providers/<provider>/` | 保持 selector/serializer 在浏览器侧，增加 smoke fixture。 |
| 共享 Extension 运行时或路由 | `extension/core/`、`extension/service_worker.js`、`extension/content.js` | 运行适用的 Provider smoke 测试。 |
| 文档或示例 | 最近的目录 `README.md`、`docs/` 或 `examples/` | 保持中英文贡献指南一致。 |

每个现有目录均有说明职责的 `README.md`。当改动改变目录职责或契约时，更新该目录文档。

## 不变式

贡献必须保持以下性质：

- 认证留在用户已认证的浏览器会话中；绝不读取 Cookie、Local Storage、Token、密码、密码
  字段、DevTools/CDP 数据、私有 API 或系统剪贴板。
- 不得增加 Playwright、Selenium、CDP、Provider 私有 API、CAPTCHA 绕过或配额与访问限制绕过。
- Broker 和 Agent endpoint 默认保持仅绑定回环地址。不得将 bridge 变成面向互联网的服务。
- Session registry 始终只保存 metadata；删除它不得影响浏览器中的会话。
- Python Provider 必须无 DOM 且与网站实现无关；只有 Extension adapter 可以了解网站的 DOM。
- 一个 Broker 只拥有一个 Extension Transport。同一 Session 的操作必须串行，progress 事件
  不是最终 RPC response。
- 点击不等于 Prompt 已提交；必须有明确的提交证据。回复在适配器获得完成证据并完成最终
  确认前不得视为完成。
- 提交状态不确定时，`chat` 不得自动重发原 Prompt；应返回结构化错误。
- 错误、超时、已关闭 Session 和不可用 Extension 都必须返回结构化失败，不能返回半截成功。

## 隐私与敏感数据

不得在源代码、测试、fixture、示例、文档、Issue、日志、截图、录屏、提交或 Pull Request
中加入以下内容：

- Cookie、access token、密码、API key、PAT、私钥或 `.env` 值。
- 真实 Conversation URL、Session ID、浏览器 profile 数据、Prompt、Assistant 回复、私有
  聊天截图或完整对话历史。
- 可识别用户身份的数据，例如姓名、邮箱、组织数据、附件，或从浏览器存储/剪贴板复制的内容。

请使用合成 host、不透明占位 ID 和虚构 fixture 文本。运行目录和本地 Session registry 都应视为
敏感的本机状态。

## 新增 Provider

1. 阅读 [Provider 开发文档](docs/provider-development.zh-CN.md)，理解 Adapter Contract，确认
   目标网站允许预期的自动化，并获取用户明确授权。不得设计凭据或访问控制绕过方案。
2. 新增最小的不可变 `ProviderDefinition`：唯一 ID、HTTPS 默认 URL、允许的 host、
   capabilities 和确定性的 URL 规范化。
3. 注册该定义，不得再创建 `ExtensionTransport`，也不得把 DOM selector 写入 Python。
4. 实现对应的 Extension profile 和 adapter。Prompt discovery、发送、提交检测、活动、
   完成、消息提取、稳定 turn identity、历史滚动和特殊序列化都必须留在该 adapter 中。
5. 用 fake transport 测试 Python metadata 和 URL 处理。用合成 fixture 测试 DOM 行为，至少
   覆盖页面未就绪、提交失败、流式输出、工具活动、最终确认、超时、虚拟化历史和 serializer
   fallback。
6. 增加 Provider 文档，更新支持状态表、capability、协议、目录和安全边界文档。位于 private submodule 的 Provider
   必须可复现地固定版本；Git 凭据只能放在 Git 配置中，不能进入项目文件。
7. 仅使用用户批准且已认证的会话，在真实浏览器中完成最小手动 smoke 检查。报告浏览器版本
   和 DOM 假设，但不要记录私有内容。

## 测试与浏览器报告

在仓库根目录运行回归命令：

```console
python -m pytest
python -m compileall web_llm_bridge
node tests/providers/chatgpt/streaming_completion_smoke.js
node tests/providers/chatgpt/submission_wait_smoke.js
node tests/providers/chatgpt/tool_activity_smoke.js
```

迭代时运行聚焦测试；影响共享行为的改动提交前必须运行完整 Python 测试和所有适用的
`tests/providers/chatgpt/*_smoke.js`。每个能够稳定复现的缺陷修复都应增加回归测试。

当前基线记录于 2026-08-22（Windows）：`python -m pytest` 在 Python 3.13.1、pytest
8.4.2 下通过 25 个测试。八个 ChatGPT Extension smoke 脚本在 Node.js v24.14.0 下通过：
history、isolation、registry、serializer、streaming completion、submission wait、tabs 和
tool activity。这些是合成 DOM/runtime 检查，不是真实已认证浏览器的端到端测试。真实登录态
E2E 仍需手动执行，且不得捕获私有会话内容。
修改 DOM selector、发送、Streaming、完成判断、历史或序列化时，必须报告 Chrome 或 Edge
版本，并将真实浏览器测试结果明确记录为 `PASS` 或 `NOT RUN`。

## 改动与评审

保持改动聚焦，说明行为变化，并在 Pull Request 中列出实际运行的命令及结果。使用 Conventional
Commits：

```text
type(scope): imperative summary
```

可使用 `feat`、`fix`、`docs`、`test`、`refactor`、`perf`、`build`、`ci`、`chore` 或
`revert` 等合适的 type。一个 commit 只处理一个逻辑主题。不要将无关格式化、重命名、生成
文件或重构混入功能或修复改动。

示例：

```text
fix(chatgpt): update response completion detection
docs(readme): clarify persistent session model
test(chatgpt): cover tool activity updates
```

subject 使用祈使语气，保持简洁且末尾不加句号。

## 许可证

提交贡献即表示你将该贡献以本仓库的 **AGPL-3.0-only** 许可证授权。项目不要求贡献者许可
协议或单独的贡献模板。
