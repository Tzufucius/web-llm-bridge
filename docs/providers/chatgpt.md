# ChatGPT Web Provider

## 认证来源

ChatGPT provider 只使用用户在 Chrome 或 Edge 中已经打开并完成认证的 ChatGPT 页面。
认证动作必须由用户完成；provider 不读取密码、Cookie、Token 或 Local Storage，不
调用私有 Conversation API，也不使用 Playwright、Selenium、CDP 或剪贴板权限。

## 页面和会话

默认入口是 `https://chatgpt.com/`。创建新会话时由 Extension 新建标签页；恢复时
使用已登记的 Conversation URL。Session registry 只保存 URL 等元数据，标签页关闭
后，读取操作可以按显式 `reopen_on_closed` 策略恢复一次绑定；`chat` 不应在状态不明
时自动重发 Prompt。

Conversation URL 需要规范化并校验 host。首页 URL 按新会话处理；不属于 ChatGPT 的
URL 必须拒绝。当前 active Session 由 Persistent Broker 独占，多个 Agent 共享同一个
Session 时操作按顺序执行。

## DOM 交互

内容脚本负责：

- 等待输入框和发送按钮真正可用；
- 输入并提交 Prompt，观察用户消息节点、输入框清空或生成状态等提交证据；
- 在长思考、工具调用和流式回复期间推送 progress；
- 通过虚拟化列表滚动和增量缓存读取历史；
- 将 DOM 转换为 Markdown/LaTeX，不点击 ChatGPT 的 Copy 按钮。

新标签页就绪或消息提交可能需要等待。提交证据在约 60 秒内仍未出现时返回
`SEND_FAILED`。最终回复采用“连续页面活动”策略：消息区、工具状态、思考区域或
Assistant 内容发生有效更新时继续等待；连续约 5 分钟没有有效更新才返回
`RESPONSE_TIMEOUT`。Stop 按钮消失后还需要短暂最终确认，不能把中间流式文本当作
最终结果。

## 历史和序列化

`get_messages()` 无参数时读取当前内容脚本已捕获的消息；`limit=N` 返回最近 N 条；
`full=True` 请求尽可能完整的历史。页面虚拟化、网络速度和可见性会影响捕获结果，
因此响应应能表达截断或 best-effort 状态。消息顺序始终从最早到最新。

序列化需保留标题、段落、粗体、斜体、列表、引用、代码、链接、表格、水平线、换行
以及行内/块级 TeX。任何无法识别的页面结构都应保留可读文本，并在必要时返回
`DOM_CHANGED`，而不是静默丢失内容。

## 已知错误

调用方应处理 `PAGE_NOT_READY`、`INPUT_FAILED`、`BUSY`、`SEND_FAILED`、`TAB_CLOSED`、
`CHAT_STATE_UNKNOWN`、`RPC_TIMEOUT` 和 `RESPONSE_TIMEOUT`；也可能遇到
`CONTENT_SCRIPT_UNAVAILABLE` 或 `INTERNAL_ERROR`。错误码比页面文本稳定；页面
DOM 改版后，优先更新 Extension adapter selector 和 smoke test，不要放宽认证或
权限边界。`PROMPT_NOT_FOUND`、`SEND_BUTTON_NOT_FOUND` 等 selector 诊断只属于
adapter 内部重试过程，不是当前 Broker 的稳定错误契约。
