# Z2 线报告 — Chat 展示、创建与输入扩展

日期：2026-09-28。分支 `codex/011-z2-chat`，基线 `96fef2db47`（设计快照，父 main `cd7d31f3cf`）。
状态：**REVIEW_READY（本线范围）**。未完成项如实列为 PARTIAL/未验证，均注明所有者与阻塞条件，不以阶段提交冒充整线完成。

## 1. 提交与检查点账

| 提交 | 内容 |
| --- | --- |
| `98be5571cb` | R0 基线冻结（baseline.md）、接缝请求（api-requests.md） |
| `a3ec20c046` | chat-api v1：领域契约 + 内存注册表 + 受控 proof |
| `54ad26c15d` / 分支 `codex/011-chat-api-ready` | chat-api v1 检查点（READY） |
| `33abf4efbf` | S2–S4 前端：展示移植、composer/面板、附件、审批、项目弹窗 |
| `0cfb01e28b` | 任务账勾选（含依赖归属） |
| `be672a59a0` | api build 脚本深度修复；两扩展试构建通过 |
| `31fb2db46d` / `codex/011-chat-api-ready-r2` | chat-api-r2（动作签名收窄 + 兼容记录） |
| `0a05235d0f` | **消费 foundation**：固定 publication SHA `8844c475bc`（实现 `8229e20824`，祖先关系已核）正常 merge |
| `47459b0acb` | chat-api r3：`ChatComponentKey` = 平台 `UiComponentKey`（type-only，运行时对象不变） |
| `3d8c3fa410` / `codex/011-chat-api-ready-r3` | chat-api-r3 检查点 |
| `d128134844` | integration-request §6（C7 产品级接线步骤） |

未合并 main、未 push、未动旧树脏项、未操作既有服务、零模型调用。

## 2. 逐任务证据（对照原包 tasks + v2 阶段）

测试证据（全部真实执行、无 skip）：
- chat-api：`cd plugins/chat/api && npx vitest run` → **15/15**；`tsc --noEmit` → 0
- chat frontend：`cd plugins/chat/frontend && npx vitest run` → **35/35**（display 11、composer-flow 7、panel-draft 7、approval-project 10）；`tsc --noEmit` → 0
- 根（foundation 合入后复跑）：`npm run typecheck` 0；`npm test` 27/27 suites；`npm run build` 10 enabled extensions；`node plugins/chat/{api,frontend}/build.mjs` 试构建成功（产物含 contract.js/entry.js/licenses）

### 设计前置（CHAT-D01–D04）：全部完成
- D01/D02/D03：`plugins/chat/api/src/contract.ts`（六槽位上下文、四 key props 逐字段、ChatLocation、快照三态）；DTO 映射 `frontend/src/adapters/agent.ts`（快照语义，无证据不造状态）；类型反例 `src/contract.typecheck.ts`（@ts-expect-error 全部真实触发）。
- D04：明确差异（不移植排队动画/CodeViewer/Mermaid/编辑器服务）逐文件登记于 `plugins/chat/upstream-manifest.json` dropped 字段。

