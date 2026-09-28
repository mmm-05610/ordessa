# Q5 任务与原包追踪

本线副本，允许勾选并追加查漏任务。共同 plan 的 owner 分配优先；原表范围外步骤登记依赖/C0 集成，不由本线偷改。原包更晚变更须有明确裁定，不自行缩需求。

- [x] R0：读完整输入，冻结实际 SHA/包/红 ID/环境，盘点复用。
- [x] R1：独立工作与接口请求完成；消费必需 checkpoint 并留精确 SHA。
- [x] R2：本线全部原包任务有实现/验收/依赖归属，生产假接口为零。
- [x] R3：检查点/接线清单/许可迁移账/报告齐备，定向及相关全链门通过。
- [x] R4：Spec Kit analyze/converge 查漏，未完成项如实；发布本线 clean ready commit。

## 原包：safety-controls

来源：docs/design/safety-controls/tasks.md，2026-09-28 派发快照。以下保留原条目便于追踪；过程授权与 owner 由共同 plan 更新。

# Tasks：Spec Kit 可执行任务与依赖

执行者接本包后先核对最终基线，所有任务必须有先红后绿、实际命令/退出码/原始日志。FR 与验证案例在 [verification.md](verification.md) 逐一对应；文档状态不是完成证明。

| ID | 所属/依赖 | 任务与交付 |
| --- | --- | --- |
| T00 | 主控，起点 | 固定三核心包与插件实现的集成 SHA、pins、官方/源码/受控分层矩阵、当前红 ID 与所有数据路径；核对 pre-effect authorizer 能否被真正执行器消费，并申请**精确公共接缝**缺口，不能先做假 API |
| T01 | Permissions；T00 | 定义强类型规则/上限与裁决合成，拒绝未知 key、跨 scope 提升和 last-match 放宽；单测在旧实现上先红 |
| T02 | Permissions；T00 | 将旧 `ApprovalRecords` 的唯一权威迁入，保留记录 ID/事件/CAS/幂等语义，补 native receipt/失联查询；双权威并存测试先红 |
| T03 | Permissions；T01/T02 | Pi/Codex/Claude 权限 adapter：严格 `assess/compile/verify`，逐 pin 测已允许工具类型，受控真实 pre-effect gate；没有证据的格只支持显式拒绝 |
| T04 | Sandbox；T00 | 原生 sandbox schema/平台限制/coverage、读写网络约束与上级上限校验；明确不同于中性 SandboxV1 |
| T05 | Sandbox；T04 | Pi/Codex/Claude adapter 与隔离效果探针：Pi 扩展缺席红；Claude 非 Bash 工具不能冒称覆盖；Codex 管理限制无法被 Profile 放宽 |
| T06 | 各域；T03/T05 | 各注册 Profile/Settings，Permissions 注册 Chat 审批区；无 UI 时后端策略仍成立，跨 scope 迟到响应不得串写 |
| T07 | Harness/集成主控；T03/T05 | 单一 ACP owner 的请求/响应授权接线与同一提交闸门；原生配置 C2 字段 claim 互斥，禁止直接从 renderer 产生 grant；请求中卸载/断连/取消负例 |
| T08 | 集成主控；T06/T07 | 旧 Profile 权限存储及 `approvals.decide` 迁移、compat 消解，产品显式启用两个可选域；不更改 wire ID/既有数据身份 |
| T09 | 主控；T08 | 独立安装与依赖方向、旧红账本逐 ID、受控 L2 三品牌及 UI 键盘/错误场景；记录 L3 未测、真实模型禁止、许可证/NOTICE 审核 |

无阻塞时 A/B 并行，T07/T08 串行。局部品牌 `unknown` 不阻止其他品牌完成，但不能把本批“全部三品牌强制能力”记作全绿；可交付明确定义为已证支持格与显式不支持格均准确，不必伪造对所有工具/OS 的支持。若共同接缝缺失，T01/T02/T04/T05 的纯域实现可继续；相关生产验收仍 blocked，不能称已完成。

## 原任务本线状态（逐 ID，2026-09-28）

