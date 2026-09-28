# Tasks — Q1 Skills v2 追踪（本线副本，已按实际执行更新）

状态记法：`[x]` 已完成并留有本树实测证据；`[~]` 部分完成（写清已完成半边与缺失半边）；`[ ]` 未做或被他线接缝阻塞。
每项证据：SHA + 文件 + 命令 + 真实退出码，明细在 [report.md](report.md)。

- [x] R0：读完整输入（README/共同 spec/plan/checkpoints + 原包 10 份文档 + 003 旧证据），冻结实际 SHA/包/红 ID/环境，盘点复用 → `research/legacy-inventory.md`、`research/brand-matrix.md`、`research/seam-gaps.md`、`implementation-baseline.md`。
- [x] R1：独立工作与接口请求完成；**已按协议消费四个检查点并留精确 SHA**（2026-09-28 晚于首轮请求发布之后）：
  foundation publication `8844c475bc`（impl `8229e20824`，merge `84e5c668f0`）、
  profile-api publication `4943628f47`（impl `f5435be938`，merge `9048f7b79f`）、
  chat-api-r3 publication `3d8c3fa410`（impl `a3ec20c046`，merge `71f926683e`）、
  harness-api publication `d3f026904e`（impl `61966e3118`，`dependsOn` foundation + permissions-api `bcd4387bec`，merge `aab8c6c4a2`）；
  三条均先核 `status=READY`、`implementationSha` 为 publication 祖先、`planAnchorRef` 与依赖后正常 merge（无 rebase/强推）。
  消费后重装本树 editable 包并重测基线（见 `implementation-baseline.md` §3）。
  消费后 harness-api 的装载接线已完成（`4c7d749a69`）；permissions-api **r1 `bcd4387bec`**（随 harness-api `dependsOn` 入树）已消费为真实强制策略上界端口（`mandatory_policy.py`）；r2/r3/r4 经 `git merge-base --is-ancestor` 实测均非本树祖先，早先记作 r3 是账目错误并已更正；r4 `ad8902d5c8` 的 merge 会删除 Z1 的 `plugins/profile/**`（55 个上游文件），本线已回退并请求 C0/Q5 处置（`integration-request.md` §7）。剩余阻塞：无原生装载运行时生产者、Z1 已 PARTIAL 关闭导致的 profile-api 导入缺口（请求转 C0）、产品装配 §G1。
  消费中撞到的真实上游缺口（已回提请求，见 `api-requests.md` §5）：
  `plugins/profile@f5435be938` 的 `ordessa_profile/plugin.py:17` 仍 `from pacthold.resource_contracts import AgentBoxProfileV1`，
  而 foundation 已搬空该模块树（符号现居 `pacthold_runtime_compat.resource_contracts.agent_box_profile_v1`），
  故 profile-api 包在本树整体 `ImportError`（其自身套件同红），本线 6 条 facet 集成钉住测试因此保持红（未 skip）。
- [x] R2：本线全部原包任务有实现/验收/依赖归属（下表），生产假接口为零（品牌能力未证格保持 `unknown`，Profile/Chat/权限层为注入端口）。
- [~] R3：检查点/接线清单/许可迁移账/报告齐备（`implementation-baseline.md`、`integration-request.md`、`api-requests.md`、`report.md`、`research/*`）；定向门按真实退出码记账（Q1 桌面 `npx vitest run` 9 files / 103 passed 绿；Q1 域套件 `329 passed, 6 errors`，6 条红全部因上游 profile-api 导入缺口且未 skip；`apps/server` 复现 foundation 记录 `42F/1092P/10S/25E`、pacthold `212 passed`、harness `2 failed/347 passed/3 skipped/28 subtests`）；**依赖 harness-api 的生产装载全链门未跑**（该检查点仍未发布），根 `npm test` 在离线树内 18/29 绿（红项含 `plugins/chat/frontend` 缺依赖与 electron 套件），非本线引入。因此 R3 只算部分。
- [~] R4：Spec Kit 侧已做 analyze（独立审阅）+ 查漏回补（G08 迁移、G15 Profile 区、4 项弱化守卫）；converge 待真实检查点；本线尚未发布 `codex/011-q1-ready`（范围未完，见 report §1）。

## 原包：skills-v2

来源：docs/design/skills-v2/tasks.md，2026-09-28 派发快照。以下保留原条目便于追踪；过程授权与 owner 由共同 plan 更新。

## Phase 0：事实和基线

