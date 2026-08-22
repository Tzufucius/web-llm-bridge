# 会话注册表

此目录由 `SessionStore` 在运行时创建和维护。`index.json` 和每个
`<session_id>.json` 文件只保存标签页会话元数据：会话 ID、标签页 ID、当前
URL、时间、序号和活动状态。

注册表不会保存消息正文、密码、Cookie、Token 或其他秘密。文件属于本机
运行时状态，不应提交到版本库；删除目录不会影响浏览器中的 ChatGPT 会话。
