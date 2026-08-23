[English](provider-development.md) | **简体中文**

# Provider 开发

Provider 将统一 Session 操作映射到用户已经在浏览器中认证的网站。新增 Provider 前，
必须确认网站允许预期自动化，且用户已经明确授权。

## 不可违反的边界

### Python：仅静态定义

Python Provider 是不可变的 `ProviderDefinition` 值，包含：

- 唯一 `id`；
- HTTPS `default_url`；
- 允许的 `hosts` 集合；
- 只读 `capabilities` 映射。

基础 `normalize_url()` 会移除首尾空白，要求 HTTPS 和允许的 hostname，丢弃 query 与
fragment，去掉路径末尾斜杠，并为根 URL 保留 `/`。参数类型无效时返回
`INVALID_ARGUMENT`，不支持的 URL 返回 `INVALID_URL`。

Python Provider **不**实现 `open`、`chat`、`get_messages` 或 `close`。其中不能包含
selector、DOM 解析、CLI 格式化、凭据或运行时连接状态。`SessionManager` 持有这些操作，
并用 Provider ID 调用唯一共享 `ExtensionTransport`。

### Session：持久绑定与恢复

Session 代码持有记录选择、全局操作锁、元数据持久化和 sequence 递增，并隐藏标签页
绑定细节。它不知道 Prompt selector，也不知道站点如何表示消息。

恢复必须遵守副作用边界。下一次分派前会统一重新绑定失效标签页。`chat` 可以为后续
调用准备新绑定，但遇到错误后绝不能重放原 Prompt。

### Transport：唯一连接所有者

`ExtensionTransport` 持有唯一 Extension listener、连接握手、内部请求 ID、pending
future、允许的 progress phase 和 timeout。Provider 不得创建其他 Transport，也不得
监听 Extension 端口。

Service worker 在转发操作前，会验证请求的 Provider 已注册且与实际标签页 URL 匹配。
Provider 不匹配时应返回 `INVALID_URL`，不能运行错误的 adapter。

### Extension：DOM 行为

只有 Extension provider profile 和 adapter 了解站点 DOM 细节。通用 Extension core
持有可复用的输入、提交、完成、历史和 Markdown 算法，并向已注册 adapter 查询站点特有
事实。

## Provider Contract

每个 Provider 都必须满足以下两部分契约。

### Python definition contract

| 项目 | 要求 |
| --- | --- |
| Identity | `id` 在 `ProviderRegistry` 中唯一，并与 Extension profile ID 完全一致。 |
| Default URL | 使用 HTTPS，并同时通过 Python 与 Extension 的 URL 匹配。 |
| Hosts | 显式 allowlist；不得使用后缀匹配或接受任意 redirect。 |
| Capabilities | 只读布尔声明，且对应行为已真正实现并测试。 |
| Runtime state | 不允许存在；Definition 必须 frozen 且与 Transport 无关。 |

在 `web_llm_bridge/providers/registry.py` 注册 Definition。重复 ID 必须失败，不能静默替换
已有 Provider。

### Extension profile contract

通过 `registerProvider()` 注册的 Profile 必须公开：

| 成员 | 要求 |
| --- | --- |
| `id` | 与 Python 相同的唯一 ID。 |
| `defaultUrl`、`hosts`、`capabilities` | 与 Python Definition 语义一致。 |
| `matchesUrl(value)` | 仅对支持的 HTTPS 页面返回 true。 |
| `normalizeUrl(value)` | 产生与 Python 规范化相同类别的稳定 URL。 |
| `timing` | 明确提供通用 Runtime 所需的页面就绪、轮询、提交、完成、回复空闲、进度和历史 timeout。 |
| `selectors` | 集中管理 Prompt、Send、生成、完成、消息、Role、Tool 和 Status selector。 |
| `adapter` | 实现下文 Runtime 方法。 |

Python 与 JavaScript URL 规范化必须等价。Query、fragment、末尾斜杠、替代 host 和无效
scheme 都需要成对测试。

### Extension adapter contract