| ID | 本线状态 | 证据 / 未达成部分 |
| --- | --- | --- |
| T00 | DONE | `baseline-t00.md`（真实 SHA/包/红 ID/环境），`api-requests.md` G1–G6 精确接缝缺口；未做假 API |
| T01 | DONE | `plugins/permissions/api` 223 passed；旧 `resolve()` last-match 在 `test_legacy_last_match_divergence.py` 实测先红 |
| T02 | DONE | `ApprovalFacts` 保真 `server_approvals`/事件/CAS/幂等 + receipt/`reconcile`；双权威并存冲突测试为红→绿；proof 16/16 |
| T03 | PARTIAL | 三品牌 `assess/compile/verify` 与真实 point 准入 DONE（124 passed）；**受控真实 pre-effect gate 不可得**（G1/C0），逐 pin 已允许工具类型只证到编译面，未证生效 |
| T04 | DONE | `sandbox/api` 89 + `sandbox/backend` 68 passed；明确不同于 `SandboxV1`（同名禁令有测试） |
| T05 | PARTIAL | 三品牌配置 adapter 80 passed、coverage/平台/跨会话反例齐；**隔离效果探针与 L2 写回读 blocked**（`harness-api` 未发布，C3 seam 显式 unbound 且断言无泄漏） |
| T06 | PARTIAL | Chat 审批区 28 + Settings 区 34 passed、后端无 UI 仍 fail-closed 有测；**Profile facet glue blocked**（profile-api 与 foundation 不兼容而回退，G4） |
| T07 | BLOCKED | 单一 ACP owner 请求/响应授权接线与同一提交闸门归 C0；本线只提供 port/反例（G1/G2） |
| T08 | BLOCKED | 旧存储/`approvals.decide` 迁移与 compat 消解、产品启用归 C0；清单见 `integration-request.md` §A/§B |
| T09 | PARTIAL | 独立安装与依赖方向、逐 ID 继承红账本零增量、jsdom 级 UI 断言 DONE；受控 L2 三品牌与真实浏览器场景未做；L3 未测；未引入新依赖故无 NOTICE 增量 |

状态口径：DONE=本线范围内实现并按其证据等级验证；PARTIAL=可独立交付部分已绿，生产门如实 blocked；BLOCKED=依赖他线，未以任何单测冒充。

## Phase 1: Convergence

查漏追加（2026-09-28，`speckit-converge` 评估当前代码所得；原任务 ID 不动）。

- [x] T010 把本线全部拒绝码映射到平台既有 wire family（`server_plugin_api.wire_errors` 的 `FAMILIES`：APPROVAL_INVALID / OUTCOME_UNKNOWN / CAPABILITY_UNSUPPORTED / CONFLICT_VERSION …），并加门断言不新增 family、不改核心错误分支 per FR-09 + contracts §C4「错误须映射至既有 wire family」 (missing)
- [x] T011 Permissions 域经真实 `addSettingsSection` 公开接缝贡献「权限与审批」设置区：规则来源、组织上限只读摘要、用户默认意图、审批历史过滤；提供者缺席则整区不注册、提供者报错则局部错误且不冒充未安装、上限项拒绝放宽 per FR-08 + ux.md §Settings + tasks T06 (missing)
- [x] T012 把旧 Profile `permission_preset`/`permission_rules_json` 版本化导入为用户意图：保真保留原值、语义不等价项标 `needsReview`、禁止自动 allow、管理员上限不从旧 Profile 推导；含逆向读取与幂等测试 per FR-10 + data-model.md §规则合成 5 + plan.md §迁移 (missing)
- [x] T013 Chat 输入区的品牌模式选择入口只列该 pin 实测能力，不把任何品牌名当跨品牌等价标签（无证据格不可选）；若裁定本轮不做，则在本线 report.md 记为显式延后并说明依据 per US4 + ux.md §Chat (partial)

依赖说明：T010–T013 均在本线写入面内可完成，不等他线检查点；原表 T03/T05/T06 Profile glue、T07/T08/T09 的生产门仍按 §二 blocked 记录，不因本轮 converge 而改写。
## 消费 harness-api 后的状态更新（2026-09-28，追加）

合并 `codex/011-harness-api-ready`（publication `d3f026904e`，implementationSha `61966e31189a911c295faba30a07316c44041f47`，status READY，dependsOn 记录本线 permissions-api `bcd4387bec`）后，原先三行 blocked 如实更新：

| ID | 新状态 | 证据 |
| --- | --- | --- |
| T03/T07（Q5 半边） | BLOCKED → PARTIAL-DONE | `plugins/permissions/backend/src/ordessa_permissions_backend/admission.py` 实现中立 `acp.admission.gate`（`AcpAdmissionPort`）适配并在 plugin 注册；29 条 port 反例覆盖缺权限、身份未观测、伪造 option、重放、跨 session/run、无回执。产品把该 port 装成宿主 authority 仍归 C0（检查点原文：ready=False、Q5 authorizer not wired）。 |
| T05（C3 绑定） | BLOCKED → DONE（受控层） | `to_harness_c3` 产出真实 `ordessa_harness_api` 的 `SetField/ResetField/IntentSet/InvokeAction`；secret 字段名与非法路径段由平台守卫抛出；原「检查点缺席」tripwire 改为缺席即红的在场+祖先+符号断言；adapters 94 passed。apply/effect 与 native receipt 依检查点自述保持 Unknown。 |
| T04/T010 | DONE | 两域拒绝码映射到 `server_plugin_api.wire_errors` 既有 family（api 侧 93 tests、sandbox 侧 18 tests）；不新增 family、不改核心错误分支。 |
| T06 | PARTIAL | Permissions 增设「权限与审批」Settings 区（T011 DONE）与品牌模式入口拒绝路径（T013：无 per-pin 能力读端口时不造假菜单）；Profile facet glue 仍 blocked。 |

