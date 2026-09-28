# Platform UI Foundations — C7 增补与范围修正

日期：2026-09-27。状态：用户授权设计并准备追加实施；当前仅文档，未更改 Qoder 工作树。

采用 Spec Kit 的 spec → plan/contracts → tasks → analyze/verify。阅读：[规格](spec.md) → [方案与契约](plan.md) → [任务与验收](tasks.md) → [追加提示词](qoder-addendum.md)。

## 本次优先级裁决

1. **保留正在实施的 C7 通用注册机制及 U01–U16**，不从头重做。实际观察 C7 为 IN_PROGRESS，`ui-components` 实现及测试有未提交改动；本会话只读，未修改它们。
2. 新增 `packages/desktop-platform/ui`：可直接 import 的基础控件/容器，不是运行时业务插件。
3. `ui-components` 仍只负责通用注册/绑定/装载/替换生命周期；任意插件定义自己的类型化组件 key，平台不枚举业务种类。
4. **撤销统一 `plugins/agent-ui`、默认 Agent UI 提供者及 12 项统一组件库的实施要求。**旧 `agent-ui-implementation` 的 T001–T023 不再是有效任务；取材研究留档，待以后分别分配给领域所有者。
5. 不把原 12 项搬进平台。Chat/Git/Profile/模型选择、Markdown/diff 引擎都不在本批。

本文件对旧设计中的领域组件归属和后续范围有优先权；C7 的作用域、代次、安全与回收等通用语义不变。Qoder 接到追加提示后由它单一写入自己的 spec/tasks/reports，不由主树会话同步修改活动树。

## 完成后的两个包

```text
packages/desktop-platform/
├── ui/                 # React 基础件：容器、布局、输入、反馈、主题样式
└── ui-components/      # 插件组件的注册/绑定/Outlet/选择/回收
```

`ui` 不依赖 `ui-components`，后者不强制依赖前者；插件可以组合使用，也可以只用其一。基础件直接 import，只有需要跨插件提供/替换的领域组件才注册。Workbench 继续负责页面/面板/浮层位置，不由 Card 或 registry 接管。
