/goal 继续当前前端工作树 `codex/010-platform-frontend` 的 C7，并完成 C8 通用 UI 基础件增补。最终要求：原 T030–T036 与 U01–U16 保持全部完成，新 UIB001–UIB008 与 V01–V08 全部有真实证据，增量报告达到 C7_C8_IMPLEMENTATION_REVIEW_READY。阶段提交是检查点不是停点。不重做已经合格的 C7，不清理、覆盖或 reset 当前未提交成果。

先读取当前工作树 AGENTS.md、apps/desktop/AGENTS.md、010 constitution、C7 权威契约/任务/报告，再读取以下主树设计文档（只读）：

`/home/maoqh/projects/ordessa/docs/design/platform-ui-foundations/README.md`
`/home/maoqh/projects/ordessa/docs/design/platform-ui-foundations/spec.md`
`/home/maoqh/projects/ordessa/docs/design/platform-ui-foundations/plan.md`
`/home/maoqh/projects/ordessa/docs/design/platform-ui-foundations/tasks.md`

这是用户最新架构裁决：保留 `packages/desktop-platform/ui-components` 的通用注册/绑定/装载/选择/回收机制；新增 `packages/desktop-platform/ui` 作为可直接 import 的通用基础件。领域组件由各业务插件自己定义契约、注册实现；平台不枚举业务组件。撤销此前统一 `plugins/agent-ui`、12 项领域组件总包及统一默认提供者的实施要求。之前的领域草图只保留历史/取材价值，不作为本线约束，不能把它们搬到核心。

先由你单一写入本线 specs：复制上述四份文档为 amendments/ui-foundations 快照；更新权威链、tasks 与范围说明，保留旧 C7 通用语义和测试。不要修改主树里的设计文档，也不要让其他会话同时改这份工作树。

两个包严格分工：ui 用 React/原生控件/scoped CSS 提供 Card、Panel、布局、工具栏、滚动区、表单控件与通用反馈，按 plan 的有限清单实现；ui-components 提供开放的类型化组件机制。ui 不依赖 registry，registry 不强制依赖 ui。Card 通过 children 装载内容，不增加 componentId/providerId 或业务模式。组件注册和 Workbench 页面/浮层贡献位置不是一回事；本轮不重写 Workbench、不建立第二套 Dialog/Portal/焦点管理器。

主代理负责契约、边界、文档、派发、审阅、亲自复验和 git；生产实现派单包子代理，同包单写者。已有 C7 子代理可继续通用任务，不要为这次裁决强行推翻；ui 可由另一子代理独立实现，待公共类型冻结再接线。共享 lock、carrier、产品装配指定唯一写者串行处理，测试串行运行。

复用当前 React/ResourceScope/Lumino/真实构建机制；本轮无需引入 ZCode、Markdown/diff 引擎、Tailwind、Agent UI runtime 或新服务定位器。基础容器使用组合模式，不堆 isChat/isGit 等布尔参数。保持主题继承、显式样式加载、基础件外零样式污染，必须在实际 Workbench 样式环境验收。

允许写入仅限计划规定的两个包、必要的通用 exports/build/产品样式接线/测试聚合、本线文档。不得改业务插件、Python/Go、其他工作树、根 main；不启停用户服务、不调用模型、不 push、不自动合并。C8 不能借机扩大 host/loader 行为。

遇到类型、路径、构建、夹具、样式等本范围问题自行查清修复并继续；一个任务阻塞时继续其他独立项。确需改变冻结契约/安全语义或外部条件阻塞全部剩余项时，一次提交最小裁决问题及证据，不能私造兼容层、skip 或放宽断言。所有成果按 Spec Kit tasks→tests→evidence 对齐，原测试按 ID/原因比较；受控组合不冒充真实业务接入。全部标准满足后提交可审阅检查点、报告剩余未验边界并停止待审。