环境事实：`plugins/harness` 消费后一度 4 errors，为本树 venv 缺 `setuptools`/`wheel`（fixture 以 `--no-build-isolation` 构 wheel），补装后复跑 2 failed / 433 passed，即 C0 登记的同一对红。

## 查漏追加二（2026-09-28，主代理在 converge 之后自测发现的同类缺口）

- [x] T014 Permissions backend 注册只读 wire 方法 `permissions.policy.describe`（required 空集，optional `principal`/`scope`；closed 响应 `{ready,ceilings,intents,needsReview}`；缺 repository 时 `ready:false` 且列表为空，绝不编造默认；未知参数由宿主 `WireService.dispatch` 抛 `INVALID_REQUEST`，本线不断言自建拒绝）— 证据 `evidence/t014-red-policy-describe.txt` / `t014-green-policy-describe.txt`（backend 118→134 passed）
- [x] T015 Permissions frontend Settings 区改由真实 describe 往返驱动（闭集解码：任何多余/缺失键整轮作废，`ready:false` 渲染「无法证明生效」而非「未安装」，非可信来源上限单列「非可执行」，needsReview 只读「待复核…不放行」）；跨语言一致性测试解析 backend `plugin.py`+`describe.py` 源码，先红 32 项、真实方法落地后才绿 — 证据 `evidence/t015-red-describe-consumer.txt` / `t015-green-describe-consumer.txt`（vitest 62→93 passed，tsc exit 0）
- [x] T016 顺带修正 backend 潜在崩溃：`policies._intent_record` 对 `BrandMode` 取 `.value`（该枚举无 `.value`）导致写意图即崩，改为 `.name`，并由 T014 的真实存取路径测试覆盖（该缺陷在 T012/T014 之前无任何测试触达，登记为已修）

## C0 审阅反馈落地（2026-09-28，逐条对应 report §十）

- [x] T017 在 API 包发布中立 `PermissionsAuthorizerPort` 与 port 名/版本常量，签名对后端 `inspect.signature` 核验 + 漂移守卫（api 327 passed）
- [x] T018 `busy()` 绑定宿主停用（`stop_hooks`+`disposal`），开放/未对账审批即拒绝停用；停用后 decide 路由关闭、admission ready=False（backend 9 新用例）
- [x] T019 `LegacyApprovalDelegate`：旧 `approvals.decide` 参数形状委托给单一 authorizer，缺 native 事实先拒后写；双开由 `DuplicateMethodError`/`DualAuthorityError` 门住（backend 158 passed）
- [x] T020 两域 `adapter_versions` 收紧为各自发布事实支持的精确 (0,1,0)，并钉住「本树无生产 installation 观测者 → 真实两 facet plan 仍 ADAPTER_MISSING」的诚实拒绝（adapters 126/99，lane 885 passed）

C0 仍持有：compat 旧 writer 实际退役、产品启用 Q5 backend、生产 `describe_installation()` 观测者与 C4 per-fragment facet 选择、真实工具副作用经 admission gate（G19）。

## 真实链路补测（2026-09-28，T021/T022）

- [x] T021 用真实宿主 `AcpAdmissionGate`/`AcpAdmissionPortAdapter` 驱动本线 authority：deny/ask/无回执/重放/伪造/缺席六类反例均**在副作用到达 relay 之前**拒绝（效果记录 `[]`），确认回执后恰好一次 accepted；backend 158→175，`evidence/t021-*-pre-effect-l2.txt`。提交侧围栏因宿主私有 `BoundAdmission` 无法由插件充当 authority → 显式拒并提 G7。
- [x] T022 沙箱 C4 受控应用证据落到真实平台服务上（plan→apply→query→reconcile `Confirmed` + 8 类平台型负例 + 零 I/O 纯度 spy）：adapters 99→118，sandbox 293 passed，`evidence/t022-*-sandbox-c4-apply.txt`。
- [!] 同时披露并修正本线一次假绿：`matrix.py` 自 `242e1969b3` 起引用的 `tests/test_controlled_c4_l2.py` 在任何提交中都不存在（`git cat-file -e` 证明），该两格曾是无证据的“已 L2”。现已写出真实测试并加 ID 级存在性守卫；详情 report §12.1。检查点：`codex/011-permissions-api-ready-r6`。
