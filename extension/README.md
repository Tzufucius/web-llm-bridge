# Web Bridge 扩展

该目录包含 Manifest V3 扩展的运行时代码：

- `service_worker.js`：维护唯一的 `ws://127.0.0.1:8765` 连接，创建 ChatGPT 标签页并路由 RPC；
- `content.js`：在 ChatGPT 页面内完成 DOM 输入、发送、长思考状态检测、进度推送、历史滚动缓存和 Markdown/LaTeX 序列化；
- `manifest.json`：声明最小的 `alarms`、ChatGPT host permissions 和 content script matches。

扩展不读取或保存密码、Cookie、Token 和系统剪贴板，也不调用 ChatGPT 私有 API。
进度消息只在活动 Chat RPC 期间转发；内容脚本会把工具调用卡片、思考/状态区域的实际变化作为 `tool_call` 或 `working` 进度，并在 Stop 按钮消失后继续确认约 3 秒的最终 DOM。完成操作栏只用于判断页面状态，不会点击 Copy，不保存历史或 Session 状态。
