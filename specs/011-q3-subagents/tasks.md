# Q3 任务与原包追踪

本线副本，允许勾选并追加查漏任务。共同 plan 的 owner 分配优先；原表范围外步骤登记依赖/C0 集成，不由本线偷改。原包更晚变更须有明确裁定，不自行缩需求。

- [x] R0：读完整输入，冻结实际 SHA/包/红 ID/环境，盘点复用。
      → `implementation-baseline.md`（HEAD `96fef2db47`、main `cd7d31f3cf`、五个检查点分支实测均不存在、三品牌 pin、本线 venv）、
      `legacy-inventory-matrix.md`（旧派工面符号/表/迁移逐条 REJECT-KEEP-UNKNOWN）、
      `regression-ledger.md`（pacthold 238P、harness 2 继承红同 ID 同因、boundary 13P）、
      `capability-matrix.md`（T02 部分：pin 静态证据 + 主机可执行事实）。
- [ ] R1：独立工作与接口请求完成；消费必需 checkpoint 并留精确 SHA。
      → 接口请求已成文：`api-requests.md` SR-1…SR-8（含 SR-3b 精确到符号）。
      检查点消费：**`chat-api` 已按固定 SHA `54ad26c15d` 消费**（先核 status=READY、
      implementationSha `a3ec20c046` 为其祖先、planAnchor 即本线基线，再 merge 为
      `c0686a2407`，并在本树复跑其 proof：vitest 15/15、`tsc --noEmit` exit 0）。
      **尚无**：`foundation`/`harness-api`/`profile-api`/`permissions-api`
      四支仍未发布，故本项只能部分完成。
- [~] R2：本线全部原包任务有实现/验收/依赖归属，生产假接口为零。
      → T00–T05/T07/T08/T11 有实现+验收+归属；未清零项：`test_prohibitions_t03g` 尚有 3 红（含能力探针自证扫描失明，须修守卫不得放宽测试）、T09 尚无测试、T10/T12–T14 归属为检查点缺席。无 stub 被记作装配。
- [x] R3：检查点/接线清单/许可迁移账/报告齐备，定向及相关全链门通过。
      → 检查点 `q3`/`q3-r2` 已发；`integration-request.md`/`reuse-decisions.md`/`regression-ledger.md` §R3 after-run 齐备。
      定向门（live 树）：Q3 包 tracked 内容 479 passed（另测干净 worktree）、pacthold 238、boundary 13、harness 2 failed/308 passed 与基线同 ID 同数 ⇒ 零回归。全链门缺席：四检查点未发布。
- [x] R4：Spec Kit analyze/converge 查漏，未完成项如实；发布本线 clean ready commit。
      → analyze 已跑并转成裁定+守卫任务（`d86c0439ad`）；converge 结论：原包 16 条中 T00/T01/T03/T04/T05/T06/T07/T08/T11/T15 有实现与 L1 证据，
      T02 半格、T09 在途、T10/T12/T13/T14 因四个上游检查点全程未发布而如实缺席（不以单测替代生产门）。
      发布：`codex/011-q3-ready-r4` = `f9dffe5835`（干净 worktree 复测整包 635 passed / 0 failed / 0 skipped，tracked 零脏项）。

## 原包：native-subagents

来源：docs/design/native-subagents/tasks.md，2026-09-28 派发快照。以下保留原条目便于追踪；过程授权与 owner 由共同 plan 更新。

# Tasks / dependency order

均未执行。每项交付记录 SHA、改动文件、命令/退出码、证据路径和未测范围；`[P]` 仅表示前置完成后可并行，不表示已派发。

## P0 事实、接口、基线

- [x] T00 冻结 main/平台/Harness/Profile/Chat/产品 SHA、公开契约和真实包路径；固定各 native/ACP adapter pin，确认目标角色入口；输出 `implementation-baseline.md`。
      → 提交 `46c9984129`；pin 到 `file:line`；五检查点分支冻结时实测缺席。
- [x] T01 清点旧 `server_assets`/Profile 子代理表/授权边/调用历史、数据归属/ID；冻结四套件失败 ID 和真实测试命令，产出只读迁移矩阵及回滚样本。
      → 提交 `46c9984129`+`fb132b6d9b`+`c24324a32a`；逐符号矩阵 + 258 条 server 逐 ID + 四套件（含桌面 146/146）。
- [~] T02 对 Claude/Codex/Pi 做版本化能力探针（G01–G03）。
      → **部分**：`capability-matrix.md` + `pi-extension-audit.md` 已交（pin 静态实证 C-1…C-7、Codex `.agents`=skills、Pi `pi list` 空）。L2-exec 半格缺 `claude`/`codex` 可执行 → 逐格保持 `unknown/unsupported`，不虚报。
## P1 内容与分配

