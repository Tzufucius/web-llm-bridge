[English](protocol.md) | **简体中文**

# 协议

Web LLM Bridge 包含两段本地协议：

- CLI/Agent 到 Broker：`127.0.0.1:8766` 上的 NDJSON over TCP；
- Extension 到 Broker：`ws://127.0.0.1:8765` 上的 WebSocket JSON 消息。

两者都是仅限回环地址的 IPC，不是公开远程 API。当前 Extension 协议版本为 `1`，两段
Transport 的消息大小上限都是 8 MiB。

## Broker NDJSON

每个请求、progress 事件和最终响应都是一个以换行符结尾的 UTF-8 JSON 对象。一个连接
可以包含多个请求。Broker 将各行作为 Task 处理，因此流水线式发送请求的调用方必须用
`id` 关联每个事件和响应，不能假设响应顺序。

### 请求 envelope

```json
{"id":"req-123","method":"chat","params":{"text":"你好"}}
```

| 字段 | 要求 |
| --- | --- |
| `id` | 必填的非空字符串，由调用方生成。 |
| `method` | 必填字符串，取值为下文方法名。 |
| `params` | JSON 对象；省略时视为 `{}`。 |

Broker NDJSON ID 在该本地 RPC 中保持不变。Broker 到 Extension 的 Transport 会创建
另一个内部 ID，因此两段协议的 ID 不会端到端保持一致。

### 最终响应

成功的最终响应为：

```json
{"id":"req-123","ok":true,"result":{"text":"你好，请问需要什么帮助？"}}
```

失败的最终响应为：

```json
{"id":"req-123","ok":false,"error":{"code":"RESPONSE_TIMEOUT","message":"连续五分钟未检测到有效页面更新","safe_to_retry":false}}
```

每个有效请求 Task 只发送一条最终响应。`result` 始终为对象，但其结构由方法定义；它
不是 OpenAI API 响应格式。Client 应忽略新增的未知字段。

### 方法

#### `open`

参数：

| 字段 | 类型与行为 |
| --- | --- |
| `provider` | 非空字符串；默认为 `chatgpt`。 |
| `new` | 布尔值；默认为 `false`。为 true 时不得同时提供 `url` 或 `session_id`。 |
| `url` | 可选的 Provider HTTPS URL，与 `session_id` 互斥。 |
| `session_id` | 可选的已有 Session ID。 |
| `reopen_on_closed` | 可选布尔值。为 `null`/省略时保留已存策略，否则覆盖该策略。 |

没有显式目标时，优先使用该 Provider 的 active 记录；没有 active 记录则打开 Provider
默认 URL。`new: true` 会创建新标签页和新 Session 记录。其他 Open 可以重新附加已记录
标签页，也可以复用匹配的 Provider 标签页。

结果字段：

```json
{
  "session_id": "3d1f...",
  "provider": "chatgpt",
  "tab_id": 42,
  "conversation_url": "https://chatgpt.com/c/example",
  "sequence": 0,
  "reopen_on_closed": false
}
```

#### `chat`

参数为 `provider`（默认 `chatgpt`）、可选 `session_id` 和非空字符串 `text`。没有选中
Session 时，Manager 会在 Provider 默认 URL 创建 Session。结果是上述 Session 描述符，
再加上非空字符串 `text`，其中包含最终序列化的 Assistant 回复。

浏览器分派前 `sequence` 就会递增，即使操作随后失败也不回退。调用方不能把它作为提交
成功的证据。

#### `get_messages`

参数为 `provider`、可选 `session_id`、`full` 和 `limit`：

- `full` 必须为布尔值，默认 `false`；
- `full` 为 false 时，`limit` 可以是 `null` 或 1 到 1000 的整数；
- 直接调用 Broker 且省略 `limit` 时，默认为 5；
- 公共 `WebLLMSession.get_messages()` 会显式发送 `limit: null`，即返回当前已捕获或
  可见的历史，不要求达到指定条数；
- `full: true` 忽略 `limit`，尝试滚动读取全部可用历史。

结果是 Session 描述符及以下字段：

```json
{
  "messages": [
    {"role":"user","content":"问题"},
    {"role":"assistant","content":"回答"}
  ],
  "truncated": false
}
```

消息从最早到最新排序。`truncated: true` 表示达到历史加载时限；`false` 不保证网站已
暴露每一个历史 Turn。

#### `list_sessions`

可选字符串 `provider` 用于过滤记录。结果为 `{"sessions":[...]}`。每条记录包含
`version`、`provider`、`session_id`、`tab_id`、`current_url`、`created_at`、
`updated_at`、`sequence`、`active` 和 `reopen_on_closed`。该方法返回 Store 记录，
因此 URL 字段是 `current_url`，不是 `conversation_url`。

协议版本 1 没有公共 `close` 方法。

## Broker progress

当前只有 `chat` 会发送 progress，且事件出现在最终响应之前：

