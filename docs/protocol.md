# 协议

本项目使用两段本地协议：Extension 与 Broker 之间使用 WebSocket，CLI/Agent 与
Broker 之间使用 NDJSON over TCP。两段协议都只面向本机回环地址，不能视为公开远程
API。

## Broker NDJSON

Agent 连接 `127.0.0.1:8766` 后，每个请求和响应各占一行 UTF-8 JSON。请求格式：

```json
{"id":"req-123","method":"chat","params":{"text":"你好"}}
```

通用响应格式：

```json
{"id":"req-123","ok":true,"result":{"text":"你好，有什么可以帮你？"}}
```

失败响应：

```json
{"id":"req-123","ok":false,"error":{"code":"RESPONSE_TIMEOUT","message":"页面在连续空闲窗口内没有完成回复","safe_to_retry":false}}
```

`id` 由调用方生成并在整个请求生命周期内保持不变。`method` 当前包括：

| method | 作用 | 典型参数 |
| --- | --- | --- |
| `open` | 创建或恢复 Session | `new`、`url`、`session_id` |
| `chat` | 发送一条 Prompt | `text` |
| `get_messages` | 读取已捕获历史 | `limit`、`full` |
| `list_sessions` | 列出 registry 元数据 | 无 |

字段可扩展，但调用方必须忽略不认识的响应字段。`result` 的具体内容由 method
定义；不要把它当作任意站点的 OpenAI API 兼容格式。

## Progress 事件

长操作可以在最终响应前发送：

```json
{"type":"progress","id":"req-123","phase":"submitted"}
```

`phase` 只能使用以下值：`submitted`、`thinking`、`working`、`tool_call`、
`streaming`。进度没有独立的成功语义，调用方必须继续读取，直到收到匹配 `id` 的
最终 response。未知 phase 应按普通进度处理。

## Extension WebSocket

Extension 连接 `ws://127.0.0.1:8765`。Broker 只接受已登记的扩展 Origin，并限制
为单一活动 Extension 客户端。消息仍使用 JSON 对象；字段至少包含请求 ID、操作名
和参数，响应携带相同 ID。Extension 的内部消息不是稳定公共 API，provider 变化时
应同时更新协议测试与 `extension/` 说明。

## 错误处理

错误对象的 `code` 用于机器判断，`message` 用于诊断，`safe_to_retry` 只表示在该
错误边界下是否可以重新执行同一 RPC。调用方不能仅根据文本判断错误。

Broker 当前会产生以下协议错误：

- `INVALID_JSON`、`INVALID_REQUEST`、`INVALID_ARGUMENT`、`UNKNOWN_METHOD`：请求格式、
  参数、方法名或单行大小不合法；
- `PROVIDER_NOT_FOUND`、`SESSION_NOT_FOUND`、`INVALID_URL`：provider 或会话地址不可用；
- `EXTENSION_NOT_CONNECTED`、`EXTENSION_ALREADY_CONNECTED`、`INVALID_ORIGIN`、
  `INCOMPATIBLE_PROTOCOL`：Extension 连接状态、来源或协议版本不符合要求；
- `PAGE_NOT_READY`、`INPUT_FAILED`、`BUSY`、`SEND_FAILED`：页面尚未就绪、输入/控件
  失败、仍在生成或未观察到提交证据；
- `TAB_CLOSED`、`CHAT_STATE_UNKNOWN`：标签页关闭，或消息可能已提交但最终状态未知；
- `RPC_TIMEOUT`、`RESPONSE_TIMEOUT`：Extension RPC 或连续页面活动等待超时；
- `RESPONSE_TOO_LARGE`：Broker 结果超过 8 MiB NDJSON 单行限制；
- `CONTENT_SCRIPT_UNAVAILABLE`、`INTERNAL_ERROR`：内容脚本响应无效或 Bridge 内部错误。

客户端自身还可能报告 `INVALID_RESPONSE`（Broker 返回的 JSON 结果不符合客户端预期）。
`DOM_CHANGED`、`PROMPT_NOT_FOUND` 和 `SEND_BUTTON_NOT_FOUND` 不是当前实现向 Broker
稳定暴露的错误码；页面 selector 问题会归入 `PAGE_NOT_READY`、`INPUT_FAILED` 或
`SEND_FAILED`。

JSON 解码失败、超出单行大小或连接在最终响应前关闭时，客户端应报告协议错误，
不要把空行当作成功结果。发送 Prompt 的请求即使网络断开也不应无条件重试，因为页面
可能已经提交了消息。