### v2 阶段
- **CHAT-V01（S0）PARTIAL**：本线基线实跑 + 迁移表完成（baseline.md）；「正式平台 SHA」已由 foundation 合入达成（8844c475bc）。
- **CHAT-V02（S0）完成**：chat-api 三检查点；无 any 逃逸（审计通过）；范围外服务修改一次性列齐（api-requests R-Z2-1/2/3/5/6）。
- **CHAT-V03（S1）PARTIAL→依赖归属**：项目门/文本发送对真实 facade 证明（composer-flow：草稿门 2 例、发送流 4 例）；**命令目录/附件 prepare/三态 submit 的真实服务归 C0**（共同 plan：S1 的 connectors 改动归 C0；本线提供 DTO/反例并消费其发布）。落地后接线验证为本线遗留动作。
- **CHAT-V04（S2）完成**：display 11 例（流式/静态两分、渲染失败保留原文、思考折叠纪律、同名工具不串展、failed/unknown 不混淆、结构化命令仅来自验证字段）。
- **CHAT-V05（S3）完成**：全局项目弹窗（Workbench composition/overlay 宿主）、项目+直达草稿、取消零后端调用（approval-project 2 例）、发送门禁（composer-flow 2 例）、固定输入区 + 审批操作面（唯一操作面、resolved 退出、FC-0029 能力门、choices-only 来源、超量计数）。
- **CHAT-V06（S4）完成**：+/ 斜杠共用面板（单实例互斥、plus 搜索不改草稿、slash token 过滤、键盘上下/Enter/Tab 补全/Esc、焦点还原、陈旧插入拒绝、缺席来源隐藏、错误局限单源可重试、disabled 原因透传）——panel-draft 7 例 + chat-api 15 例。
- **CHAT-V07（S4）完成（fixture 层）**：选择/粘贴合流、预览/移除/重试、object URL 所有权（handed-off 不回收）、未就绪阻止发送并指因、未知结果不自动重发——panel-draft + composer-flow。**真实内容 hash 往返依赖 R-Z2-2**。
- **CHAT-V08（S5）待 C0**：产品装配（products 归 C0；两扩展启用方式与 build-all 依赖检查已写入 integration-request §1）；旧 UI 注册链关闭保留 ID 同上（§4）。
- **CHAT-V09（S5）未验证**：真实浏览器矩阵/Electron 门/受控 hash 校验——依赖装配，登记于 §5 未验证清单。
- **CHAT-V10（S5）**：本报告即交付；独立审阅见 §6。

### 实施序列（CHAT-I01–I07）
- I01–I05 完成（证据同上；I01 来源账 = upstream-manifest.json 逐文件 git-hash + kept/dropped/adapted；许可副本 `plugins/chat/licenses/ZCode-LICENSE` + THIRD-PARTY-NOTICES.md）。
- I06 PARTIAL：适配完成；旧 UI 切换归 C0；断言映射登记 integration-request §4。
- I07 未验证：浏览器矩阵依赖装配（见 §5）。

### 专项（X01–X06）：全部完成并有测试
X02/X03/X05/X06 对应 chat-api 注册表例、composer-flow X05 例、审批 resolved 例；X01 scope 撤回语义由 chat-api 例覆盖，最终 glue 装配按集成宿主校验（登记 api-requests 备注）；X04 decode 失败 fallback + renderer 重复拒绝。

## 3. 来源复用账

ZCode `29628c9a`（Apache-2.0；ai-elements 含 Vercel 派生物）浅取核对，7 个目标模块、10 个源文件 git-hash、逐文件 kept/dropped/adapted 全记录于 `plugins/chat/upstream-manifest.json`。依赖固定版本：streamdown 2.5.0、@streamdown/cjk 1.0.3、shiki 4.0.2、use-stick-to-bottom 1.1.3、radix-ui ^1.6.7（根锁已有）。lucide-react 1.17.0 经核实本批无直接引用，未声明依赖。

## 4. 契约变更

- chat-api v1（a3ec20c046）→ r2（be672a59a0）：prepare/execute 签名收窄为显式 location 入参 + ChatPrepareResult 三态；发布时无外部消费者，兼容性在 checkpoint limitations 与 tasks.md 修订账记录。
- r3（47459b0acb）：消费 foundation 后 `ChatComponentKey` 即平台 `UiComponentKey`；运行时对象不变，产品级构造点切换（import map/externals/re-export 三步）登记 integration-request §6 归 C0。

## 5. 已知失败 / 未验证（诚实清单）

| 项 | 状态 | 所有者/条件 |
| --- | --- | --- |
| 附件真实 prepare/refs + 内容 hash 往返（A06 受控端到端） | 未验证 | C0 传输接缝（R-Z2-2）；UI/fixture 已就绪，落地后本线接线 |
| 原生命令目录真实取数 | 未验证 | C0（R-Z2-3）；无目录时缺席呈现已证 |
| 提交三态真实服务证据 | 部分（adapter 映射有测试；真实 refused/unknown 分支证据待真实服务） | C0（R-Z2-1） |
| reasoning 独立状态/真实耗时/块序列 | 未验证（展示层无证据时 unknown/无耗时已证） | C0（R-Z2-5） |
| 文件 picker 附件通道（R-Z2-6） | 未验证 | C0 平台桥 |
| 真实浏览器矩阵（深浅/360px/768px/1280px/200%/IME/长内容/弹窗）+ Electron 门 | 未验证 | C0 装配后 |
| 产品启用 + 旧 agent-conversation 关闭 | 待集成 | C0（integration-request §1/§4） |
| 根 package-lock 最终生成 | 待集成 | C0（本线增量已登记 §2） |

