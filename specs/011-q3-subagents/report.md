# Q3 原生子代理定义 — 本线报告（滚动更新）

分支 `codex/011-q3-subagents`。状态词只用四个：**完成**（有指名证据）、
**部分**（已交付一层，另一层缺）、**阻塞**（指名 owner + 精确缺口）、
**未测**（未运行，绝不写成通过）。

本文档的每一项在勾选前都必须能被独立复算；`specs/011-plugin-rollout/README.md`
与 `docs/design/native-subagents/verification.md` 是判据来源。

## 阶段提交账（本线已落地的提交）

| T10 Profile facet/editor | **已落盘并审阅（L1）** | 本机在**已提交树 + 仅这两个文件**的隔离复测：整包 **671 passed / 0 failed**（提交前基线 643 + 本面 28）。28 tests / 140 断言 / 无 skip；覆盖 owner 只能由宿主注入、编译只跟解析器不认调用方塞来的有效集、mid-output 改动不动在途快照、失败 apply 不清旧覆盖、Unknown 保持可查不冒充成功、卸载只隐藏且重投后字节不变、未知 schema 片段隔离保留但拒编译。G16 的**生产链半格仍缺**（需 SR-2 的一次性 permit 与 generation 激活） |

| --- | --- |
| `46c9984129` | T00 基线冻结、T01 旧实现盘点/迁移矩阵、检查点缺席实测 |
| `fb132b6d9b` | apps/server 逐 ID "before"（258 非过）与环境差异归因；Pi 扩展缺席实测 |
| `92b80e5cba` | T02 Pi extension-backed 审查清单 A1–A7；交 C0 的 integration-request |
| `0c3f24c4e4` | 复用来源/许可账（无第三方源码入库，锁文件未动） |
| `d8c60439ad` | Spec Kit analyze 4 HIGH 转成裁定 + 守卫任务 T03b/T03g/S1/CA1/CA2/M1/M2 |
| `c24324a32a` | 第四套件（桌面闭包）冻结 + 分阶段报告开档 |
| `c0686a2407` | **消费 `chat-api` 检查点**（固定 SHA `54ad26c15d`，先验祖先关系后 merge） |

## 1. T00–T15 原包任务逐条

