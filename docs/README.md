# 文档目录

本目录记录 `web-llm-bridge` 的架构、协议和 provider 开发约束。先阅读根目录
`README.md` 完成安装，再根据需要查阅以下文档：

- `architecture.md`：进程边界、依赖方向和会话生命周期；
- `protocol.md`：Extension WebSocket 与 Broker NDJSON 的消息约定；
- `provider-development.md`：实现或评审 provider 时需要遵守的接口边界；
- `providers/chatgpt.md`：ChatGPT Web provider 的浏览器会话与 DOM 约束。
