# 任务与结果闭环缺口盘点（2026-10-06）

来源：repo-scout 只读侦察，主会话落盘。口径：`status.md:778`「任务/结果闭环」、`specs/029-agent-tools-product/interfaces.md` 任务消费命令与 AU 合同。引用一律 文件:行。凡未实跑的结论标**未验证**。

## B.1 核心已有什么（**已实现**）

- **OperationStore 投影**：`packages/backend/environment-api/src/ordessa_environment_api/operations.py:18`（`operation-records/1`）、`:168-203`（`OperationRecord.result`、`StepRecord.evidence`）、`:239-273`（`OperationStorePort`：reserve/read/claim/record/publish/record_outcome/read_usages）。
- **状态机**：`packages/backend/persistence-sqlite/src/ordessa_persistence_sqlite/operation_records.py:121-124`（status ∈ reserved/running/unknown/published/refused/cancelled，与 outcome ∈ unknown/concluded 一致）、`:306`（published/refused/cancelled ⇒ concluded）、`:476-513`（publish：步骤全 concluded＋Usage 原子转 Node holder）。
- **operationRef→请求键索引（纯读接缝）**：`operation_records.py:20` `_IDENTITIES="core.operation-identities"`、`:358-360` reserve 时写入；读取范式 `packages/backend/pacthold/src/pacthold/agents/management.py:307-317`（权限＋identity 反查）。
- **managed-first-input-result/1**：`packages/backend/pacthold/src/pacthold/agents/inputs.py:31`、`_first_result :232-239`、`reconcile_first_input :374-444`（双证据→step concluded→`publish_operation`＋Usage 转 Node）。`harness-sessionless-input/1` `:30`。
- **输入预留/claim**：`inputs.py:467-559`（reserve：draft fence＋first-session fence＋invocation binding `submitInput`）、`:561-604`（claim_dispatch 发一次 InvocationContext）。
- **已有 operation 读投影**：`assembly.py:116-118`、`lifecycle.py:97-101`、`management.py:345-354`。
- **既有 operation kind 枚举**（无 "task"）：`agent-preparation`（`assembly.py:201`）、`agent-stop/agent-release/agent-recovery`（`lifecycle.py:35`）、`configuration-change`（`management.py:174`）、`managed-input`（`inputs.py:546`）。

**关键缺口（未实现）**：`ManagedInputReservations` **不在** `AgentServices`（`packages/backend/pacthold/src/pacthold/agents/public.py:25-32` 只有 profiles/nodes/configuration/providers/assembly/lifecycle；`agent_services()` 签名 :35-37 无输入端口）→ 无 wire、无 CLI、无 composition 消费（消费者仅 tests：`products/agent-tools/tests/integration/test_managed_input_reservations.py:16` 与 evidence tests）。`supports.managedInput` **硬编码 False 且全仓无 writer**（`packages/backend/pacthold/src/pacthold/agents/profiles.py:46`）。

## B.2 wire 有什么（**未实现 tasks/results**）

- `products/agent-tools/src/ordessa_agent_tools/schema.json`：`results` 段仅 `catalogEntry/manifest/list/preview`（`:37-66`）；`methods` 仅 `agents.capabilities`＋`agents.profiles.*`（`:68-172`）。**无 tasks/results 形状与方法**。
- `products/agent-tools/src/ordessa_agent_tools/schema-management.json`：`results` 有 `preparationOperation/lifecycleOperation/preparationQuery/nodesList/nodeRead/nodeRecord/nodeBinding`（`:67-146`）；`methods` 有 providers/nodes prepare·queryPreparation·list·read·configuration×4·applyProfile·acquireAccess·recover·stop·release（`:148-401`）。**无 `agents.tasks.*`、无 `taskOperation`/`taskResult`**。
- **supportedMethods 门控**：`apps/server/src/ordessa_server/agent_core_wire.py:73-78` —— 只放行 profile/configuration/provider/node_observation/（prepare·queryPreparation ∧ `nodePreparation`）/（stop·release·recover ∧ `nodeLifecycle`）。核心契约绑定表 `packages/backend/pacthold/src/pacthold/agents/schema.py:11-42`（`_BINDINGS`＋`_MANAGEMENT_BINDINGS`）**无 tasks/results 条目**。
- 顺带发现：`agents.nodes.acquireAccess` 在 schema（`schema.py:38`、`schema-management.json:356-367`）但被门控排除，落到 `agent_core_wire.py:111-112` → `CAPABILITY_UNSUPPORTED`（有方法无广告，`provider-owner-pipeline.md:36` 自记"wire 尚未广告"）。
- Provider SPI 同样无任务方法：`packages/backend/pacthold/src/pacthold/core/lifecycle.py:17-22` `RUNTIME_METHODS` 无 `submit_input`/读结果方法。

