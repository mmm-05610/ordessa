# Chat 公共契约与贡献位置 v1

状态：设计冻结候选，尚非已发布 TypeScript API。本文定义可接受语义，实施类型必须与 C7 实际 UiComponentKey/UiAction/ResourceScope 一致；不在 Chat 复制平台 Token 或 generation。

## 1. 三种注册不要混淆

| 机制 | 注册的是什么 | 所有者 |
| --- | --- | --- |
| Workbench | Chat 模块、侧栏/主视图、设置章节、浮层位置 | Workbench |
| UiComponents | 某个类型化组件 key 的具体实现，产品选择用谁 | 平台 C7 |
| ChatContributions | Chat 页面某处要放哪个已定义组件、如何提供 props | Chat |

ChatContributions 只管理贡献描述符及其 scope，不保存组件实现，不选择 provider，不调度插件。贡献使用 C7 key 和 Outlet；普通 Chat 内部组件不必注册。

平台不出现 Chat 的 slot 名字。Chat 不 import ModelProvider/Profile/Git 实现。新的字段提供者只增加自己的插件代码及必要产品装配，不改 Chat 的分支判断。

## 2. 六个 UI 扩展位置

v2 另新增结构化输入来源 `addInputSource`（见 input-contracts.md），供 + 与 / 共用；它不是第七个任意组件挂载位置，也不替代本表。

| 位置 | 可见上下文 | 适用例子 | 缺席行为 |
| --- | --- | --- | --- |
| `composer.toolbar` | 当前 draft/session 身份、只读连接/运行状态 | Profile、provider/model 选择器、Skill 选择 | 不占空位；核心发送/停止不依赖它 |
| `session.actions` | 当前已打开 session 身份 | 明确的外部动作入口 | 不显示；草稿中不实例化 |
| `session.auxiliary` | 当前 session 身份、运行状态 | 上下文使用量、资源说明 | 不显示；默认不自动打开浮层 |
| `message.actions` | session 身份 + messageId + 只读消息状态 | 引用、保存、由服务支持的分支操作 | 不显示；不默认暴露完整消息内容 |
| `settings.sections` | locale/主题等展示环境，无当前会话 | Chat 扩展自己的设置区 | 移除章节，不删除任何配置 |
| `content.renderers` | 指定内容块的 kind、可读摘要、只读 payload | Git Diff、特定资源预览 | 保留类型/摘要或原始文本，禁用专有动作 |

平台基础 Toolbar 负责排列，不负责发现插件；Chat 将对应贡献装入它。`session.auxiliary` 是 Chat 页面上的内容区，不是另一个工作台 docking 系统；贡献要开窗口时使用已有 Workbench 服务。

暂不开放任意 `beforeSend`/`afterSend`、审批拦截、消息改写或私有 store 访问钩子。展示扩展不能截获或悄悄改写待发消息。

## 3. 上下文与目标安全

Chat 提供只读 `ChatLocation`：

```ts
// 示意。SessionTarget 应引用集成基线领域 API 的真实身份类型；不得创造第二路由标准。
type ChatLocation =
  | { kind: 'draft'; draftId: string; connectionId?: string; serverInstanceId?: string;
      projectId?: string; harnessId?: string; contextRevision: number }
  | { kind: 'session'; target: SessionTarget; projectId?: string; harnessId?: string;
      contextRevision: number };
```

- 字段不存在就缺席；不能从 title、插件 ID 或 endpoint 猜 server/harness 身份。当前基线能提供的字段见 service-adaptation。
- 位置上下文不提供凭据、完整历史、服务实例、任意命令执行口或 `getAllServices()`。
- 字段插件用自己的服务读取/应用配置，Chat 只给目标。无可用目标时应显示选择前置条件或隐藏，不落到全局配置写入。
- `contextRevision` 只用于 UI 防陈旧上下文，不替代服务目标引用。会话切换/草稿身份变化时旧贡献动作失效；旧异步返回不可更新新会话控件。
- C7 generation 防提供者换代；Chat 位置 revision 防同一提供者跨会话串动作；业务服务仍负责目标/审批/run校验。三者不可相互替代。
- 这不是恶意代码安全沙箱：可信插件仍有自身服务权限；上下文约束用于明确依赖与避免误操作，不宣称隔离不可信插件。

若现有配置服务仅有“修改当前选中会话”而无目标参数，就不能把它包装成任意 target API。先保留既有选择上下文并在调用入口校验；真正跨会话配置要单独补服务契约，不属于外观移植暗改。

## 4. 贡献描述符

公开 API 归 `plugins/chat/api`，拟 `ChatContributionsToken`。若集成基线上已存在同义契约，复用并迁移，不创建第二 Token。

每条贡献有稳定 namespaced `id`、明确 slot、整数 `order`、类型化 `UiComponentKey<P>`、纯投影函数 `context → hidden | props`。用泛型工厂封装成不透明贡献记录，保证 key 与 props 对应；不能公开 `any` 数组规避校验。不允许提供者提交任意 `ownerId`，所有权来自 `forScope(hostIssuedScope)`。

