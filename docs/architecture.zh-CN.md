[English](architecture.md) | **简体中文**

# 架构

## 目标

Web LLM Bridge 将已经认证的浏览器页面作为执行界面，将本机 Python 进程作为控制面。
Python 不启动浏览器、不接入调试协议，也不注入凭据。所有页面交互都由 Manifest V3
扩展在用户或扩展打开的标签页中执行。

公共抽象是与 Provider 无关的浏览器会话，而不是 OpenAI API 模拟器。站点特有的 DOM
知识保留在扩展中。

## 仓库结构

| 路径 | 职责 |
| --- | --- |
| `web_llm_bridge/` | Python 协议、Transport、Provider 元数据、Session 管理、Broker、Client 和 CLI。 |
| `extension/core/` | 与 Provider 无关的浏览器运行时、路由、历史、Markdown、RPC 和标签页机制。 |
| `extension/providers/` | 站点特有的 Profile、DOM Adapter 和 Serializer。 |
| `tests/` | Python 架构/协议回归测试和合成 Extension smoke 测试。 |
| `docs/` | 架构、协议、Provider 契约和实现假设。 |
| `examples/` | 最小 Python 与 Agent CLI 用法。 |
| `scripts/` | 跨平台人工控制台和 Agent CLI 启动入口。 |

## 进程拓扑

```text
CLI / 本地 Agent / WebLLMSession
              |
              | NDJSON over TCP，127.0.0.1:8766
              v
Persistent Broker
  SessionManager ---- SessionStore（仅元数据）
        |
        | 单一 ExtensionTransport
        | WebSocket，127.0.0.1:8765
        v
Manifest V3 Extension
  service worker ---- provider registry / tab routing
        |
        v
content runtime ---- provider adapter ---- 已认证网页
```

两个监听器都绑定回环接口。它们是本地 IPC 边界，不是对外暴露的远程服务 API。

## 所有权边界

### Client 与 Session 句柄

`WebLLMClient` 每次连接发送一个 Broker RPC。`WebLLMSession` 是轻量的 Broker-backed
句柄，只包含 `provider`、`session_id`、`conversation_url` 和
`reopen_on_closed`。它不拥有标签页、WebSocket、Broker 进程或凭据。退出其异步上下文
不会关闭任何共享资源。

当前协议没有公共 `close` RPC。`SessionManager.close()` 只在 Broker 退出时用于关闭
Broker 所有的 Transport。

### Broker 与 SessionManager

Broker 是唯一监听扩展连接的 Python 进程。它负责：

- 校验并分派本地 NDJSON 请求；
- 持有一个 `SessionManager`、一个 Provider registry、一个 `SessionStore` 和一个
  `ExtensionTransport`；
- 将扩展进度改写为以调用方请求 ID 关联的 Broker 进度；
- 将类型化异常转换为稳定错误对象；
- 拒绝超过 8 MiB NDJSON 单行限制的响应。

`SessionManager` 持有编排和恢复策略。当前单一 `asyncio.Lock` 会串行化该 Manager 上
所有 `open`、`chat` 和 `get_messages` 操作，包括不同 Session 或 Provider 的操作。
`list_sessions` 只读取元数据，不获取该锁。

Broker 不会主动持久化 Prompt 或回复正文，也不是远程代理。

### Session 与 SessionStore

Session 是可持久化的绑定记录，不是网页 Conversation 的副本。Store 保存 schema
version、Provider ID、Session ID、tab ID、当前 URL、创建/更新时间、sequence、active
状态和 `reopen_on_closed`。每个 Provider 最多有一条 active 记录。

每次 Chat 分派前，`sequence` 都会先递增并持久化。因此它统计 Chat 尝试，包括随后失败
的尝试；它不能证明页面已经接受消息。

Store 不包含消息正文或认证材料。删除本地 registry 不会删除 Provider 网站中的
Conversation。

### Python Provider 定义

