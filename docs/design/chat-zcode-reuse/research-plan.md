# Research / Implementation Plan

## 1. 来源与已核实事实

固定来源：[ZCode 29628c9acdb81b703bbd4080c207a0e7ce5e276e](https://github.com/zai-org/ZCode/tree/29628c9acdb81b703bbd4080c207a0e7ce5e276e)。本机固定 SHA 源码已读取；未启动其完整产品做像素比较，所以以下是源码支持的实现与交互结论，不声称截图一比一。

路径均相对 `packages/ui/src/`。ZCode 根 Apache-2.0；ai-elements 文件另明确 Vercel 派生版权、Apache-2.0。保留 notices 和修改说明；若额外复制其他来源文件需另核许可。

关键现场：

- `v4/ConversationTurnGroup.tsx` 调用 `ToolCallBlock`；实际工具展示路径不是仅 ai-elements/tool。
- `v4/ConversationRowView.tsx` 的 ReasoningRowView 明确 streaming/complete 都默认收起；用户可展开，传 streamingText；不搬整段 V4 行模型。
- `ToolLayout.tsx` 有模块级 `toolLayoutOpenState` Map 与 memoryDiagnostics 注册；注释说明表只增不减。必须改实例所有权，不能原样移植。
- `ExecuteOutput.tsx` 向上阅读时冻结可见文本，回到底部恢复；这不是单纯“停止自动滚动”。移植必须让暂停/新输出可见，避免用户误以为运行停止。
- `message.tsx` 明确已完成消息改 static，禁正文动画；内建 code renderer 曾触发重复更新，当前用定制 CodeBlock。因此本方案不沿用旧 Agent UI 草案的默认 code 插件直接拼装。
- 主树现有 view 用 `@assistant-ui/react` 外部 store runtime 和通用 details 展示；它不是 ZCode 数据层。迁移不得同时保留两套消息/草稿权威。业务服务继续唯一，展示层更换需逐条保留原断言。

## 2. 模块取材单

| 目标 | 固定源文件/符号 | 保留什么 | 删除/替换什么 |
| --- | --- | --- | --- |
| MessageLayout | `components/ai-elements/message.tsx` 的 Message/MessageContent/MessageActions/MessageAction | 用户气泡、助手全宽、动作排列 | ai UIMessage 类型换本域 role；平台 Button/CSS 替代私有控件；不搬其 store/编辑器/文件动作 |
| MarkdownBody | 同文件 `resolveMessageStreamdownMode`、MessageResponse 的模式/错误fallback设计 | 真流式才 streaming，完成态 static；渲染失败保留原文；主题变更更新显示，正常 token 更新不重挂整段 | 不搬 ZCode citation、artifact reader、路径重写、browser/editor 服务；链接动作交消费方 |
| ReasoningBlock | `components/ai-elements/reasoning.tsx` 的 Reasoning/Trigger/Content 与 shouldAutoCollapseReasoning、底部锁定 helpers；V4 ReasoningRowView 的组合方式 | 默认折叠、轻量摘要、左竖线详情、手动选择优先、流式摘要、合理内容卸载 | 删除 test-id/intl/诊断依赖；耗时仅用真实传入值，不用 UI timer 冒充后端耗时；不用全局折叠缓存 |
| ToolFrame | `ToolCallBlocks/ToolLayout.tsx`、`ToolSummaryRow.tsx` | 紧凑摘要、详情惰性挂载、展开箭头、类型/目标/来源/状态的信息层次 | 模块 Map→视图会话级状态；业务模式布尔项不进公共契约；剪贴板走明确动作；Tooltip错误要有键盘可达替代 |
| CommandTool | `ToolCallBlocks/renderers/execute.tsx` 的 ExecuteToolCallBlock JSX 布局 | `$` 命令区域、有限高度输出、运行/失败/无输出的布局 | 不搬 bashOutputDisplaySchema/executionOutputPreviewSchema 和猜 command/cmd/script 的多协议解析；输入为归一化展示数据 |
| CommandOutput | `ToolCallBlocks/renderers/ExecuteOutput.tsx` + `components/ui/scroll-fade-viewport.tsx` | 约五行预览、用户上滚暂停跟随、底部恢复、渐隐遮罩、清理 observer/RAF | 删除 logger；恢复跟随入口与新输出提示补齐；只冻结局部显示快照，不冻结业务状态；切工具 ID 清快照 |
| GenericTool | `renderers/fallback.tsx` 的 summary/detail 组合思路 + ToolFrame | 不认识工具类型也可看输入/输出/错误 | 不搬 ToolCallBody、snapshot 获取服务、ZCode raw 对象；不能直接 JSON.stringify 任意含秘密的服务对象 |
| Composer | `components/ai-elements/prompt-input-textarea.tsx` 的键盘/composition/defaultPrevented 处理 | Enter、Shift+Enter、IME、建议先消费事件；输入与工具栏分区 | 删除 upstream controller/附件管理；不自动删除附件/清草稿；不搬 LexicalChatInput |
| ConversationScroll | `components/ai-elements/conversation.tsx` + use-stick-to-bottom | 接近底部跟随、主动阅读不抢、回底入口 | 不搬 messagesToMarkdown/Download/AI SDK；输入框在滚动视口外 |

### 摘要动画的明确裁决

`ToolCallBlocks/QueuedSummaryContent.tsx` 使用 motion/react，含 300ms transition、500ms hold、有界 pending queue 与 reduced-motion。初版**不移植这套排队动画**，直接显示最新摘要，避免为装饰加入动画运行时；保留类别行低强调、展开过渡和可关闭的轻微运行态效果。此为明确视觉差异，不能宣称逐像素复刻。用户若后续要求滚动摘要动效，再单列性能验收，不让实施者自行决定引入 motion。

### 代码块与依赖裁决

- 流式 Markdown 使用 `streamdown@2.5.0` + `@streamdown/cjk@1.0.3`，消费固定版本 API；复制上述模式判定和保底逻辑，不自己写 Markdown parser。
- 代码块使用自有薄 React wrapper + `shiki@4.0.2` 的公开 token API；不复制高亮算法。ZCode `code-block.tsx` 的语言/复制/换行标题结构可提取，**不搬 CodeViewer（依赖 @pierre/diffs、代码评论）及 Mermaid 分支**。
- 不启用 `@streamdown/code` 内建 renderer；明确替换 Markdown code 显示，先纯文本，异步高亮结果只应用于当前 code/language/theme 版本。原文是复制来源，未知语言或失败时保留文本；不得用任意 HTML 输出执行代码。
- `use-stick-to-bottom@1.1.3`、`lucide-react@1.17.0` 沿固定取材版本；React/Radix 使用平台集成基线已有锁版本。包可用性/peer/exports 在实施预检验证，版本不是已兼容证明，不自动追 latest。
- Streamdown 的必要样式由 Chat 自己构建和隔离；平台基础件不为 Chat 引入 Tailwind/Markdown。沿用取材研究的局部样式方案，但不得恢复旧 Agent UI 总包依赖清单。

## 3. 归属与目标内部结构

```text
plugins/chat/                       # 目标领域目录；实际迁移须先做映射
├── api/                            # 少量公开组件key + Chat贡献契约
├── frontend/
│   ├── entry.tsx                   # Workbench页面/侧栏/设置注册
│   ├── adapters/                   # 现有会话服务→展示DTO；无第二协议客户端
│   ├── state/                      # 草稿与会话级展示状态；不持有后端run权威
│   ├── views/                      # 页面组合、会话导航、固定底部输入区
│   ├── components/
│   │   ├── messages/               # 正文/思考/Markdown/code
│   │   ├── tools/                  # 紧凑摘要、命令输出、通用fallback
│   │   ├── interactions/           # 审批/提问，只消费业务动作
│   │   └── composer/               # 受控输入、附件、建议、工具栏
│   └── contributions/              # scoped扩展位置，不是另一个服务容器
├── tests/
└── upstream-manifest.json / licenses / THIRD-PARTY-NOTICES.md
```

先分清 UI 与服务所有权，再决定旧 agent-conversation/agent-sessions 的文件去向。本设计不把会话服务塞入 Chat、不假定旧插件 ID 可以改名。迁移要保留数据与 ID，不复活旧兼容链。

## 4. Chat 接入与外部扩展（本版边界，下一步冻结具体类型）

- 消费：现有会话公开服务、Workbench、平台 ui 与 ui-components；服务 API 按集成基线核实，不照抄历史报告里的 Token。
- 提供位置：会话标题动作、输入区工具栏、会话辅助区、设置章节、特殊内容块渲染。Provider/model/Profile 控件由其插件登记，Chat 不逐个 import 它们。
- 动作区贡献按 scope+唯一 ID 登记/回收，明确排序；渲染块用确定的 kind→组件 key 映射，不用任意 predicate 抢占链。新增 kind 后没有提供者时显示可读摘要，无隐式副作用。
- 平台 UI 注册只选择“这个组件谁实现”；Chat 贡献只决定“这个位置放什么”。不要做第二份实现 registry；内容贡献持 key/只读上下文，由 C7 Outlet 承担装载与 guard。
- 初期拟公开 MessageBody、ReasoningBlock、ToolActivity、Composer 四个组件契约，用于独立消费/替换；具体 key/props 在服务适配核实后统一冻结。ToolFrame/CommandOutput 等内部部件不全部注册。审批/提问展示先内部组合，确需跨插件消费再公开，不为凑数量制造 API。
- 贡献者缺席：对应配置/按钮消失，保存的数据不删除；历史内容没有专用 renderer 则保留摘要。卸载 UI 绝不停止运行或关闭通道。

## 5. 必须由 Ordessa 做的薄适配

只把服务已确认的 message/tool/interaction 状态转换成显示 DTO，保留未知态；工具类别来自现有结构化信息，无法确认就 generic。不能根据文字包含 bash/edit 就推测执行权限或成功。

折叠状态键包括会话稳定身份与 itemId；缓存只属当前视图/显式有限会话集合，销毁时回收。不得复制 ToolLayout 顶层 Map。Clipboard/file/open 外部动作统一传入，并遵守 generation 与业务校验。

UI 本地 pending 只防重复手势，不能替代原服务的接受/拒绝/未知结果、旧审批归属和停止证据。Agent 输出与思考分开，复制回答默认不混入隐藏思考或工具日志。

## 6. 上游验收而非“看着像”

实施者记录原文件 SHA256、保留符号/逻辑、目标文件、删去依赖、适配说明和许可证。用同一组受控内容留“源码可解释的目标外观 + Ordessa 截图”。没有可运行的上游 fixture 时如实写无像素基准，不伪造原版截图。

必要反例：同名工具跨会话不串展开；无输出与空/0/false区别；用户打开思考后状态变化不收起；静态历史不触发流式补全；代码高亮晚返回不覆盖新代码/主题；工具内部链接按 Enter 不双触发父行；输出冻结有恢复入口；卸载清 timer/observer；渲染失败原文保留；禁外部请求。