- [x] T00 固定平台/Profile/Harness/Chat 集成 SHA、对外 API、各品牌 native+adapter pin 和项目身份接缝 → `implementation-baseline.md` §1–§2（本树起点 `96fef2db47`、旧实现 `752f148b1b`、检查点不存在的事实）、`research/brand-matrix.md` §1 pin 逐条 `file:line`。提交 `df915f222b`。
- [x] T01 冻结旧数据表/发布 ID/目录摘要/Profile 固定版/旧 wire 行与套件失败 ID 原因，清点非 Skill kind 所有者 → `research/legacy-inventory.md` §A.5/§B.1/§B.2/§B.3 + `implementation-baseline.md` §3–§4（本树真实退出码：pacthold 0/238P、harness 1/2F+308P+3S、apps/server 2/78 收集错误含逐条 ABSENT 产物原因、非 Skill kind = compat 持有、`command` 为休眠枚举）。
- [~] T02 品牌受控矩阵 → `research/probe-results.md` 已把 14 个运行时格 + 3 个静态格从「无证据」转为实测：Claude 在**精确 pin**（0.81.2/SDK 0.3.280）验证项目 `.claude/skills` 自动发现与 `/name` 展开到 wire、`CLAUDE_CONFIG_DIR/skills` 默认为关；Codex 在 0.155.0-alpha（**版本错位**）验证发现根、缺 description 静默丢弃、`forceReload`、`skills/config/write` 往返、`extraRoots/set` 触发 `skills/changed`；Pi 在 0.86.1 验证四个发现根与 `/skill:name`，并**实测本仓 Pi 运行链 argv `--skill-dir/--agent-dir` 被拒**。**缺失半边**：Pin 版本（Codex 0.147.0 / Pi 0.84.2）原生二进制不在本机，任何品牌的 `loaded` 独立观测在生产通路仍为 unknown；未跑真实模型（未授权）。

## Phase 1：内容和分配

- [x] T03 迁格式/树扫描、修订仓、受限预览，保留 digest/目录布局（G01/G02）→ `api/`、`formats/agent_skills/`、`library/store.py`，`test_g01_legacy_fidelity.py`、`test_tree_bounds.py`、`test_no_execution.py`、`test_library_g02_refusals.py`；本域重复实现已在新包内消除，与 server-compat 的唯一 owner 替换归 C0（`integration-request.md` §2）。提交 `df915f222b`。
- [x] T04 迁分块导入/版本审批/差异与来源，安装更新不动绑定（G03/G04）→ `library/{import_transfer,revisions,diff,catalog,records}.py` + `test_import_session/test_library_g03_import_states/test_library_revisions/test_library_diff_preview/test_records_pinning/test_catalog_snapshot`。
- [x] T05 新增用户全局/项目通用与品牌特定分配表、CAS/幂等、确定性解释器（G05/G06）→ `assignments/{model,store,resolver,authorization,snapshot,ports}.py` + `test_assignments_*`（40 例）。表 DDL 暂在本包 `ensure_schema()`，须由 C0 搬入共享迁移链（`integration-request.md` §3）。
- [x] T06 Workspace 项目身份鉴权、内容归属与「另项目/Profile 专用不能引用」反例（G07）→ `assignments/authorization.py` + `test_assignments_authorization_g07.py`；principal/serverScope 的官方语义仍待 C0 裁定（`api-requests.md` §G5），本线以注入 `WorkspaceLookup` + 本地数据根常量作用域实现并拒绝伪造 projectId。
- [~] T07 迁 Profile 旧固定版本绑定为三态 facet + 编辑器 DTO，接会话 item 覆盖，做用户数据 dry-run/回退证据（G08/G09）→ 提交 `6923c0e0e8`：`migration/profile_bindings.py`（plan/apply/verify/rollback + 计划摘要 + 版本守卫 + 非 skill 行字节不变 + 真实用户数据默认拒跑）与 `desktop` Profile 三态/编辑器 DTO（`contracts/src/profile.ts`、`desktop/src/profile{Gateway,Model,Section}.ts(x)`）。消费 profile-api 后（`45221aa246`）新增 `profile_contribution/{port,provider}.py`：facet `assets.skills` 经真实 `ProfilePluginServices.register_v2_facet` 注册，三态映射到其 value state，`assignments` 的 Profile 层由真实端口满足。**缺失半边**：`ordessa_profile` 在本树 ImportError（上游 `AgentBoxProfileV1` 位置，见 `api-requests.md` §R-Q1-1），故 6 条集成钉保持红（未 skip）；真实用户数据搬迁仍未执行（需备份/回滚演示与用户确认）。

## Phase 2：装载与 UI