## B.3 CLI 有什么（**tasks/results 全缺**）

- `products/agent-tools/src/ordessa_agent_tools/cli.py:27-115` 现有命令面：`init`、`doctor`、`capabilities`、`providers{list,describe}`、`nodes{list,inspect,prepare,query-preparation,stop,release,recover,apply-profile,configuration{describe,inspect,apply,query}}`、`profiles{list,show,entry,preview,create,edit,clone,rename,archive,restore}`。
- **无 `tasks`、无 `results`、无 `operations` 命令组**（`interfaces.md` 目标形：`tasks run/inspect/watch/result`＋`operations reconcile`）。
- 可复用的校验/投影件：`preparation.py:54 query_result_valid`、`configuration.py:131 operation_result_valid`、`lifecycle.py:74 disposition`。
- **客户端硬约束**：`client.py:230-235` `support_keys` 是固定集合 `{profileCatalog,nodes,managedInput}`（＋v2 `{configurationManagement,nodePreparation,nodeLifecycle}`），新增任何 `supports` 键会被判 `CORE_RESPONSE_INVALID`——**新增能力位必须同批改客户端**。
- 既有验收锚点：`products/agent-tools/acceptance/install_use.py:132` 断言 `supports.managedInput is False`；`status.md:114` 记 `run hello` 解析退出 2（命令不存在）。

## B.4 缺口清单

1. **任务创建（run）＝需新写操作（复用既有机制）**
   - 机制已在核心：`ManagedInputReservations.reserve/claim_dispatch`。缺：挂进 `AgentServices`＋wire（新 `agents.tasks.run`，effectful 由 requestId 驱动）＋ composition 装配。
   - 三前置未接：`ControlledInputCapturePort`（`inputs.py:77-80`）生产 capture store、policy surface（`pacthold.agents.inputs.reserve` 已存在，`inputs.py:453`）、**provider 侧真正写原生帧的桥**——`claim_dispatch` 只发 InvocationContext，`RUNTIME_METHODS` 无 submitInput，managed 运输 writer lease 在 `packages/backend/harness-transport/src/ordessa_harness_transport/channel.py:316-360,:437` 但与 submitInput 的生产装配**未实现/未验证**。
2. **任务查询（inspect/watch）＝纯读接缝，可先行**
   - `core.operation-identities`（`operation_records.py:20,:358-360`）＋`read_operation`＋通用投影。现状三个既有 `query` 全被 kind 门挡死：`management.py:318`（限 `configuration-change`）、`assembly.py:301`（限 `agent-preparation`）、`lifecycle.py:279`（限 lifecycle kinds）→ **需一个按 operationRef 的通用只读投影**。
   - 权限可复用 `management.py:307-315`（`admit_object_access(..., f"{env}:operation:{ref}", "read")` ＋ principalScope 匹配）。
   - watch＝轮询同一读；`interfaces.md` 明确"watch 超时只是观察超时"。
3. **任务取消（cancel）＝需新契约**
   - 现有 lifecycle 只有 stop/release/recover（`schema.py:39-41`）；`acceptance.md` A12 断开≠cancel、`interfaces.md` 本地 SIGINT≠原生取消。**没有 cancel 语义**——须新操作或显式 typed 拒。
