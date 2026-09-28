# Q1 Skills v2 阶段报告

状态：**REVIEW_READY（本线已交付范围）/ 整线 PARTIAL**。未合并 main、未 push、
**未发布 `codex/011-q1-ready`**：G19 的 L3 生产装载链与 §G1 产品装配仍未闭环（见 §5）。
日期 2026-09-28。分工：主代理派单包子代理实现/改测试，自己审差分、跑门、写文档、管 git。

## 1. 提交账（本树真实 SHA）

| 提交 | 内容 |
| --- | --- |
| `96fef2db47` | 起点（= `refs/heads/codex/011-plugin-plan`，设计快照父提交 `cd7d31f3cf`） |
| `df915f222b` | 域包落地：`api/`、`formats/`、`library/`、`assignments/`、`harness_adapters/`、`native_discovery/`、`service/wire/plugin`、`desktop/`、`contracts/` + Phase 0 文档 |
| `6923c0e0e8` | G08 迁移器、Profile 桌面区、4 处守卫补强、品牌受控探针结果 |
| `6df28d0022` | 任务裁定与报告、基线数字修正、上游缺陷入请求账 |
| `8cfc293a00` | 第二轮审阅 7 项发现闭环（replay/rollback 类型化拒绝、桌面守卫与断言修正） |
| `84e5c668f0` | merge 消费 foundation `8844c475bc`（impl `8229e20824`） |
| `9048f7b79f` | merge 消费 profile-api `4943628f47`（impl `f5435be938`） |
| `71f926683e` | merge 消费 chat-api-r3 `3d8c3fa410`（impl `a3ec20c046`） |
| `45221aa246` | 消费 foundation：搬迁符号重指、改用发布版贡献/拒绝面、`profile_contribution/` 经真实 `register_v2_facet` 注册 `assets.skills` |
| `54763b34e6` | Chat `/`、`+` 贡献经 `createChatContributions()` 真实注册（G17 反例 18 例）+ 合并后基线复算 |
| `5aeea4f0cb` | 包隔离 G21 半边：测试 helper 的 `sys.path` 兜底改为仅在模块不可导入时生效，隔离 venv 装 wheel 跑通 |
| `592f01b328`/`7ad8864b92` | 报告 SHA 账更正；受影响套件逐 ID/原因 diff（G22 半边）；隔离与 diff 的命令日志/JUnit 哈希入树到 `specs/011-q1-skills/evidence/` |
| `ddc8f17e71` | resume/plan 失败关闭修正 + 本报告账目刷新（该提交正文提到账目刷新，实际账目由本笔补齐） |
| `1580159638`/`6a6a2ec1e1` | T16 最小数据恢复演示：`migration/restore.py`（快照含 sha256 清单与每修订树摘要、9 个类型化拒绝）+ 12 条测试（热 WAL 拒收、备份字节损坏可检、恢复幂等、G08 计划摘要逐字复现；两处守卫各以 /tmp 变异证明会红） |
| `e3358c0790` | Chat 快照改由真实 `skills.resolve`/`previewEffective` 载荷驱动（真实 generation 守卫）+ 本包独立 tsconfig/build 门 |
| `aab8c6c4a2` | merge 消费 harness-api `d3f026904e`（impl `61966e3118`，`dependsOn` 含 permissions-api `bcd4387bec`） |
| `4c7d749a69` | 品牌 adapter 与 apply-chain 走真实 harness-api：删私有意图词汇与 bool 形能力端口，注册进 `harness.configuration-adapters`，+44 测试 |

旧实现来源 `752f148b1b`（`ordessa_assets 2.0.0a1`：`src/` 23 个 `.py`、13 测试文件 69 测试函数、0 skip，从未注册进 Server）。
`git diff 752f148b1b HEAD -- plugins/server-compat/.../assets/ core_wire.py plugin.py profiles/clone.py packages/.../agent_skill_v1.py apps/server/tests/test_asset_hubs.py` = 空。