- [~] T08 品牌 adapters 的 assess/compile/verify、名字冲突、原生发现、目标声明、版本 fail closed（G10–G13）→ 消费 harness-api `d3f026904e` 后（提交 `4c7d749a69`）三品牌已是真实 `ConfigurationAdapter` 实现：`assess→Assessment`、`compile→IntentSet`（`MountContent/RemoveOwnedContent（本域只声明内容目录类意图，不产 SetField）` + `ContentRef{assetId@revision, sha256, size}`）、`verify→Verification/VerificationUnknown`；本线私有的 `IntentSet/MountContent/ReloadSession` 词汇与 bool 形 `HarnessCapability` 端口**已删除**，只留一份词汇。注册经 `server_plugin_api.Contribution(point_id="harness.configuration-adapters")` 并由 harness 真实 registry（`server_plugin_api.stage_contributions + ordessa_harness/contributions.py::HarnessContributionRegistry`）验证：重复 adapter id、重叠 facet/入口/版本区间均拒绝且不发布。**仍缺**：原生装载/发现/reload 的运行时观测在本树无任何真实生产者（harness-api 只发 DTO），G10–G13 的运行时半边与 T14 的 L3 未闭环；`plugins/harness/tests` 的受控 L3 fixture 不可导入，已按请求提出而非越界引用。
- [x] T09 Settings 内容库与默认/项目分配视图，复用现有桌面列表/预览 + 平台控件，键盘/错误/权限（G14）→ `desktop/src/{entry,view,model,gateway,sha256,effect-text}.ts(x)` + `desktop/tests/{model,gateway,evidence,entry,settings}.test.*`（82 例，含 CAS 保草稿、焦点、窄屏、归属徽标、`已投放，未确认装载` 文案规则）。产品装配（manifest 登记）归 C0（§G1）。
- [~] T10 Profile 编辑器三态、固定版更新、专用导入、双源说明，旧贡献卸载只摘 UI（G15）→ `6923c0e0e8` 交付组件与 18+6 例测试；真实挂载插槽待 Z1（§G6），facet 存储待 §G3。
- [~] T11 旧 projection/ledger 分解、stored/selected/projected/loaded/used 分证据（G16）→ `api/evidence.py` 六级互不混淆（旧 `USED = UNKNOWN` 别名与「摘要一致即 loaded」路径未迁入）；消费 harness-api 后 `verify` 返回真实 `Verification/VerificationUnknown`，`plugin.py` 删除 bool 形 `HarnessCapability/HarnessDeliveryPort` 第二词汇（提交 `4c7d749a69`）。**仍缺**：投影账的宿主侧落库/查询属 Harness application 运行时（本树无生产者），`loaded` 独立观测仍 unknown。
- [~] T12 Chat `/`、`+` 贡献与可浏览/可显式调用区分（G17）→ 消费 chat-api-r3 后交付真实贡献：`desktop/src/chatContribution.ts` 用 `createChatContributions()`/`ChatInputSource` 公共注册点贡献 Skills 行（`contracts/src/chat.ts` 的 `SkillChoice`），18 条测试覆盖 G17 三反例（旧 generation 不刷新新会话、系统命令不被覆盖、自动触发型不给假「调用」按钮），并用 /tmp 变异验证守卫。**缺失半边**：显式调用路由仍不存在（ACP 侧无生产者），`skills.invokeDescriptor` 三品牌均 `unknown`；确认生效快照的 `runtimeGeneration` 端口需 Z2 补（`api-requests.md` §R-Q1-2）；产品注入 `ChatContributionsToken` 与构建期 import-map 条目归 C0。未私有 import Chat 内部，已守边界。

## Phase 3：产品联调、删除和交付

