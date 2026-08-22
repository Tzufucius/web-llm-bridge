# Web Bridge 扩展

该目录包含 Manifest V3 扩展的运行时代码：

- `service_worker.js`：维护唯一的 `ws://127.0.0.1:8765` 连接，创建 ChatGPT 标签页并路由 RPC；
- `content.js`：在 ChatGPT 页面内完成 DOM 输入、发送、历史滚动缓存和 Markdown/LaTeX 序列化；
- `manifest.json`：声明最小的 `alarms`、ChatGPT host permissions 和 content script matches。

扩展不读取或保存密码、Cookie、Token 和系统剪贴板，也不调用 ChatGPT 私有 API。
