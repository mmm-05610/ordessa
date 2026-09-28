# Z3 api-requests（按检查点协议维护）

格式：调用者 → 目标操作 / 精确符号 / 最小 DTO 语义 / 失败反例 / 请求 owner / 状态。
状态取值：`OPEN`（未发布，独立工作先行）| `CONSUMED@<sha>`（已按固定 SHA 消费）| `CLOSED`。
生产者发布检查点后本文件逐条回填消费 SHA；本线不以 OPEN 缺口勾任何依赖型任务为完成。

## REQ-Z3-1 → C0 harness-api：C2 配置 adapter 注册点

- 调用者：`plugins/assets/model-provider` adapters（T02）。
- 目标操作：注册 facet=`assets.model-provider` 的 Pi/Codex/Claude 三个 configuration adapter 到
  `harness.configuration-adapters` v1（多贡献者点）。
- 需要符号（按 `docs/design/harness-v2/contracts.md` C2/C3 目标稿）：注册条目字段
  `adapter_id, facet_id, facet_schema_version, harness_id, supported version range, entries,
  payload schema, claims`；方法 `assess(context, request) -> supported|unsupported|unknown`、
  `compile(context, before, desired) -> IntentSet|Refusal`、`verify(context, observed) -> Match|Mismatch|Unknown`；
  typed intent 外壳（`SetField/ResetField/MountContent/RemoveOwnedContent/BindSecret/InvokeAction`）。
- 失败反例：同 `(facet_id, harness_id, entry, version-range)` 重叠注册必拒；未注册 facet 的 intent 必拒；
  adapter 读 HOME/网络/spawn 必红（静态边界测试）。
- owner：C0。状态：**OPEN**（2026-09-28 `refs/heads/codex/011-harness-api-ready` 不存在）。

## REQ-Z3-2 → C0 harness-api：C4 应用服务 + C5 submit permit

- 调用者：T05 Chat glue 下一轮提交闸门消费端。
- 目标操作：`harness.configuration` 后端端口
  `inspect/plan/apply(plan_id, operation_key, submission_permit)/query/reconcile`；
  一次性 submission permit（绑定 principal、session/channel、runtime_generation、submission_id、
  输入摘要、配置摘要、expiry；重放/换目标拒绝）。
- 失败反例：无 permit 的裸 apply 必拒；同 operation_key 不同 payload 必拒（conflict）；
  同目标不同 key 必须串行；permit 过期/重放必拒。
- owner：C0（permit 消费闸门在唯一会话发送 owner，归 C0/Z2 生产接缝）。状态：**OPEN**。
- 本线先行部分：`NextTurnSelector` 按冻结端口协议（旧包 `domain-ports.md` HarnessConfigPort +
  SESSION_CONFIG 三态错误）以 E1 假闸门驱动全部状态机；生产接线替换后重跑同套反例。

## REQ-Z3-3 → Z1 profile-api：facet 注册与 overlay 语义

- 调用者：`plugins/assets/model-provider/profile-contribution`（T04）。
- 目标操作：注册 facet `assets.model-provider`（单原子 item `choice`，值
  `(providerConfigId, modelId)`）；经 `ProfileContributions.forScope(scope).addEditor(...)` 注册
  模型选择编辑器；overlay precedence 由 Profile 侧管理（`set/clearSessionOverride` 语义按
  `docs/design/profile-v2/contracts.md`）。
- 需要符号：facet descriptor（facetId/apiMajor/schemaVersion）、editor 注册、会话覆盖读/写/清、
  Profile 引用查询（供归档保护）。
- 失败反例：重复 facetId 拒绝；引用端口缺席时归档必须 `REFERENCE_STATE_UNKNOWN`（fail-closed，
  不得当空）；Profile 缺席时目录/设置仍可用。
- owner：Z1。状态：**OPEN**（`refs/heads/codex/011-profile-api-ready` 不存在）。

## REQ-Z3-4 → Z2 chat-api：composer 模型选择器贡献点

