# 014 任务账（三包）

> 勾选规则：完成=实现+定向测试+证据落 report；依赖接缝的项勾选时注明"fixture 级/受控级"，生产级验收统一登记到 seams 回填后。详单与验收口径见 [dispatch/](dispatch/) 各简报。

## P-A — profile 解锁与产品就绪

- [x] PA-1 R0 基线冻结：环境安装（含 `-e plugins/profile`、`-e plugins/runtime-compat` 补录）、`pytest plugins/profile/tests -q` 计数（旧账 140）、TS 三包 tsc/vitest 计数、消费 SHA（foundation 经 main）
  - 140 口径经替身协议适配后全绿（首跑 3 红=合并线 C4 服务协议收紧 vs 检查点时代测试替身；`51c7905108` 适配、断言零改动）；最终 152（+PA-5 矩阵 12）。安装顺序坑（sandbox/permissions 先于 products/server）→ S-10 增补。npm 根 lock 缺 profile 三 workspace → 本地重算未提交 → S-02 增补。详见 reports/P-A-report.md §0/§2
- [x] PA-2 profile-api r2 交付：核对修复在位（plugin.py:19-21）；修 `specs/011-plugin-rollout/checkpoints/profile-api.json` 元数据（dependsOn=foundation 8844c475bc、planAnchorRef）；以提交 SHA 交付并在 011-z1 report 增补 r2 段（不动旧 ready ref 4943628f47）
  - 修复在位无需恢复；checkpoint 原位更新 version r2（implementationSha=e6f720d347…，planAnchorRef=codex/014-a-profile）；旧 ref 零移动；011-z1 report 增补「014 / profile-api r2」段
- [x] PA-3 四线解锁复验（scratch 组合树，不落本分支）：Q1 六测试 ID 绿（433 口径）；Q3 test_profile_facet_t10.py 28 条绿（671 口径）；Q4 461 保持 + facet 缺口登记；Q5 import 冒烟 + glue 缺口登记；每线记计数与漂移
  - Q1: 433 零漂移 + 6 ID 全绿（merge 1163f46d06）；Q3: t10 28 绿 + 整包 890（漂移 +219=consolidation 分支后续批次，零新增红；merge 7cc74652e3）；Q4: 518P/4F/2E + import 链通 + T08 缺口登记（漂移定性归 mcp 线；merge ef9e0204f0）；Q5: import OK + 634 passed，T06 缺口登记。scratch 树已删
- [x] PA-4 桌面三包产品就绪：`plugins/profile/{api,frontend,integrations/chat}` 补 manifest.json + build.mjs（对照 plugins/commands 形状）；本地构建演练过；启用耦合（chat-api）写回 S-01
  - 三包 manifest+build.mjs 补齐（api 双 entry 出 contract.js；frontend 补诚实 entry 桩）；ORDESSA_PRODUCT_OUTPUT_ROOT 演练三包均出 entry 产物（未触 products/）；依赖闭包已写回 S-01（e6f720d347）
- [x] PA-5 品牌矩阵受控版：pi/codex/claude-code × {字段投影, 覆盖/清除, reset, restart-resume}，真实 adapter 接口驱动；CLI 缺席品牌以受控 fake endpoint 为上限并如实登记；G18 浏览器几何 checklist 列出不勾（待装配）
  - 12 条全绿 + 三品牌金样钉定；经 PiProjection/harness_deployment/ClaudeProjection 真实品牌面只读驱动（非只调 ProfileDB）；F5 事实第一手（pi 0.86.1 在位但版本偏斜+拒收投影 flags；codex/claude 缺席）→ 真实 CLI 装载格三品牌 unknown；G18 checklist 见 report §6（887d0700df）
- [x] PA-6 报告与交付：`reports/P-A-report.md` + 011-z1 report 增补；终提交 SHA；PARTIAL 项逐条
  - report §8 PARTIAL P1-P9 逐条（真实 CLI 装载/G18/T08/T06/漂移账/wire 装配/admission/S-09/生产级复核）；实现终 SHA e6f720d347，交付=分支 tip
- [x] PA-7 退役准备（S-08③，只出裁定与清单不执行删除）：`agent-box.profile@1` 双声明仲裁裁定（谁唯一声明）；harness `generic/profile_*.py`、`harness-profile-store` entrypoint、`{claude,hermes,opencode}/profile*.py`、server-compat `server_profiles` 的逐文件退役清单+消费者核查；执行归集成波次（见 seams S-08）
  - 裁定=profile-api 唯一声明者（"先者赢后者 FAIL"加载顺序实证）；清单 R1-R10 含调用方/测试/迁移归属+执行顺序；R10 归 B 侧波次；S-08 已回填；specs/011-z1-profile/retirement-request.md

## P-B — model-provider 真实应用链

