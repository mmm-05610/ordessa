# P-C 简报 — chat 真实接缝（命令目录 / 附件 / 三态提交）

**工作目录**: `worktrees/014-c-chat`（分支 `codex/014-c-chat` = main 491aa92392，chat 已在 main，无合并步骤）

**必读输入**（按序）: 本目录 [spec.md](../spec.md)（US3/US4/US5）、[plan.md](../plan.md)（事实 F3/F4/F8、纪律）、[seams.md](../seams.md)、`specs/011-z2-chat/report.md` + `api-requests.md`（R-Z2 原文）+ `integration-request.md`（§1/§4 退役清单）、`docs/baseline.md`、根 `AGENTS.md`。

**目标一句话**: 把"两端已备、断点在中间"的三条链接通——品牌原生命令目录（R-Z2-3）、附件 refs 通道（R-Z2-2 plugin 半边）、提交三态（R-Z2-1）——并把旧 agent-conversation 链退役（plugin 半边），生产接缝缺席处一律诚实缺席。

**首要认知（F3）——断点的精确位置**：
- connectors 侧（已实现有测试，只读消费）：三态 `plugins/connectors/acp/src/submission.ts:13-26`、`client.ts:657`；附件 `attachments.ts:35-41`（prepare→sha256 ref）、`client.ts:608-645`；命令 `commands.ts:8-25`（四态目录）、`client.ts:183-195`（getNativeCommands，**全仓零消费**）、`client.ts:431`；`plugins/connectors/ordessa/src/acp-next-submit.ts:92-141`（wire `acp.submission.authorize`，头注 :3-8 自述缺 backend owner）。
- server 侧（已在 main，只读）：`plugins/harness/src/ordessa_harness/server_acp/plugin.py:201-227`（acp_submission_authorize）、`apps/server/src/ordessa_server/acp_admission.py`。
- **中间层（本包的战场）**：`plugins/agent/contracts/src/agent.ts:118`（`send(): Promise<void>` 需升三态）+ 目录成员；`plugins/agent/sessions/src/model.ts:115-146`（facade 供给）；`plugins/chat/frontend/src/adapters/agent.ts:126-141/150-155`（映射，现 command 恒 absent）；`chat-page.tsx:202-220`（附件入口现因 supported=false 禁用）。
- F4（2026-09-28 二次修正，拆开两件事）：Claude **有** ACP 桥——钉版官方 `@agentclientprotocol/claude-agent-acp@0.81.2`（`plugins/harness/packaging/claude/`，自带 fake-endpoint 受控探针架式），不走 Go 桥。**命令目录＝未探针（不是 unsupported）**：`parseNativeCommands` 品牌无关，adapter 是否播发 `available_commands_update` 无正反证据 → PC-10 探针定夺。**附件＝负证据**：`harnesses.toml:86-89` 诚实移除 `attach`（真实握手 promptCapabilities 空）→ 诚实缺席，翻绿归 harness 线（S-07 附件项）。
- F8：integration-request §6 的 C7 import map 切换**已在 main**，勿重做。

## 写入面（只许这些）

`plugins/chat/**`；`plugins/agent/{contracts,sessions,conversation}/**`；`specs/011-z2-chat/**`（报告增补）；`specs/014-plugin-release/**`（勾选 PC-*、写 `reports/P-C-report.md`、更新 S-01/S-02/S-05/S-07 状态）。

**禁区**: `plugins/connectors/**` 与 `plugins/harness/**`（只读消费——发现 port 缺口 → seams 增条，不改它们；**唯一例外**：PC-9 的 DTO 冻结窄口，只许改 `plugins/connectors/acp` 附件 DTO 本体与其定向测试）；`plugins/commands/**`（它是扩展宿主命令注册表，**不是** Chat 菜单，Q1 api-requests.md:88 已明确）；products/、tooling/、apps/、根锁、兄弟树。`plugins/agent/{connections}` 不动。

## 任务（详账 tasks.md PC-1..PC-8）

### PC-2 命令目录接通（R-Z2-3）
链路：connectors `NativeCommandReader`/`getNativeCommands` → agent contracts 增命令目录成员（四态 DTO，缺席有类型）→ sessions facade 供给 → chat `facadeCommandCatalog` 从恒 absent 变真实四态。反例必测：stale-session、channel-down、unobservable（connectors 已有，穿过中间层仍要红）；目录缺席显示"无命令+原因"，**无伪命令**。brands：Go 桥 server.go:327-352 的 per-brand 命令集为事实源（只读）；claude 行由 PC-10 探针定夺（播发即接线，不播发才诚实 absent）。

