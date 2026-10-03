# 026 — 开放环境整体迁移 Spec Kit

状态：初稿已完成三角度攻击、修订与同组独立复核，可交实施方案审核；**没有执行产品迁移**。一个牵头 Agent 按依赖完成全项，不需要用户协调多个执行会话。

当前R4新增合同/插件结构尚未独立复核；上述三角度结论仅覆盖R2原19项。先读plugin-architecture.md看完整插件格局，再读E3/E4/E5/A1合同。不要把未实施目标当现产品可用能力。

R5已完成主会话落地前回审与修补，见reviews/pre-implementation-review.md。新增execution-detail.md将R01–R17追踪到合同/工单/验收，并明确002交付、owner切换和逐切片验证。R5不是新的独立代理复核，也不是产品测试；本包可以用于启动001来源/授权核对，不能绕过启动许可直接迁移。

R6兼容清理见compat-retirement.md及evidence/compat-inventory.json：取消永久legacy-compat插件，不以整体搬目录替代业务清空；002冻结逐符号归属，006/007/010拆解，012在A95内验证C95-1–7。静态盘点不是已实施或运行验收。

R7（M14，2026-10-03）追加前端插件开发基础设施：contracts/frontend-infrastructure.md及frontend-infrastructure-update.md。当前完整范围12工单/129任务/111验收；旧R2–R6计数和“未实施”是历史设计记录，实际实施进度以实施树status/evidence为准。

## 分层阅读

| 层级 | 内容 | 文件 |
| --- | --- | --- |
| L0 产品结果 | 迁移要达到什么、什么不变、什么不做 | spec.md |
| L1 架构与合同 | 包、状态所有者、对象、前后端合同 | architecture.md、data-model.md、contracts/ |
| L2 迁移策略 | 来源固定、阶段、切换、持久兼容、回退及具体执行交付 | research.md、plan.md、migration.md、execution-detail.md |
| L3 执行工单 | 每单目标、依赖、写权、门、反例 | orders/001…012 |
| L4 具体任务 | 逐条编码和验证动作 | tasks.md、task-registry.json |
| L5 结果证明 | 验收场景、证据、攻击与处置 | acceptance.md、reviews/、status.md |

先读 spec 与 architecture，再读 migration-map 和 contracts/recovery 的强制接缝，再执行 orders。tasks 不能绕过工单依赖。任务注册表是编号/依赖权威，tasks.md 是可读投影；结果权威是 status.md 和 evidence，不把复选框当证据。

规模：7个阶段、12张工单、129个任务、111组验收。审查结果见reviews/report.md：19项第一轮问题均修订后由原审查者复核设计闭合；非生产符合性证明。R3/R4新增合同尚未独立复核。结构检查命令：node specs/026-open-environment-migration/checks/validate-package.mjs。

R3补充 contracts/relationships.md：同一Environment内的能力关联、领域单写者、订阅连续性和作用域。工单分配表是原单既有阶段的追加交付，A66–A75必须验收；不引入业务语义或第二关系核心。

R4补充contracts/platform-services.md（数据空间、宿主交互、秘密/诊断）、resource-references.md（持久资源关联）、agent-domain.md（Agent单owner与公开接口）、plugin-architecture.md（领域平铺与多入口）。新增18显式任务和A76–A95；旧“plugins路径不动/保留assets分组”约束由R4取代，身份兼容仍不变。未实施工单的修订以文档R4纳入记录，不伪造设计提交SHA，实施源由001冻结。

## 方案权威

024 V3、025 V4保留历史，本包是二者联合落地合同；同一主题最终修订条款优先。本文新增决策见 decisions.md。尤其 D6 已改为按保证等级处理，不再沿用024“缺指纹拒绝所有输入”的候选规则。

本包不单独授权编码、开工作树、集成产品树、重启服务、写真实用户数据、安装系统资产、真实模型调用、合并 main 或 push。实施 Agent 必须按启动闸门核实授权，不能沿用聊天中的旧运行许可。

## 组织方式与流程偏离

采用 incremental-work-order 的可判定工单/四列门/反例/单提交者原则。用户明确只派一个牵头 Agent，因此一条有序队列；不初始化第二套 docs/implementation 全局账，不自动开树/提交：本包尚是 Spec Kit 设计，不是已投递任务。每单无需父树合并，依赖的是同一实施树前序证据与提交。检查点不是自动 main 合并许可。

三名审查子代理只读材料并返回攻击，主会话唯一方案写者。未来执行侧默认单 Agent，若需要代理，先按 charter 中声明独立单元决定，不增加常驻协调层。
