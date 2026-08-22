# Provider 开发

Provider 是站点适配层，负责把统一的 Session 能力映射到一个已经认证的浏览器
页面。新增 provider 时，应先确认站点允许自动化和用户明确授权，再实现下面的
Adapter Contract。

## Python 与 Extension 的边界

Python provider 只描述 provider 的静态 **metadata、URL 和 capabilities**。
Broker 的 `SessionManager` 通过唯一 `ExtensionTransport` 调用 `open`、`chat` 和
`get_messages`。Python provider 不持有 Transport，不解析页面 DOM、不保存 selector、
不读取 Cookie/Token，也不判断输入框或回复节点。

Extension adapter 才拥有页面交互的全部细节：selector、DOM 状态、提交和生成状态、
turn identity、历史滚动以及站点特有的 serializer。这样页面 DOM 变化只需要更新
对应的 Extension provider，而不会把站点细节泄漏到 Broker 或 CLI。

## Adapter Contract

每个 Extension provider profile/adapter 必须明确以下契约：

| 能力 | 约束 |
| --- | --- |
| **metadata** | 提供唯一 provider ID、默认 URL、允许的 host 和 capabilities；不得包含认证材料。 |
| **URL** | `matchesUrl` 只接受该站点的 HTTPS 地址，`normalizeUrl` 产生稳定的 Conversation URL；不属于站点的 URL 必须返回 `INVALID_URL`。 |
| **prompt discovery** | 通过集中管理的 selector 找到可见、可编辑且处于可用状态的 Prompt 输入框；找不到时返回 `PROMPT_NOT_FOUND` 或由页面就绪层归类为 `PAGE_NOT_READY`。 |
| **send** | 以站点支持的 DOM 事件写入文本并点击发送控件；禁止使用剪贴板、CDP、私有 API 或认证材料。 |
| **submission detection** | 发送后确认用户消息节点、输入框清空、生成状态或等价证据，不能把点击动作本身当成提交成功；限定窗口内没有证据返回 `SEND_FAILED`。 |
| **generation** | 识别思考、工具调用和流式生成等活动，按照协议发出 `thinking`、`working`、`tool_call`、`streaming` progress。静态 Stop 按钮或静态工具卡片不能单独算作活动。 |
| **completion** | 生成结束后执行短暂最终确认，使用最终 Assistant 内容和 completion marker 判断完成；连续无有效页面活动时返回 `RESPONSE_TIMEOUT`，不能返回半截文本。 |
| **message extraction** | 从 DOM 提取 role、文本和结构化内容，按最早到最新排序，并返回 `truncated` 等 best-effort 状态。 |
| **turn identity** | 使用站点的稳定 turn ID 或等价的容器属性区分 user/assistant turn，避免虚拟化列表和 DOM 重渲染造成重复消息。 |
| **history scroll** | 支持虚拟化消息列表的增量捕获、向上滚动、去重和恢复原滚动位置；达到历史超时必须明确标记截断。 |
| **special serializer** | 处理站点特有的 Markdown、代码、链接、表格、换行及行内/块级 TeX；无法识别的结构应保留可读文本，不能点击 Copy 或写入系统剪贴板。 |

## Python provider 最小接口

Python 侧的不可变 `ProviderDefinition` 包含 `id`、`default_url`、`hosts`、
`capabilities` 和 `normalize_url(url)`。Provider registry 只注册这些定义；新增
Provider 不得创建第二个 `ExtensionTransport`，也不得在定义中包含 DOM selector、
CLI 输出逻辑或运行时连接状态。`chat` 在状态不确定时不得自动重发原 Prompt；标签页
恢复策略由 `SessionManager` 按显式策略控制。

## 认证和秘密

Provider 只能复用用户已经在浏览器中建立的会话。禁止通过读取 Cookie、Local Storage、
密码字段、DevTools/CDP、私有 API 或系统剪贴板来获取认证材料。测试不得把真实认证
状态、Conversation URL 或回复正文提交到仓库。

## 测试清单

- 使用 fake transport 覆盖 Python provider metadata、URL 校验，以及 SessionManager 的
  open、chat、history、close 和错误映射；
- 使用 DOM fixture 覆盖 prompt discovery、send、submission detection、generation、
  completion、turn identity、history scroll 和 special serializer；
- 覆盖长思考、工具调用、流式输出、最终确认和页面未就绪；
- 验证同一 Session 的并发操作会串行化，重复请求不会意外重发 Prompt；
- 验证日志和 registry 不包含认证材料、Prompt 或回复正文；
- 在真实浏览器中进行最小的手动 smoke test，并注明浏览器版本和页面结构假设。

Provider 测试应独立于 Broker 网络测试；Broker 测试只验证协议、锁和生命周期，避免
因站点 DOM 改变而同时破坏两层。

## 发布约束

新增 provider 时更新 capability 列表、协议文档、目录 README 和安全边界说明。若
实现位于父仓库的 private submodule，必须固定可复现的 commit，并在 CI 中检查
submodule 可用性；GitHub HTTPS 凭据由 Git 配置管理，不进入 Python 配置或浏览器扩展。
