# Q4 任务与原包追踪

本线副本，允许勾选并追加查漏任务。共同 plan 的 owner 分配优先；原表范围外步骤登记依赖/C0 集成，不由本线偷改。原包更晚变更须有明确裁定，不自行缩需求。

- [ ] R0：读完整输入，冻结实际 SHA/包/红 ID/环境，盘点复用。
- [ ] R1：独立工作与接口请求完成；消费必需 checkpoint 并留精确 SHA。
- [ ] R2：本线全部原包任务有实现/验收/依赖归属，生产假接口为零。
- [ ] R3：检查点/接线清单/许可迁移账/报告齐备，定向及相关全链门通过。
- [ ] R4：Spec Kit analyze/converge 查漏，未完成项如实；发布本线 clean ready commit。

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