- 调用者：`plugins/assets/model-provider/chat-contribution`（T05）。
- 状态：**CONSUMED@54ad26c15d8480823374d85590919ba6bcca60d2**（chat-api READY，
  implementationSha `a3ec20c046`，ancestor 核实；固定 SHA 已 merge 进本线分支，merge 提交
  `25f726dc3e`）。消费 proof：`chat-contribution/tests/chat-api-registration.test.tsx`
  （真实 `createChatContributions` 注册表 5 例：槽位可观察、投影、scope 撤销、重复 id 拒绝）。
- **槽位映射记录（非静默替换）**：设计稿写 `composer.footer`，冻结 chat-api 六槽位无 footer；
  本线经其发布的 composer 挂点 `composer.toolbar` 注册（`chatContribution()` +
  本域 key `ordessa.chat.model-selector` major 1）。若 Z2 后续冻结 footer 槽，切换机械
  （一处槽位串+order）。此映射已同步 Z2 可读（本文件在 `git show codex/011-z3-model-provider:...` 可读）。
- 后续依赖（不阻断本线，属生产装配）：`ChatSessionGateway`/传输服务实现归 C0（Z2 api-requests
  R-Z2-1/2/3）；submit permit（REQ-Z3-2）仍 OPEN。

## REQ-Z3-5 → C0 foundation：桌面 PluginContext server wire 传输口

- 调用者：desktop 设置分区/选择器的 `providerModels.*` 调用。
- 目标操作：扩展内 `ModelProviderService` 需要 Server wire invoke 通道（旧 DELIVERY 未完成项 #6）。
- 失败反例：transport 未绑定必须类型化拒绝，不得静默空数据。
- owner：C0。状态：**OPEN**。本线先行部分：组合层绑定 + 未绑定即拒绝的 E1 测试沿用旧实现。

## REQ-Z3-6 → C0 foundation：可导入核心包（pacthold/server-plugin-api/apps/server）

- 调用者：本线全部 Python 测试。
- 状态：**CONSUMED@8844c475bc02a185ab194c69eed873122aa48349**（foundation READY，
  implementationSha `8229e20824aa`，ancestor 核实；固定 SHA 已 merge，merge 后本线全量基线
  复跑：Python 137 passed / desktop 10 / chat 21，六方法形状与现行 compat `_PARAM_SHAPES`
  AST 比对全一致。适配明细见 server/MIGRATION.md「foundation 消费适配」。

## REQ-Z3-7 → C0 foundation：新失败码注册进 wire error-family 映射

- 调用者：`modelProvider.*` 七方法的错误面（server/choices.py）。
- 目标操作：在 `apps/server/src/ordessa_server/wire/errors.py` `_BY_CODE` 注册（owner 文件，本线不改）：
  `PROVIDER_NOT_FOUND→NOT_FOUND`、`MODEL_NOT_FOUND→NOT_FOUND`、`PROVIDER_ARCHIVED→CONFLICT_REQUEST`、
  `CONFIG_REVISION_CONFLICT→CONFLICT_VERSION`、`SELECTION_UNSUPPORTED→CAPABILITY_UNSUPPORTED`、
  `OPERATION_UNKNOWN→OUTCOME_UNKNOWN`、`ADAPTER_MISSING→CAPABILITY_UNSUPPORTED`、
  `VERSION_UNVERIFIED→CAPABILITY_UNSUPPORTED`、`TARGET_STALE→CONFLICT_REQUEST`、
  `RESUME_UNAVAILABLE→CAPABILITY_UNSUPPORTED`、`VERIFICATION_MISMATCH→OUTCOME_UNKNOWN`、
  `CREDENTIAL_UNRESOLVED→UNAUTHENTICATED`、`PROTOCOL_UNSUPPORTED→CAPABILITY_UNSUPPORTED`。
- 过渡事实：注册前这些码经 `details.internalCode` 精确携带、family 暂落 UNAVAILABLE（host 既有约定），
  语义已 typed、可机器判别；注册后 family 自动正确，无需改本线代码。
- 失败反例：`modelProvider.inspectChoice` 对不存在 config 必须带 `internalCode=PROVIDER_NOT_FOUND`。
- owner：C0。状态：**OPEN**。
