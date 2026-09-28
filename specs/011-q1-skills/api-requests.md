# Q1 接口请求登记（检查点协议 §依赖不构成整线停机）

日期 2026-09-28。分支 `codex/011-q1-skills` @ 见 report.md 各阶段 SHA。
共同符号级证据、来源行号见 [research/seam-gaps.md](research/seam-gaps.md)；本文件是按 owner 派发的请求账，
每条含调用者、目标操作、所需 DTO、失败反例、当前阻塞级别与 Q1 的独立替代路径。

## 0. 当前检查点消费状态

| 检查点 | 生产者 | 期望分支 | 本树实测状态 |
| --- | --- | --- | --- |
| foundation | C0 | `codex/011-foundation-ready` | **已消费** publication `8844c475bc`（merge `84e5c668f0`） |
| harness-api | C0 | `codex/011-harness-api-ready` | **已消费** publication `d3f026904e`（merge `aab8c6c4a2`）；适配器/apply-chain 已改走真实类型（`4c7d749a69`） |
| profile-api | Z1 | `codex/011-profile-api-ready` | **已消费** publication `4943628f47`（merge `9048f7b79f`）；但包在本树不可导入 → 要求 `-r2`（§R-Q1-1） |
| chat-api | Z2 | `codex/011-chat-api-ready` | **已消费** r3 publication `3d8c3fa410`（merge `71f926683e`） |
| permissions-api | Q5 | `codex/011-permissions-api-ready` | 不存在（Q1 不依赖） |

本树不读他树未提交文件；每条消费前核 `status=READY`、`implementationSha` 为 publication 祖先、
`planAnchorRef` 可达 `96fef2db47`，再正常 merge（无 rebase/强推），消费后重装本地包并重测基线。
剩余真实缺口不再是「检查点未发布」，而是：profile-api 包在合并态不可导入（§R-Q1-1）、
原生装载运行时生产者与可导入的受控 L3 fixture（§R-Q1-3）、产品装配 §G1。

## 1. 请求给 C0

### G1 产品装配：`SkillsServerPlugin` 进入默认插件集
- 调用者：`plugins/assets/skills/src/ordessa_skills/plugin.py`。
- 现状：激活集硬编码在 `products/server/src/ordessa_server_product/composition.py:40-55`
  （`default_plugins()` 只返回 workspace/server-compat/acp-channel），`products/**` 归 C0 独占。
- 需要：把 `SkillsServerPlugin()` 纳入默认集（或发布一个插件贡献组在
  `bootstrap/runtime.py:514-527` 合并）；同时登记 compat `assets.*`（11 个方法，
  `core_wire.py:252-262`）的退役账，避免新旧双注册（G20 反例）。
- 失败反例：双注册时 `MethodRegistry.register` 必须 `DuplicateMethodError`；旧 `assets.publishSkill`
  历史 wire ID 在迁移期仍可读，不能被静默删除。
- 阻塞级别：阻塞 T15 产品装配；不阻塞开发。Q1 已可用 `build_runtime(data_root, server_plugins=(SkillsServerPlugin(),))`
  自证（`runtime.py:420-433`）。

### G2 Harness 配置适配点与装载观测（最硬依赖）
- 调用者：`plugins/assets/skills/src/ordessa_skills/harness_adapters/{pi,codex,claude}.py`。
- 现状：`harness.configuration-adapters` v1、`MountContent`/`RemoveOwnedContent`/`IntentSet`、
  `harness.configuration` 端口（inspect/plan/apply/query/reconcile）在代码中零符号，
  仅存在于 `docs/design/harness-v2/contracts.md:26-77`。本树唯一可用的是 pre-start
  `RuntimeSourceDeclaration`/`declare_source("skill-tree", …)`（`pacthold/…/runtime_composition/protocol.py:281-319`）
  与 `generic_cli.py:20-38` 的只读挂载，且其 `agent-box.skill@1` 生产者已随旧插件退役而断链
  （`docs/known-issues.md:27`）。
- 需要：C0 发布 (a) 适配器注册点与 `assess/compile/verify` 三段签名，(b) 受管目标句柄
  （按 `assetId/revision/treeDigest` + `runtimeGeneration/projectId/profileRevision/assignmentRevision` 绑定，
  不接受适配器给的绝对路径），(c) 撤销/reset/reload/resume 动作，(d) 独立 loaded 观测端口。
  Q1 不发明第二套名字，直接消费 harness-api 发布的类型。
