# Chat：ZCode 展示复用方案

2026-09-27 · v2 产品设计已按用户确认定稿，未实施、未派发。采用 Spec Kit 结构，不是派工单。代码起点与服务接缝仍须实施预检，不冒充已发布 API。

新增权威文档：[创建与输入交互规格](input-spec.md)、[输入数据与扩展契约](input-contracts.md)、[实施计划](plan.md)、[验收矩阵](checklist.md)。这些文档及 tasks.md 的 v2 阶段替代旧版“无附件/命令面”的范围限制；旧服务缺口仍是真实前置工作，不能由 UI 猜造。

阅读：[spec.md](spec.md) → [research-plan.md](research-plan.md) → [扩展与组件契约](contracts.md) → [服务适配事实](service-adaptation.md) → [tasks.md](tasks.md)。本批已补齐扩展位置、契约语义和当前服务映射；实际可编译类型与迁移基线仍需在平台集成版本上核实，不把活动树观察当作已验收基线。

核心裁决：用户希望复用 ZCode 的工具调用、Agent 正文、思考展示。**主工具 UI 取材是 `ToolCallBlocks/ToolLayout.tsx` + `ToolSummaryRow.tsx`，不是仅移植 `ai-elements/tool.tsx` 的通用大卡片。**必须保留其信息层次和交互，不允许只看截图再自行重写全部组件。

平台只提供 `ui` 基础件和 `ui-components` 注册机制。消息/思考/工具展示归 Chat；本方案不恢复统一 Agent UI 包。

现状：本次主树与 platform-frontend 树仍有 `plugins/agent/conversation`、`plugins/agent/sessions`；不能把历史会话中提及的 `plugins/chat` 完成报告当作当前代码事实。下文 `plugins/chat` 是目标领域目录，不授权删除旧实现或修改持久 extension ID。正式实施前需要 source→destination 和测试迁移表；展示迭代不强迫先把会话服务归并进 Chat。
