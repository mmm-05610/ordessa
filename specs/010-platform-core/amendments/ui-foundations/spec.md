# Feature Specification：通用基础件与开放组件装载

Created：2026-09-27。分支：沿用 `codex/010-platform-frontend`。范围：C7 保持 + C8 基础件增补。

## User Scenarios & Testing

### US1（P1）：插件组合基础 UI 而不重造容器

独立验证：无 runtime、无 Workbench、无业务插件的普通 React 根。

- Given 插件需要一个带标题与工具栏的框，When 组合 Card/Panel/Toolbar/ScrollArea，Then 头尾可固定、内容独立滚动，完全由 children 决定内容。
- Given 两个并列表单，When 输入与校验状态改变，Then 仅调用提供的事件，不自行保存、提交网络请求或计算业务规则。
- Given 禁用/只读输入或图标按钮，Then 原生键盘语义、可访问名称与焦点表现正确。

### US2（P1）：新增组件种类不修改平台

独立验证：两个独立构建的受控扩展共享自己的测试领域 API；该 API 不位于平台 foundation carrier。

- Given 测试提供者定义新 key，When 注册并被消费，Then 平台零源码改动即可在 Card 内装载；props 静态类型匹配。
- Given 消费者关闭或提供者卸载，Then 遵守既有 C7 回收与旧动作失效语义；Card 不需要知道被装载组件的种类。
- Given 组件仅在插件内部使用，Then 可直接组合，无需注册 key、provider 或装配选择。

### US3（P1）：宿主中一致呈现且不互相污染

独立验证：同一浏览器展示裸 React 根、Workbench 内容区及已有浮层中的相同 fixture。

- Given 插件使用基础件，Then 遵循既有主题；样式不改变相邻非基础件 DOM。
- Given 加载了 Workbench 的 `.wb button` 等现有宽选择器，Then 基础按钮仍保留规定的状态、尺寸与焦点；不靠卸载 Workbench CSS 测过。
- Given 浮层打开，Then 内容组件不再创建一套 portal、焦点圈或 Escape 管理器。

## Functional Requirements

- **F01**：基础件只含 DOM/React 展示能力，不认识 Git/模型/Profile/审批/运行状态，不依赖插件、app、产品或 Workbench 实现。
- **F02**：平台接受插件自定义 key；保留 C7 类型约束、冻结产品选择、scope、原子批次、generation、错误隔离和 guard；不新增公共业务 key 清单。
- **F03**：基础件组合使用 children/明确子部件；不设置 isChat/isGit/approvalMode 等业务参数。
- **F04**：输入值受控；表单只提供 label/description/error 布局，不自带 schema、持久化、自动保存或请求。
- **F05**：基础件导入无自动注册、DOM 注入、全局监听副作用；CSS 通过公开显式入口由装配加载。
- **F06**：继承主题、支持原生键盘与 aria、窄容器、reduced-motion；组件外样式不受污染。
- **F07**：`ui` 与 `ui-components` 能独立使用；静态 Card/Button 不需要服务 Token 或注册表。
- **F08**：保留 C7 原门禁并增加基础件/实际组合门禁；不为了新方案删除既有反例。

## Key Entities

基础件 props/children、受控输入值、展示状态（busy/disabled/invalid）、组件 key/binding（沿 C7）、语义 theme tokens。没有业务实体或新数据库。

## Success Criteria

- S01：plan 中最小公开基础件均可独立导入、渲染和组合，不启动业务服务。
- S02：受控新领域组件在 Card 中经真实 C7 装载，平台实现不增加任何领域名称判断；实际独立构建证明共享 key 身份。
- S03：360px/768px 两种容器、深浅主题，裸根与 Workbench 环境通过几何/键盘检查，页面无意外横向溢出。
- S04：C7 U01–U16 与 C8 V01–V08 全有证据；原测试 ID 无未解释退化。

## 非目标

不创建 Agent UI、Git、Profile、Chat 新业务；不迁移所有旧 UI；不引入 Markdown、Diff、富文本、图表/虚拟化引擎；不新建 Dialog/Popover/全局 overlay 系统；不做在线主题编辑器或在线 provider 选择；不修改后端。
