# Agent UI 默认实现：Spec Kit 实施包

> 2026-09-27 后续裁决：**统一 Agent UI 实施包已撤销，不再执行本目录任务。**改按 [Platform UI Foundations](../platform-ui-foundations/README.md) 实施两个通用平台包。本文取材研究留档，未来按领域分配，不自动授权任何组件移植。

日期：2026-09-27。状态：**设计待用户审核；未实施、未派发**。

目标不是再研究“可以借鉴谁”，而是冻结可执行的复用边界：具体源文件、保留逻辑、删除依赖、Ordessa 适配、反例和交付证据。采用 Spec Kit 的 spec → research/plan → data-model/contracts → tasks → analyze → implement 顺序，不采用派工单体系。模板结构参照本仓 010 使用的 `.specify/templates`；未声称运行过 Spec Kit CLI。

## 阅读顺序

1. [spec.md](spec.md)：范围、用户故事、验收标准。
2. [research.md](research.md)：已核实的复用来源、文件和依赖裁决。
3. [plan.md](plan.md)：目录、所有权、接线、构建、安全与分阶段实施。
4. [data-model.md](data-model.md)：数据和状态的归属。
5. [tasks.md](tasks.md)：依赖明确的任务及证据。
6. [quickstart.md](quickstart.md)：验收入口。
7. [checklists/readiness.md](checklists/readiness.md)：实施前与交付前核对。

既有 [12 项组件总览](../agent-ui-contracts/component-catalog.md) 与 [领域契约](../agent-ui-contracts/contracts/agent-ui.md) 是语义输入；后者四项 TS 示例尚非完整 API。本批补齐 12 项可编译类型，不允许以四项草图取代完整范围。通用 registry、generation、Outlet、动作 guard 由前端 C7 提供，不在此重写。

## 本轮决策摘要

- 一个 `plugins/agent-ui` 包：轻量 `/api` + 默认提供者；五个内部组件家族，不拆 12 个运行时插件。
- 12 项全部有默认实现、独立 fixture 和测试；未接入真实业务页面不能宣称真实 Chat/Profile 改造完成。
- 优先移植 ZCode 已核实的小展示组件；复杂算法用现成包；领域状态和服务适配由 Ordessa 自己写。
- 不整搬 ZCode UI workspace，不新增另一套聊天运行时，不让上游业务对象进入公开 props。
- 本批不迁移 Chat/Profile/model-provider、不停用户服务、不改 Server/Pacthold；默认产品切换另列集成步骤，不借此修改宿主。
- 执行工作树从**已审阅的 C7 集成版本**派生；本文不固定未来尚未知的 SHA。正式派发时记录 BASE_SHA、C7_SHA；C7 未就绪时可做源代码取材和组件测试，不得用假平台冒充接线完成。

所有文档在仓内；`/tmp` 上游检出仅是本次研究缓存，不是实施依赖。源代码可按 research 中的仓库与提交重新取得。