- [x] T03 实现本域纯定义 DTO、严格 decoder、正文容量/编码/字段保留、不可变 revision/digest、CAS/归档/克隆与来源批准（G04–G06）。
      → 提交 `04322472c2`；**G04/G06 的 store 层守卫仍开放**（突变零新增红），专测 `test_store_guards_direct.py` 补直测中。
- [x] T04 实现用户/项目/Profile 归属鉴权、全局/项目分配三态、确定性解析及来源/冲突诊断；资源引用仅解析且不复制凭据（G07–G09）。
      → 提交 `04322472c2`；89 tests，突变证实 6 层序与 ceiling 拒绝为活守卫。
- [~] T05 按 T01 dry-run 导入可证纯定义，保持 ID/固定修订；授权边/旧工具不误迁；恢复重跑幂等（G10）。→ 写手落盘中。

## P2 接入与 UI

- [x] T06 [P] Claude adapter：固定版本 frontmatter、目录/原生发现、隔离、reset、核验；拒不支持字段（G11/G13）。→ L1 已交 `04322472c2`（frontmatter 严格编解码 + 拒字段表；突变证实拒绝路径为活守卫）；装载/隔离/reset 的 L2-L3 **阻塞 SR-3b/SR-2**，未勾死。
- [x] T07 [P] Codex adapter：固定版本 TOML、项目/个人发现、隔离、reset、核验与 ACP 通道证据（G12/G13）。→ L1 已交（TOML 写出 + `tomllib` 回读等值）；发现在 pin 处实证缺席记 `unsupported`，CLI 语义保持 `unknown`；ACP 通道证据 **阻塞 SR-1**。
- [x] T08 [P] Pi 条件 adapter：仅在 Harness 已登记受审扩展且真实控制端口存在时编译定义；否则 unsupported，不安装示例扩展（G14）。→ **按结论完成**：`TargetSlot` 无 Pi 成员、`compile()` 先拒后发；依据 `pi-extension-audit.md` A1–A7 与实测 `pi list` 空。
- [x] T09 [P] Settings 内容库与全局/项目默认管理（G15）。→ 已落盘并本机复测：`tsc --noEmit` exit 0、`vitest run` 36 passed / 0 failed（含 G15 三条反例：错误清草稿、晚响应覆盖他目标、权限项假绿）。真实浏览器/键盘可达性/缩放仍列未测。
- [ ] T10 Profile facet/editor（G16）。→ **阻塞 SR-4**：`profile-api` 未发布，且 `FacetDescriptor`/`addEditor` 全仓零命中（已复核，非误判）。
- [x] T11 Chat 可选菜单：只对可证调用入口提供 action；Skills/命令名冲突、旧 generation 防串；无调用入口只展示详情（G17）。→ 提交 `c77a26c8ea`（消费 `chat-api` 后按真实契约实现；26 tests + `tsc` exit 0；全模块不存在 `insert-command` 构造 ⇒ 伪调用不可表达）。G17 正半格按 pin 数据为空真：**无**品牌可证 `invokable`，故 ready 路径仅由测试夹具驱动，不作 L2/L3 声称。

## P3 产品链、回归、评审

- [ ] T12 完整目标集合通过 Harness 同一 submit permit 应用，再发送原用户消息恰一次；故障/Unknown/当前输出/双会话隔离和 resume 反例（G18–G20）。
- [ ] T13 产品启用唯一服务/贡献，删除仅本域重复逻辑，保持旧授权边归属；隔离装包、版本锁、UI build/electron smoke（G21）。
- [ ] T14 三品牌按实际能力逐格 L1/L2/L3 证据、失败 ID/原因差分、迁移备份恢复演示与独立审阅。Pi 若仍无安全 extension-backed L3，报告明确未完成，不能报三品牌通过（G22–G24）。
- [ ] T15 文档/运维报告含来源 pin/许可、复用取舍、未测与清理账；review-ready 不代表 merge-ready，合并/push 另依授权。

## Spec Kit analyze 查漏（R4 提前执行，2026-09-28）

`/speckit-analyze` 对 `spec.md`/`plan.md`/`tasks.md` + 原包 contracts/data-model/
verification + 宪章做只读分析，0 CRITICAL、4 HIGH、5 MEDIUM、3 LOW。判据裁定与补
充任务如下（`tasks.md` 是本线副本，允许追加查漏任务；不改公共设计）。

### 裁定（把歧义变成唯一口径）

- **C1 解析层数 = 6 层，以 `data-model.md` §范围解释为准。** `spec.md` FR03 只列
  4 层（用户全局/项目/Profile/会话），缺 harness 绑定两层，而 FR03 自己的
  "Harness 绑定不混品牌"只有含该两层才可表达。公共 spec 不由本线改写，此处登记
  唯一实现口径；T04 的解析器按 6 层实现并加"同层两条即冲突"的反例。