| T | 状态 | 证据 / 缺口 |
| --- | --- | --- |
| T00 冻结 SHA/契约/pin | **完成** | `implementation-baseline.md`（HEAD `96fef2db47`、main `cd7d31f3cf`、五个 `*-ready` 分支实测不存在、三品牌 pin 到 `file:line`） |
| T01 旧实现盘点 + 迁移矩阵 + 套件红 ID | **完成** | `legacy-inventory-matrix.md`（逐符号 REJECT/KEEP-LEGACY/UNKNOWN）、`regression-ledger.md` **四套件全冻结**：pacthold 238P(exit 0)、harness 2 同 ID 同因继承、apps/server 258 非过逐 ID、桌面闭包 `npm ci`+typecheck+`npm test` 146/146(exit 0，lock 未被改写) |
| T02 版本化能力探针 | **部分** | 已交付：`capability-matrix.md`（pin 静态证据 C-1…C-7、Codex `.agents`=skills 根、Pi `pi list`=No packages installed）+ `pi-extension-audit.md`。缺：Claude/Codex L2-exec（CLI 不在本机）、任何 L3（无 harness-api） → 逐格 `unknown/unsupported` 保留 |
| T03 纯定义 DTO/decoder/revision/CAS/导入批准 | **已落盘（L1），两项守卫开放** | 提交 `04322472c2`；`dto/decoder/store/service` 等已入库，`test_revisions_t03`/`test_cas_archive_clone_t03`/`test_import_preview_t03`/`test_credentials_t03` 陆续落盘。**开放项**：store 层 CAS 与"修订不可覆写"在 475 测试的受控突变下**零新增红**（`service.py:170-178` 先自查，store 是并发最后一线），已派专测 `test_store_guards_direct.py` 补直测 → G04/G06 在此之前不算过 |
| T04 归属鉴权/三态/确定性解析/引用不复制凭据 | **已落盘并审阅（L1）** | 同提交；5 模块 + 89 tests exit 0，146 断言、无 skip/xfail；突变审计证明守卫为活：反转 6 层序→3 新红，删 ceiling 工具越界拒→4 新红（`regression-ledger.md` §Guard mutation audit） |
| T05 dry-run 导入幂等 | **已落盘并审阅（L1）** | 提交 `126f7429b8`：`migration.py` + `test_migration_t05.py` 本机 live 树复跑 88 passed / exit 0；分类实现迁移矩阵、grant 边形状结构不可导入；真实用户库迁移仍未测 |
| T06 Claude adapter | **已落盘并审阅（L1）** | 提交 `04322472c2`；`claude.py` 按 pin `0.81.2` 分表：supported/rejected/unknown-behaviour，`permissionMode`/`mcpServers`/`hooks` 编译前逐字段拒。突变审计：清空 `_REJECTED_BY_NAME` → **3 新红**（守卫有效）；改 classification 标签 → 0 新红（该突变不改行为，已记为方法学教训）。装载/隔离 L2-L3 仍 **阻塞 SR-3b/SR-2** |
| T07 Codex adapter | **已落盘并审阅（L1）** | 同提交；`tomlwriter.py` 每份文档用 stdlib `tomllib` 回读等值自校验；发现列按 pin 实证标 `unsupported`（`.agents` 实为 skills 根），CLI 是否 honour `.toml` 保持 `unknown`（本机无 0.147.0 可执行）。ACP 通道证据 **阻塞 SR-1** |
| T08 Pi 条件 adapter | **完成（结论 unsupported）** | `pi.py`：`TargetSlot` 无 Pi 成员、`compile()` 在任何 intent 之前抛拒；解锁仅接受宿主授予的 `AuditedExtensionRegistry`（缺 owner/review_ref 不解锁）。依据 `pi-extension-audit.md` A1–A7 + 实测 `pi list`=No packages installed；G14 如实记"明确缺席" |
| T09 Settings 内容库 | **完成（L1）** | 本机复测：`settings` `npx tsc --noEmit` exit **0**、`npx vitest run` **95 passed / 0 failed / 0 skipped**（7 文件）。含 G15 正半格（空/错/归档/版本差异/键盘次序可导出）与三条反例（错误清草稿、他目标晚响应覆盖、权限项视觉假绿）。写手在 src 修出一处**真实泄漏**：转义标签段里 `onerror=` 形态原样进预览串（可复制粘贴存活），现把 ASCII `=` 折成视觉等价全角；code/code-block 为独立节点类型不受影响。残余待复核项：内联 `code` 段含标签状文本时的折叠边界只由代码顺序保证，未见专用断言 |



