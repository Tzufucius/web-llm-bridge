# scripts

此目录提供不依赖 Shell 类型的跨平台 Python 启动入口：

- `manual_console.py`：自动启动或复用 Broker，然后进入人工交互控制台；
- `agent_cli.py`：自动启动或复用 Broker，然后执行一次面向智能体的 CLI 命令。

两个入口的帮助、参数说明和交互提示统一使用英文。浏览器扩展仍需由用户显式加载并登录。
