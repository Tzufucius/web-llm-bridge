# ChatGPT Provider

该 Provider 保存 ChatGPT 的地址校验、页面选择器、活动判断和 KaTeX 序列化规则。

## 支持范围

- Hosts：`chatgpt.com`、`www.chatgpt.com`；
- Prompt：优先 `#prompt-textarea`，并保留语义 textbox fallback；
- Messages：依赖 `data-message-author-role` 区分 user 与 assistant；
- Completion：结合 Stop、Assistant 内容稳定、工具/状态活动和完成操作栏判断；
- History：依赖可滚动消息容器、稳定 turn 属性和重叠窗口增量采集；
- Math：读取 KaTeX/MathML 中的 TeX annotation，输出行内或块级 LaTeX。

## 状态策略

发送后必须观察到用户消息、输入框清空、生成状态或 Assistant 变化之一。回复完成需要
文本稳定 1500 ms，并在生成停止后连续确认序列化结果 3000 ms；页面连续 5 分钟没有
有效活动时返回 `RESPONSE_TIMEOUT`。工具卡片和状态节点只有发生变化时才算活动。

## 已知限制

ChatGPT DOM、ARIA 文案和虚拟化列表可能随站点发布改变。隐藏消息、尚未加载的长历史、
复杂 MathJax 包装、图片和嵌套列表不保证完全保真。Provider 不点击 Copy，也不读取
Cookie、Token 或私有 API。

Last tested：2026-08-22，Chrome/Edge Manifest V3 合成 DOM smoke；真实登录态 E2E 待本轮用户协同验证。

Assistant 图片会作为 Artifact descriptor 提取。Adapter 过滤头像、图标、placeholder
和用户上传图片，按 turn/index 保持稳定身份，并将私有 source 仅用于后续
`get-artifact` 获取，不会进入普通 Agent 输出。
