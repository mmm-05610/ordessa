# Data Model / Contract completion

权威语义为相邻 `agent-ui-contracts` 的总览与公共约定。本批补齐 TS 声明，不新增持久化数据模型。

| 数据 | 权威所有者 | UI 允许持有 |
| --- | --- | --- |
| messages / tool records / run status / usage | 消费业务插件 | readonly 快照；稳定展示 ID |
| draft text / attachments / answers / selections | 消费业务插件 | 受控值；onChange 不代表保存 |
| Profile 来源 / overrides / application status | Profile 与字段提供者 | 已计算标签和状态，不计算合并 |
| file/resource/diff | 消费业务插件 | 展示文本、已授权资源与动作；不读取磁盘 |
| expanded / active suggestion / search / scroll | 当前 UI 实例 | 本地 state，conversationId/draftId 换代时重置 |
| provider generation / binding status / action validity | C7 UI 服务 | 消费平台机制，不自建 generation |

## 完整类型产物

`api/conversation.ts`：MessageDisplay、DisplayContent（包括 12 项目录需要的嵌入类型）、ConversationViewProps、ComposerProps。
`api/interaction.ts`：ToolActivityProps、ApprovalViewProps、QuestionViewProps。
`api/configuration.ts`：EntitySelectorProps、ConfigurationSectionProps、ConfigurationStateProps。
`api/review.ts`：ResourcePreviewProps、ChangeReviewProps。
`api/work.ts`：WorkProgressProps、RunSummaryProps。
`api/keys.ts`：12 个单实例 key；major=1；禁止消费者复制创建。

所有 API 仅类型、key、轻量组合 helper；不得 import src、CSS、Streamdown、Radix、业务 SDK。公共 props 不泄漏上游 AI SDK/工具专属枚举。React 类型与可信 ReactNode slot 允许。

## 三项补齐规则

1. Question 用明确 discriminated union 表达 single/multiple/text/textarea；答案按 questionId 关联，选项 ID 不从标签生成；必填/输入长度可做表单反馈，业务校验仍由回调所有者负责。
2. Conversation 嵌入 Tool/Approval/Question/Resource/Change/Progress 的 renderer 由消费方经独立 binding 组成。缺 renderer 显示类型+可读摘要，无动作；默认实现不直接调用另一提供者。允许 API 层轻量组合 helper，不允许把具体实现藏在 helper。
3. Action 使用 C7 的实际公开类型与 guard；不按草图复制另一份类型。pending 手势锁防双击，最终 succeeded/cancelled 只来自 props。guard 解决提供者换代，业务服务仍须验证 run/审批归属，两者不可替代。

字段命名/类型精化可按以上语义完成；新增配置规则、改未知状态、扩大副作用、删除既定能力必须作为契约差异上报，不能以实现便利为由自行裁决。