### PC-3 附件接通 plugin 半边（R-Z2-2）
chat 侧 add-content 由 `ChatAttachmentCapability.supported` 驱动激活（capability 有真实上游才亮）；prepare(idempotencyKey)→ref→submit 携带 refs（connectors submission attachments+sha256 通道现成）；release/重试/四态 phase（prepare/ready/refused/unknown）；refused 保留附件。生产宿主 prepare owner 缺席（S-05）→ 界面诚实禁用+原因，**受控测试**证明 refs 全链往返 sha256 一致（A06 形状）。

### PC-4 三态 submit（R-Z2-1）
`agent.ts:118` 合同升级：`send(): Promise<ChatSubmissionResult 三态>`（兼容迁移：旧消费者语义=resolve→accepted，逐个迁移并记录；contracts 包版本与修订说明按 chat-api r4 规则写）；sessions `model.ts` 映射接 `acp-next-submit`（authorize 已有 server 端）；`BackendAdmissionState` 缺席（S-05）时：请求在 HTTP 前诚实 refused/unknown——**unknown 保留 requestId、禁止自动重发；refused 不清草稿**（chat-page.tsx:122-159 分支已就位，接真上游）。受控三态注入回归逐级保真。

### PC-5 runtimeGeneration 透出
受控链已有 generation fence（acp-next-submit.ts:37,115-119；acp_admission.py:32,125-138），把它回灌 chat DTO：ChatLocation/快照带已确认 generation（替换纯前端 contextRevision 的对外语义，内部计数可留）；chat-api 修订记录兼容性。Q1 的消费面（SkillsChatSnapshotPort）不在 main——只登记形状，不实现。

### PC-6 旧链退役（plugin 半边）
删 `plugins/agent/conversation/{view,interaction-card,styles,entry}.tsx`（语义已迁 `plugins/chat/frontend/src/components/interactions/approval-panel.tsx`；先逐条核对 integration-request §4 表）；`@assistant-ui/react` 依赖从 conversation 的 package.json 摘除（根锁摘除归 S-02）；`apps/desktop/renderer/agent-conversation.test.tsx` 的等价覆盖核对后在 S-01 确认可删（删除归 core）。`plugins/agent/sessions` 去留**不裁决**（integration-request §4 归 core），只登记。

### PC-7 R-Z2-5 reasoning 状态（时间盒）
`AgentMessage.reasoning: string` → 状态化（streaming/complete/interrupted/unknown + duration），connectors 半边不动（登记 S-05 同族）；做不完如实 PARTIAL，不阻塞收口。

### PC-9 DTO 冻结（S-05 回执；唯一允许写 connectors 的窄口）
`plugins/connectors/acp/src/attachments.ts` 的 `AcpPreparedAttachment` 补 `preparedId`（core 需要，用于 Server DTO 对接）；**只改 DTO 字段 + 既有定向测试的期望**，不动 prepare 语义/实现/其他文件；TSD/类型检查全绿；交付 SHA 写回 seams S-05，core 按 SHA 接 Server DTO。此任务与 PC-3 同域，宜先做。

### PC-10 claude 命令探针（S-07 命令项）
在**本包测试目录**写一个受控探针：`npm ci` 安装 `plugins/harness/packaging/claude` 闭包（node_modules 产物，不算改 harness 跟踪文件），以该目录既有 `provider-session.test.mjs` 的架式（fake Anthropic loopback endpoint + 临时 Claude config + fake token，零真实模型/凭据）拉起钉版 adapter，开一个受控会话，观察是否收到 `available_commands_update`。结论两分支都要留第一手证据（转录/日志摘录进 report）：播发 → claude 行命令目录经 NativeCommandReader 接线（正例测试 + 四态）；不播发 → 诚实 absent+原因写回 seams S-07。**不改 plugins/harness 任何跟踪文件**；探针代码与测试放 plugins/chat。

## 门与反例（终态前必须全过）

| 门 | 断言 | 反例 |
| --- | --- | --- |
| 命令四态 | 三态以上路径实测（ready/absent 至少，loading/error 受控注入） | 恒 absent / 伪命令 = 红 |
| 附件往返 | 受控链 sha256 一致；refused 保留 | 仅 UI 可点 = 红（F3 口径） |
| 三态保真 | 注入 refused/unknown 逐级到达 UI；unknown 不重发 | resolve≠accepted 混淆 = 红 |
| 退役 | conversation 文件删净、引用零残留、覆盖核对留档 | 半删/隐性引用 = 红 |
| 诚实 | claude absent、S-05/S-06 缺席处禁用+原因 | 假可用/静默回退 = 红 |
| 回归 | chat-api/frontend/connectors（只读侧）计数不回退 | 下降未解释 = 不许收口 |

## DoD

实现 + 门 + `reports/P-C-report.md`（链路图文字版、计数、F3 对照逐条"真实接缝已生效/诚实缺席+S 编号"、缺口）+ 011-z2 report 增补 + tasks.md PC-* 勾选一致。git：本分支正常提交，不 push 不外并；子代理规矩同 P-A。
