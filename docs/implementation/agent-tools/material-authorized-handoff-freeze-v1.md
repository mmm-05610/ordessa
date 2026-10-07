# C 路交接冻结：受权材料读取/消费证据（FROZEN 2026-10-07）

总协调者冻结，C 路正式编码唯一依据。基线 `c47696b74b11863a9ee2fd1542033e72ce9b513b`。
015 纯 DTO（`MaterialProviderPin/UseTarget/Receipt/Release` 三件套）与 019 比对规则
已实现已验证，不重冻；本文件只冻结“受权读取交接四项”
（consumer pin、read 动作、读结果/消费证据 DTO、释放门），
全部在 `material-handoff-proposal.md:15` 明确缺席。
盘点输入：C 路只读盘点结论（基线 c47696b，EXISTS/MISSING 逐项）。

## 1. consumer pin DTO（`MaterialConsumerPin`，新 frozen DTO，放 `materials.py`）

- 形状复用 `MaterialProviderPin` 三元模式（`materials.py:227-252`）：
  `(consumer_id, consumer_version, owner_activation: ActivationRef)`，
  闭合 camelCase `to_dict/from_dict`、frozen 深快照、逐字段复制。
  `consumer_id` 规则沿 provider id 小写式；`consumer_version` 沿固定版本形状
  （拒 latest/*，沿 020 `_schema_version` 门）。
- 锁定对象：**消费方 host 的 `owner_activation`**（非材料提供方）。
  跨身份一致性门：consumer pin 环境 == 材料 resource 环境 == target 环境 ==
  原取得证据环境，否则 typed 拒绝（沿 `materials.py:437-442` 交叉校验模式）。
- **信任来源**（020 L23 警告照抄适用）：consumer pin 不得由请求方自报；
  必须复制自**准入侧可信 host 证据**（`AdmittedResourceProviderMetadata.owner_activation`
  语义，或 B 冻结 §3 的 `AdmittedConfigurationProviderMetadata.owner_activation`）。
  比对机制复用 `_pin_equal` 式逐字段相等（`configuration_references.py:132-138`），
  但 expected 值语义为“准入侧复制”，不是 caller-supplied。
- 原取得证据字段集（交接给消费方的取得证据）：复用既有 `MaterialReceipt` 中的
  `immutableMaterialRef + contentDigest + evidenceRef`（指针式，不带正文），
  另加 `provenanceRef`。交接时核心只核对这四项与原 receipt 一致，不中转正文。
- 冷恢复缺口登记：consumer pin 携带 `owner_activation` 后面对
  “Host 仅内存、无 ActivationRef 公开 rehydrate”缺口
  （`material-operation-contract-v1.md:47` 已登记）；冻结时不得宣称冷恢复核验能力，
  同 generation 才可用，不同 generation 必须拒。

## 2. read 原 context action（新具名动作 `"read"`）

- 新动作 `"read"`，非 cleanup：`issuer.issue(request, digest, step_id, "read",
  binding.targetRef, delegation_ref=None, cleanup=False)` +
  provider 侧 `verify_and_consume(context, "read", provider_ref, target_ref, input_digest)`。
  authority 须能授予 `("read",)`。`invocation.py` 绑定形状校验允许非 cleanup 自定义动作
  （只约束 stop/release/query 的 cleanup 关系），实现面无结构阻碍。
- **不复用 `"query"`**：query 已被 lost-receipt 语义占用
  （query_acquire 合同 + `_authorize_claim_read`/`verify_claimed_query` 链），
  复用会把“受权读取”与“获取回执查询”混同，破坏“读≠消费”证据链。
- 票据形状复用既有五元 `verify_and_consume`（authorized-capability L25 已固定）、
  `InvocationContext` 不透明票据、`_gate` principal 门禁。
- read 的 target 为 `MaterialUseTarget` + `MaterialConsumerPin` 双绑定：
  票据 targetRef 沿既有 target，consumer 身份由 §1 pin 在 DTO 层携带，
  authority 核验两者环境一致。

## 3. 读结果 DTO 与消费证据 DTO

- 读结果（新小型只读类型 `MaterialReadResult`，放 `materials.py`）：
  `(outcome, correlation, immutableMaterialRef, contentDigest, evidenceRef, errorCode)`。
  outcome 三态沿 `MaterialOutcome`；success 必须同 correlation 且四项与原 receipt 一致；
  **无 lease、无正文**（不是 acquire 的 `MaterialReceipt`，其绑定 lease/acquisition
  correlation 语义不符）。校验模式复用 `_check_result` 式逐字段钉回固定事实。
- 消费证据 DTO（新类型 `MaterialConsumptionEvidence`，放 `materials.py`）：
  绑定 `immutable_material_ref + consumer_pin + target(Node/目录/epoch) +
  消费侧 correlation + evidence_ref`。
  “唯一配置 owner”资格核实方式：owner 票据验证（provider 侧 `verified_consumption`
  式核验），非自报。形状冻结后 copyComplete 门（§4）方可引用。
- “读≠消费”证据链：读取成功（§3 读结果）≠ 已消费；消费成立当且仅当
  `MaterialConsumptionEvidence` 经 owner 票据核实。释放 copyComplete 仅认后者。

## 4. 释放门（门条件新冻结，机制复用）

- 机制复用释放三件套全部校验（新 correlation 拒复用获取三元组、
  `input_facts` 只含 leaseRef、digest 绑定、success 必须同 correlation 的
  ReleaseReceipt；`action="release"` + `cleanup=True` 既有合法绑定族）。
- 门条件（新冻结）：
  1. `copyComplete`：仅在 §3 `MaterialConsumptionEvidence` 存在且经 owner 票据核实后受理；
     否则保 hold，不释放。
  2. `runtimeRequired`：已证实停止/替换证据（沿 Node 生命周期结论引用）方可释放。
  3. `dynamic`：candidate 确认后同事务切换（A 路分阶段语义对接，另行绑定）。
- 门验证者职责划分（沿 handoff 控制边界 L7）：核心掌握释放时机/授权，
  消费证据真值归 Runtime owner（“消费及三寿命释放仍需原 Runtime owner 明确证据”）；
  核心只核形状与关联，不签发消费真值。
- 缺 owner 消费证据保 hold 并列剩余（沿夜派 C:45 “否则保 hold 并列剩余”）。

## 5. 写权与测试归属（本轮特批）

- C 独占：`pacthold/agents/materials.py`（仅 §1/§3 新 DTO）、
  `pacthold/agents/material_consumption.py`（新建，交接协调：read acilquire 式
  获取 + §2 票据 + §3 结果/证据 + §4 门；沿 `material_operations.py` 既有
  `_gate/_check_result` 模式，不另建执行账）、
  `pacthold/agents/public.py`（仅导出新 DTO 名，由总协调者复核）、
  `pacthold/core/resource_admission.py`（仅可选材料能力合同的 §1 pin 信任来源注释，
  不改行为）、新测试
  `products/agent-tools/tests/integration/test_authorized_material_consumption.py`。
  不得写 Environment/Registry/issuer/public 装配/Assembly（沿夜派 C:47）。
- 受控 provider 明确内容读取计数；核心持久记录/日志不得出现测试正文 canary
  （沿夜派 C:48）。
- 需要新 Registry 查询由 B 按冻结 API 提供；需要 issuer 适配由总协调者安排有界串行切片，
  不自行造新 authorizer（沿夜派 C:47）。

## 6. 验收门

1. 错 consumer/purpose/version/目录/epoch 拒；错 issuer 在 claim 前拒；
   原材料回执关系核实（四项与原 receipt 一致）。
2. unknown 不重新 resolve、不因无 lease 当无资源；读成功不等于已消费，
   没 owner 消费证据不释放 copyComplete（保 hold）。
3. 自报 consumer pin（非准入侧复制）typed 拒绝；跨环境 pin 拒绝；
   不同 generation 拒绝。
4. `"read"` 与 `"query"` 语义隔离反例：read 票据不能当 query 回执反查，
   query 票据不能当 read 授权。
5. 受控 provider 内容读取计数断言；日志无 canary 正文扫描断言。
6. 冷恢复缺口明确 NOT_RUN（不私换 Store/issuer，不宣称能力）。