- 失败反例：重叠 facet/harness/版本区间注册须拒绝；未批准 revision 在任何原生写入前类型化拒绝；
  只有目录摘要一致时状态必须是 projected 而非 loaded（G16）。
- 阻塞级别：阻塞 T08 的产品侧装载与 T11/T13/T14（G19 要求 L3）。Q1 独立推进部分：品牌格式模块、
  能力矩阵 unknown 登记、`observe_loaded_marker` 级别的离线证据反例。

### G5 serverScope / principal 语义（低紧急）
- 调用者：`assignments/`。现状：服务端无 principal 概念，鉴权=单数据根 bearer token
  （`runtime.py:458`），handler 只见 params（`server_plugin_api/contract.py:71`）。
- 需要：明确「serverScope = 该 Server 数据根实例身份」书面语义，或在 descriptor 上给类型化上下文。
- 失败反例：伪造/跨 Server `workspaceId` 必须拒绝而非解析成功（G07）。
- 独立路径：Q1 以 `workspace.records.get()` 存在性校验 + 本地 `server_scope` 列实现，等 C0 裁定后对齐。

### G7 统一 conformance fixtures（非阻塞）
- 需要：把 `apps/server/tests/fixtures/*acp_peer*` 类假对端与裸 host 组装 helper 发布为可导入包。
- 独立路径：Q1 自带 pytest fixture（`build_runtime(server_plugins=…)` + 合成数据根）。

## 2. 请求给 Z1（profile-api）

### G3 Profile `assets.skills` facet 与会话覆盖
- 调用者：`profile_contribution/`。
- 现状：Profile 是 server-compat 内部实现（`profiles/repository.py:19`），无公开 profile-api 包、
  无 facet 机制；`server_profile_assets(profile_id,asset_id,revision,enabled)`（`database.py:208-216`）
  是既有固定修订绑定；会话覆盖只有 send intent 的 `overrides` 合并（`sessions/service.py:93-97,142`）。
- 需要：公开 (a) `assets.skills` facet 读写，条目三态 `inherit | enable(revision) | disable`，
  按 `profileId + expectedVersion` CAS，(b) 解析期可读的会话 item 覆盖，
  (c) 修订身份三元组 `(profileId, configRevision, configObjectDigest)` 可进 Skills snapshot，
  (d) `server_profile_assets` → `enable(revision)` 的迁移契约（含双向校验样本）。
- 失败反例：CAS 过期、归档 Profile、未批准 revision 均类型化拒绝；迁移重跑不得双写（G08）；
  Profile 专用内容不得出现在公开选择列表（G09）。
- 阻塞级别：阻塞 T07 的产品接线与 T10。Q1 独立推进部分：本域分配表/解析器 + 迁移账的只读 dry-run 实现。

### G6 Profile 编辑器的 Skill 区插槽
- 需要：Z1 的 Profile editor 暴露 section 插槽（本树尚无 editor UI）。Settings sections 插槽已就绪
  （`WorkbenchComposition.addSettingsSection`，`contracts/workbench/src/workbench.ts:25-30,41`）。
- 独立路径：Q1 先把 Skill 选择区做成可独立挂载的组件 + 单测，等插槽到位再接。

## 3. 请求给 Z2（chat-api）

### G4 Chat `/` 与 `+` 贡献点
- 调用者：`frontend/` chat 菜单 glue。
- 现状：无 slash/attachment 贡献 registry（`plugins/commands` 是扩展宿主命令注册表，不是 Chat 菜单）；
  最接近的是 host 拥有的 `AgentOption` 菜单（`contracts/agent/src/agent.ts:68-74`）。无 `SkillChoice` 类型。
- 需要：接受 `SkillChoice{targetSession, assetId, revision, nativeName, description, origin, state,
  explicitInvocationSupported, invokeDescriptor?}` 的贡献点；数据源只能是当前已确认 snapshot。
- 失败反例：旧 `runtimeGeneration` 的异步响应不得更新新会话菜单（G17）；与系统斜杠命令重名须拒绝或命名空间化；
  选择菜单项绝不自动发送；无显式调用路由的品牌不得出现「调用」按钮。
- 阻塞级别：阻塞 T12 的 Chat 半边。Q1 独立推进部分：`invokeDescriptor`/browse-only 判定逻辑与类型，
  在 Skills 侧以纯函数 + 单测交付，明确不 import Chat 私有实现。