- `forScope(scope).add(contribution)` 返回幂等 disposal；关 scope 自动撤回。重复 ID 拒绝，不采用最后写入者覆盖。
- 固定 slot 内按 order、id 排序；顺序不取决于加载时机。不提供越过别人调整排序的接口。
- projection 同步纯计算，不 fetch、不 subscribe、不修改服务；需要数据的已注册组件依赖自己的公开服务并在 scope/React 生命周期内清理。
- contribution 撤回时取消它的位置订阅/绑定，不能撤掉别人的 UI provider。provider 存在但 contribution 缺席时不装载；contribution 存在而 optional provider 缺席时隐藏。
- 投影或 render 抛错只隔离本条贡献，显示本条简洁错误与通用诊断；不能把真实错误当 optional 缺席静默隐藏。
- toolbar/settings 等贡献缺席不影响原有发送/停止/审批能力。数据删除不是 UI 卸载动作。

## 5. 特殊内容 renderer

`content.renderers` 使用稳定 `contentKind`（如插件拥有的 namespaced kind）与 key 建立一对一映射；同 kind 重复注册显式拒绝，禁止按优先级/任意 predicate 抢占。实现替换走同一个 key 的 C7 产品选择，不另做优先级系统。

payload 不是无约束 `any`：贡献需声明解码/校验边界，校验函数为纯函数，失败显示可读 fallback，不执行动作。可信内置 DTO 可直接按类型使用；跨协议未知数据必须验证后交组件。Chat 不负责理解插件专有 payload 内容。

内容 kind 来自真实结构化数据或显式业务投影，不能仅靠工具名称/文本中有 diff 就推断存在 Git 审阅能力。本批通用工具仍有原文 fallback；Git 专业 renderer 不在 Chat 实施范围。

## 6. 第一版四项可替换展示接口

同一逻辑 Chat 领域 API，key 的 major=1。默认 provider ID 拟 `ordessa.chat.default`；最终插件 manifest ID 保持现有标识或走明确迁移，provider ID 不等于擅自重命名持久 extension ID。

| key 后缀（前缀 ordessa.chat） | 必须输入 | 可选明确动作 | 本地状态 |
| --- | --- | --- | --- |
| `message-body` | conversationKey/messageId、role、正文、streaming/complete/interrupted/unknown、显示选项 | 打开已验证链接、复制可见正文 | 代码换行/展开；不读消息服务 |
| `reasoning` | conversationKey/partId、文本、streaming/complete/interrupted/unknown、可选真实 duration | 复制（消费方明确提供才显示） | 默认折叠；用户选择优先 |
| `tool-activity` | conversationKey/toolId、title、state、可读参数/输出、可选结构化 command 展示、截断/错误说明 | 查看完整输出、复制、打开关联内容 | 展开与输出跟随，按身份回收 |
| `composer` | draftId、受控 text、editable、send/stop 的 enabled/pending/reason、工具栏 children | text change/submit/stop；服务有能力才有附件/建议回调 | 焦点、建议高亮、输入法；不保存草稿 |

`ToolActivity` 不自行解释 ZCode raw 或品牌 tool schema；Unknown 与 Failed 不混淆，已有 completed 不等于“审批通过”。结构化 command 不存在就 generic 展示，不伪造命令详情。

交互结果采用实际平台 UiAction；accepted 不是业务最终成功。复制正文不默认带入思考/日志。复用者可在没有 Chat 页面时绑定这些组件，但需要默认提供者确实已启用；仅 import API 不会启用 Chat。当前不额外拆一个必需的 Agent UI 插件，若以后要独立安装提供者再另批物理拆分。

Conversation 的滚动容器、ToolFrame、CommandOutput、审批与提问面板仍为 Chat 内部组件；不为所有内部函数创建公共 key。

## 7. 三个接入样例（依赖无环）

1. Model-provider：提供自己 model-selector key/实现；可选连接 ChatContributions，登记 composer.toolbar；props 带 location。模型数据与应用接口来自自己的服务及 Harness 配置能力，不经 Chat 保存。Chat 不在时独立设置仍能运行。
2. Profile：同样登记选择器；配置全局/会话覆盖语义归 Profile，不在 Chat 计算。卸载 Profile 后选择器消失，当前会话已有配置不被重置。
3. Git：提供自己的 diff key/实现；有结构化 diff 引用时登记内容映射。没有 Git 时通用原文仍可阅读；Chat 不 required Git。

可选接缝使用现有宿主可选服务生命周期。如果其语义会随 Chat 卸载连带停止整个业务插件，必须将 UI 接入放在独立轻量 glue 扩展入口（同业务域目录），保持后台能力继续运行；不能为了接入 UI 强制整个 Model-provider/Profile 依赖 Chat。具体装配按集成宿主 API 校验，不改宿主调度器。