| T10 Profile facet/editor | **已落盘并审阅（L1；生产半格待 SR-2）** | `674d2cdae4`；本机隔离复测（已提交树 + 仅该两文件）整包 671 passed / 0 failed，本面 28 tests / 零 skip，写手 16 条突变逐条杀红。Z1 接缝按其真实类绑定并复跑其 140/140。两点更正我先前的派工假设：其公开面**没有** `ItemValueSchema`（真实载体是 `ItemDescriptor.value_schema`），且因本包守卫禁 plugin→plugin 导入，Z1 词汇改由**组合期注入**（`ProfileV2Api.from_contracts`）而非 import | profile-api `4943628f47` 已合并且取到 Z1 分支尖内容：`register_v2_facet` 实测在位、Z1 自测 140/140（`911d60fb8b`）。解除靠消费其新提交，非我改任一生产者包；G16 由单包写手实现中，落盘验收前不算过 |
| T11 Chat 可选菜单 | **完成（L1，含 r3 契约跟进）** | 31 tests / 0 failed，`tsc --noEmit` exit 0（本机实测）。已跟进 chat-api r3 的 `invoke.execute(location: ChatLocation)`：只信选择期位置，过期即 `unavailable` 且零端口调用；写手用还原旧闭包反证 5 条选择期用例必红。伪调用仍结构性不可表达（无 `insert-command` 构造）。真实 gateway/reader 缺席 ⇒ L2/L3 仍不主张 | | SR-5 已按固定 SHA `54ad26c15d` 消费并在本树复验（vitest 15/15、tsc exit 0，merge `c0686a2407`）；`ChatInputEntryAction` 自带 `invoke{execute}` 与 `disabled{reason}`，G17 无需向 Z2 新增接缝。真实 gateway 仍缺（SR-2/SR-3b），故默认全 `disabled` 并带具名原因 |
| T12 同一 submit permit 应用 + 原消息恰发一次 | **已落盘并审阅（L1/L2 fixture 级；生产格阻塞）** | `apply.py` + `test_apply_t12.py` 本机 **28 passed / exit 0**；只驱动 C0 真实端口形状（`application.py:211-217`，实现 `configuration_service.py:202/239`），默认产出是指名缺失端口的类型化拒绝、不造伪 permit；六守卫突变全杀红（放 Unknown 发送→3、release 可复用→1、新会话当恢复→3、过期 generation→1、busy 放行卸载→1、去掉诚实默认→1）。缺失协作方四项（admission ready / 一次性 permit / 原生 runtime generation / 操作绑定收据）⇒ G18–G20 生产格**未过** | SR-2：`runtime_generation`/`submission_permit`/reset 全仓零符号 |
| T13 产品启用唯一服务/贡献 | **本包内半格已落盘；产品装配交 C0** | `plugin.py`/`wire.py` + `test_plugin_registration_t13.py` 本机 **52 passed / exit 0**：契约形状注册、store root 只可在宿主 data root 下、激活与处置不写不删、组合背不了的面不宣称可用（`resolvePreview` 不报 ready）、默认 attestation 既不给权限也不绑项目。`products/**` 与根锁归 C0（I-1/I-2/I-9），本线未改 | `products/**`、根锁归 C0（I-1）；本线只交 descriptor |
| T14 三品牌逐格 L1/L2/L3 + 迁移备份恢复 + 独立审阅 | **部分** | L1 可交；L2-exec 缺 CLI；L3 缺 foundation/harness-api。**不得报三品牌通过** |
| T15 文档/运维报告 | **完成** | 本文 + baseline/matrix/ledger/api-requests/integration-request/pi-audit |

## 2. FR → 实现 → 门（G01–G24）逐格