```json
{
  "type": "progress",
  "id": "req-123",
  "provider": "chatgpt",
  "session_id": "3d1f...",
  "tab_id": 42,
  "url": "https://chatgpt.com/c/example",
  "phase": "streaming",
  "elapsed_ms": 12400,
  "idle_ms": 180
}
```

当前 `phase` 取值为 `submitted`、`thinking`、`working`、`tool_call` 和
`streaming`。Extension Transport 会丢弃集合之外的 phase。Consumer 仍应将未来新增的
未知 phase 视为观测数据，绝不能将其作为最终结果。

`elapsed_ms` 是 content runtime 启动 Chat 操作后的时间；`idle_ms` 是最近一次有效页面
活动后的时间。两者都是非负数，Extension 事件缺失时 Broker 会填 `0`。
`session_id` 取自调用方参数；Manager 隐式创建 Session 时它可能为 null，不能替代最终
Session 描述符。

第一次 progress 可能是在提交前发出的 `working`。只有观察到提交证据后才会发送
`submitted`，但它仍不保证最终会生成回复。调用方必须继续读取，直到收到同一 Broker
`id` 的最终响应。

## Extension WebSocket

### 连接与握手

Broker 只接受一个活动 Client，且其 Origin 必须匹配 Chrome Extension Origin。Origin
拒绝可能发生在 WebSocket 握手阶段，不保证收到 JSON 错误。

Extension 首先发送：

```json
{"type":"hello","protocol_version":1}
```

Broker 响应 `{"type":"hello_ack","protocol_version":1}`。不兼容的 hello 会收到
`INCOMPATIBLE_PROTOCOL` 错误；第二个活动 Extension 会收到
`EXTENSION_ALREADY_CONNECTED`。Extension 还会发送 `ping`，Broker 以 `pong` 响应。

### 请求、响应与进度

Broker 发送：

```json
{"type":"request","id":"transport-id","method":"chat","params":{"provider":"chatgpt","tab_id":42,"text":"你好"}}
```

支持的内部方法为 `open`、`chat` 和 `get_messages`。响应为以下两种之一：

```json
{"type":"response","id":"transport-id","ok":true,"result":{}}
```

```json
{"type":"response","id":"transport-id","ok":false,"error":{"code":"PAGE_NOT_READY","message":"...","safe_to_retry":false}}
```

Progress 使用相同 Transport ID，并包含 `tab_id`、`url`、`provider`、`phase`、
`elapsed_ms` 和 `idle_ms`。该 WebSocket 契约属于内部接口；Provider 变化时可以连同
Extension 测试和协议测试一起更新。

## 错误与重试安全

每个 Broker 失败都包含供机器判断的 `code`、诊断用 `message` 和布尔值
`safe_to_retry`。不能从本地化的 message 文本推断行为。

`safe_to_retry` 含义严格受限：在产生错误的位置，已知重复执行同一 RPC 不会复制页面侧
副作用。它不表示重试一定成功。`false` 表示无法证明盲目重试安全，不一定表示故障永久
存在。

当前实现默认将该字段设为 `false`。明确的安全情形是分派前发现
`TAB_CLOSED`，Extension 会将其设为 true。`CHAT_STATE_UNKNOWN` 始终为 false：分派
已经开始，而标签页或消息通信丢失导致无法判断 Prompt 是否提交。绝不能自动重放该
Prompt。

当前面向 Broker 的错误码包括：

| 范围 | 错误码 |
| --- | --- |
| Envelope 与参数 | `INVALID_JSON`、`INVALID_REQUEST`、`INVALID_ARGUMENT`、`UNKNOWN_METHOD` |
| Provider/Session 选择 | `PROVIDER_NOT_FOUND`、`SESSION_NOT_FOUND`、`INVALID_URL` |
| Extension 可用性 | `EXTENSION_NOT_CONNECTED`、`TAB_CLOSED`、`CONTENT_SCRIPT_UNAVAILABLE` |
| 页面操作 | `PAGE_NOT_READY`、`INPUT_FAILED`、`BUSY`、`SEND_FAILED` |
| Chat 歧义 | `CHAT_STATE_UNKNOWN` |
| 时间与大小 | `RPC_TIMEOUT`、`RESPONSE_TIMEOUT`、`RESPONSE_TOO_LARGE` |
| 兜底 | `INTERNAL_ERROR` |

`PROMPT_NOT_FOUND` 和 `SEND_BUTTON_NOT_FOUND` 是 content runtime 内部诊断。目前会重试
这些错误，并在稳定 Broker 边界归并为 `PAGE_NOT_READY`。`DOM_CHANGED` 不是当前稳定
错误码。

握手条件还会使用 `INCOMPATIBLE_PROTOCOL` 和 `EXTENSION_ALREADY_CONNECTED`；无效
Origin 由 WebSocket Server 拒绝。Python Client 遇到畸形、超大或非对象的 Broker
结果时可能抛出 Client 侧 `INVALID_RESPONSE`。在最终响应前连接关闭也属于 Client 侧
Transport 失败，不能视为成功。