Python `ProviderDefinition` 是不可变的静态元数据：`id`、`default_url`、允许的
`hosts`、`capabilities` 和 HTTPS URL 规范化。它没有 DOM selector、连接状态或
`open`/`chat`/`get_messages` 方法。

调用共享 `ExtensionTransport` 的是 `SessionManager`，而不是 Provider 实例。这样可将
Provider 注册与 Transport 所有权分开，也可防止每个 Provider 各自创建监听器。

### ExtensionTransport

Broker 所有的 Transport 是 `127.0.0.1:8765` 上唯一的监听器。它只接受一个活动扩展
连接，校验 Chrome 扩展 Origin 和协议版本，关联请求与响应，过滤 progress phase，
并管理超时。它的请求 ID 是 Transport 内部 ID，不要求等于调用方的 NDJSON 请求 ID。

对于 Chat，收到合法 progress 会重置 Transport 等待时限。内容运行时另行执行 5 分钟
有效页面活动超时，因此类似心跳的 progress 不能将无活动页面变成成功完成。

### Extension core 与 Provider adapter

Service worker 持有 Broker 连接和标签页路由。Content runtime 持有通用输入、提交确认、
进度生成、完成等待、历史捕获和 Markdown 遍历。

Extension provider 提供站点特有的元数据和行为：

- URL 匹配与规范化；
- selector 以及 Prompt、Send、生成状态发现；
- 消息 role、turn identity、completion marker 和 activity snapshot；
- ChatGPT KaTeX 提取等特殊序列化。

扩展不需要密码、Cookie、Token、私有 Conversation API、DevTools/CDP 或剪贴板权限。

## 依赖方向

```text
CLI / WebLLMSession -> Broker client -> Broker server -> SessionManager
                                                   |-> SessionStore
                                                   |-> ProviderRegistry
                                                   `-> ExtensionTransport
                                                          |
                                                          v
extension core -> extension provider adapter -> page DOM
```

CLI 格式不能泄漏到 Provider。Python Provider 定义不能依赖 CLI 或 Extension DOM 模块。
通用 Extension core 可以调用已注册 adapter，但 adapter 不能持有 Broker Transport。

## Chat 请求生命周期

1. Client 创建非空字符串 `id`，向 `127.0.0.1:8766` 发送一行 UTF-8 JSON 对象。
2. Broker 校验 envelope，随后 `SessionManager` 获取全局操作锁并解析或创建 Session
   记录。
3. 分派前，Manager 递增已存储的 Session `sequence`。
4. `ExtensionTransport` 创建自己的请求 ID 并把操作发送给 service worker。Service
   worker 根据标签页 URL 核验请求的 Provider，再将操作转发给 content script。
5. Content runtime 写入 Prompt、点击 Send 并等待提交证据。只有此后才发出
   `submitted`。
6. 等待最终内容时，扩展发送允许的 progress phase。Transport 将其关联到内部 pending
   call；Broker 再用原始 NDJSON `id` 对外发送。
7. 最终内容稳定后，响应沿相同层级返回。Manager 更新 URL 和 Session 元数据、释放锁，
   Broker 发送且只发送一条最终响应。

Progress 仅用于观测。它不表示成功，也不能替代最终响应。

## 故障与重试约束

Chat 是具有副作用的操作。开始向 content script 分派后，标签页关闭或消息通信失败可能
使提交状态无法确认。Extension 将此歧义映射为 `CHAT_STATE_UNKNOWN`，并设置
`safe_to_retry: false`。`SessionManager` 和 Client 都不会自动重发 Prompt。

如果在 content script 分派前已确认标签页关闭，Extension 可以返回
`TAB_CLOSED`，并设置 `safe_to_retry: true`。启用 `reopen_on_closed` 后，
`get_messages` 会重新绑定并重试一次。对于 `chat`，Manager 可以为后续操作重新绑定，
但仍抛出原始错误，绝不会重放 Prompt。

即使 `safe_to_retry` 为 true，错误仍然是失败。该字段只表示：在产生错误的边界上，已知
重复执行同一个 RPC 不会复制页面侧副作用。