| G | 门要求（正/反） | 状态 | 证据或阻塞 |
| --- | --- | --- | --- |
| G01 pin 锁定，不把官网最新当仓内支持 | **完成** | `capability-matrix.md` 全表按 pin；Pi 主机 0.86.1 与 pin 0.84.2 漂移单独登记 |
| G02 三品牌 native/extension-backed/unknown 分列 | **完成** | 同上 §Field matrix（Pi=extension-backed 缺席，Codex=X，Claude=A/unknown） |
| G03 每品牌每字段支持/不支持/未知 + 证据 | **完成（L2-static 层）** | 字段矩阵每格带 C-n 或 X/U 出处；L2-exec/L3 层 **未测** |
| G04 修订不可变 + 摘要 + 审批来源 | **完成（L1）** | 服务层 + store 层双层皆有证：新增 `tests/test_store_guards_direct.py`（5 tests exit 0），受控突变 mut2 使"修订不可覆写"拒绝变 no-op → **1 新红**；此前零新增红的成因（`service.py:170-178` 先自查）与结案见 `regression-ledger.md` §Closing the G04/G06 store-guard condition |
| G05 导入安全预览并固定来源 | **待审阅** | T03 `import_preview` 反例：symlink 穿越、递归 include、URL fetch、导入即执行；另有 T03g 全局禁令集覆盖 |
| G06 CAS/幂等、归档旧引用仍可读 | **完成（L1）** | 幂等重放/同键异 payload 拒/归档保冻结引用有测试；store 层 CAS 现由直测覆盖——mut1（CAS 判断失效）→ **2 新红**，且含反空转对照（正确版本确实写入）以证两条断言非互相凑数 |
| G07 分层确定性解析、项目不外泄、伪 projectId 拒 | **待审阅** | T04 |
| G08 Profile 专用只归本人 + 引用固定版 | **待审阅** | T04 |
| G09 引用逐属主授权、强制边界不被定义提升 | **待审阅** | T04（`ceiling.py` 缺席权威→拒；C-7 结构佐证但不替代运行裁决） |
| G10 旧纯定义 dry-run/恢复字节/ID 一致 | **完成（L1，合成夹具）** | 矩阵 + `migration.py` 分类/两步入库/幂等重放，`test_migration_t05.py` 88 tests exit 0；真实用户数据恢复演示未测（不在本轮授权） |
| G11 Claude 装载/移除受控可证 | **阻塞 SR-3b/SR-2** | 记 `unsupported/unknown`，不许"文件生成即 loaded" |
| G12 Codex TOML 装载/移除受控可证 | **部分 + 阻塞** | 生成/回读 L1 可做；ACP 路径识别 **X**（pin 静态证据） |
| G13 A/B 实例隔离 + 原生同名诊断 | **部分** | 同名/撞原生诊断 L1 可做；真实双会话隔离 **阻塞 SR-2** |
| G14 Pi 经已审 extension-backed 入口或明确缺席 | **完成（缺席）** | `pi-extension-audit.md` + `pi list` 实测 |
| G15 Settings 空/错/归档/版本 diff/键盘 | **阻塞** | T09 |
| G16 Profile 修改不即刻生效、下一次提交用新快照 | **阻塞 SR-2/SR-4** | 快照 DTO L1（`DefinitionSnapshot`）可做，生效链不可 |
| G17 Chat 只对证实可调用项出 action | **阻塞 SR-5** | 无可证调用入口 → 只详情 |
| G18 apply Confirmed 后原消息发送一次 | **阻塞 SR-2** | — |
| G19 reset/重启恢复同 native session | **阻塞 SR-2** | — |
| G20 busy 卸载受阻、晚到计划 stale | **阻塞 SR-2** | — |
| G21 干净安装/独立插件测试/typecheck/build/smoke | **部分** | 本包独立 pytest 可做；`npm`/electron smoke 属 C0 集成树（I-1/I-2） |
| G22 三品牌 L3 实际产品链按支持矩阵记录 | **部分（如实记未完成）** | 无任何 L3；Pi 无 extension-backed |
| G23 受影响套件逐 ID 同因对比含收集阶段 | **完成（before 侧）** | `before-server.ids` 258 条 + junit；after 侧随每阶段 commit 追加 |
| G24 备份恢复与隔离复证、独立审阅 | **部分** | 隔离复证=本线独立 venv + 仓外证据 + 用户 HOME 零读写；真实用户数据恢复演示 **未测**；独立审阅 **未做** |

## 6. 本线发布物（检查点）

| 记录 | 分支 | 发布提交 | implementationSha | status |
| --- | --- | --- | --- | --- |
| `q3` | `codex/011-q3-ready` | 见 `git rev-parse` | `8a484f2aeb3466701890a093e1085b46e3a3655f`（干净 worktree 实测 386 passed / 0 failed） | **PARTIAL** |
| `q3-r3` | `codex/011-q3-ready-r3` | 见 `git rev-parse` | `445dc76a74` | **PARTIAL**（T05 落地、R3 零回归入账；当时保留一个自证失明的守卫为红） |
| `q3-r4` | `codex/011-q3-ready-r4` | 本次 | `f9dffe5835c8bed9d8e4fcdb7cf0fa9f5d742940` | **PARTIAL**（禁令守卫全部落地，整包 635/0；仅 L2-exec/L3 与 T09/T10/T12–T14 缺席） |
| 消费更新 | （无新分支） | `d9a2dcb2ec` 等 | 记录提交，非代码 SHA | **已按固定 SHA 消费 `foundation` 8844c475bc 与 `profile-api` 4943628f47**：本包 639 passed/0 failed；pacthold/harness 基线因上游增删测试而标记为**不可与消费前逐 ID 比较**；同时发现并上报跨线符号冲突（见下） |
| `q3-r5` | `codex/011-q3-ready-r5` | 本次 | `ca7d239b4a` | **PARTIAL**（T09 落地 G15/L1；foundation+profile-api 已消费；剩 T10 因跨线冲突不可执行、T12–T14 与 L2-exec/L3 缺席） |
| `q3-r6` | `codex/011-q3-ready-r6` | 见 `git rev-parse codex/011-q3-ready-r6` | `bc3a4cc309` | **PARTIAL**（五个上游检查点按固定 SHA 消费并逐一复验；分离 worktree 复测 671/0；两贴 TS 全绿；Z1+Q5 自身 456 passed；server 逐 ID 与归一化后原因零漂移。接缝四面已在树内实测但**不属本 SHA**，因两份守卫仍钉住被删词汇 | 
| `q3-r2` | `codex/011-q3-ready-r2` | `deb9c053a7` | `4c7af38c0a50752715c614c0f9705cd920d7fa32` | **PARTIAL**（撤回首版 limitation[0]：G04/G06 store 层守卫已直测并双双被突变杀死） |