- [~] T13 下次用户提交冻结集合，Harness 先应用再发送；A/B 不串、失败不清 Profile 覆盖、终态 execution 不复活（G18）→ 提交 `4c7d749a69`：`harness_adapters/apply_chain.py` 在发布的 `Plan/PlanResult/ApplicationResult/ReconfigurationDecision/ResumeRequest` 类型上实现「冻结 snapshot → plan → 许可 → apply」：修订漂移在任何写入前拒绝、`Unknown` 永不报成功、resume 不回退成空会话、拒绝后 Profile 覆盖保留；20 条 `test_apply_chain_t13.py`（含「仅发布的 `RuntimeConfirmed` 计 applied」与 `HARNESS_APPLY_PLAN_REQUIRED` 类型化拒绝，逐条 /tmp 变异验证）。**仍缺**：把意图集真正交给运行实例执行的宿主侧装配、§G1 产品默认插件集、以及可导入的受控 L3 对端 fixture。
- [~] T14 三品牌受控原生加载启用/更新/移除与同名/原生目录冲突，全真实 Ordessa 通路（G19，要求 L3）→ 已推进到 **L2**（提交 `497f636136`）：`harness_adapters/producer.py` 用真实事实构造 `agent-box.skill@1` 交付集，经发布版 `assemble_runtime_composition` + `RuntimeCompositionCoordinator.preflight/start/projection_receipt` 与 `FakeHost/FakeSandbox` 跑通闭环：只读落声明 guest 槽、内容摘要一致、回执 `PROJECTED`、`attest(LOADED, projection_digest)` 仍 `unknown`（G16）；16/17 守卫经 /tmp 变异证明会红，唯一被上游校验遮蔽的 manifest 存在性守卫如实登记。**未完成（阻塞）**：G19 的 L3 需真实实例接收交付集，而 harness-api 不导出任何 skill 类型、消费者全在 harness 内部，已按符号级提给 C0（`api-requests.md` §R-Q1-4）。
- [ ] T15 更新产品装配/工作区清单/锁，移除旧 Assets-Skill 服务与旧 Profile glue 重复入口，保留其他 kind 数据与兼容 wire 语义（G20）→ 归 C0：本线只提交退役账（`integration-request.md` §1–§2）并证明 `skills.*` 与冻结 `assets.*` 方法集不相交（`test_plugin_registration.py`）。非 Skill kind 行不被本包读写（`test_library_kind_isolation.py`）。
- [x] T16 干净检出/隔离 wheel+前端构建、受影响套件逐 ID/原因 diff、UI smoke、最小数据恢复演示（G21/G22）→ 已完成**包隔离半边**（G21）：本地 wheel 仓 + 全新 venv（`--no-index`）+ `pip check` 绿 + 从 site-packages 导入运行，隔离结果 `329 passed + 同一批 6 条上游红`，逐 ID 与树内一致，无 skip；日志与 sha256 在 `/tmp/q1-evidence/`（`COMMANDS.md`、`SHA256SUMS.txt`）。为隔离所需的唯一改动：测试 helper 的 `sys.path` 兜底改为仅在模块不可导入时才加（已提交）。**已完成**：受影响套件逐 ID/原因 diff 见 `research/suite-id-diff.md`——apps/server 67 条红与 foundation 钉住的 JUnit（重算 sha256 命中 `92ef3914…` 账本）ID/类型/原因类**逐条一致**，new `[]`、gone `[]`，唯一首行文本差是 `test_cancel_recall_flake_087` 的路径缩写（C0 报告已预登记）；harness 同 2 条 Pi SDK lock 红且原因字节一致；Q1 自身 6 条红 ID 与原因不变，测试内 0 skip/0 xfail。**未做**：electron/UI smoke 与根 `npm test` 全绿（离线缺 Z2 chat 依赖）、真实用户数据恢复演示（只有合成数据 plan/apply/rollback 证据）。
  → 追加完成（`1580159638`+`6a6a2ec1e1`）：最小数据恢复演示。`migration/restore.py` 对合成根做「快照(sha256 清单+每修订树摘要) → 迁移 apply → 脚本化破坏（改写正文/删修订目录/改绑定行）→ 恢复」，断言字节一致、恢复幂等、非 Skill kind 行不变、恢复后 G08 计划摘要逐字复现；12 条测试含热 WAL 拒收与备份字节损坏可检（各以 /tmp 变异证明拆掉守卫会红）。范围如实限定：整文件回退 DB（非行级）、仅合成根（路径形状守卫，旗标不验证备份证据）、不覆盖 WAL 热备/跨机/加密。
- [~] T17 完整报告逐模块复用/未测矩阵/删除账/证据摘要 → 本文件 + [report.md](report.md)；状态 REVIEW_READY（本线范围），整线 PARTIAL。未合并、未 push。

## 需求—验证映射

| FR | T | G |
| --- | --- | --- |
| 01–03/07 | 03–04/06–07 | 01–04/07–09 |
| 04–06/08–09 | 05–07/13 | 05–09/18 |
| 10–13/16 | 08/11/14 | 10–13/16/19 |
| 14–15 | 09–12/15 | 14–17/20 |

如实备注：T16/G21–G22 的数量/退出码必须在 T01 固定当前集成基线后填写；本设计文档不预填旧环境的历史数字。
→ 已按本树重算，见 `implementation-baseline.md` §3（旧树 90F/670P/10S/158E 仅作历史，不与本树混用）。
