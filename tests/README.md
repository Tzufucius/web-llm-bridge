# Bridge 回归测试

此目录保存不依赖真实 ChatGPT 登录态的 Web Bridge 合成回归测试。

- `tool_activity_smoke.js`：模拟工具调用卡片位于 `main` 外、连续更新后 Assistant 出现，验证 `tool_call` 进度和最终回复。

运行：

```powershell
node tools/chatgpt_web_bridge/tests/tool_activity_smoke.js
```