无新增已知失败；基线 146 测试与 foundation 聚合套件在本线全程保持绿。

## 6. 偏差与过程事实

- **子代理派单受限**：主代理按目标要求应「只派单包子代理实现/审阅」，但本会话 Agent 派单三次均因运行时配额（exceed quota limit）失败；按「普通阻塞自行解决」改为本会话直接实现 + 自审，偏差在此如实登记。审阅清单（写入面/契约语义/移植保真/测试真实性/诚实性/检查点祖先）已由本会话执行并通过，建议合并前由 C0 或兄弟会话复核 diff。
- `apps/desktop/tsconfig.json` 一行契约别名（线界外的机械修改，integration-request §3 申报，请 C0 复核）。
- api build.mjs 相对深度错误在试构建中发现并修复（be672a59a0）。
- 新测试发现并修复的真实缺陷：fixture 快照身份导致 useSyncExternalStore 循环（测试基建）；DraftStore 非 React 状态导致受控输入被恢复（产品缺陷，已以订阅式 store 修复）；面板按键转发的 defaultPrevented 语义。
- 临时文件清理：tests/debug*.tsx 已删除；`docs/ui-preview/*.png` 由测试再生后已还原；ZCode 源码浅取在 /tmp/zcode-src（非仓库内）。

## 7. 消费与后续

- 本线消费记录：foundation `8844c475bc`（merge 0a05235d0f，复跑全绿）。harness-api 截至本报告未发布；发布后本线按协议消费并接线 R-Z2-1/2/3，随后执行 CHAT-V08/V09 遗留项并回填本报告。
- 待办交接：C0 集成按 integration-request §1–§6 执行。

## 8. 014 P-C 增补（2026-09-28，分支 codex/014-c-chat）

原五条 C0 待办中的 R-Z2-1/2/3/5 已在本分支以真实接缝接通（详见 `specs/014-plugin-release/reports/P-C-report.md`）：

- **R-Z2-1 三态**：agent-contracts 0.2.0 `send(): Promise<AgentSubmissionOutcome|void>`（冻结客户端零破坏）；sessions 门面为映射 owner（fail-closed admission 前置、链路断→unknown 保 requestId、typed refused、旧 resolve→accepted）；chat gateway 1:1。本报告 §2「三态真实服务证据」行升级为**受控级已生效**（refused/unknown 注入逐级到 UI，unknown 不重发）。
- **R-Z2-2 附件 plugin 半边**：capability 驱动入口、prepare(idempotencyKey)→不透明 ref→submit attachmentRefs→connectors sendControlled verify(sha256 全等)链路全通；A06 受控往返一致；refused/unknown 保留+原因；生产 owner/picker 缺席=禁用+原因（S-05/R-Z2-6）。§5 首行升级为受控级。
- **R-Z2-3 命令目录**：connectors `getNativeCommands` 零消费状态终结——contracts 可选成员→sessions 门面→chat 四态投影+slash 输入源；反例（stale-session/channel-down/unobservable/malformed/无成员）全带原因；claude 行经 PC-10 受控探针实证**不播发** `available_commands_update`→诚实 absent（转录在 P-C 包）。
- **R-Z2-5 reasoning**：`AgentMessage.reasoningState?` 契约化+展示层消费（有证据用证据，无证据不造耗时）；connectors 半边登记 S-05 同族。
- **PC-6**：`plugins/agent/conversation` 全包退役（等价覆盖 18 gates 逐条核对留档 P-C report §6）；`agent.conversation` view id 引用清零；S-01 退役条件确认满足。
- 其余未变项照旧：R-Z2-6 picker、浏览器矩阵/Electron 门、产品启停（S-01）、根锁（S-02）。
- 契约修订：chat-api r4（全增量，账在 contract.ts 尾部）；本线 §4 的 r3 账不被推翻。