| 成员 | 行为 |
| --- | --- |
| `findPrompt()` | 返回可见且可用的 Prompt 元素；暂不可用时返回 null。 |
| `findSendButton()` | 返回可见 Send 控件；通用 Core 会检查 enabled 状态。 |
| `isEnabled(button)` | 拒绝 disabled 和 `aria-disabled` 控件。 |
| `isGenerating()` | 报告活动生成状态；永久存在的控件不能使其永久为 true。 |
| `getMessages()` | 按 DOM 顺序返回当前渲染的消息节点。 |
| `getUsers()`、`getLastAssistant()` | 支持提交证据和最终回复选择。 |
| `getRole(node)` | 只返回 History 可理解的 Role（`user` 或 `assistant`）。 |
| `findTurnContainer(node)`、`turnAttributes` | 提供稳定 Turn identity 以去重；通用 Runtime 只有按节点的 fallback。 |
| `hasCompletionMarker(node)` | 发现用于活动/确认信号的站点完成 UI；它本身不能证明内容最终完成。 |
| `activitySnapshot()` | 返回稳定 `signature` 和 `toolCall` 布尔值，让真实 Tool/Status 变化计为活动。 |
| `isActivityNode()`、`isActivitySubtree()` | 将 MutationObserver 活动限定到相关页面区域；无关 DOM 动画不能重置回复空闲时间。 |
| `serializer.serializeElement(element)` | 可选地序列化 Provider 特有结构；返回 `undefined` 时回退到通用 Markdown 遍历。 |

## 行为要求

### Prompt 输入与发送

通用 Core 支持 content-editable 控件和 native value 控件。它会分发 input event、核对
规范化后的写入文本、等待 enabled Send button，再点击发送。Provider 不得通过剪贴板、
DevTools/CDP、私有 API 或认证数据走捷径。

Prompt/Send 元素缺失和输入失败会在 page-ready 窗口内重试。用尽等待时限后，对外暴露
`PAGE_NOT_READY`；selector 特有的 `PROMPT_NOT_FOUND` 和
`SEND_BUTTON_NOT_FOUND` 只保留为内部诊断。

### 提交检测

点击 Send 不是提交证据。在提交窗口内，至少必须观察到以下一种情况：新增 User 消息、
Prompt 清空、开始生成或 Assistant 节点变化。否则返回 `SEND_FAILED`。

确认成功前不得发送 `submitted`。

### 生成、进度与完成

Activity 必须来自相关 DOM mutation、Assistant 文本、Tool/Status snapshot 变化或
completion-marker 变化。只能发送 `submitted`、`thinking`、`working`、`tool_call` 或
`streaming`。Progress 仅用于观测，绝不能作为结果。

完成条件包括：Assistant 内容非空、无活动生成、原始文本稳定、序列化候选稳定，以及最终
重新读取的结果与候选一致。Completion marker 变化可以重置确认，但仅存在 marker 不足以
证明完成。达到回复空闲 timeout 时必须返回 `RESPONSE_TIMEOUT`，绝不能返回半截成功。

### 历史与 Turn identity

History capture 返回按最早到最新排序的 `{role, content}`。它按稳定 Turn identity 缓存，
只在内容增长时更新记录，在 origin/path 变化时重置，并在收集完成后恢复原滚动位置。

完整历史是 best effort。Adapter 必须支持虚拟化列表的增量向上滚动和重叠去重。达到加载
时限时设置 `truncated: true`。该值为 false 也不能保证网站已经暴露全部历史。

### 序列化

通用序列化覆盖标题、段落、强调、列表、引用、preformatted/code 文本、链接、表格、
水平线和换行。Provider serializer 应只增加 TeX 等站点特有结构。未知结构应保留可读
文本，不能点击 Copy button 或写入剪贴板。

## 错误与重试契约

每个跨越 Extension 边界的错误都包含 `code`、`message` 和 `safe_to_retry`。默认值为
false。只有已知重复执行同一 RPC 不会复制副作用时，才能标记为 true。

