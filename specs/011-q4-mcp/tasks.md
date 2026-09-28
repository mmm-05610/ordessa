# Q4 任务与原包追踪

本线副本，允许勾选并追加查漏任务。共同 plan 的 owner 分配优先；原表范围外步骤登记依赖/C0 集成，不由本线偷改。原包更晚变更须有明确裁定，不自行缩需求。

- [x] R0：读完整输入，冻结实际 SHA/包/红 ID/环境，盘点复用。
- [x] R1：（foundation 8844c475bc / chat-api-r3 3d8c3fa410 / permissions-api bcd4387bec / harness-api d3f026904e 已消费并留 SHA；profile-api 4943628f47 消费即登记 Z1 组合冲突）
- [ ] R1b：消费 profile-api-r2（Z1 发布即接线 facet 面；harness-api 已并入并接线 T013）
- [x] R2：本线全部原包任务有实现/验收/依赖归属（T00–T10+T011–T014，见进度账/收敛账），生产假接口为零（fail-closed 类型化拒绝）
- [x] R3：检查点/接线清单/集成请求/许可迁移账（SDK MIT 钉版与替代路线均登记）/报告齐备；定向门 461/461、全链 apps/server per-ID 新增红 0
- [x] R4：Spec Kit analyze/converge 查漏，未完成项如实（report.md §二/§三）；ready 分支 `codex/011-q4-ready` → 见 git rev-parse；工作树 clean。

## 原包：mcp

来源：docs/design/mcp/tasks.md，2026-09-28 派发快照。以下保留原条目便于追踪；过程授权与 owner 由共同 plan 更新。

# Tasks：分阶段、单 owner、每项有门

工作树从已验收 main 建，任务仅在用户批准方案后开始。本表不授予 push/merge 或真实外部 MCP 副作用。

| ID | Owner 文件面 | 可执行任务 | 退出门 |
| --- | --- | --- | --- |
| T00 | MCP 方案/契约 owner，只读核心 | 核对最终集成 SHA、贡献符号、固定 Pi/Codex/Claude 版本与 ACP adapter、SDK tag/许可证；填实接口绑定/缺口表。 | V00：缺失被逐项报告且不能被假 stub 混入生产。 |
| T01 | `plugins/assets/mcp/backend/definition*` | 从旧 MCP store 迁 canonical/digest/version；实现 literal/secretRef 判别、严格 schema、CAS 与不变修订。 | V01：畸形/未知 transport/secret 明文/重复修订红→绿，旧摘要/ID 字节互证。 |
| T02 | `backend/assignment*` | 用户默认、项目、Profile、会话四类分配与工具子集；完整快照/冲突/撤销/批准升级。 | V02：顺序、disable/re-enable、未批准更新不生效、跨服务/项目拒绝。 |
| T03 | `backend/probe*` | 限时 stdio/HTTP 受控 probe；协议协商、取消/清理；无凭据结果单列。 | V03：超时/大帧/假响应/子进程孙进程均不泄漏；不把 initialize 当 catalog。 |
| T04 | `adapters/codex*`, `adapters/claude*` | 各自固定目标版本，C2 编译完整 native 集合、原生来源隔离、工具目录观察、受控重启恢复。 | V04：双会话不串，额外原生来源被识别/阻止，只有文件落盘不得报 loaded。 |
| T05 | `adapters/pi*`, `backend/managed*` | 固定 MCP SDK client、Pi 最小受管扩展、连接租约/唯一 owner 与工具转发；不能重复 native 投影。 | V05：Pi 两会话不同 server/凭据，单次关闭无泄漏，扩展不能绕过授权。 |
| T06 | `backend/permissions*` glue | 接 Permission 公开判定；catalog 子集与最终授权双门，无人值守有界预授权与拒绝。 | V06：已发现未授权工具、未知副作用、过期/跨主体授权均在副作用前拒绝；无 UI 不放行。 |
| T07 | `backend/secret*` glue | 只消费统一 credential service；plan 绑定 secret revision，后端瞬时解析和脱敏。 | V07：秘密不进持久定义/前端/事件/普通 native 文件；轮换拒绝 stale plan。 |
| T08 | `frontend/**` | MCP Settings、Profile facet/settings、Chat 状态与按需选择，复用现有平台 UI/贡献。 | V08：服务缺席、provider 卸载、悬空引用、断线/错误状态和输出中变更。 |
| T09 | MCP 产品装配 owner + compat 单 owner | 公共贡献组装与 mcp kind 迁移；只减旧 `server-compat`，无宿主新分支。 | V09：旧数据/wire/摘要互证、裸宿主无业务、compat mcp 新写入为零。 |
| T10 | MCP 验收 owner | 全链受控双会话、异常/卸载/重复连接/工具权限/计划重试、无模型 UI+ACP smoke，输出证据矩阵。 | V10：按品牌/lane/证据等级逐格核算，逐 ID 回归与无新增未解释红；不虚报外部服务通过。 |

