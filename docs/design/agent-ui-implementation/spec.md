# Feature Specification: 可替换的 Agent UI 默认组件

**Feature Branch**：拟 `codex/agent-ui-default`，未创建。
**Created**：2026-09-27。**Status**：Draft for approval。
**Input**：预先决定复用项目与移植方式，让无人值守实施者按既定边界完成，不重新设计架构。

## User Scenarios & Testing

### US1：业务插件使用现成对话组件（P1）

业务只提供消息和受控草稿，即可展示流式内容、思考、工具及输入区。不导入默认实现。

独立验证：受控消费扩展通过真实 UI 服务绑定 Conversation/Composer/ToolActivity；没有 Chat/Server 也能操作。

1. Given 用户正在读历史，When 新 token 到达，Then 阅读位置不被抢走，可显式回到底部。
2. Given 中文输入法正在选字，When Enter，Then 不提交；普通 Enter 提交恰一次，草稿仅随 props 改变。
3. Given 相同消息 ID 位于不同会话，When 切换会话，Then 不串折叠、消息和草稿状态。

### US2：安全处理审批与提问（P1）

独立验证：Approval/Question fixture，不含真实 Harness。

1. Given pending 审批，When 选择业务提供的选项，Then 只提交原始 ID；submitting/resolved/unknown/unavailable 不可提交。
2. Given 多题受控答案，When 编辑并提交，Then 不预选、不丢多选/自由文本；提交结果不由 UI 猜测。
3. Given 提供者被卸载，When 旧回调被调用，Then 动作被 guard 拒绝，不调用业务。

### US3：配置界面共享表现但不共享业务规则（P1）

独立验证：同一个 EntitySelector 分别显示虚构模型、Profile、Skill；ConfigurationSection/State 只接收展示投影。

1. Given 来源是 Profile、生效状态是 pending，Then 两个维度分别显示，不报已应用。
2. Given 消费方移除某配置区，Then UI 消失、零删除数据调用；不出现伪错误占位。
3. Given 选项 unavailable 或加载失败，Then 原选中值仍诚实可见，不自动选另一项；重试必须有显式动作。

### US4：独立审阅内容与观察工作（P2，仍属本批必做）

独立验证：ResourcePreview/ChangeReview/WorkProgress/RunSummary 单独置于窄面板及主区。

1. Given 未知运行状态或部分用量，Then 不推断成功、不把缺失用量当零。
2. Given 大型/损坏 diff，Then 有文本与截断说明，不白屏、不静默删内容、不执行补丁。
3. Given 用户文本含 HTML/危险 URL/远程图片，Then 不执行脚本、不自动导航或请求外部图片。

## Requirements

- **FR-001**：全部 12 项接口必须有真实默认实现；API 独立可导入，默认提供者缺席仍能解析 key。
- **FR-002**：消费者只依赖 API + 平台 UI 服务；默认实现不得依赖 Chat/Profile/Harness/Server/store。
- **FR-003**：复制来源、提交、文件、保留符号、修改说明与许可证必须逐文件可追溯；禁止未经登记的整目录复制。
- **FR-004**：输入状态受控，所有业务副作用由显式回调完成；UI 仅拥有展开、焦点、搜索词、滚动等展示状态。
- **FR-005**：未知状态、部分历史、缺席实现、失效动作分别表达。不得以漂亮 UI 掩盖数据不完整。
- **FR-006**：提供者替换、卸载、重激活遵守 C7 generation；组件不复制平台错误边界和注册表。
- **FR-007**：支持键盘、焦点可见、深浅主题、reduced-motion、中文输入；Portal 不绕过现有浮层容器/主题。
- **FR-008**：内容渲染离线可用；字体、语法资源不得从 CDN 加载；外部链接/附件交消费者授权动作。
- **FR-009**：不引入业务持久化、网络客户端、轮询、命令执行、全局状态库或第二个聊天运行时。
- **FR-010**：本批无真实模型调用；浏览器几何证据和受控对端证据不得称为真实多 Harness 联调。

## Edge Cases

空/部分/错误历史；空字符串与数值 0 的工具结果；超长代码行；中文和英文混排；未闭合 Markdown fence；嵌套审批缺席；同一动作快速双击；重激活前旧异步回调；diff 无 hunk/rename-only/多文件/截断；选中项暂不在过滤结果；modal 中 selector；高对比与键盘无鼠标；组件报错不吞相邻内容。

## Success Criteria

- **SC-001**：12/12 组件可在不加载业务服务的受控 gallery 展示，且各有正常、空/缺席、失败/未知、可操作/禁用夹具。
- **SC-002**：替换单个 ToolActivity 提供者，只改变对应区域；Conversation/Composer 不被重置，缺席时保留可读描述。
- **SC-003**：US1–US4 的每条验收场景有定位到测试的 evidence 索引；禁止靠固定测试总数代替行为覆盖。
- **SC-004**：真实构建后的 provider 与 consumer 使用同一个 API key/React；关闭默认提供者时 API 加载成功、受控业务调用次数为零。
- **SC-005**：在 360px 窄容器、768px、1280px，深浅主题下无页面级横向溢出；代码/diff 自身允许横向滚动。
- **SC-006**：所有新增失败为零；继承失败按 ID/原因比较。浏览器未运行只能报该门未验，不能用 jsdom 冒充。

## Assumptions / Non-goals

C7 提供中性组件设施；本批不重塑它。正式使用现有平台公共控件若不存在，可在 Agent UI 内用原生元素/Radix 做私有薄封装，不因此扩建核心。暂不做富文本 Lexical 编辑器、交互终端、PDF/Office 渲染、Mermaid 执行、可编辑 diff、任务调度、自动重试与模型品牌管理。