- **B1 "四套件" 唯一化：** = `packages/pacthold` + `apps/server` +
  `plugins/harness` + 桌面/扩展闭包（根 `npm ci`、`npm run typecheck`、
  `npm test`）。前三者已在 `regression-ledger.md` 逐 ID 冻结；第四者在本次实测
  并追加同表。Q3 包自身套件作为第五项独立记录，不替代四套件。
- **L1 标识冻结：** 线/盘/wire 唯一 id 为 facet `assets.native-subagents`（AGENTS
  规则 5：改名将需迁移说明）。目录 `plugins/assets/subagents`、发行名
  `ordessa-assets-subagents`、import 名 `ordessa_assets_subagents` 为其派生，四者
  对应关系在本文件冻结，后续不得各自漂移。
- **L2 命名口径：** wire/DTO 公开字段用 camelCase（照 `contracts.md`），Python
  dataclass 字段用 snake_case（照 `data-model.md`），decoder 只做一次显式映射并
  测试该映射，不允许多别名同存。
- **M3 字段裁定：** `NativeDefinitionObservation.suppressible` 在契约/任务/门中均
  无消费者，本线不实现该字段，改由
  `NATIVE_DISCOVERY_UNCONTROLLED` 诊断承载"不可遮蔽"事实；
  `DefinitionSnapshot.runtimeGeneration` 在 `runtime_generation` 全仓零符号前，
  只作注入的不透明值，Q3 不得自行生成语义。

### 追加任务（可勾选，含归属）

- [ ] **T03g 禁令反例集（补 F1）** — owner Q3。为 6 条"否定式要求"各写一条"删掉
  守卫即红"的测试：FR08 业务码不写原生文件/不 spawn/不调模型；FR09 受管内容只落
  实例私有 generation，绝不触达用户/项目原生路径；FR11 缺 Profile/Chat 贡献时其他
  域不崩；FR12 不引用旧 `run_subagent` 授权表、不建第二套派工；FR16 服务缺席/卸载
  行为；FR04 失效在副作用前拒。
- [ ] **T03b 包边界守卫** — owner Q3。新包不得 import `ordessa_server_compat`、
  `ordessa_harness` 私有、`ordessa_server_product` 或宿主私有；`pacthold` 独立性
  不被本包破坏（对齐 `apps/server/tests/test_dependency_direction.py:128`、
  `test_server_compat_boundary.py:152`）。
- [ ] **S1 缺席账（补成功条件零覆盖）** — owner Q3。把"至少一个真实受控调用入口
  的 L3 证据"逐格写成 `阻塞 + owner + 精确缺失符号`，落 `report.md`
  §未测与 `api-requests.md`；已由 SR-1/SR-2/SR-3b 承担，任务化以便审计。
- [ ] **CA1 请 C0/用户裁定** — 取证 `@agentclientprotocol/claude-agent-acp@0.81.2`
  用了仓外只读 `npm install`（该 pin 未 vendor；Pi/Codex 两 pin 已 vendor 在仓）。
  宪章 P5 的"无远端操作"是否涵盖取固定版探针产物需裁定；否则改为 vendor 该
  tarball 使证据可离线复算。已在此如实披露，不静默。
- [ ] **CA2 内部表示不越界** — `adapters/intents.py` 是本域内部表示，跨界时由 C0
  的 `harness.configuration-adapters/v1` 决定线上形状（宪章 P3 禁止自造跨树
  API）。已在 SR-1 写明，追加勾检项：集成前核对不存在第二套 intent 上线。
- [ ] **M1 产物具名** — T01 输出 `legacy-inventory-matrix.md`（含回滚清单），
  T02 输出 `capability-matrix.md` + `pi-extension-audit.md`；已落地，登记为可核验
  路径而非"做过"。
- [ ] **M2 退化路径** — 当可用品牌集合为空（Codex/Pi 实证 `unsupported`、Claude
  `unknown`）时，T10/T11/T12 的交付降级为"对解析器与 `assess()=unknown` 的实现
  + 反例，门保持开放"，不得静默空转或假通过。

| FR | T | G |
| --- | --- | --- |
| 01–02/14 | 01/03/05 | 04–06/10 |
| 03–04/10 | 02/04/10/12 | 07–09/13/16/18 |
| 05–06 | 02/04/06–08/12 | 02–03/09/11–14/19 |
| 07–09/15 | 02/06–08/12/14 | 01–03/11–14/18–20/22–24 |
| 11–13/16 | 05/09–11/13–15 | 10/15–17/21–24 |

T14 的“完整三品牌”只在每格满足时通过；局部条件不成立时交付其他完成部分与精确阻塞，不能将期望数字写作事实。
