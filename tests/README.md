# Bridge 回归测试

此目录保存 Python 分层测试，以及不依赖真实 ChatGPT 登录态的 Extension 合成回归测试。

- `core/`：协议、依赖方向和 Agent CLI 测试；
- `core/test_launcher.py`：跨平台 Broker 自动启动和 CLI help 路径测试；
- `broker/`：Broker 请求、NDJSON 边界和 progress 顺序测试；
- `session/`：公共句柄、单一 Transport、Store 原子写和损坏恢复测试；
- `providers/chatgpt/`：Provider metadata，以及 streaming、submission、tool、history、serializer 和 tabs smoke。

运行：

```powershell
python -m pytest
Get-ChildItem tests/providers/chatgpt/*_smoke.js | ForEach-Object { node $_.FullName }
```
