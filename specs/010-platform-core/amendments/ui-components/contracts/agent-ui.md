# Agent UI 领域组件接口 v1

归属：`plugins/agent-ui/api`，建议导入名 `@ordessa/agent-ui/api`。只包含领域类型、单实例 key 和轻量消费 helper；不导入实现入口、业务 store、ACP SDK、Server 客户端或 ZCode services。第二版已扩展至 12 个接口，完整能力见 [组件总览](../component-catalog.md)。本文保留四项较详细的 TS 草图，尚不是完整的可编译 API；后续冻结类型时须按总览一起补齐。

下列四项草图的 key：`ordessa.agent-ui.conversation`、`ordessa.agent-ui.composer`、`ordessa.agent-ui.approval`、`ordessa.agent-ui.configuration-state`，major 均为 1。实际符号名分别为 `ConversationViewKey`、`ComposerKey`、`ApprovalViewKey`、`ConfigurationStateKey`。其他八项按组件总览中的 key 后缀声明；每项 props 与 key 一起形成公开 API。

默认实现的 providerId 建议均为 `ordessa.agent-ui.default`，唯一键是 `(组件 key, providerId)`，不是 providerId 单独全局唯一。一个普通 Agent UI 扩展可一次注册本批已实现的多项组件，不要求 loader 支持一个 entry 返回多个插件。替代插件可只提供其中一个接口。未实现的 key 不登记实现。

## 1. 数据和动作共同约定

- UI 数据是业务状态的只读投影。所有列表 readonly；增量更新提交新快照，不在组件里解析 ACP 事件或维护第二份会话权威状态。
- ID 由消费者分配并在其会话范围内稳定；渲染 key 同时包含 conversationId 与 itemId，不把不同 Harness 的同名原生 ID 当同一消息。
- API 的 ID 都是不透明字符串，不要求 Server/Harness 的四元 ref；真实引用由消费者保存在回调闭包中。
- 动作采用平台 `UiAction<Input>`，accepted 仅代表操作已被业务接纳。最终状态必须来自后续 props。
- 非文本数据不得作为原始 HTML 注入；URL/文件打开请求交回消费者执行。远程图片默认不直接加载，由消费者提供已允许的显示资源或占位。
- `ReactNode` 插槽仅接收本产品已加载扩展的可信组件；用户文本走结构化内容字段。
- locale、主题、排版方向使用平台已有上下文；组件不可硬编码品牌、模型或凭据字段。

## 2. ConversationView

```ts
type DisplayContent =
  | { kind: 'text'; text: string }
  | { kind: 'markdown'; text: string }
  | { kind: 'reasoning'; text: string; state: 'streaming' | 'complete' | 'interrupted' }
  | { kind: 'tool'; tool: ToolDisplay }
  | { kind: 'attachment'; attachment: AttachmentDisplay }
  | { kind: 'approval'; approval: ApprovalDisplay }
  | { kind: 'unsupported'; label: string; text?: string };
interface MessageDisplay {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'notice';
  authorLabel?: string;
  state: 'streaming' | 'complete' | 'interrupted' | 'error' | 'unknown';
  parts: readonly { id: string; content: DisplayContent }[];
}
interface ConversationViewProps {
  conversationId: string;
  messages: readonly MessageDisplay[];
  history: 'not-loaded' | 'loading' | 'partial' | 'complete' | 'error';
  historyMessage?: string;
  activity: 'idle' | 'running' | 'stopping' | 'waiting-for-input' | 'unknown';
  connected: boolean;
  onLoadEarlier?: UiAction<void>;
  onOpenAttachment?: UiAction<{ attachmentId: string }>;
  onOpenLink?: UiAction<{ href: string }>;
  renderApproval?: (approval: ApprovalDisplay) => React.ReactNode;
  header?: React.ReactNode;
  empty?: React.ReactNode;
  footer?: React.ReactNode;
  ariaLabel: string;
}
```

默认实现：贴近底部时跟随新增内容；用户向上阅读时不抢滚动，显示“有新内容/回到底部”入口；conversationId 切换后重置本地滚动/折叠状态。历史只通过显式 onLoadEarlier 请求，不轮询。不得把 connected=false 显示成“运行已结束”。不支持内容显示 unsupported 占位，不静默丢掉。

内嵌审批由消费方通过 renderApproval 装入独立 ApprovalView 绑定；回调缺席时只显示审批描述和“此处不可操作”，默认实现不自行导入或查找另一个提供者。这样替换 ApprovalView 可作用于对话和独立工作面板，不要求 Conversation 实现依赖其实现。

```ts
interface ToolDisplay {
  id: string;
  label: string;
  state: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown';
  argumentsText?: string;
  resultText?: string;
  resultFormat?: 'text' | 'markdown' | 'json';
  errorMessage?: string;
}
interface AttachmentDisplay {
  id: string;
  name: string;
  mediaType?: string;
  byteLength?: number;
  preview?: { kind: 'image'; src: string; alt: string }; // 由消费者授权的显示资源
  state: 'ready' | 'loading' | 'unavailable';
}
```

