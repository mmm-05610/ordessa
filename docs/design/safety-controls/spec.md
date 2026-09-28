# Feature specification

## 用户故事（按优先级）

### US1：Profile 选择偏好，管理员上限永不被放宽（P1）

用户为一个 Profile 选“多数工具需问我”，管理员规定某目录永久禁止写。下一次用户提交前，服务解析 Profile 的意图与上限；即便 Profile 改成宽松、同会话换 Profile 或客户端伪造 allow，该目录仍拒绝。选择动作不打断正在输出；已冻结的这轮不回溯改变。

**独立验收**：同一会话连续两轮使用不同 Profile，只在第二轮提交边界应用新策略；管理员 deny 永远胜出；缺上限提供者或修订变化时零工具副作用。

### US2：待审批工具一次且仅一次裁定（P1）

Harness 报出真实、已归属会话/执行的待授权操作；用户可在 Chat 审批卡允许一次、允许受限范围或拒绝。重放、并发、过期、跨会话审批不产生第二次执行。用户断连、超时、关闭窗口、未知返回一律不默许；审批 UI 不产生权威 allow。

**独立验收**：相同 requestId 重放只返回既存结果；不同身份/参数重用 ID 拒绝；响应丢失后先 query/reconcile，不重复提交副作用操作；execution 终结后审批失效。

### US3：独立设置 Harness 原生隔离（P1）

用户可为 Profile 指定目标 Harness 原生 sandbox 要求，例如 Codex 的读写/网络模式或 Claude Bash 沙盒约束。应用时检查管理员上限、运行平台、Harness/adapter 版本和隔离覆盖范围；不支持则显式拒绝，不把进程私有配置根或“工具审批”冒称 OS 级隔离。Pi 若只靠可选 extension，缺该 extension 就没有受支持的原生 sandbox。

**独立验收**：两个同品牌会话 A/B 采用不同隔离意图，A 变化不影响 B；观察到隔离仅覆盖 Bash 的情形不得宣称全部工具均隔离；必要实例重启恢复与同一会话身份核验按 Harness v2 执行。

### US4：用户可理解允许、审批和隔离的不同结果（P2）

Settings 管全局/管理员规则，Profile 管可配置的会话意图，Chat 只负责模式选择与真实审批卡；只有错误/待审批才显示额外状态。`YOLO/auto/plan` 等各品牌原生命名只作为该品牌选项，不跨品牌等价化，不用一个“完全访问”按钮同时改变权限和隔离。

## 功能需求

| ID | 必须满足 | 归属 |
| --- | --- | --- |
| FR-01 | 权限策略是独立、可版本化的业务实体；上级约束与 Profile/session 意图分库存储，任何低层输入不可提高上限 | Permissions |
| FR-02 | 授权判断发生在 Harness 工具副作用前的后端可信边界，输入含主体/会话/执行/工具/目标/参数摘要/策略修订；缺字段、缺权威、未知工具、过期结果 fail closed | Permissions + Harness 接缝 |
| FR-03 | `allow/ask/deny` 仅是 Ordessa 解释层结果，不把不同品牌原生模式名等同；若品牌无法表达所需强制规则，不静默降级 | Permissions adapters |
| FR-04 | 审批请求、决定、关联 native request、过期及执行事实可查询、CAS 与幂等；允许仅按已批准对象/范围使用一次 | Permissions |
| FR-05 | 原生 sandbox 作为独立配置 facet，有平台、版本、覆盖工具、读写/网络作用域与隔离证据；不等同 Pacthold `SandboxV1` | Sandbox asset |
| FR-06 | 原生 sandbox 无法核验、adapter 缺席、要求比原生上限更严而无法表达、跨会话会互相污染时，在提交消息/启动有副作用操作前拒绝 | Sandbox + Harness |
| FR-07 | 应用只在下一用户提交闸门，当前输出不中断；同一已冻结 turn 的策略快照不可被 UI 选择回改 | Profile + Harness 既有接缝 |
| FR-08 | Settings/Profile 以各自公开贡献接缝展示编辑面；业务无 UI 时后端规则仍生效；UI 卸载不丢数据、也不伪造可用性 | 两插件 |
| FR-09 | 不支持/未知/提供者卸载/策略冲突/断连分别有稳定拒绝码与用户可理解诊断；含审计事实但不记录秘密或完整工具内容 | 两插件 |
| FR-10 | 旧 `server-compat/profiles/permissions.py` 等授权语义必须被显式审计/迁移；不得用现有 last-match-wins 直接实现不可提升管理员上限 | Permissions |

## 非目标

- 不创建统一 `SafetyService`、不把品牌策略塞进 Pacthold/Server/Workbench、不增加业务路由到 `apps/server`。
- 不实现通用容器、虚拟机、工作树或远程执行隔离；不替代 Pacthold 执行资源 `SandboxV1`。
- 不把自然语言提示词或 Hook 当强制权限边界；不声称原生规则对一切 MCP、网络、子代理跨进程副作用自动覆盖。
- 不真实调用模型、不触碰用户运行配置/凭据；受控 fake adapter 和临时目录是本批证据。

## 成功判据

T00 固定集成平台 SHA 和导出接口；所有 P1 需求具 L1 单测 + L2 受控 Harness/ACP 路径 + 正反例，至少一条真实 pre-effect 拒绝路径。三品牌差异矩阵没有“未知却标绿”。仓库内依赖方向与独立安装门禁通过；原有已登记红账本逐 ID 零未解释增量。