首版冻结的是"可复算的绿"而非"移动中的树"：T03 写手在其自身 150 轮上限处中途停笔
（末行为 "Now the service module:"），T05/T09/T03g 写手仍在编辑，整包实跑
`43 failed, 587 passed`。这些在途文件未被跟踪、不在上述 implementationSha 内，
因此发布不掩盖在途破损；本修订如实同时给出两个数字。

实际分支指向：`codex/011-q3-ready` = `ca8a81e89e`。main 仍 `cd7d31f3cf`，
远端未配置 ⇒ 未合并、未推送。

## 3. 三类事实结尾账（消费 harness-api / permissions-api 之后重写）

### 完成（各有指名证据）
- **T00 / T01 / T02(静态半格) / T15**：基线冻结、四套件逐 ID、旧实现逐符号迁移矩阵、
  pin 级能力矩阵与 Pi A1–A7 清单、复用与许可账。
- **T03–T05、T07、T08、T09、T10、T11、T12、T13(包内半格)**：本包内容域、六层解析与
  ceiling、dry-run 导入器、Codex/Pi 编译策略、Settings 内容库（G15 95/95）、
  Profile facet（Z1 真实接缝 140/140 复跑）、Chat 输入源（跟到 chat-api r3）、
  apply 编排（28 tests、六守卫可杀）、服务与线注册（54 tests）。
- **接缝对接**：adapters 已改为**只产出 `ordessa_harness_api` 真实类型**并删掉本域重复
  意图词汇；permissions 授权裁决走真实 `Authorizer` 端口并有全码表覆盖测试。
- **零回归**：pacthold 212、boundary 15、harness 仅 2 条继承同因红、
  server 67 个非过 ID 同集合同原因（归一化后零漂移）、Z1/Q5 兄弟包 456 passed；
  两贴 TS 全绿且根锁 0 改动。

### 阻塞（具名到端口与符号，不再用"上游没跑完"含糊）
- **G18/G19/G20 与 T12 生产半格**：需 C0 在默认组合注入
  `acp.admission.native_evidence`、`acp.admission.principal`、`server.instance_id`
  （`SR-3c`）；当前 admission 端口推导为 `ready=False`，且无一次性 permit、
  无原生 runtime generation 激活、无操作绑定原生收据（`missing_production_collaborators()`）。
- **G03/G22 的 L2-exec/L3 半格**：本机无 `claude`/`codex` 可执行（已实测），
  真实模型未授权；Pi 无已审扩展（`pi list` 实测为空）。
- **契约缺口 6 条已提 C0**（SR-12 的 G-1…G-6），其中最实质的是 **G-1 无内容投放端口**
  与 **G-2 无法表达"重建级选项"**；另 **G-3** 契约允许 `supported` 不带证据，本线自行收紧。
- **T14 独立审阅**未做；真实用户数据迁移/恢复演示不在本轮授权。

### 未测（绝不写成通过）
- 包内 18 条守卫红：禁令与边界两文件仍钉着被删词汇，迁移未完成 ⇒ 在迁移落地前
  **接缝面不提交、不发新检查点**。
- Settings 的真实浏览器可达性/200% 缩放/屏幕阅读器；`npm run build`、
  `test:electron`、`tests/acp-connector`（属 C0 集成树）。