- [x] PB-1 R0 基线重建：合并基线全量复跑（旧口径 137 py + 10 desktop + 21 chat vitest + contracts tsc）；回填消费 SHA（foundation/chat-api 经 main）；安装命令冻结（含各子包 `-e`）；核实 S-11（wire invoke 现状）
  - R0=137/10/21/tsc 0（合并后动工前实测）；chat 旧 alias 问题在新基线消失（验证）；消费 SHA=内容引入提交 ancestry 实证（910457d04e/4bba5f1c71/ab9cb22bff/edca4049b1）；S-10 安装序列冻结（含顺序坑第一手复现）；S-11 核实=交付在 codex/013-b-server-runtime@742389c2e6（不在 main/本树），口径「接口与实现已交付、生产绑定在 INT-01」，已回填 S-02/S-11 注记
- [x] PB-2 C2 注册落地：adapters `types.py` ↔ harness-api `contracts.py` 类型对齐；`registration_manifest()` → `CONFIGURATION_POINT` 贡献；真实 registry 重叠拒绝复验（contributions.py:187-190）
  - bridge.py 薄桥（方向 adapters→harness-api 单向+边界测试钉住）+ 插件声明面（ContributionBatch, open_points, owner 宿主注入）；真实 HarnessContributionRegistry stage/commit 重叠拒/区间拒/不相交受，host 级 MP-11 见 PB-5；不动 products 组合（d1cc14ee60）
- [x] PB-3 C4 绑定与 submit permit：`HarnessConfigPort.apply/read_back` 绑 `ConfigurationApplicationService`（configuration_service.py:150）；一次性 permit 全流程；无 permit 裸 apply 必红；admission 未翻转前生产=诚实 refused/unknown（S-06）
  - harness_binding.py 全链 plan→apply(operation_key,permit)→verify→read-back；受控级：permit 全流程+重放回耐久结果/过期拒/跨会话隔离/unknown 阻塞；生产级：无 permit source 零效果诚实拒（S-06/P-E 前不报绿）——受控级/生产级分层陈述在 report §3（ca85ef584d）
- [x] PB-4 wire error families：13 码经 `wire.error-families` 贡献点自发布（server_plugin_api/contributions.py:74）；异族冲突反例；UNAVAILABLE 不冒充
  - REQ-Z3-7 清单逐字 13 码 plugin.py 自发布；激活后 family_for 全对；反例=异族冲突拒批且首 owner 存活/静态表矛盾拒/未知码仍 UNAVAILABLE；011 REQ-Z3-7 就此 CLOSED（ca85ef584d）
- [x] PB-5 三品牌 E2 受控矩阵：pi/codex/claude-code × MP-03/06/07/10/11 逐格证据（受控 fake endpoint；MP-06 真进程 restart-resume）；缺格=该品牌不 ready，整体 PARTIAL
  - 25/25 格全绿（test_e2_brand_matrix.py）：真实 build_runtime host+本包声明面+C4+FakeEndpoint 实收请求=下游实际路由证据；session/new 冒充必不确认；双会话交错；MP-10 哨兵零命中；host 级 MP-11。真实 CLI 装载格三品牌 unknown（如实）→整体口径=受控级全绿、生产装配格 PARTIAL（b37e846fdb）
- [x] PB-6 Profile glue：消费 P-A 的 r2 SHA；`EffectiveChoiceResolver`/视图端口接真实 ProfileContributions；A 未交付前 fixture 先行 + 登记依赖（不碰 plugins/profile）
  - P-A 已交付（r2 implementationSha e6f720d347）→按 012 合并式消费：merge codex/014-a-profile（fcf588b3d4）；profile_glue.py 经真实 FacetRegistry.register(v2=True, owner 注入) 注册（REQ-Z3-3 CLOSED）；8 门含第二 owner FACET_ID_CONFLICT 拒；plugins/profile 零改动（79f4bdf391）
- [x] PB-7 退役准备与金样（S-08①②，只出清单与顺序不执行删除）：adapters common.py golden 渲染 conformance 钉住（承接 S-08②）；server-compat `model_configs` writer（core_wire.py:238-276）逐行退役清单+消费者核查+"先退再装"顺序确认写回 S-08①；执行归集成波次
  - retirement-request.md：W1-W15 逐行（行号=现行树实测，派单旧行号漂移已声明）+消费者核查（装配注入/边界断言/回归四件/W5 跨域引用）+顺序确认；金样一致性 +5 门扩到注册路径（DIALECTS≡harness 家族表、native target≡harness pins）；S-08 已回填；不动 server-compat/harness 源文件（4db11759c6）
- [x] PB-8 报告与交付：`reports/P-B-report.md` + 011-z3 report 增补；终提交 SHA；PARTIAL 项逐条
  - report §9 PARTIAL 逐条（生产 admission S-06/P-E/E3 真实模型/产品装配/IR 窗口）；197 passed 终账；交付=本分支 tip SHA（本提交）

