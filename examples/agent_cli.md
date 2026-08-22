# Agent CLI 示例

先确认 `web-llm-broker serve` 正在运行，并且已认证的 ChatGPT 标签页已加载扩展。
`web-llm-agent` 通过 Broker 操作 Session，不需要读取浏览器认证材料。

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

`--json` 会输出单行对象，便于脚本解析：

```json
{"id":"...","ok":true,"result":{"text":"..."}}
```

失败时进程返回非零状态码，并输出类似下面的对象：

```json
{"id":"...","ok":false,"error":{"code":"DOM_CHANGED","message":"页面结构已变化","safe_to_retry":false}}
```

脚本应按 `error.code` 和 `error.safe_to_retry` 决定后续动作。`SEND_FAILED` 或连接
中断不代表 Prompt 一定没有提交，不能无条件重试；`RESPONSE_TIMEOUT` 也不应把半截
文本当作成功答案。

## 读取历史

```powershell
web-llm-agent get-messages --limit 20 --json
web-llm-agent get-messages --all --json
```

历史是页面当前已捕获的数据，可能受虚拟化列表、网络速度和页面可见性影响。不要把
输出写入包含凭据的日志或上传到公共服务。
