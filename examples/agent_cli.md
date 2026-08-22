# Agent CLI 示例

先确认已认证的 ChatGPT 标签页已加载扩展。`web-llm-agent` 会自动启动或复用本机
Broker，并通过 Broker 操作 Session，不需要读取浏览器认证材料。

## 建立或恢复 Session

```powershell
web-llm-agent list-sessions --json
web-llm-agent open --new --json
web-llm-agent open --session-id SESSION_ID --json
```

`open --new` 建立新的 Conversation；恢复已有记录时优先传 `--session-id`，避免在
脚本中硬编码 Conversation URL。

## 发送 Prompt

短文本可用参数：

```powershell
web-llm-agent chat --text "列出三个可执行的测试步骤"
```

长文本从 stdin 传入：

```powershell
Get-Content .\prompt.txt -Raw | web-llm-agent chat --stdin --json
```

`--json` 会把成功结果作为单行 JSON 对象写入 stdout，便于脚本解析：

```json
{"text":"..."}
```

进度和诊断信息写入 stderr。失败时进程返回非零状态码，并在 stderr 输出以 `Error:`
开头的诊断；Agent 不应把人类可读诊断当作 JSON 结果。Broker 原始 NDJSON 协议的
结构化错误格式如下：

```json
{"id":"REQUEST_ID","ok":false,"error":{"code":"CHAT_STATE_UNKNOWN","message":"...","safe_to_retry":false}}
```

直接接入 Broker 协议或 Python API 的调用方应按 `error.code` 和 `safe_to_retry` 决定
后续动作。`CHAT_STATE_UNKNOWN` 表示 Prompt 可能已经提交，不能自动重发；
`RESPONSE_TIMEOUT` 也不应把不完整文本当作成功答案。

## 读取历史

```powershell
web-llm-agent get-messages --limit 20 --json
web-llm-agent get-messages --all --json
```

历史是页面当前已捕获的数据，可能受虚拟化列表、网络速度和页面可见性影响。不要把
输出写入包含凭据的日志或上传到公共服务。
