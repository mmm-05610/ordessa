# 002 T002-03/T002-04 — Q01–Q12 保证等级冻结与 request-key MAC 编码

冻结日期：2026-10-03。合同载体：`packages/backend/environment-api/src/ordessa_environment_api/`
（DTO/errors/codec，CONTRACT_VERSION=`oe-contract/1`）与 TS 镜像
`packages/desktop-platform/contracts/foundation/src/open-environment/`。向量：
`tests/contracts/vectors/open-environment.json`（17 例，Python 权威生成，TS 逐字节断言）。

## Q01–Q12 逐项：实际支持、required 保证、raw 差异、provider 职责、消费者

「实际支持」列基于 001 基线证据（known-issues、021 台账、本轮实测），不是接口存在推定。
`H` = Harness（原生适配），`A` = Agent 域，`P` = Profile/资源域，`S` = Server/传输。

| Q | 联合最低合同（冻结） | 当前实际支持（证据） | 原子性缺口处理 | 主要消费者 |
| --- | --- | --- | --- | --- |
| Q01 target/binding/owner 可信映射 | `CanonicalFactTarget`+`RecoveryBinding`（native authority/owner/session/generation 必填，PID/path 不算） | 部分：ACP connector 有 native alias 实践；`opencode` 规范 id 不可启动（known-issues identity 行） | 不可比较 → 只读 unverified，不合并实体 | Agent sessions、Harness history、Chat picker |
| Q02 字段 known/unset/unknown + 可比较 revision | `FieldState`、`ConfigSnapshot.observedEvidence`、`CurrentFactView.revision` | 部分：overlay/mask 语义在 profiles.v2（M04 产品测试钉住）；无统一三态投影 | 缺完整基底只 lastObserved，不伪 current | 全部选择控件（010 收束） |
| Q03 present/unset patch 解析 | `ConfigOperationSummary.patchKinds`；解析由 Agent 公开接口 | 现状：`profiles.v2.setSessionOverride` 是真实现路径（C02 L3 证据）；`chooseForSession`/`inspectChoice` 惰性（known-ires C02 行） | 解析缺席操作 unsupported，不经 Profile glue 兜底 | Profile 编辑器、model 选择 |
| Q04 capture+提交关联/条件 | `InputCapture`（不可变 digest）、`GuaranteeLevel` | raw 现可用（受控链）；reliable 待 005 Store+指纹 | 无原子保证保 raw，拒「可靠配置+输入」请求 | Chat send、011 全链 |
| Q05 configApply 与 inputAcceptance 分记 | `SubmissionReceipt` 与 ConfigOperationReceipt 分离；partial 逐字段 | 现状合并于 turn 回执（`sessions.createAndSend`） | 已应用 model+发送拒不谎称整体回滚 | Chat、Agent |
| Q06 稳定 request/creationAttempt 查询 | `RequestKey`（跨重启/generation/transport 不变）+ `ComparisonUnavailableError` | 部分：wire 有 `sendOutcome.query`；无跨重启持久 key | unknown→查询，不自动 create/apply/prompt | 011 恢复链 |
| Q07 原生自主变化来源/版本事件 | `SequenceTriple`（source/ingest/knowledge 三域分列） | 部分：harness 配置 journal 存在（166 项测试）；无统一 knowledge revision | gap/stale/conflict 阻可靠 capture；重复原观察不解锁 | Agent config、Harness |
| Q08 首次 creation 意图/证据 | `CreationReceipt`（对象/Usage 同事务交接） | `sessions.createAndSend` 单步；无 creationAttempt 查询 | 无 create-with-config 能力则 raw 按原生合同 | 011 首发链 |
| Q09 原生命令/未知事件通道 | envelope 不裁剪 + `UnclassifiedDeliveryFact`（有界义务） | 部分：ACP 透传实践存在；未知 delivery_role 无义务登记 | 不设 Core 命令白名单；未知 payload 不当审批 | Harness surfaces、Chat |
| Q10 control 来源/单消费 | `ControlRef`（control_id+delivery_revision）+ ResponseSlot 语义 | approvals.decide 存在；单消费 slot 未冻结 | 假 approvalId 只可显示未验证 | 审批卡、permissions |
| Q11 cursor/gap/credit | `SubscriptionRef` + envelope gap 标记（codec 层冻结） | 部分：连接器帧缓存/gap 实践 | 溢出明确 gap，不尾部假完整 | 订阅面（009） |
| Q12 owner 退出预检/合法 closure | `CutReceipt`（admission cut + blockers）+ `settlement_notes` | 无统一 drain 门（004 实现） | unknown 责任不销毁；UI 可撤 | 004/007/008 生命周期 |

## T002-04 request-key 作用域与完整输入 MAC 编码（冻结）

- **key 身份**（`RequestKey`）：`environment_namespace`（数据根持久命名空间）+
  `principal_scope`（授权 principal）+ `request_id`。重启/activation generation/
  transport/raw-reliable **不产生新 key**。
- **比较字段**（不属身份）：target/binding/guarantee/input digest。同 key 异比较
  → `digest_conflict` 拒绝，不当新请求。
- **MAC 编码**：`HMAC-SHA256(canonical_json({key 身份三字段, binding_digest,
  guarantee, InputCapture.content_digest}), key=ProtectedFingerprintPort 管理的
  opaque key, 以 key_id 命名)`。附件经 attachment_digests 进入 content_digest
  计算（不可变内容快照），**路径/stat/句柄不参与**。算法/key_id/scope 记入
  `FingerprintDescriptor`。
- **轮换与墓碑**：轮换产生新 key_id；旧 key 请求比较 → `ComparisonUnavailableError`，
  spent 墓碑不删、同 key 永不再派发；无 TTL 自动清理（安全确认：保留策略=无限期，
  清理须显式授权操作并保留审计行）。
- **key 失效不自动降级**：reliable 缺指纹/Store/原生证据 → `GuaranteeUnavailableError`
  发前拒绝；raw 路径不受影响（测试 `test_reliable_guarantee_refuses_without_fingerprint_and_never_downgrades`）。

## T002-01 — M04–M06 覆盖条款 → 受影响 case 映射（024 V3 候选规则的落地版）

024 V3 的 D4/D5/D6 候选规则经 M04/M05/M06（2026-10-03 用户确认）转为冻结条款；
025 V4 §14 的 B3-01/F-01/F-02/A-03/A-04 已直接编入 targets/codec 测试。不覆盖
024/025 历史文档，仅映射：

| 用户决策 | 覆盖的 024 候选 | 冻结位置 | 受影响验收 |
| --- | --- | --- | --- |
| M04（D4 收尾） | V3-6 收尾责任链 | `CutReceipt.settlement_notes`/closure 语义（004 实现） | A09–A12、A70、A73 |
| M05（D5 范围证据） | V3-8 功能/移除安全范围 | `RecoveryBinding`/ScopeObligation 语义；owned 退出要范围证据、borrowed 仅 release | A27、A57、A58 |
| M06（D6 指纹） | V3-2 未知输入指纹 | `FingerprintDescriptor`/`InputCapture`/`GuaranteeUnavailableError` + 上节 MAC 编码 | A13–A17、A38、A50–A54 |
| M07/M08/M10–M13 | — | 不改发行/数据身份；非中断输出；插件自有资源+单 Agent owner；无永久 legacy-compat | A89–A95（C95-1–7） |
