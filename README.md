# ChatGPT Web Bridge

本工具由两个部分组成：

```text
正常 Chrome / Edge
    ↓
Manifest V3 Extension
    ↓
ws://127.0.0.1:8765
    ↓
Python ChatGPTSession
```

Python 不启动或接管浏览器，也不读取密码、Cookie、Token。ChatGPT DOM 只在
`extension/content.js` 中处理，浏览器登录状态完全由用户正常使用的 Chrome/Edge 维护。

## 安装 Python 依赖

```bash
python -m pip install -r tools/chatgpt_web_bridge/requirements.txt
```

本版本不再使用 Playwright，不需要 `playwright install chromium`。
请使用启动 Bridge 的同一个 Python 环境安装依赖。可用以下命令确认解释器和版本：

```powershell
python -c "import sys, websockets; print(sys.executable); print(websockets.__version__)"
```

`websockets` 需要 14.0 或更高版本；如果版本过低，请在同一终端执行上述安装命令。

## 加载扩展

Chrome：

1. 打开 `chrome://extensions`；
2. 开启“开发者模式”；
3. 选择“加载已解压的扩展程序”；
4. 选择本目录下的 `extension/`。

Edge 使用同样步骤，入口为 `edge://extensions`。
扩展最低要求 Chrome/Edge 120。

扩展没有 popup。点击工具栏扩展图标会立即尝试连接本地 Python Bridge。

## 运行 Bridge

```bash
python tools/chatgpt_web_bridge/chatgpt_web_bridge.py
```

程序先提示输入 ChatGPT URL。输入后，`ChatGPTSession.open()` 启动并监听
`127.0.0.1:8765`，等待扩展完成握手，再由扩展创建并绑定一个新的 ChatGPT 标签页。

建议先保持 Chrome/Edge 和扩展运行，再执行命令。扩展会自动重连；若 Python Bridge
尚未运行或曾因协议冲突暂停重连，点击工具栏扩展图标即可再次尝试。

## Python 接口

```python
session = await ChatGPTSession.open("https://chatgpt.com/")
messages = await session.get_messages()
answer = await session.chat("你好")
```

每个 Session 绑定一个浏览器 `tabId`。ChatGPT 从首页跳转到 `/c/...` 时，tabId 不变，
同一个 Session 继续使用原标签页。多个 Session 可以共享一个 Bridge，但每个 Session 有独立 tabId。

`get_messages()` 只读取当前页面 DOM 中已经加载的 `user` / `assistant` 纯文本。极长会话如果发生 DOM 虚拟化，
未加载到 DOM 的早期消息不会被读取。

## CLI 命令

- `/history`：读取当前绑定标签页消息；
- `/exit`、`/quit`：关闭 Python WebSocket Bridge，不关闭 Chrome/Edge 或 ChatGPT 标签页。

## 错误与限制

Bridge 使用结构化错误码处理扩展未连接、标签页关闭、输入框失效、发送按钮失效、页面生成中和回复超时等情况。
Python 与扩展只允许一个 WebSocket 客户端，监听地址固定为本机回环地址，不提供远程访问接口。

本工具不再使用 Playwright、独立浏览器 Profile 或手动登录脚本。扩展不读取或保存密码、Cookie、Token；
登录请直接在用户自己的 Chrome/Edge 中完成。页面历史消息受 ChatGPT DOM 虚拟化影响，未加载到 DOM 的早期消息可能无法读取。