T01/T02 可与 T04/T05 的**只读研究**并行，生产代码在 T00 接缝确定后按文件 owner 分派。T06 是实际工具调用的强制前置，不能因夜间无人值守延期；安全域若尚未交付，允许 T01/T02/T03 完成但 T10 整体不得报绿。

## Q4 进度账（主代理维护，2026-09-28）

| 原任务 | 状态 | 证据 |
| --- | --- | --- |
| T00 | 完成（r2：V00 ACP 入口探针补轮，reports/t00-acp-probe.md） | t00-interface-bindings.md + reports/t04-t05-research.md（固定工件/红账/缺口表）；harness-api 发布后需补 V00 对接轮 |
| T01 | 完成 V01 | reports/t01-t02.md；commit f382aceecf（legacy 字节互证 7 例） |
| T02 | 完成 V02 | 同上（13 例解析/冲突/子集反例） |
| T03 | 完成 V03（无凭据面） | reports/t03.md；commit 02e4175f13（49 例含进程树回收/协商/取消） |
| T04 | L1 完成；V04 生产格 blocked harness-api(G2)+受控探针 | reports/t04-adapters.md；两品牌 assess 恒 unknown/unsupported，无假绿 |
| T05 | 域+L2 client 完成；Pi 装载格 blocked G4 | reports/t05-domain.md、t05-client.md（17 例 L2 反例+变异审计）；路线 B 限定替代已登记 C0 裁定（integration-request 10） |
| T06 | fail-closed 双门+真实 Q5 API 接线完成 V06(L1 受控) | reports/t06-wiring.md（23 例真实 backend proof）；生产 tools/call 转发仍随 T05 装载格 |
| T07 | 完成 V07(L0/L1) | reports/t06-t07.md（61 例含脱敏/轮换/stale 整批拒）；HostCredentialPort 生产注入等装配（integration-request 9） |
| T08 | Settings/Chat glue 完成；Profile facet blocked Z1 r2 | reports/t08-frontend.md（vitest 31 + tsc + build exit 0） |
| T09 | Q4 侧服务/wire/迁移工具完成；产品装配+compat 删除归 C0 | reports/t09-service.md（真实 host dispatch 30 例）、t09-migration.md（19 例查询等价）；integration-request 1/4/6-9 |
| T10 | 部分推进：Pi 桥真机格+ACP adapter 会话注入格有实测证据；产品装配链与 codex/claude 真 CLI 格阻塞（report.md §二 1/2） | 未勾——按 verification.md 矩阵逐格核算需 C0 装配与 CLI 环境授权 |

## Phase 1: Convergence

- [x] T011 Implement managed-lane Streamable HTTP client（reports/t011-http-client.md；33 例 L2+变异审计；commit 见 git log T011） (per-session client/session, TLS/redirect/auth checks per pinned policy, calls through the Q4 double gate) per FR-01/FR-05/FR-06, contracts §3 managed 段 (missing) — 无外部依赖，可即时实现
- [x] T012 Surface native permission posture（缺席语义/标注面完成，reports/t012-t014.md；运行时事实生产者等装配，已登记） honestly when Ordessa authority is absent: observation DTO + 展示接缝 + fail-closed 语义 per FR-09, contracts §4 (partial) — 运行时面等 harness-api，缺席语义先行
- [x] T013 harness-api 已消费（pub d3f026904e）：薄适配 native_binding+真 C2/C4 接线+提交闸门完成（reports/t013-harness-wiring.md，L2 链级）；L3 格升格随 T10 剩余阻塞见 report.md §二
- [x] T014 76 码封闭词表+零重叠守卫+posture 面（reports/t012-t014.md；真实 compat 串对照+变异审计）
