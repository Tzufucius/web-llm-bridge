# 示例

示例默认 Broker 已在 `127.0.0.1:8766` 运行，且浏览器扩展已经连接到本机 Broker。
示例只使用用户自己的已认证 ChatGPT 页面，不包含登录、Cookie 或 Token 操作。

- `basic_chat.py`：使用标准库发送两次最小 NDJSON RPC；
- `agent_cli.md`：使用 `web-llm-agent` 处理 stdin、JSON 输出和错误。

示例不是稳定的远程 API 客户端。生产 Agent 应固定错误处理、超时和日志脱敏策略。