## 2. 门账（每条命令真实退出码；均为合并四个检查点并重装全部本地包之后，最新复测在 `ddc8f17e71` 之后）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `.venv/bin/python -m pytest plugins/assets/skills/tests -q` | **1** | `427 passed, 6 errors in 4.12s`（6 条为 profile-api 上游缺口的集成钉，未 skip、未删断言；逐 ID 与隔离运行一致） |
| `cd plugins/assets/skills/desktop && npx vitest run --maxWorkers=1` | **0** | `Test Files 10 passed (10)` / `Tests 125 passed (125)` |
| 本包独立前端门（G21 前端半边） | **0** | `npx tsc --noEmit -p plugins/assets/skills/desktop` 与 `-p …/contracts` 各 exit 0（自查出并修掉 fakes/entry/chat 测试里 4 处既有类型错）；`node build.mjs` exit 0，产物落 `products/desktop/dist/extensions/ordessa.skills/`（已被 `.gitignore` 的 `dist/` 忽略，不入 git） |
| `cd apps/desktop && npx tsc --noEmit` | **2** | 9 个 `error TS`：5 在 `plugins/chat/**`、4 在 examples；**Q1 路径零诊断** |
| `npm test`（根，`npm ci` 后） | **≠0** | `18/29 suites green`；红项 `typecheck`、`build:*`、`workspace:plugins/chat/frontend`、`node-test:products/desktop`、6×`electron:*` → 离线依赖/无显示环境，非本线 |
| `.venv/bin/python -m pytest packages/pacthold -q` | 0 | `212 passed`（= foundation 记录） |
| `.venv/bin/python -m pytest plugins/harness -q` | 1 | `2 failed, 433 passed, 3 skipped, 37 subtests`（2 项为 foundation 登记的继承红；通过数增长来自合并进本树的 harness-api 新测） |
| `.venv/bin/python -m pytest apps/server -q --tb=no` | 1 | `42 failed, 1116 passed, 10 skipped, 25 errors`；67 条红 ID/类型/原因类与 foundation 钉住的 JUnit 逐条一致（`research/suite-id-diff.md`），`1092→1116` 是合并进本树的 Z1/Z2/Q5 新测试所致，不是红转绿 |
| 隔离安装 G21 | — | 本地 wheel 仓 → 全新 venv `--no-index` 安装 → `pip check` 绿 → `import ordessa_skills` 落在 site-packages → `329 passed + 同 6 红`；日志/sha256 在 `/tmp/q1-evidence/` |
| 逐 ID/原因 diff（G22） | — | `research/suite-id-diff.md`：apps/server 67 条红与 foundation 钉住 JUnit（sha256 `92ef3914…`）逐条一致，new/gone 均空；harness 同 2 条；Q1 同 6 条；通过数增长 +24/+67/+44 来自合并进本树的新包与新测，不是红转绿 |
| JUnit（树外） | — | `/home/maoqh/ordessa-builds/q1-skills-evidence/skills-{pytest,vitest}-6df28d00.xml` |

环境坑（已写进 `implementation-baseline.md` §3）：本地包必须同一条 pip 命令装齐，否则依赖解析失败会留下
`apps/server 78/87/95 errors` 的假账；首轮该数字已标作废。
假绿审计：0 skip/0 xfail/0 `assert True`；关键守卫逐个 /tmp 变异验证（digest→loaded 9 红、绝对路径 4 红、
replay/rollback 5 红、generation/session/target 各 1–2 红、apply-chain 拒绝路径逐项红）；能力引用守卫要求
被引 `file:line` 真实存在且该行含所引 token。

## 3. 真实 API 接线现状

- Server：`skills.*` 19 方法经 `server_plugin_api` 发布面注册；测试驱动真实 `build_runtime(server_plugins=(Workspace, Skills))` + 真 wire dispatch；旧 `assets.*` 未动且族不相交由测试钉住。
- Foundation 贡献面：`ContributionBatch` + `wire.error-families`，取代此前用 `WireError.__cause__` 夹带本域错误码的临时手法。
- **Harness**：三品牌为真实 `ConfigurationAdapter`（`assess→Assessment`、`compile→IntentSet(MountContent/RemoveOwnedContent)`——本域只声明内容目录类意图，不产 `SetField` 携 `ContentRef{assetId@revision, sha256, 真实 size}`、`verify→Verification/VerificationUnknown`），经 `harness.configuration-adapters` 贡献点注册并由 `server_plugin_api.stage_contributions` + harness 真实 `HarnessContributionRegistry` 验证拒绝（重复 id / 重叠 facet-入口-版本区间；未绑定点时宿主 `ContributionPointUnboundError` fail-closed）；`apply_chain.py` 用发布的 `Plan/ApplicationResult/ReconfigurationDecision/ResumeRequest` 实现「先应用再发送」语义。Q1 私有意图词汇已删除（避免第二份词汇）。
- Profile：`assets.skills` facet 经真实 `ProfilePluginServices.register_v2_facet(owner)` 注册，`assignments` 的 Profile 层由真实端口满足。
- Permissions（Q5 permissions-api **r1 `bcd4387bec`**，随 harness-api 的 `dependsOn` 进入本树）：`mandatory_policy.PermissionsCeilingMandatoryPolicyPort`
  读真实 `ordessa_permissions_api.PolicyCeiling`（`ceilings.py:156`、`CeilingEntry.matches:135`、`intersect_ceilings:293`、
  `TOOL_EXPOSURE["skill"]=EXEC:78`）。**如实边界**：发布的 ceiling 是**只减不增的禁用/需批面**，
  没有强制 ENABLE、没有 project/harness/revision 维度，`require-approval` 属执行期，只作为诊断透出；
  端口缺席走 `NotConfiguredMandatoryPolicyPort` 的类型化可见态而非「全允许」。产品装配需把
  `permissions.authorizer@1` 传入 `SkillsServerPlugin(permissions=…)`（宿主只按声明 `requires` 授端口），
  因此端到端宿主例尚未存在，已登记。