## 4. 请求给 Q5（已消费 **r1**，剩余为观察项）
Skills 装载不产生工具副作用；`allowed-tools` 不提升权限（spec 非目标）。Q5 的 permissions-api r3
实际消费的是 **r1 publication `bcd4387bec`**（随 harness-api 的 `dependsOn` 入树；早先记作 r3 属账目错误，已更正），已被本线消费为真实强制上界端口：`PolicyCeiling` 只减不增、无强制 ENABLE、
无 project/harness/revision 维度，`require-approval` 属执行期。观察项（不阻塞）：若将来需要「按项目/品牌
的强制安装政策层」，需 Q5 扩 ceiling 作用域或另立政策面；本线不自行发明第二套策略引擎。

## 5. 消费检查点后新增的请求（2026-09-28 晚）

### R-Q1-1 → **改派 C0**（Z1 已以 PARTIAL 关闭：`codex/011-z1-ready` = `29445bc50b`，其报告记 7/7 派工配额失败，不会再出 `-r2`）
- 事实：`plugins/profile/src/ordessa_profile/plugin.py:17` 仍写
  `from pacthold.resource_contracts import AgentBoxProfileV1`；foundation（`8844c475bc`）已把
  `pacthold.resource_contracts` 模块树搬空，符号现居
  `pacthold_runtime_compat.resource_contracts.agent_box_profile_v1`（本树实测 ImportError）。
- 影响：合并 profile-api 后 `import ordessa_profile` 在本树整体失败，`python -m pytest plugins/profile`
  同因红；Q1 已把 `assets.skills` facet 改为经 `ProfilePluginServices.register_v2_facet` 真实注册，
  其 6 条集成测试（`plugins/assets/skills/tests/test_profile_facet_contribution.py`）因此保持失败，
  **未 skip、未删断言**。纯映射测试绿。
- 请求：Z1 出一版把该导入改指搬迁后的公开位置（或由 C0 在 pacthold 恢复再导出），
  并在新树重发 `codex/011-profile-api-ready-r2`；Q1 按固定 publication SHA 消费后复跑这 6 条并回填 SHA。

### R-Q1-2 → Z2（chat-api 后续版）
- 需要：`ChatLocation`/快照里带 **已确认生效的 `runtimeGeneration`**（或等价的 generation guard 端口），
  否则 Skills 只能自带 `SkillsChatSnapshotPort` 抽象、由产品注入；
  现 Q1 侧的 generation/session/target 三重守卫与 18 条测试已就位（`desktop/src/chatContribution.ts`）。
- 另需：产品在构建期提供 `@extensions/ordessa.chat-api/contract.js` 的 import-map 条目
  （Q1 侧暂按 `plugins/chat/*/vitest.config.ts` 的 alias 形态自测，未深路径 import）。

### R-Q1-3 → C0
- `harness-api` 仍未发布（本树无 `codex/011-harness-api-ready`），T08 运行时/T11 落库/T13/T14（G19 L3）继续阻塞；
  请求里已明确 Q1 侧可 1:1 映射的意图词汇（`harness_adapters/intent.py`）。
- 新树 `apps/server` 套件与 `plugins/harness` 套件的完整数字须由 C0 在集成树复核（本树重装本地包后
  已能复现 foundation 记录里的 `42 failed / 1092 passed / 10 skipped / 25 errors`，见 `implementation-baseline.md` §3）。

## 6. R-Q1-4 → C0：缺一个可公开导入的技能交付接缝（L3 的唯一阻塞点）
- 调用者：`harness_adapters/producer.py`（已能产出合法 `agent-box.skill@1` 交付集）+ `harness_adapters/apply_chain.py`。
- 现状（本树实测）：`plugins/harness/api/src/ordessa_harness_api/__init__.py` 内 grep `skill` 零命中；
  唯一消费者是 harness 内部 `adapters/generic_cli.py:20-38`，providers 侧靠 `request.resolved_inputs` 内部交接
  （`claude/provider.py:51`）。插件不得导入宿主内部（AGENTS.md 规则 3），故 Q1 只能做到 L2。
- 需要：harness-api 公开发布「已解析技能输入」类型或注册口，使 Q1 交付集可被真实实例接收；
  同时给出 `harness.configuration` plan/apply 的一次提交接缝（Q1 已按现有类型写好 apply_chain）。
- 失败反例（Q1 侧已备）：未批准修订/摘要漂移/重名/超限时零交付且实例不写；只有原生装载观测才允许升 loaded。
- 影响：这条到位前 T14/G19 的 L3 与 `skills.discoverNative`/`invokeDescriptor` 的 supported 判定不能兑现。