- `base.py` "文件存在不得升格为 loaded" 那一格仍只读码、未做突变击杀。
- 导入器的事务性（跨条目中途失败无故障注入缝隙）与 bulk 聚合预算边界。
- G16 的"当前输出不被打断"仅证明到"选择不动端口 + 在途快照稳定"，真实流式轮次属 Chat/Harness。

## 4. git 边界自查（readiness 末项：main/远端未动）

实测于本线写作过程中（2026-09-28 02:41 +08）：

| 项 | 值 | 命令 |
| --- | --- | --- |
| `main` | `cd7d31f3cfba6a0e1ec65f9a13014c6b9751540b` — **未移动** | `git rev-parse main` |
| `merge-base main HEAD` | `cd7d31f3cf…` == main，即本线只做单向领先，未反向改主树 | `git merge-base` |
| 本线领先 main | 19 commits | `git rev-list --count main..HEAD` |
| 远端 | **本 worktree 未配置任何 remote** → 结构上不可能已推送 | `git remote -v` 空输出 |
| 本线 ready 分支 | 尚未创建（发布时以检查点记录提交为准） | `git branch --list 'codex/011-q3*'` |
| 根 `package-lock.json` / `package.json` | 未被本线改写（0 行差异） | `git status --porcelain -- …` |
| 其他树 | 未写入：本线全部写入面为 `plugins/assets/subagents/**` 与 `specs/011-q3-subagents/**`，加一次对 `chat-api` 发布提交的 merge（只读消费） | 见各提交 |

`git status` 的未跟踪项只含本线包目录与仓外证据根；探针产物、`.venv`、
`node_modules`、`__pycache__` 均在 `.gitignore` 内（`--ignored` 计数 5），
不入库。

## 4b. 已实测但**尚未提交**的接缝面（不在任何已发布 SHA 内）

| 面 | 本机实测 | 落地状态 |
| --- | --- | --- |
| adapters 改用真实 `ordessa_harness_api` 类型（删本域重复词汇） | 179 tests；突变：放开"文件存在即 loaded"→4 红、去凭据扫描→红、去 shell 层→5 红、放宽 facet 校验→红；本轮我自查"路径不是目标"这条：把 `decoder.is_path_shaped` 改成恒 `False` → **10 条红**（8 条参数化拒绝 + `test_secret_binding_slot_and_ref_refuse_path_or_shell_strings` + FR09 完整性守卫），控制组的 2 红属当时在飞的写手文件，不计入 | **已闭合**（迁移后的 3 条红由守卫写手转绿；被 150 轮上限截断的那名写手想补的两条——rebuild-class 拒绝、路径非目标——实测均有断言：`test_adapter_intents_t06.py:213`、`test_prohibitions_t03g.py:1288`、`test_adapter_intents_t06.py` 参数化拒绝） |
| permissions 授权裁决接缝 | 宿主注入端口名与冲突类型后 100 passed（接缝+上限+引用三片）；两突变各杀 2/3 条；缺注入 → 现有 C5 码 `OPERATION_UNKNOWN`/`ADAPTER_MISSING` 拒绝，绝不放行 | **已闭合**：`src/**` 对 `ordessa_permissions_backend` 的 grep 命中数 **0**（18 个源文件逐个为 0） |
| apply 编排（G18–G20 域内半格） | 28 tests；六突变逐一杀红 | 已闭合 |
| 服务/线注册（T13 包内半格） | 54 tests；八突变逐一杀红（含 8 个伪造身份变体） | 已闭合；`wire` 侧把服务已具备的 viewer 作用域读法真正接上的一刻仍在写手手里，未落地前 §C1 只算**服务面**闭合 |
| §C1/§C5 服务面（viewer 作用域读、`operation_status`、具名管理员面） | 21 tests；三突变：读侧忽略 viewer→10 红、`operation_status` 凭空造成功→2 红、receipt 作用域丢主体→2 红 | 服务面闭合；**线面（wire 传 viewer）仍开放**，落地前外部线客户端仍看到整个已认证作用域库 |