- **自我更正（重要）**：本报告先前把该消费写成 permissions-api r3 `6ac8f54a14`，实测不符：
  `git merge-base --is-ancestor` 显示 r2 `de09f3f12b`、r3 `6ac8f54a14`、r4 `ad8902d5c8` 均**不是** HEAD 祖先，
  树内实际是 r1 内容（`plugins/permissions/api/…` 与 r3 有差异）。当前绑定符号在 r1 里存在且测试通过。
- **r4 消费尝试已回退**：把 publication `ad8902d5c8` 正常 merge 进本树的结果**删除了 55 个上游文件**，
  含 Z1 已交付的 `plugins/profile/**`（`pyproject.toml`、`src/ordessa_profile/*`、`api/*`）与
  `evidence/platform-bindings.md`。这属于共同 plan 禁止的「挑一边整文件覆盖」，故本线立即
  `git reset --hard` 回到合并前的 `e3358c0790`（合并结果保留在本地分支 `q1-abandoned-permissions-r4-merge` 供复核），
  复位后 profile 包在位、门数不变（393 + 同 6 红、桌面 125）。请求见 `integration-request.md` §7。
- Chat：`createChatContributions()`/`ChatInputSource` 公共注册点贡献行，仅用 `@extensions/ordessa.chat-api/contract.js` 类型；
  快照侧已改由真实 `skills.resolve` 载荷驱动（含 `runtimeGeneration`），缺 generation 记 unknown。
- **交付生产者（T14 的关键缺口）**：`harness_adapters/producer.py` 用真实事实构造 `AgentSkillV1`
  （`agent-box.skill@1`，来自 `pacthold_runtime_compat.resource_contracts.agent_skill_v1:14`，实测
  `pacthold.resource_contracts.agent_skill_v1` 已 ModuleNotFoundError），经发布的
  `assemble_runtime_composition` + `RuntimeCompositionCoordinator.preflight/start/projection_receipt` +
  `FakeHost/FakeSandbox` 跑通 dispatch→preflight→start→receipt：每棵树只读落在声明的 guest 槽且内容摘要一致，
  回执 `status == "PROJECTED"`，`attest(LOADED, projection_digest)` 仍为 `unknown`（G16 钉住）。
  证据级别 **L2**；17 条守卫里 16 条以 /tmp 变异证明会红，唯一无红的 manifest 存在性守卫被上游校验遮蔽，如实登记。
- 边界：`test_dependency_direction.py` 的 `ALLOWED_ROOTS`/`PLATFORM_MODULE_GRANTS` 为模块精确白名单，
  新增 `ordessa_harness_api` 有明确理由（独立发布 API 包，不引 harness 内部），未整体放宽。

## 4. 逐模块复用裁定与 FR/G 覆盖

见 `specs/011-q1-skills/tasks.md`（T00–T17 逐项带 SHA、文件、命令与缺失半边）与
`research/legacy-inventory.md`；删除账：旧 `USED=UNKNOWN` 别名、`verify_load` 摘要即 loaded、
`harness_delivery` 第二应用器、`capabilities.py` 空品牌表、bool 形 `HarnessCapability` 端口 —— 均未保留，
`harness_adapters/capabilities.py` 为 Skills 域唯一能力表且由测试守。

## 5. 阻塞（有名有姓，非本线可解）

