# ChatGPT Web Bridge

这是一个单文件 Python 工具，通过 Playwright 操作 ChatGPT 网页 DOM，支持：

- 绑定 ChatGPT 首页或已有 Conversation URL；
- 读取当前页面中已经加载的 `user` / `assistant` 消息；
- 发送文本并等待完整 Assistant 回复；
- 在同一个标签页中连续多轮对话。

## 安装

```bash
pip install playwright
playwright install chromium
```

## 运行

```bash
python tools/chatgpt_web_bridge/chatgpt_web_bridge.py
```

浏览器会以可见模式启动。首次运行时，请在打开的 ChatGPT 页面中手动登录。登录状态会保存在：

```text
tools/chatgpt_web_bridge/chatgpt_browser_profile/
```

该目录包含浏览器本地数据，已加入 Git 忽略规则，不应手动提交或分享。

## Python 接口

```python
session = await ChatGPTSession.open("https://chatgpt.com/")
messages = await session.get_messages()
answer = await session.chat("你好")
```

`get_messages()` 只读取当前 DOM 中已经加载的消息。极长会话如果使用了页面虚拟化，未加载到 DOM 的早期消息不会被读取。

工具不调用 OpenAI API、ChatGPT 私有接口、Cookie/Token 提取接口或网络抓包功能。

## CLI 命令

- `/history`：读取并打印当前页面消息；
- `/exit`、`/quit`：退出并关闭浏览器上下文。