4. **三家完成事件解释器落点（提供者侧，已实现，缺回写桥）**
   - Codex：`plugins/harness/codex/src/ordessa_harness_codex/client.py:55-56`（`TURN_TERMINAL_STATUSES`）、`:220-263`（`wait_turn_completed`，非终态/缺 native 身份 ⇒ `LostReceipt`）。
   - Pi：`plugins/harness/pi/src/ordessa_harness_pi/client.py:254,283-294,316`（`disposition started/handled`；无 disposition 只证 acceptance，不得谎报完成）。
   - Claude：`plugins/harness/claude-code/src/ordessa_harness_claude_code/stream_json.py:9,214-251`（`_is_turn_result`/`_checked_result`）、`sdk.py:155-211`（`__turn_pending`，终态缺 native session evidence ⇒ `SdkOutcomeUnknown`）。
   - 三家解释器**均已在提供者包内**，符合 `design.md:30`「消费者不编写各家完成事件解释器」；**缺的是 provider 结论 → `record_operation_step`/`publish_operation` 的生产回写装配**（未实现）。
5. **结果读取权限**：复用 `operation:{ref}` read 授权范式；CLI 可存非秘密 operationRef 但不是唯一 ledger。
6. **与首输入/turn 的关系（`contracts.md` 使用通道约束）**
   - `design.md:28-34`：保留原生 payload/request id/未知事件/原生错误，**不统一为 sendMessage**；`run` 在消费者适配层实现一次受控任务提交，不意味 core 新增 sendMessage。
   - 第一次 `tasks run` ≈ 首输入（隐式建 Session）：`inputs.py:525-558` 走 sessionless Unit 权限＋first fence（`_first_fence :300-344`），结果为 `managed-first-input-result/1`；后续输入走 `session_ref`（`:535`）。投影须容纳两种 binding（`sessionlessInputBinding` vs `nativeSessionRef`）。
   - turn 完成 ≠ 首输入 published：后者需 `FirstInputObservationPort` 双证据（association＋effect evidence，`inputs.py:241-270`、端口定义 `:187-195`）。
7. **镜像/客户端副作用**：schema 由核心生成、`packaging/generate_schema.py --write` 再生成（`provider-owner-pipeline.md:10`）；`client.py:230-235` supports 键集须同批改。

## B.5 建议实现顺序

**先做（纯读接缝，无新副作用）**

1. 通用 operation 只读投影＋wire 方法（effectful:false）＋`supportedMethods` 门控行＋`schema.py` 绑定表＋`generate_schema.py --write` 镜像再生成＋ CLI `tasks inspect/result`。权限复用 `operation:{ref}` read。
2. 同批扩展 `supports` 能力位与 `client.py:230-235` 键集（否则客户端拒答）。
3. `tasks watch`＝(1) 的轮询＋timeout（exit 7 语义）。
4. `operations reconcile`：复用 `queryPreparation`/`queryChange` 的 replay-only 模式推广到通用 kind。

**后做（需新写操作/装配）**

5. `tasks run`：`ManagedInputReservations` → AgentServices/wire；先补 capture port 生产装配、policy、provider submitInput 桥（managed writer lease）。
6. 完成事件回写：三家提供者解释器 → `record_operation_step`/`publish_operation`；首输入走 `FirstInputObservationPort`。
7. `cancel`：新契约或显式 typed 拒，依赖真实原生能力与证据；不得由 stop/SIGINT 冒充。

## 关键发现摘要

1. 核心 OperationStore/状态机/`core.operation-identities` 读接缝**已实现**，是 tasks/results 的现成底座。
2. `ManagedInputReservations`（reserve/claim/首输入发布）**已在核心实现但零装配**——不在 `AgentServices`、无 wire、无 CLI。
3. `supports.managedInput` **硬编码 False 且全仓无 writer**（`profiles.py:46`）。
4. wire 侧 `schema.json`/`schema-management.json` **无任何 tasks/results 形状与方法**；`supportedMethods` 门控亦无对应行。
5. CLI 现有 5 个命令组，**无 `tasks`/`results`/`operations`**。
6. 三个既有 `query` 全被 kind 门挡死 → 通用 operation 只读投影必须新建（纯读、可先行）。
7. 三家完成事件解释器**已在提供者侧就位**，缺的只是 provider→OperationStore 回写桥。
8. `RUNTIME_METHODS` 无 `submitInput`，managed writer lease 与 submitInput 未打通——**run 的真正阻塞**。
9. `cancel` 无任何语义（A12 禁止用 stop/SIGINT 冒充）→ 需新契约。
10. 顺序：读接缝（inspect/result/watch/reconcile＋supports 键集同批）先行 → run → 完成回写 → cancel；全程须守 `design.md:28-34` 不统一为 sendMessage。
