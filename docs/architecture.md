# 架构

## 目标

项目把“浏览器中已经认证的页面”作为 ChatGPT 的执行端，把本机 Python 进程作为
控制面。Python 不启动、接管或注入浏览器调试协议；所有页面交互由 Manifest V3
Extension 在用户打开的 ChatGPT 标签页中完成。

## 组件

```text
CLI / 本地 Agent
       |
       | NDJSON，127.0.0.1:8766
       v
Persistent Broker ---- SessionStore（仅元数据）
       |
       | WebSocket，127.0.0.1:8765
       v
Manifest V3 Extension
       |
       v
已认证的 ChatGPT Web 标签页
```

### Extension

Extension 维护到 Broker 的唯一 WebSocket 连接，负责创建或定位 ChatGPT 标签页、
路由请求，并在内容脚本中完成 DOM 输入、发送、历史捕获和 Markdown/LaTeX 序列化。
它不保存密码、Cookie、Token、Prompt 或 Session registry。

### Broker

Broker 是唯一连接 Extension 的 Python 进程，也是多个 Agent 调用之间的 session
owner。它负责：

- 串行化同一个 Session 上的 open、chat、get-messages 操作；
- 将本地 NDJSON 请求映射为 provider 操作；
- 转发带 request ID 的 progress 事件；
- 将会话元数据写入 `SessionStore`，并在重启后恢复 active 记录；
- 将 provider 异常转换为稳定的结构化错误。

Broker 不应缓存 Prompt 或回复正文，不应成为远程代理。默认只监听回环地址。

### Provider

Python Provider 把站点的 metadata、URL 规范化和 capabilities 暴露给 Broker，并
提供统一的 open、chat、get-messages、close 方法。它不解析页面 DOM，也不保存
selector 或站点认证状态。当前只有 ChatGPT provider，见 [providers/chatgpt.md](providers/chatgpt.md)。

DOM 细节属于 Extension provider adapter：prompt discovery、send、submission detection、
generation、completion、message extraction、turn identity、history scroll 和
special serializer 都在浏览器侧执行。该边界使 Python provider 保持站点无关，也让
页面 DOM 变化可以局部修复。

### SessionStore

SessionStore 保存可恢复绑定所需的最小元数据：Session ID、tab ID（如果可得）、当前
Conversation URL、创建和更新时间、sequence、active。它不保存消息正文或认证材料。
删除运行时 registry 不会删除浏览器中的 Conversation。

## 依赖方向

```text
cli -> broker client -> broker server -> Python provider -> extension protocol
                                      \-> session store
                                                   \-> Extension provider adapter -> DOM
```

Python provider 不应反向依赖 CLI 的输出格式；CLI 也不应直接访问 Extension。这样
可以让 Agent 使用稳定的 Broker 协议，并让 DOM 适配变化停留在 Extension 边界内。

## 一次请求的生命周期

1. CLI 为请求生成唯一 `id`，向 `127.0.0.1:8766` 发送一行 NDJSON。
2. Broker 校验方法和参数，获取当前 Session，并取得操作锁。
3. Provider 通过 Extension 向 ChatGPT 标签页执行操作。
4. 长操作期间，Extension 和 Broker 可发送带同一 `id` 的 progress 事件。
5. 页面完成、失败或达到连续空闲超时后，Broker 发送一条最终 response，并释放锁。
6. Broker 更新 Session 元数据；调用方根据 `ok` 和错误码决定是否重试。

`chat` 在提交状态不确定时不得自动重发原 Prompt。关闭标签页后的读取可以按显式
策略恢复绑定；恢复后的重试次数必须有限，避免重复执行副作用。

## 并发与故障

同一 Broker 同时只允许一个活动的 Chat 操作。连接断开、页面 DOM 改变、会话不存在、
响应无活动超时和 Extension 未连接都必须转成错误码，而不是返回半截成功结果。进度
消息只是观测信息，不改变最终 RPC 的返回结构。
