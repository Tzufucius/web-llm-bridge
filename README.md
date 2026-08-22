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

新建标签页后，ChatGPT 可能仍在加载会话、输入框或发送按钮。内容脚本会等待页面就绪，发送按钮暂时不可用时持续轮询；点击发送后还会等待用户消息节点、输入框清空、生成状态或 Assistant 节点等提交证据，最长约 60 秒。等待期间 CLI 会显示“ChatGPT 正在工作”，不会立即把页面卡顿当作发送失败。超过等待窗口仍没有任何提交证据，才返回 `SEND_FAILED`，这通常表示页面仍未完成加载或 DOM 结构已变化。

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

### 长思考与进度提示

发送消息后，内容脚本不会要求 Assistant DOM 节点立即出现。ChatGPT 处于思考、调用浏览或代码分析工具、状态刷新或流式生成阶段时，扩展会通过 WebSocket 推送进度，CLI 使用单行显示“正在思考”“正在工作”“正在调用工具”或“正在生成回复”。进度消息只关联当前 Chat RPC 的 `request_id`，不改变 `chat()` 的公开返回值。

响应超时采用“连续 5 分钟没有有效页面活动”的空闲策略，而不是固定总时长；只要消息区域、工具调用卡片、思考/状态区域或 Assistant 内容实际更新，就会继续等待。内容脚本同时使用语义 DOM 选择器、MutationObserver 和轻量轮询快照，以覆盖不在 `main` 内的工具卡片及仅更新属性的状态节点。Stop 按钮消失后还会进行约 3 秒的最终确认，重复检查 Assistant 文本、响应 DOM 和 Markdown/LaTeX 序列化结果；页面卡顿或流式提交延迟时会优先等待，避免把中间文本当作最终答案。完成操作栏只用于状态检测，不会点击 Copy。静态 Stop 按钮或静态工具卡片本身不算活动，避免页面卡住后无限等待。若连续 5 分钟无更新，Bridge 返回 `RESPONSE_TIMEOUT`，不会把半截回复当作成功答案。

标签页关闭后的恢复是显式策略：

```python
session = await ChatGPTSession.open(
    "https://chatgpt.com/c/CONVERSATION_ID",
    reopen_on_closed=True,
)
```

启用后，`get_messages()` 遇到 `TAB_CLOSED` 会基于最近记录的 Conversation URL 自动重新打开并只重试读取一次；`chat()` 只恢复绑定并保留原错误，不会自动重发状态不确定的 prompt。CLI 会先询问是否基于当前 URL 重开，重开后需要用户再次输入消息。ChatGPT 首页跳转到 `/c/...` 时 tabId 保持不变，Bridge 会在 RPC 返回时更新当前 URL。

## CLI 命令

- `/history`：读取当前内容脚本缓存；
- `/history N`：读取最近 N 条，N 范围为 `1~1000`；
- `/history all`：请求完整历史；
- `/exit`、`/quit`：只关闭 Python WebSocket Bridge，不关闭 Chrome/Edge 或 ChatGPT 标签页。

## 错误与限制

Bridge 固定监听 `127.0.0.1:8765`，只接受 Chrome/Edge 扩展 Origin，并且同一时间只允许一个扩展 WebSocket 客户端。扩展只负责 WebSocket、标签页创建和消息路由，不保存 Conversation 历史或 Session registry。

ChatGPT 页面 DOM 或 selector 变化时，可能返回 `DOM_CHANGED`、`PROMPT_NOT_FOUND`、`SEND_BUTTON_NOT_FOUND` 等结构化错误。历史加载受页面虚拟化、网络速度和 DOM 可见性影响；超时会保留部分结果并提示截断。聊天响应若连续 5 分钟无页面活动会返回 `RESPONSE_TIMEOUT`。真实登录态下的多轮对话、长思考、长历史、公式和关闭标签页恢复需要在用户的 Chrome/Edge 环境中验证。
