# Agent CLI 示例

先确认已认证的 ChatGPT 标签页已加载扩展。`web-llm-agent` 会自动启动或复用本机 Broker，并通过 Broker 操作 Session，不需要读取浏览器认证材料。

## 建立或恢复 Session

```powershell
web-llm-agent list-sessions --json
web-llm-agent open --new --json
web-llm-agent open --session-id SESSION_ID --json
```

`open --new` 建立新的 Conversation；恢复已有记录时可传 `--session-id`，也可以使用 `--url` 打开指定 Conversation URL。

## 发送 Prompt

短文本可用参数：

```powershell
web-llm-agent chat --text "列出三个可执行的测试步骤"
```

长文本从 stdin 传入：

```powershell
Get-Content .\prompt.txt -Raw | web-llm-agent chat --stdin --json
```

指定 `--json` 后，成功和失败都会向 stdout 写入单行 JSON；进度和诊断信息写入 stderr。

成功示例：

```json
{"ok":true,"result":{"text":"..."}}
```

失败示例：

```json
{"ok":false,"error":{"code":"CHAT_STATE_UNKNOWN","message":"...","safe_to_retry":false}}
```

失败时进程返回非零状态码。Agent 应根据 `error.code` 和 `safe_to_retry` 决定后续动作，而不是解析 stderr 中的自然语言。`CHAT_STATE_UNKNOWN` 表示 Prompt 可能已经提交，不能自动重发；`RESPONSE_TIMEOUT` 也不应把不完整文本当作成功答案。

## 读取历史

```powershell
web-llm-agent get-messages --limit 20 --json
web-llm-agent get-messages --all --json
```

历史是页面当前已捕获的数据，可能受虚拟化列表、网络速度和页面可见性影响。不要把输出写入包含凭据的日志或上传到公共服务。
