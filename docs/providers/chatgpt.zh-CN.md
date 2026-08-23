[English](chatgpt.md) | **简体中文**

# ChatGPT Web Provider

该 Provider 通过 Web LLM Bridge 的统一 Session 模型，提供对已认证 ChatGPT 网页标签页的
访问。通用 Provider Contract 见 [Provider 开发](../provider-development.zh-CN.md)，线协议
细节见[协议](../protocol.zh-CN.md)。

## 认证与安全边界

用户在 Chrome 或 Edge 中登录 ChatGPT。Provider 复用该可见浏览器 Session，但不读取
密码、Cookie、Token、Local Storage 或私有 Conversation API。它不使用 Playwright、
Selenium、DevTools/CDP 或剪贴板，Extension manifest 也不申请剪贴板权限。

测试 fixture 和日志中不能放入真实 Conversation URL、Prompt、回复或 Account 数据。

## 声明的支持范围

Python 与 Extension Definition 使用 Provider ID `chatgpt`、默认 URL
`https://chatgpt.com/`，并允许 `chatgpt.com` 和 `www.chatgpt.com` 两个 host。
Manifest 声明的最低 Chrome 版本为 120；当前手工支持目标是启用 Manifest V3 的
Chrome 或 Edge 120 及以上版本。

声明的 capability 为：

| Capability | 值 |
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

这些 capability 描述浏览器 DOM 行为，不表示具有 API 级投递保证，也不保证能完美重建
虚拟化历史。

## URL 与标签页行为

只有两个允许 host 上的 HTTPS URL 可以匹配。规范化会移除 query 和 fragment，去掉非根
路径末尾斜杠，并将根路径保留为 `/`。元数据会保留 `www` host，而不是将其重定向。

常规 ChatGPT URL 不包含显式端口，调用方也不应添加端口。当前 Python normalizer 会重建
不含端口的 URL，而 JavaScript normalizer 使用 `URL.origin`；因此显式端口不是受支持的
一致性情形。

执行 Open 时，Extension 依次尝试：

1. 已记录的标签页，前提是其 Provider 与规范化 URL 仍匹配；
2. 规范化 URL 相同的其他现有标签页；
3. 新建一个 active 标签页。

`new: true` 会跳过复用并创建新标签页。Extension 最多等待 30 秒，让 content script
响应 `ping`；超时返回 `PAGE_NOT_READY`。

持久 Session 记录只保存 Provider、Session/tab ID、当前 URL、时间戳、sequence、active
标志和恢复策略。Chat 或历史读取成功后会回写当前标签页 URL，因此从首页导航到
`/c/...` 后仍可在以后恢复。

设置 `reopen_on_closed: true` 后，读取可以重开已记录 URL 并重试一次。Chat 绝不会
重放。如果在分派前已确定标签页关闭，`TAB_CLOSED` 可以安全重试；如果开始分派后消息
通信失败，Provider 返回 `CHAT_STATE_UNKNOWN`，此时重试不安全。

## DOM Profile

当前 Profile 使用以下信号：

| 用途 | 主要信号 |
| --- | --- |
| Prompt | `#prompt-textarea`；可见 content-editable textbox fallback |
| Send | `#composer-submit-button`、`data-testid=send-button` 或英文 `Send prompt` aria-label |
| Generation | 可见 Stop button/test ID |
| Messages | `data-message-author-role`，取值为 `user` 或 `assistant` |
| Turn identity | `data-turn-id`、conversation-turn `data-testid`、`data-turn`，最后才按节点 fallback |
| Completion activity | 英文或中文 Copy/message-action 控件 |
| Tool/status activity | Tool、function、browser、search、code、thinking、live/status/log/busy selector 和状态文本 |

Selector 集中定义在 `extension/providers/chatgpt/profile.js`。站点 DOM 发布可能使其失效，
而不改变任何 Python API。

### Prompt 输入与提交

如果可见 Stop 控件表示仍在生成，content runtime 会先拒绝新的发送。随后它会等待 Prompt
和 enabled Send 控件，最长 30 秒；通过 DOM/native value 语义写入，分发 input event，
核对规范化文本，再点击发送。

