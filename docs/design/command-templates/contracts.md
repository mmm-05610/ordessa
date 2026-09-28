# Domain contracts：模板服务与注册接缝

此处是目标语义，不声称已发布 API。T00 必须对集成 SHA 的公开类型逐符号核对；已有同义服务直接复用，不复制 Token/registry。

## 后端服务

`command-templates.service` 是业务端口，`commandTemplates.*` 是该插件借 Server 公共 method descriptor 注册的方法族；不可要求 Server 的 wire/handlers 按模板分支。principal 从认证上下文注入，server/project/profile 身份须后端核验。

| 操作 | 输入与输出/错误 |
| --- | --- |
| list/get/revisions/previewDiff | 授权元数据、定界正文、固定修订；跨 owner/超大正文拒绝 |
| create/saveRevision/approve/archive | expectedVersion、operationKey、body/schema/digest；CAS、幂等；归档不删绑定历史 |
| importPreview/importCommit | 用户明确选的原生文件/字节，安全预览后转换；动态命令/不可无损语法拒绝 |
| assignments.list/upsert/remove | 范围身份、明确 enable/disable、pinned revision、CAS/operationKey |
| resolveEffective | 鉴权 target + Profile 修订 → 可用项、来源、冲突、真实缺席原因 |
| renderPreview | target、templateId/revision、typed args、draftId/revision → rendered bytes/digest/receipt；零发送 |
| validateInsert | receipt、当前 target/draft/context revision → 可插入或 stale/refused；不得代 Chat 改草稿 |

稳定错误族至少有：UNAUTHORIZED_TARGET、CONTENT_MISSING、REVISION_UNAPPROVED、PARAMETER_INVALID、OUTPUT_LIMIT、NAME_CONFLICT、STALE_PREVIEW、CONTRIBUTOR_GONE、NATIVE_UNSUPPORTED、CAPABILITY_UNKNOWN、CAS_CONFLICT。未知≠不支持；列表错误不可静默变空。

存储、解析、渲染是纯本域模块，可在 Profile、Chat、Harness 缺席时工作。服务查询无 spawn、无模型调用、无项目磁盘递归读取。会话已输出中进行目录查询可行，但**发送**仍只由现有 ACP owner 控制。

## Profile contribution

facet `assets.command-templates` 使用 Profile v2 的 `FacetDescriptor`：值为 `templateId -> inherit|enable(revision)|disable`，另可提供本人专用内容引用。Profile 的正文只留引用；其受控 Settings 区贡献模板管理入口。facet 被卸载则 Profile 编辑项直接隐藏，原数据保留；应用时缺 facet/修订返回不能应用，绝不把未知字段下发。模板本体在 Profile 缺席时仍能通过本域 Settings 管理。

## Chat contribution

目标为使用 [Chat 输入契约](../chat-zcode-reuse/input-contracts.md) 中**尚未发布的** scoped `addInputSource`，同时向 `slash`/`plus` 贡献条目；每条含 namespaced id、group `templates`、来源、固定 revision、参数提示和 `availability`。它不能复用 `insert-command` 来把模板名字丢给 ACP 原生；选择动作是 scoped `add-content/prepare` 风格的**参数填写→服务预览→插入草稿**，如真实 API 不表达此原子流程，T00 提交最小 Chat 输入动作扩展及红绿反例，不能私改 Chat store 或绕过发送门。

查询只需目标身份、query、surface、AbortSignal，不得读取全历史/草稿全文。菜单点击不会发消息。前端旧 generation、目标/草稿 revision、provider scope 卸载时禁插；预览当前已变化，先刷新再二次确认。多模板显示同名但不覆盖原生系统命令；slash 命名空间与 Chat 平台实际解析器冻结，不能用模板插件自行截获全局 `/`。**展开后的草稿必须以普通文本提交**：若正文恰以 `/` 起头，不得在 send 时再次被本地/原生命令解析；若现有 Chat 无“字面文本提交”路径，先补最小公开契约并以反例钉住，不能靠隐藏字符改写用户可见文本。

`plugins/commands` 的 `CommandsToken` 是 `execute(id)` 回调注册；它不是正文仓、参数引擎、会话发送端口。若未来将“打开模板面板”作为 Workbench 全局命令，可只注册此导航动作，不把 templateId 当泛型 Command 执行。

## Harness contribution（可选原生投影）

点 `harness.configuration-adapters` v1，facet `assets.command-templates`，业务域内每品牌模块实现 `assess/compile/verify`。`compile` 只能产出受管 `MountContent`/`RemoveOwnedContent` 或已声明 action，不能写 HOME、spawn、调用模型。Harness runtime 独占隔离目标、generation、reload/restart-resume、reconcile；内容域不能自己复制 ACP 客户端。

原生投影**不是**通用 Chat 展开的前置依赖。投影不自动打开原生扩展命令的执行权限；同名、原生已有项、项目发现优先级无法证清时拒绝 native projected。Profile/其他业务同次配置由 Harness 合成一次计划，冲突时在副作用前拒绝，不能 last-wins。

## 生命周期与资源所有权

服务激活/卸载沿 Server 插件宿主既有原子 descriptor。正在渲染或应用的计划引用提供者时按公共 busy/generation 规则处理；卸载仅撤服务和 UI 贡献，历史正文数据不删。Chat 请求取消只取消该 UI 任务，不意味已经发出的业务 send 可撤销。展开 receipt 有 TTL/容量上限，清理由模板服务所有；插入后是 Chat 草稿资源，其生命周期归 Chat。