整包合并实测（2026-09-28 01:41Z，接缝四面+依赖声明+守卫迁移+服务面全部落地后）：
`PYTHONPATH=plugins/assets/subagents/src .venv/bin/python -m pytest plugins/assets/subagents/tests -q`
→ **890 passed / 0 failed，真实 exit 0**（重定向到文件后取 `$?`，非管道尾），且 skip/xfail 扫描无命中。

结论写死在此：**890 这个数字仍是工作树实测，不是 `-r6` 记录的内容**；发布出去的那笔提交（`bc3a4cc309`）只含已在分离 worktree 复测 671/0 的部分。等 `wire` 那一笔落地后，一并提交、分离 worktree 复测、再发 `-r7`。

## 4c. 审阅中抓到的两处"看着绿、其实欠账"（整包已 845 passed / 0 failed 之后仍然成立）

包级测试现在全绿，但绿的原因里混进两处未闭合项，先记下来再处理：

1. **`pyproject.toml` 仍写 `dependencies = []`**，而 `src/**` 实际导入
   `ordessa_harness_api`、`ordessa_permissions_api`、`server_plugin_api`
   （以及下面第 2 条那个不该存在的 backend 导入）。守卫放宽了白名单却没有同步声明依赖，
   后果是"独立安装"与隔离环境（G21）会拿到一个装不起来就跑不通的包——
   这是声明层缺失，不是测试层能掩盖的。须补：
   `ordessa-harness-api`、`ordessa-permissions-api`、`ordessa-server-plugin-api`
   （照 `plugins/assets/sandbox/backend/pyproject.toml` 的先例，无版本硬锁）。
2. **守卫把 `ordessa_permissions_backend` 放进了白名单**（`test_boundaries_t03b.py:102-107`
   的理由是"Q5 没在 API 里再导出这三个符号"）。这正是 SR-13b/SR-15 判为**必须禁止**的
   plugin→plugin 私引：放宽守卫去迁就一个可消除的依赖，等于把边界规则倒果为因。
   处理顺序已定：先由接缝改为宿主注入端口名与冲突类型（进行中），
   再从白名单删掉该条并让它继续被禁——两个方向不能同时留。

结论：**"整包 845 全绿"不等于 R2 可勾**。上面两条闭合前，接缝四面仍不进入任何发布 SHA；
`-r6` 记录的仍是 `bc3a4cc309`（分离 worktree 复测 671/0）。

**2026-09-28 01:41Z 复核：两条都已闭合，但记账要按实测方向写。**
1. 依赖已声明：`dependencies = ["ordessa-harness-api", "ordessa-permissions-api", "ordessa-server-plugin-api"]`
   （照 `plugins/assets/sandbox/backend/pyproject.toml` 先例无版本硬锁），`ordessa-permissions-backend`
   只进 `dev` extra。旧的 `test_the_manifest_declares_no_runtime_dependency`（SR-13 之前的 stdlib-only 断言）
   改写为 `test_the_manifest_declares_exactly_the_published_contract_runtime_deps`，从 src 实际导入推导，不是重述常量。
   写手突变证明其有牙：删掉 `ordessa-harness-api` → 声明/导入双向核对守卫红。
2. `src/**` 已不再导入兄弟插件实现包：端口名与冲突类型改由宿主注入（组合根在包外，才有权引 backend），
   缺注入按 `ADAPTER_MISSING`/`OPERATION_UNKNOWN` 拒绝而非猜测；守卫拆成 src/tests 两个作用域
   （src 禁 backend，tests 容忍并保留"SR-15 落地即删"的理由注释）。我自己在符号层复测了 SR-15 的前提：
   `ordessa_permissions_api` 对 `AUTHORIZER_PORT / CorrelationConflict / VersionConflict / Authorizer / ApprovalFacts`
   **五个名字全部不导出**（`hasattr` 逐项 False），所以这条注入不是想象中的洁癖，是生产者缺口的真实绕法。
   我复查了守卫方向没有放宽：M3 突变（删 tests 作用域那条 backend 容差）杀 2 条，M1（src 重新引 backend）杀 6 条。

