# Bridge 回归测试

此目录保存不依赖真实 ChatGPT 登录态的 Web Bridge 合成回归测试。

- `tool_activity_smoke.js`：模拟工具调用卡片位于 `main` 外、连续更新后 Assistant 出现，验证 `tool_call` 进度和最终回复。
- `streaming_completion_smoke.js`：模拟 Stop 提前消失、Assistant 节点替换、完成操作栏延迟出现和最终文本延迟提交。
- `submission_wait_smoke.js`：模拟新标签页发送后用户消息节点和 Assistant 延迟出现，验证提交确认等待及 `working` 进度。
- `test_session_store.py`：验证 Session 元数据、列表排序、原子写入和损坏文件恢复。
- `test_broker.py`：验证 Broker 的 open 幂等、Session 列表、Agent RPC 和并发串行化。

运行：

```powershell
node tools/chatgpt_web_bridge/tests/tool_activity_smoke.js
node tools/chatgpt_web_bridge/tests/submission_wait_smoke.js
node tools/chatgpt_web_bridge/tests/streaming_completion_smoke.js
python -m unittest discover -s tools/chatgpt_web_bridge/tests -p "test_*.py"
```