文本/Markdown/JSON 是工具结果的基础表达。第二版另有 ToolActivity、ResourcePreview、ChangeReview 等接口，Conversation 的内容类型与渲染入口在正式冻结时按总览补齐；交互终端和品牌专有 SDK 对象不直接塞进消息 DTO。不能靠任意 `any` 属性规避适配。

## 3. Composer

```ts
interface ComposerProps {
  draftId: string;
  text: string;
  attachments: readonly AttachmentDisplay[];
  interaction: 'editable' | 'read-only';
  send: { enabled: boolean; pending: boolean; reason?: string };
  stop?: { enabled: boolean; pending: boolean; reason?: string };
  placeholder?: string;
  onTextChange(text: string): void;
  onSubmit: UiAction<{ draftId: string }>;
  onStop?: UiAction<void>;
  onPickAttachments?: UiAction<void>;
  onRemoveAttachment?: UiAction<{ attachmentId: string }>;
  suggestions?: {
    items: readonly { id: string; label: string; description?: string; disabledReason?: string }[];
    onChoose: UiAction<{ id: string }>;
  };
  beforeInput?: React.ReactNode;
  toolbar?: React.ReactNode;
  footer?: React.ReactNode;
  ariaLabel: string;
}
```

文本、附件和发送可用性由消费者控制。组件提交后不自行清空草稿；明确接纳/拒绝/未知结果由 Chat 按业务规则更新。按钮触发 pending 后应防重复手势，消费者仍承担幂等和“已发送”判定。

IME composition 期间 Enter 不提交；默认 Enter 提交、Shift+Enter 换行。建议项选择与提交事件不能同一次按键双触发。文件选择交回 onPickAttachments；拖入和粘贴通过可选的文件接收回调交回业务，正式类型需按总览补齐，不暗中读取或上传文件。

Profile、provider/model 和其他贡献的注册仍在 Chat；Composer 只呈现传入 toolbar 等布局位置，不认识这些插件。draftId 切换清除输入框内部建议高亮等本地状态；text 由新 props 决定。

## 4. ApprovalView

```ts
interface ApprovalDisplay {
  id: string;
  title: string;
  description?: string;
  state: 'pending' | 'submitting' | 'resolved' | 'unavailable' | 'unknown';
  options: readonly { id: string; label: string; description?: string; disabledReason?: string }[];
  selectedOptionId?: string;
  statusMessage?: string;
}
interface ApprovalViewProps {
  approval: ApprovalDisplay;
  onChoose: UiAction<{ approvalId: string; optionId: string }>;
  ariaLabel: string;
}
```

只有 pending 且选项未禁用时可操作。submitting/resolved/unavailable/unknown 均不可提交。选项来自业务服务，不根据名称猜“允许一次/永久允许”，不将 missing 选项造为许可。resolve 状态仍可作为历史卡片展示；是否从待办区移除由业务插件决定。

审批状态变化与 UI generation 是两种校验：平台防旧实现回调，业务服务防旧 run/旧审批提交；两者都要保留。

## 5. ConfigurationState

```ts
interface ConfigurationStateProps {
  label: string;
  valueLabel?: string;
  origin: 'default' | 'profile' | 'session';
  application: 'effective' | 'pending' | 'applying' | 'failed' | 'unsupported' | 'unknown';
  explanation?: string;
  onResetOverride?: UiAction<void>;
  onApply?: UiAction<void>;
  children?: React.ReactNode;
}
```

来源与生效状态是两个独立维度。例如“来自 Profile”可以同时“待下轮应用”，不能合成一个成功徽标。组件呈现说明及可用动作，字段编辑器由业务插件传入 children。Profile 提供者缺席时，对应配置区不注册/隐藏，保留数据；不靠本组件展示成报错字段。

不包含统一 provider/model 实体、技能配置 schema 或通用配置持久化。第二版明确提供 EntitySelector 与 ConfigurationSection，分别表达选择和配置区；它们消费由业务转换的数据，详细范围见组件总览。

## 6. 依赖方向和消费示意

```text
Chat / Profile / Model-provider
  ├── import Agent UI API 的 key 和 props
  └── requires UiComponentsToken
        └── 绑定 key → ComponentOutlet

Agent UI 默认插件
  ├── import 同一 Agent UI API
  └── requires UiComponentsToken
        └── scope.registerBatch(当前已实现的组件)
```

组件提供者不依赖 Chat/Profile/Harness 服务；业务数据转换在消费者内部。领域 API 独立构建、独立可导入，但不要求 API 自己成为运行时插件，也不创建空 activate。构建必须证明默认实现未启用时 API 仍能加载。