对于 `chat`，分派后发生标签页关闭、content script 不可用或 Extension 消息通信丢失
时，必须转成 `CHAT_STATE_UNKNOWN` 并设置 `safe_to_retry: false`。不得泄漏会诱导自动
重发的低层 Transport 错误。

分派前的 `TAB_CLOSED` 可以标记为安全。只读恢复仍属于 SessionManager 策略；Provider
adapter 不能自行重开或重试标签页。

## 接入新 Provider

1. 新增并注册 Python `ProviderDefinition`。
2. 新增 Extension profile、必要时的特殊 serializer 和 adapter。
3. 按依赖顺序在 `service_worker.js` 和 manifest content-script 列表中加载 profile 与
   adapter。
4. 将 Provider host 加入 `host_permissions` 和 content-script `matches`。
5. 保持 Python 与 Extension 的元数据、URL 行为、capability 和 ID 同步。
6. 新增 Provider 文档和聚焦测试，不能放宽安全边界。

## 验证清单

- Python 测试覆盖不可变元数据、重复注册、URL 规范化/拒绝和 capability 对齐。
- Fake Transport 测试覆盖 open、chat、history、active Session 选择、全局串行化、
  sequence 行为和恢复策略。
- DOM fixture 覆盖 Prompt 发现、native/content-editable 输入、Send 就绪、提交证据和
  `SEND_FAILED`。
- DOM fixture 覆盖长思考、Tool、流式输出、完成确认、空闲 timeout，以及 Provider 使用
  的每种 progress phase。
- History fixture 覆盖稳定 ID、虚拟化重叠窗口、URL 重置、limit、完整历史、截断和滚动
  恢复。
- Serializer fixture 覆盖每种声明格式和可读 fallback。
- Tab routing 测试区分安全的分派前 `TAB_CLOSED` 与不安全的分派后
  `CHAT_STATE_UNKNOWN`。
- 日志、fixture 和 Session 文件不包含凭据、真实 Conversation URL、Prompt 或回复正文。
- Broker 网络测试与 Provider DOM fixture 相互独立。

## 手工浏览器测试

记录浏览器版本、Extension 版本/commit、Provider Account 状态、页面 URL 类别、Locale
和日期。使用不敏感的测试文本。

1. 加载 unpacked Extension 并启动 Broker，确认只连接一个 Extension。
2. 打开 Provider 首页和已有 Conversation，验证 URL 规范化以及复用标签页/新建标签页
   行为。
3. 发送短 Prompt，观察提交、progress 和一条完整最终响应。
4. 测试长回复，并在支持时测试 Tool call；确认操作不会在半截流式文本或静态 Status
   元素出现时提前完成。
5. 分别读取当前、限量和完整历史，检查顺序、去重、截断、滚动恢复、Markdown 和特殊
   序列化。
6. 在读取前关闭标签页，再在 Chat 过程中关闭标签页。确认读取恢复策略正确，且 Chat
   Prompt 绝不会自动重放。
7. Chat 过程中禁用或重新加载 Extension，验证错误表达未知 Chat 状态，而不是重试安全。
8. 检查 Session registry 和日志是否包含 Prompt、回复、Cookie、Token 或其他秘密。

合成 DOM 测试不能替代该手工认证浏览器验证。

## 发布约束

新增 Provider 时更新 capability 列表、协议文档、Provider 目录文档和安全边界。如果代码
位于 private submodule，必须固定可复现 commit，并在 CI 检查 submodule 可用性。凭据
属于 Git 配置，不能进入 Python 配置或浏览器扩展。

### Artifact 契约

需要暴露媒体的 Provider 可以实现 `adapter.getArtifacts(messageNode)` 和
`adapter.resolveArtifact({turn_id, index})`。前者只返回最小 descriptor（kind、turn/index、
MIME、尺寸、alt、quality、ready），并附带供 Broker 本地保存的私有 source 字段；后者在
signed source 过期时按 turn/index 重新解析，由 `get-artifact` 内部调用而不是 RPC。公共
结果不能包含 CSS selector、`outerHTML`、React 内部信息、凭据或完整 data URI。