点击后，它最长等待 60 秒，直到出现至少一个提交信号：新增 User 消息、Prompt 清空、
开始生成或 Assistant 节点变化。没有证据时返回 `SEND_FAILED`。只有通过该检查后才会
发送 `submitted` progress phase。

### Activity、progress 与完成

Runtime 观察 main/message/tool/status 区域内的相关 mutation。Assistant 文本变化、
activity snapshot 变化和 completion-marker 变化也计为有效活动。静态 Stop、Tool 或
Status 元素不会在自身相关状态未变化时反复重置活动。

当前 timing 为：

| 设置 | 值 |
| --- | --- |
| Poll interval | 200 ms |
| Progress interval | 1,500 ms |
| 原始文本稳定时间 | 1,500 ms |
| 序列化完成确认 | 3,000 ms |
| 页面/Send 就绪 | 30,000 ms |
| 提交确认 | 60,000 ms |
| 回复空闲 timeout | 300,000 ms |

提交前 progress 就可能报告 `working`；之后是 `submitted`；等待回复时可能报告
`thinking`、`working`、`tool_call` 或 `streaming`。Progress 包含 elapsed 和 idle
毫秒数，绝不是完成信号。

只有同时满足以下全部条件，回复才会完成：

- 最新 Assistant 包含非空文本，或包含至少一个 ready Artifact；
- 未检测到活动生成；
- Assistant 文本、Artifact signature 和有效页面活动稳定 1.5 秒；
- 序列化候选保持不变 3 秒；
- 最后一次重新序列化当前 Assistant 节点的结果与候选一致。

Completion-marker 变化会重置候选确认，但 marker 不要求必须存在，仅有 marker 也不足以
证明完成。如果连续 5 分钟没有有效页面活动，Runtime 返回 `RESPONSE_TIMEOUT`，绝不会
把半截文本作为成功结果。

## Artifact 与调试

图片只从 Assistant turn 提取。头像、favicon、图标、工具图标、装饰元素、loading
placeholder 和用户上传图片会被过滤。source 按原图/下载资源、原图链接、最大 `srcset`、
`currentSrc`、`src`、`data:`、`blob:` 的顺序选择；无法确认质量时使用 `unknown`。

`debug-snapshot` 返回脱敏页面快照，`debug-trace` 返回单次 Chat 的内存事件轨迹，均不
返回完整 DOM、Prompt、Cookie、Token、signed URL 或图片内容。图片生成后先用
`wait-artifact` 等待 ready，再用 `get-artifact` 按 Artifact ID 落盘；不能直接下载任意 URL。

## 历史行为

Content runtime 会持续捕获已渲染的 `user` 和 `assistant` 消息，并按 Turn identity
缓存 `{role, content}`。更长的渲染内容可以替换较短缓存。页面 origin/path 变化时缓存
重置，防止一个 Conversation 的 Turn 泄漏到另一个 Conversation。

对于 Full 或足够大的历史请求，Runtime 会定位最近的可滚动消息祖先，以重叠增量向上
滚动，捕获并去重 Turn，随后恢复原位置；如果用户原本接近底部，则继续跟随底部。历史
加载时限为 60 秒，轮询间隔为 250 ms。

结果从最早到最新排序。`limit=N` 返回最近 N 条已捕获消息。`full=true` 尝试读取全部
历史。`truncated=true` 表示达到时限。虚拟化、延迟加载、页面可见性和网络速度仍可能
使未标记截断的结果不完整。

## Markdown 与 LaTeX

通用序列化保留可读文本，并支持标题、段落、粗体/斜体、列表、引用、fenced
preformatted text、inline code、链接、表格、水平线和换行。

ChatGPT serializer 从 Math/KaTeX 内容读取 `application/x-tex` annotation，并输出
`$...$` 或 `$$` block。提取 TeX annotation 后，它会抑制重复的 KaTeX HTML、MathML
和 MathJax presentation wrapper。它绝不点击 ChatGPT 的 Copy button。

### 已知限制