1. **profile-api 在合并态不可导入**：`ordessa_profile/plugin.py:17` 仍从 foundation 已搬空的
   `pacthold.resource_contracts` 取 `AgentBoxProfileV1`（符号现居 `pacthold_runtime_compat.…`）；
   `pytest plugins/profile` 同因红。→ 请求 Z1 出 `-r2`（`api-requests.md` §R-Q1-1），Q1 的 6 条钉保持红等复跑。
2. **原生装载无运行时生产者**：harness-api 只发布 DTO；本树不存在原生发现/reload/loaded 观测的实现，
   且受控 L3 对端 fixture 在 `plugins/harness/tests` 不可导入 → T14/G19（L3）与
   `skills.discoverNative`/`invokeDescriptor` 的 supported 判定继续不能兑现。
3. **产品装配（§G1）**：`products/server` 默认插件集与 `products/desktop` 扩展清单/import-map 归 C0；
   裸 `build_runtime` 不能在激活前绑贡献点，故本线用显式插件序列自证，未冒充产品级。
4. Chat 的「确认生效快照 `runtimeGeneration`」端口与显式调用路由缺（§R-Q1-2）→ US6「调用」不假绿。
5. 环境：Codex 0.147.0 / Pi 0.84.2 原生二进制不在本机；根 npm 离线装不齐 Z2 chat 新依赖。
6. **Z1 已以 PARTIAL 关闭**（`codex/011-z1-ready` = `29445bc50b`，其报告记「7/7 派工配额失败」），
   故 §R-Q1-1 的 profile-api `-r2` 不会由 Z1 交付：请求转 C0（foundation 搬空 `pacthold.resource_contracts`
   的收口方），一行改指 `pacthold_runtime_compat.resource_contracts.agent_box_profile_v1` 或在 pacthold 恢复再导出；
   在此之前本线 6 条 facet 集成钉保持红（不 skip、不私自 shim 他包）。

## 6. 未测清单（不冒称）

三品牌生产通路 `loaded`/`used` 与 pin 版本运行时行为；Profile 会话覆盖生效时机的产品半边与真实用户数据迁移（合成根的备份/恢复演示已交付，见 §2 与 tasks T16；真根迁移需用户确认与备份策略）；
Chat 端到端真实菜单与跨会话隔离运行时；G18 的真实「先应用再发送」执行腿；G19（L3）；
electron smoke 与 UI 全链；L4 真实模型（未授权，一次未发）。

## 7. 审阅记录

三轮独立审阅（第一轮 3 MAJOR + 6 MINOR、第二轮 2 MAJOR + 5 MINOR、第三轮 1 MAJOR 文档陈旧 + 4 MINOR）全部处置并附变异验证；第三轮另把 `apply_chain` 的 resume 失败开放与 `plan` 参数无类型校验改为「仅发布的 `RuntimeConfirmed` 计 applied」与 `HARNESS_APPLY_PLAN_REQUIRED`（+8 测试）；
`4c7d749a69` 与隔离改动之后建议再做一轮针对性复核（重点：harness-api 适配器的拒绝路径是否只在测试内成立、
`apply_chain` 与宿主装配的接缝、6 条红转绿后的 facet 断言）。

## 8. 下一步（按检查点协议）

Z1 发布 profile-api `-r2` → 本线固定 publication SHA merge → 复跑 6 条钉并回填 SHA；
C0 提供可导入的受控 L3 对端与产品装配后 → 跑 T14/G19 与 T15 →
T16 剩余半（`apps/server` 逐 ID diff、electron smoke、数据恢复演示）→ 之后才发布 `codex/011-q1-ready`。


补充核查（非对称探针，防止把可做的事误记为阻塞）：曾假设「6 条红里至少 `ordessa_profile.contracts` 层可用」，实测 `import ordessa_profile.contracts` 同样抛 `AgentBoxProfileV1` ImportError（包 `__init__` 再导出 plugin），故这 6 条红本线无法减少，只能等上游一行改指搬迁后的位置。
新增接缝请求（符号级，交 C0）：harness-api 目前不导出任何技能类型（`plugins/harness/api/src/ordessa_harness_api/__init__.py` 内 grep "skill" 为空），唯一消费者是 harness 内部 `adapters/generic_cli.py:20-38` 与 providers 的 `request.resolved_inputs`；因此 Q1 的 L2 交付集无法交给真实运行实例，G19 的 L3 不能由 Q1 单侧闭环。
