# ChatGPT Web Bridge

本工具通过浏览器扩展把用户正常运行的 Chrome/Edge ChatGPT 页面桥接到 Python：

```text
正常 Chrome / Edge
    ↓
Manifest V3 Extension
    ↓
ws://127.0.0.1:8765
    ↓
Python ChatGPTSession
```

Python 不启动或接管浏览器。扩展不读取、保存密码、Cookie 或 Token，登录请直接在用户自己的 Chrome/Edge 中完成。
本工具不调用 ChatGPT 私有 Conversation API，也不使用 Playwright、Selenium、CDP、数据库或剪贴板权限。

## 安装 Python 依赖

请在启动 Bridge 的同一个 Python 环境中执行：

```powershell
python -m pip install -r tools/chatgpt_web_bridge/requirements.txt
python -c "import sys, websockets; print(sys.executable); print(websockets.__version__)"
```

`websockets` 必须为 14.0 或更高版本。若诊断命令显示版本过低，请使用同一个 `python` 解释器升级，避免 Bridge 与升级命令使用不同环境。

## 加载扩展

Chrome：

1. 打开 `chrome://extensions`；
2. 开启“开发者模式”；
3. 选择“加载已解压的扩展程序”；
4. 选择本目录下的 `extension/`。

Edge 使用同样步骤，入口为 `edge://extensions`。扩展最低要求 Chrome/Edge 120。

扩展没有 popup。点击工具栏扩展图标会立即尝试连接本地 Python Bridge；Bridge 未运行时扩展会自动重连。

## 启动流程

```powershell
python tools/chatgpt_web_bridge/chatgpt_web_bridge.py
```

启动菜单：

- 直接按 Enter 或输入 `1`：新建 `https://chatgpt.com/` 对话，不加载历史；
- 输入 `2`：输入已有 Conversation URL。已有会话默认加载历史，提示处直接按 Enter 等同 `Y`；
- 首页 URL（`https://chatgpt.com/`）会提示并按新对话处理。

历史加载选项：

- 直接按 Enter：最近 5 条；
- 输入数字：加载最近 `1~1000` 条；
- 输入 `n`：随后自定义 `1~1000`；
- 输入 `a` 或 `all`：尽可能加载完整历史。

启动时只显示加载数量和是否截断，不自动打印全部消息。历史读取在内容脚本中通过 DOM 滚动和 `turnCache` 增量缓存完成，适配 ChatGPT 的虚拟化消息列表；超出 60 秒时返回已经捕获的消息并标记截断，同时记录 warning，因此这是 best-effort 历史加载，不保证私有页面状态下的绝对完整性。

输出统一由 DOM Markdown/LaTeX serializer 生成，支持标题、段落、粗体、斜体、列表、引用、代码、链接、表格、水平线、换行和行内/块级 TeX。不会点击 ChatGPT 的 Copy 按钮，也不会静默覆盖系统剪贴板。

## Python 接口

```python
session = await ChatGPTSession.open("https://chatgpt.com/")
messages = await session.get_messages()
recent = await session.get_messages(limit=20)
complete = await session.get_messages(full=True)
answer = await session.chat("你好")
```

公开接口保持兼容。`get_messages()` 无参数调用继续有效，返回当前内容脚本已经捕获的消息；`limit=N` 返回最近 N 条，`full=True` 忽略 `limit` 并请求完整历史，消息顺序始终为最早到最新。

标签页关闭后的恢复是显式策略：

```python
session = await ChatGPTSession.open(
    "https://chatgpt.com/c/CONVERSATION_ID",
    reopen_on_closed=True,
)
```

启用后，`get_messages()` 遇到 `TAB_CLOSED` 会基于最近记录的 Conversation URL 自动重新打开并只重试读取一次。`chat()` 不会自动重发状态不确定的 prompt；CLI 会先询问是否基于当前 URL 重开，重开后需要用户再次输入消息。ChatGPT 首页跳转到 `/c/...` 时 tabId 保持不变，Bridge 会在 RPC 返回时更新当前 URL。

## CLI 命令

- `/history`：读取当前内容脚本缓存；
- `/history N`：读取最近 N 条，N 范围为 `1~1000`；
- `/history all`：请求完整历史；
- `/exit`、`/quit`：只关闭 Python WebSocket Bridge，不关闭 Chrome/Edge 或 ChatGPT 标签页。

## 错误与限制

Bridge 固定监听 `127.0.0.1:8765`，只接受 Chrome/Edge 扩展 Origin，并且同一时间只允许一个扩展 WebSocket 客户端。扩展只负责 WebSocket、标签页创建和消息路由，不保存 Conversation 历史或 Session registry。

ChatGPT 页面 DOM 或 selector 变化时，可能返回 `DOM_CHANGED`、`PROMPT_NOT_FOUND`、`SEND_BUTTON_NOT_FOUND` 等结构化错误。历史加载受页面虚拟化、网络速度和 DOM 可见性影响；超时会保留部分结果并提示截断。真实登录态下的多轮对话、长历史、公式和关闭标签页恢复需要在用户的 Chrome/Edge 环境中验证。