已知保真限制包括：图片和非文本附件、代码围栏的 syntax language、包含 Markdown
fence delimiter 的代码、复杂嵌套列表、row/column span、交互式引用、没有可用 TeX
annotation 的 MathJax 结构，以及当前 DOM 未暴露的内容。未知元素会尽量回退到可读的
后代文本。

## 错误与重试行为

调用方应处理 `PAGE_NOT_READY`、`INPUT_FAILED`、`BUSY`、`SEND_FAILED`、
`TAB_CLOSED`、`CHAT_STATE_UNKNOWN`、`RPC_TIMEOUT`、`RESPONSE_TIMEOUT`、
`CONTENT_SCRIPT_UNAVAILABLE`、`INVALID_URL` 和 `INTERNAL_ERROR`。

`PROMPT_NOT_FOUND` 和 `SEND_BUTTON_NOT_FOUND` 是内部重试诊断，不是稳定 Broker 错误。
当前不会发出 `DOM_CHANGED`。DOM 失效通常表现为 `PAGE_NOT_READY`、`SEND_FAILED`、
`RESPONSE_TIMEOUT` 或不完整的 best-effort 历史结果。

应以 `safe_to_retry` 为准，不能依赖 message 文本。具体而言：

- Tab lookup 产生的分派前 `TAB_CLOSED` 标记为 true；
- 分派后的 tab/content-script/Extension 丢失会变成 `CHAT_STATE_UNKNOWN`，标记为 false；
- 其他错误默认为 false，除非未来实现能明确证明重试安全。

## 手工认证浏览器测试

使用不敏感内容，并记录 Chrome/Edge 版本、Extension commit、ChatGPT Locale、与本次运行
相关的 Account/Feature Tier、页面 URL 类别和日期。

1. 加载 unpacked Manifest V3 Extension，启动 Broker，确认 Extension 完成协议版本 2
   握手。
2. 打开 `https://chatgpt.com/`，调用 `open` 后发送短 Prompt。确认 ChatGPT 导航到
   `/c/...` 时 URL 得到更新，且只返回一条最终响应。
3. 发送足够长、会产生流式输出的 Prompt。验证出现 `streaming` progress，且文本仍在
   变化时不会返回最终结果。
4. 发送会调用当前可用 ChatGPT Tool 的 Prompt。验证相关 DOM 变化产生
   `tool_call`/`working`，且静态的已完成 Tool Card 不会使请求永久保持活动。
5. 测试标题、强调、列表、引用、链接、代码、表格、inline TeX 和 block TeX。不使用
   Copy，对比返回 Markdown 与可见回复。
6. 在长 Conversation 中分别使用 `limit`、公共无 limit 默认值和 `full=true` 读取历史。
   验证顺序、去重、滚动恢复和 `truncated` 行为。
7. 在另一个标签页打开相同 Conversation，验证规范化 URL 复用；随后使用 `new=true`，
   验证创建独立标签页和 Session。
8. 在 `get_messages` 前关闭标签页，分别测试关闭和启用恢复策略。确认启用时重新绑定并将
   读取重试一次。
9. Chat 期间关闭标签页，或重新加载/禁用 Extension。确认 Prompt 不会自动重放，且分派
   歧义报告为 `CHAT_STATE_UNKNOWN` 与 `safe_to_retry: false`。
10. 检查 `${WEB_LLM_BRIDGE_HOME:-~/.web-llm-bridge}/sessions` 和进程输出，确认没有存储或记录 Prompt、
    回复、Cookie、Token 或密码。

最近一次合成验证：2026-08-22，Chrome/Edge Manifest V3 DOM smoke fixture。在声称特定
当前 ChatGPT 页面版本通过验证前，仍需执行真实登录态端到端测试。

图片只从 Assistant turn 中提取。头像、图标、loading placeholder 和用户上传图片
会被过滤。source 优先使用明确的原图/下载资源，其次是原图链接、最大 `srcset`、
`currentSrc`、`src`、`data:`，最后是 `blob:`。Adapter 返回稳定的 `(turn_id, index)`
引用，并在内部签名中记录图片 readiness，使纯图片回复可以安全完成。