## P-C — chat 真实接缝

- [ ] PC-1 R0 基线冻结：chat/agent/connectors 各套件计数（chat-api 22 it、frontend 35、connectors 受控套件）；环境冻结；确认 F8（C7 切换已在 main）
- [ ] PC-2 命令目录接通：connectors `NativeCommandReader`（commands.ts:8-25、client.ts:183-195）→ agent contracts facade 增目录成员 → sessions 供给 → chat `facadeCommandCatalog` 四态（adapters/agent.ts:150-155 恒 absent 处）；反例：stale-session/channel-down/unobservable；Claude=诚实 absent（S-07）
- [ ] PC-3 附件接通（plugin 半边）：add-content 激活由 capability.supported 驱动（chat-page.tsx:202-220）；prepare→ref→submit refs（submission.ts attachments+sha256）；release/幂等/四态 phase；生产 owner 缺席=诚实禁用 + S-05
- [ ] PC-4 三态 submit：`agent.ts:118` send 升级三态（兼容迁移记录）；sessions model.ts:115-146 映射；acp-next-submit 接 authorize + BackendAdmissionState 缺席时诚实 refused/unknown；unknown 保 requestId 不重发反例
- [ ] PC-5 runtimeGeneration 透出：受控链 generation fence（acp-next-submit.ts:37,115-119）回灌 chat DTO（ChatLocation/快照）；chat-api 修订按 -r4 规则带兼容说明；Q1 消费面（SkillsChatSnapshotPort）不在 main，只登记接口形状
- [ ] PC-6 旧链退役（plugin 半边）：`plugins/agent/conversation/{view,interaction-card,styles,entry}.tsx` 退役（语义已迁 chat approval-panel）；对 `apps/desktop/renderer/agent-conversation.test.tsx` 逐条核对等价覆盖后在 S-01 确认可删（删除本身归 core）；启停与锁 → S-01/S-02
- [ ] PC-7 R-Z2-5 reasoning 状态升级（时间盒内做，非阻塞；picker=R-Z2-6 归 S-05 同族接缝不扩本包）
- [ ] PC-8 报告与交付：`reports/P-C-report.md` + 011-z2 report 增补；终提交 SHA；PARTIAL 项逐条
- [ ] PC-9 DTO 对齐核实（S-05 回执修正）：connectors 侧 `AcpPreparedAttachment` **已含** `preparedId`（`plugins/connectors/acp/src/attachments.ts:10-12`，注释明言 Server ACP DTO 未携带）——核实该形状并作为对接基准写回 S-05；缺的字段在 **Server ACP DTO（core 侧补）**，本包**不改 connectors**
- [ ] PC-10 claude 命令探针（S-07 命令项）：受控驱动 `plugins/harness/packaging/claude` 钉版 adapter（fake Anthropic endpoint，沿用该目录既有探针架式；不改 plugins/harness 任何跟踪文件），实测是否播发 `available_commands_update`：播发→经 NativeCommandReader 接线并记第一手证据；不播发→诚实 absent+原因写回 S-07

## P-D — claude 附件通路（harness）

- [ ] PD-1 R0 基线冻结：plugins/harness 既有套件计数（含 tests/test_capability_declarations.py）；环境（packaging/claude `npm ci` 已装闭包核对 0.81.2）
- [ ] PD-2 重探针（第一手，推翻或确认旧负证据）：受控拉起钉版 adapter（fake Anthropic endpoint 架式，零真实模型/凭据），转录 initialize 的 `agentCapabilities.promptCapabilities`（源码预期 image:true+embeddedContext:true，`acp-agent.js:1108`）；实测 image 块端到端往返（prompt→adapter→fake 端点收到 base64 图）与 resource_link 下发语义；给旧负证据定来历结论（0.77 时代遗留 vs 读取位置错误）
- [ ] PD-3 能力翻绿：`harnesses.toml` claude-code 行恢复 `attach`（附新证据注释与旧证据推翻说明）；`tests/test_capability_declarations.py` FAMILY_MATRIX 同步；`docs/server-round1/fullstack/claude-production-packaging.md` 证据更新
- [ ] PD-4 通路接线：claude 家族通道接受附件投递——从 connectors 附件 DTO 形状（对齐 P-C PC-9 冻结件）到 session/prompt 的 image 块 / resource_link；语义如实分层：图片=真实附件块、非图片文件=URI 链接、audio 未声明不宣称；受控往返测试（内容哈希一致）
- [ ] PD-5 报告与交付：`reports/P-D-report.md`（探针转录与哈希、旧证据来历结论、能力变更 diff、语义分层表）；终提交 SHA；S-07 状态回填