## 5. 假绿禁令自查
- 无 `session/new` 冒充 resume；无 `plugins/` 之外的写入；无二进制入库；
  无 skip/xfail 藏红；探针产物在仓外；用户 `~/.claude|codex|.pi` 内容未读未写。
- 每个守卫配一条"删掉守卫就红"的反例（审阅时按此验收，未达即退回写手）。

## 7. 停笔点（供 /goal resume 续做）

- 已发布 `codex/011-q3-ready-r5`（代码 SHA `ca7d239b4a`，干净 worktree 复测 642/0）。
  其后的 `guard-writer 末笔` 提交只在 feature 分支，**未并入 r5**；若要并入需重冻 SHA 再发 `-r6`。
- 两个单包写手各自撞到自身 150 轮上限中途停笔（T03 内容片、T03g 禁令片）。
  它们的产物已被本机实测覆盖（整包 642 passed / 0 failed），停笔不等于产物破损；
  但"写手未报完成"这一事实如实记录，不把它当作验收。
- 续做顺序：① 等 `harness-api`/`permissions-api`；② 按 C0 真实 `IntentSet/TargetHandle`
  把本域自建 intents 降为内部构造（SR-1b 三问）；③ 交 C0/Z1 解决
  `pacthold.resource_contracts.AgentBoxProfileV1` 冲突后接 T10 facet 执行链；
  ④ 以消费后新基线做逐 ID after-run，再发 `-r6` 并把 T12–T14 的 L3 半格按实测补上。

## 8. 两处自纠（我先前报告的错误，按事实更正）

1. **度量法错误**：早前我在 `settings` 目录写「`npx tsc --noEmit` exit 0」，命令形态是
   `npx tsc --noEmit 2>&1 | tail -4; echo $?` —— 那取到的是**管道尾命令**的退出码，不是 tsc 的。
   本轮改用「重定向到文件后取 `$?`」重测：**当前 tsc 实际 exit 2**。同批里 vitest 我用的是
   `${PIPESTATUS[0]}`，那个数（2 failed / 93 passed）可信。凡本报告中标为 exit 0 的门，
   若后续复核发现度量法不符，须以本条为例逐条重取，不接受"看起来通过"。
2. **发布后状态漂移**：`-r5` 记录后写手仍在动，`report.md` 一度把 T09 写成「完成（L1）」。
   现按事实降为「部分」，并明确区分"已发布 SHA 内的测量"与"当前工作树测量"。

## 9. 清洁度审计（readiness 项：私有环境/临时文件/只提交源与文档）

以 tracked 集合为准实测（非 `du` 全目录，避免把被忽略的依赖算进来）：

| 检查 | 方法 | 结果 |
| --- | --- | --- |
| 二进制入库 | 逐个 tracked 文件跑 `file -b`，只匹配 ELF/archive/PNG/JPEG/Zip | **零命中** |
| 源码带可执行位 | `git ls-files -s plugins/assets`，模式非 `100644` 者 | **零命中** |
| 本面 tracked 规模 | `git ls-files plugins/assets/subagents` | 71 个文件，合计 1.2 MB（纯源与文档） |
| `node_modules` / `.venv` / `__pycache__` / egg-info | `git check-ignore -v`、`git status --ignored` | 全部命中 `.gitignore`（`node_modules/` 在第 1 行），未进暂存区 |
| 探针与日志 | 位置 | 均在仓外 `/home/maoqh/ordessa-evidence/q3/`（日志、JUnit、逐 ID 清单、解包 tarball、npm 安装件），未入库 |
| 仓外 scratch | `/tmp/mut*`, `/tmp/q3*`, `/tmp/verify*` | 每次突变审计后删除；`git worktree remove` 已回收 `/tmp/q3clean`、`/tmp/q3c2-5` |

一处**我自己制造的假阳性**记下以免复现：第一版检查用 `file | grep -i "executable"` 判二进制，
Python 源码会被 `file` 描述成 “ASCII text executable”，于是把 `.py` 全报成可疑二进制。
改为只匹配真实二进制族后为零命中。凡"看起来像"的判据都要先证伪自己的度量法。
