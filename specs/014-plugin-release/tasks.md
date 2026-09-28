# 014 任务账（三包）

> 勾选规则：完成=实现+定向测试+证据落 report；依赖接缝的项勾选时注明"fixture 级/受控级"，生产级验收统一登记到 seams 回填后。详单与验收口径见 [dispatch/](dispatch/) 各简报。

## P-A — profile 解锁与产品就绪

- [ ] PA-1 R0 基线冻结：环境安装（含 `-e plugins/profile`、`-e plugins/runtime-compat` 补录）、`pytest plugins/profile/tests -q` 计数（旧账 140）、TS 三包 tsc/vitest 计数、消费 SHA（foundation 经 main）
- [ ] PA-2 profile-api r2 交付：核对修复在位（plugin.py:19-21）；修 `specs/011-plugin-rollout/checkpoints/profile-api.json` 元数据（dependsOn=foundation 8844c475bc、planAnchorRef）；以提交 SHA 交付并在 011-z1 report 增补 r2 段（不动旧 ready ref 4943628f47）
- [ ] PA-3 四线解锁复验（scratch 组合树，不落本分支）：Q1 六测试 ID 绿（433 口径）；Q3 test_profile_facet_t10.py 28 条绿（671 口径）；Q4 461 保持 + facet 缺口登记；Q5 import 冒烟 + glue 缺口登记；每线记计数与漂移
- [ ] PA-4 桌面三包产品就绪：`plugins/profile/{api,frontend,integrations/chat}` 补 manifest.json + build.mjs（对照 plugins/commands 形状）；本地构建演练过；启用耦合（chat-api）写回 S-01
- [ ] PA-5 品牌矩阵受控版：pi/codex/claude-code × {字段投影, 覆盖/清除, reset, restart-resume}，真实 adapter 接口驱动；CLI 缺席品牌以受控 fake endpoint 为上限并如实登记；G18 浏览器几何 checklist 列出不勾（待装配）
- [ ] PA-6 报告与交付：`reports/P-A-report.md` + 011-z1 report 增补；终提交 SHA；PARTIAL 项逐条
- [ ] PA-7 退役准备（S-08③，只出裁定与清单不执行删除）：`agent-box.profile@1` 双声明仲裁裁定（谁唯一声明）；harness `generic/profile_*.py`、`harness-profile-store` entrypoint、`{claude,hermes,opencode}/profile*.py`、server-compat `server_profiles` 的逐文件退役清单+消费者核查；执行归集成波次（见 seams S-08）

## P-B — model-provider 真实应用链

- [ ] PB-1 R0 基线重建：合并基线全量复跑（旧口径 137 py + 10 desktop + 21 chat vitest + contracts tsc）；回填消费 SHA（foundation/chat-api 经 main）；安装命令冻结（含各子包 `-e`）；核实 S-11（wire invoke 现状）
- [ ] PB-2 C2 注册落地：adapters `types.py` ↔ harness-api `contracts.py` 类型对齐；`registration_manifest()` → `CONFIGURATION_POINT` 贡献；真实 registry 重叠拒绝复验（contributions.py:187-190）
- [ ] PB-3 C4 绑定与 submit permit：`HarnessConfigPort.apply/read_back` 绑 `ConfigurationApplicationService`（configuration_service.py:150）；一次性 permit 全流程；无 permit 裸 apply 必红；admission 未翻转前生产=诚实 refused/unknown（S-06）
- [ ] PB-4 wire error families：13 码经 `wire.error-families` 贡献点自发布（server_plugin_api/contributions.py:74）；异族冲突反例；UNAVAILABLE 不冒充
- [ ] PB-5 三品牌 E2 受控矩阵：pi/codex/claude-code × MP-03/06/07/10/11 逐格证据（受控 fake endpoint；MP-06 真进程 restart-resume）；缺格=该品牌不 ready，整体 PARTIAL
- [ ] PB-6 Profile glue：消费 P-A 的 r2 SHA；`EffectiveChoiceResolver`/视图端口接真实 ProfileContributions；A 未交付前 fixture 先行 + 登记依赖（不碰 plugins/profile）
- [ ] PB-7 退役准备与金样（S-08①②，只出清单与顺序不执行删除）：adapters common.py golden 渲染 conformance 钉住（承接 S-08②）；server-compat `model_configs` writer（core_wire.py:238-276）逐行退役清单+消费者核查+"先退再装"顺序确认写回 S-08①；执行归集成波次
- [ ] PB-8 报告与交付：`reports/P-B-report.md` + 011-z3 report 增补；终提交 SHA；PARTIAL 项逐条

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

- [x] PD-1 R0 基线冻结：plugins/harness 既有套件计数（含 tests/test_capability_declarations.py）；环境（packaging/claude `npm ci` 已装闭包核对 0.81.2）
  - 完成：改动前 2 failed（继承红同 ID）/456 passed/3 skipped；环境命令与 products/server 依赖链补录见 report §1；npm 闭包 0.81.2 核对
- [x] PD-2 重探针（第一手，推翻或确认旧负证据）：受控拉起钉版 adapter（fake Anthropic endpoint 架式，零真实模型/凭据），转录 initialize 的 `agentCapabilities.promptCapabilities`（源码预期 image:true+embeddedContext:true，`acp-agent.js:1108`）；实测 image 块端到端往返（prompt→adapter→fake 端点收到 base64 图）与 resource_link 下发语义；给旧负证据定来历结论（0.77 时代遗留 vs 读取位置错误）
  - 完成（受控级）：`packaging/claude/attachment-probe.mjs` GREEN；握手实测 `promptCapabilities {image:true,embeddedContext:true}`；image 往返 sha256 一致；resource_link=https 原文/file:// markdown 链接；audio 静默丢弃（探针钉死）；旧负证据=0.77 时代观测+升版未重探（连根说明 report §2）；转录+哈希 `reports/P-D-probe-transcript.json`
- [x] PD-3 能力翻绿：`harnesses.toml` claude-code 行恢复 `attach`（附新证据注释与旧证据推翻说明）；`tests/test_capability_declarations.py` FAMILY_MATRIX 同步；`docs/server-round1/fullstack/claude-production-packaging.md` 证据更新
  - 完成：四投影相等（toml/JS 投影/派生 claims/FAMILY_MATRIX）；文档新建入库（历史 §1–7 恢复+§8 证据段）；`test_claude_production_template.py` 派生 golden 一字同步（写入面注记 report §3/§8）
- [x] PD-4 通路接线：claude 家族通道接受附件投递——从 connectors 附件 DTO 形状（对齐 P-C PC-9 冻结件）到 session/prompt 的 image 块 / resource_link；语义如实分层：图片=真实附件块、非图片文件=URI 链接、audio 未声明不宣称；受控往返测试（内容哈希一致）
  - 完成（受控级）：`claude/attachments.py` 组装+校验+五类类型化拒绝；测试 6 条（§8）；端到端哈希一致由 PD-2 探针承载；prepare 存储语义未做（归 P-C/S-05）
- [x] PD-5 报告与交付：`reports/P-D-report.md`（探针转录与哈希、旧证据来历结论、能力变更 diff、语义分层表）；终提交 SHA；S-07 状态回填
  - 完成：report 落盘；S-07 行已回填 P-D 完成态；交付 SHA=本分支头提交（不 push 不外并）
