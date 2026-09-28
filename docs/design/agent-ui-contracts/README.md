# 可替换 UI 组件契约设计

> 2026-09-27 范围修正：通用 component-platform 契约继续用于 C7；统一 `plugins/agent-ui` 与 12 项公共组件库的后续实施安排已撤销。领域组件由各插件拥有；平台新增基础件包 `ui`。以 [Platform UI Foundations](../platform-ui-foundations/README.md) 为最新范围裁决，旧领域草图不再是实施要求。

日期：2026-09-27。状态：设计待审；没有追加正在运行的 Qoder 任务，也没有修改产品代码。

采用项目现有 Spec Kit 文档结构。这是 `010-platform-core` 前端线的候选补充，先留在主树设计目录；批准后由该线在自己的检查点之后引入，保持单一写者。

## 决策摘要

1. 核心提供通用的 UI 实现选择、作用域管理与渲染入口；现有 Lumino 服务注册仍是唯一服务注入机制。
2. 通用实现放 `packages/desktop-platform/ui-components`。组件领域契约放 `plugins/agent-ui/api`，可独立导入；具体实现放该插件的 `src`。纠正此前将 Agent 契约放入平台 contracts 的建议，遵守 C4 的领域归属。
3. 产品明确选择某个组件接口的提供者。没有优先级争抢、按加载先后覆盖或静默回退。
4. 第二版覆盖五组、12 个领域接口：对话与输入，工具/审批/提问，选择与配置，资源/变更审阅，进度/运行摘要。完整职责见组件总览；内部 Markdown、代码块和按钮先不成为注册点。
5. 卸载会撤销实现，消费位置更新为缺席；必需位置显示可理解的提示，可选位置隐藏。卸载 UI 不停止后端执行。
6. 替换选择在下一次前端重新装配生效。同一已选择提供者卸载后可重新激活，使用新实例；v1 不承诺跨实现保留焦点、滚动、输入法和内部折叠状态。草稿和业务状态由消费者控制。

## 阅读顺序

- [spec.md](spec.md)：用户行为、需求与完成标准。
- [component-catalog.md](component-catalog.md)：第二版完整组件目录，每项的输入、动作、组合和业务边界；建议先读此文。
- [contracts/component-platform.md](contracts/component-platform.md)：可追加给前端核心线的通用契约。
- [contracts/agent-ui.md](contracts/agent-ui.md)：领域 API 的共同规则与四个已有 TypeScript 草图；完整能力范围以组件总览为准。
- [plan.md](plan.md)：现状依据、包边界、装配方式与交付顺序。
- [tasks.md](tasks.md)：按负责范围划分的实施和验收项。

## 追加范围

前端 Qoder 只追加通用包、必要的产品构建接线和受控组件验证。12 个 Agent 领域接口与上游组件移植留给后续插件批次。核心交付不需要等待真实 Chat/Profile 改造，也不能为了验证而把 Agent 字段放进平台。

这份设计覆盖本阶段接口与失败语义；实施前需在 Qoder 的实际提交上核对文件路径。当前根 main 为 `cd7d31f3cf`，读取的 C 树分支为 `codex/010-platform-frontend`，正在变化；本设计不把其报告值当成独立验收结果。
