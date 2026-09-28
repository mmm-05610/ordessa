# Research：逐模块复用裁决

## 1. 固定来源与证据等级

主要源码：[zai-org/ZCode @ 29628c9acdb81b703bbd4080c207a0e7ce5e276e](https://github.com/zai-org/ZCode/tree/29628c9acdb81b703bbd4080c207a0e7ce5e276e)。下表路径均相对 `packages/ui/src/`，不是让执行者再找近似文件。该快照在本机已读取，路径和符号已核对；**尚未在 Ordessa 编译移植，不能声称兼容性已经验证**。

复用分三种，交付时必须如实区分：

- **S 源码移植**：保留具体函数/组件结构或算法，改类型/依赖/样式，保留许可与修改记录。
- **L 库消费**：声明依赖，使用公开 API，不复制库实现。
- **O 自有薄适配**：Ordessa 特有状态/动作/布局组合。不得以“参考”冒充已经复用源代码。

## 2. 12 项实现配方

| 接口 | 确定来源 | 保留与改造 | 明确不搬 |
| --- | --- | --- | --- |
| ConversationView | S `components/ai-elements/conversation.tsx` 的 Conversation/Content/EmptyState/ScrollButton；`message.tsx` 的 Message/MessageContent/MessageActions/MessageAction；L use-stick-to-bottom；L Streamdown | 保留跟随/手动脱离、用户/助手排版与动作区域；替换角色类型、标签、CSS；内容块按本域 DTO 组合 | ConversationDownload/messagesToMarkdown、AI SDK UIMessage；message.tsx 其余文件操作、store、编辑器、浏览器集成 |
| Composer | S `components/ai-elements/prompt-input-textarea.tsx` 的 Enter/Shift+Enter/composition 与 defaultPrevented 优先逻辑 | 受控 textarea；建议菜单先消费键盘事件；文本和附件回调归业务；用现有平台/Radix 基础控件构成工具栏 | usePromptInputAttachments/controller、自动删除附件、隐式上传；ChatPromptEditor/LexicalChatInput 全量编辑器 |
| ToolActivity | S `components/ai-elements/tool.tsx` 的 Tool/ToolHeader/ToolContent/ToolInput/ToolOutput 布局 | 用领域六态重写状态适配；input/output 折叠与代码区保留；false/0/空结果不得因 truthiness 被隐藏 | ai ToolUIPart/DynamicToolUIPart；ToolCallBlocks 整棵业务 renderer 树；根据输出猜成功 |
| ApprovalView | S `components/ai-elements/confirmation.tsx` 的标题/内容/操作区布局；O 状态 wrapper | 保留待办与历史表现，按原始 optionId 调动作；guard + props 双重限制 | AI SDK approval 联合类型和布尔 approved 状态推导；生成权限选项 |
| QuestionView | L 原生 form/fieldset + 现有 Radix 控件；O 受控问答组件 | 单/多选、短/长文本、必填提示、显式提交/跳过；复用 Approval 的私有展示外壳，不复用其状态机 | 不搬 ask-question.tsx：该文件主要显示已回答工具历史；WorkflowRunQuestionRow 明确为只读，也不是可应答表单 |
| EntitySelector | L Radix Popover + 原生搜索框/选择列表；O 受控分组选择 | 单/多选、分组、搜索、禁用解释、选中值保留；实现组合框键盘与 aria 关系，复用平台容器 | ZCode ModelConfigSelect 的品牌/会话服务；不新增 cmdk/全局命令系统 |
| ConfigurationSection | L 基础表单控件；O section/field/error/actions 薄布局 | 标题说明、任意受控字段 children、字段错误/只读、独立 save/apply 动作 | `settings/model-provider-section/SectionLayout.tsx` 依赖品牌导航/feedback，不作源码移植；ProviderFormControls 的凭据规则不属于 UI |
| ConfigurationState | O 来源×生效状态徽标及动作 | default/profile/session 与 effective/pending/applying/failed/unsupported/unknown 分开显示；字段渲染由消费者传入 | Profile 合并、配置应用、凭据判定、store |
| ResourcePreview | S `components/ai-elements/attachments.tsx` 的 Attachments/Attachment/AttachmentInfo 布局与 MIME 分类思路；L 共用 Markdown renderer | 结构化附件元信息、消费者授权图片、文本/Markdown 预览；未支持格式显示元信息与显式打开动作 | ai FileUIPart/SourceDocumentUIPart、任意 URL 自动 img、音视频 autoplay、文件读取/下载权限逻辑 |
| ChangeReview | S `components/ui/lightweight-diff-preview.tsx` 的 getLightweightDiffLineParts 与行布局；S `lib/patchDiffPreview.ts` 的纯文本预览函数闭包（见下） | 每文件输入；轻量 +/- 行、可见截断、完整文本打开动作；CSS/intl/store 类型替换成本地显示选项 | @pierre/diffs 引擎、worker、同步高亮、真实 Git/应用 patch；不整搬 patchDiffPreview.ts |
| WorkProgress | S `components/ai-elements/task.tsx` 的 Task/TaskContent/TaskItem/TaskItemFile；`plan.tsx` 的 PlanHeader/Title/Description/Content/Footer 布局 | 受控层级项和状态，展开/折叠；触发器改为可键盘操作 button；步骤不等于固定工作流 | workflow 协议/执行服务、AI 自动规划、shimmer 动画运行时 |
| RunSummary | O 本域摘要组合，复用私有 badge/metadata/action primitives | 输入的运行状态、主体、时间、用量和允许动作；数值缺失显式未知，0 有效 | 从 elapsed/output/连接状态推断终态；统计服务、计费公式与执行控制 |

### 思考区（Conversation 内部模块，不新增第 13 个公共接口）

S `components/ai-elements/reasoning.tsx`：提取 `shouldAutoCollapseReasoning`、`getReasoningBottomDistance`、`isReasoningScrollAtBottom` 及手动展开不被自动收起覆盖的逻辑；采用 Collapsible 展示结构。删除 intl/test-id 包依赖、QueuedSummaryContent、UI 推算运行耗时的 timer；显示耗时只能来自 props。内容完成不等于整轮完成。折叠动画用本地 CSS/reduced-motion，卸载清所有计时/观察器。

### Diff 提取闭包

只提取 `getPlainTextPatchPreviewLines`、`getPlainTextPatchContentLines`、`getPatchPreviewLineContent`、`parseTruncatedMarkerOmittedLineCount` 及它们需要的 collect/normalize/limit/marker 私有函数与常量。保留 800 行可见预览上限及省略数量；改品牌 marker 名并保持测试。**不提取** countPatchFileDiffs/getPlainTextPatchFallbackLines/getSingularPatch/parsePatchFiles/filetype 判断链，因此不需要 @pierre/diffs。每文件 preview 可丢 hunk 头用于紧凑显示，但完整 patch 必须仍可查看；多文件未知原文直接纯文本显示，不能假装已正确分文件。

## 3. 依赖与样式决策

初始新增依赖固定版本（研究快照版本，不声称最新版）：`streamdown@2.5.0`、`@streamdown/cjk@1.0.3`、`@streamdown/code@1.1.1`、`use-stick-to-bottom@1.1.3`、`lucide-react@1.17.0`。实施安装前检查发布包 exports/peer/license 与当前 React；包或版本不可取得时暂停该依赖任务，不能自行追 latest。

React/react-dom 与 radix-ui 使用 C7 集成基线锁定版本、保持 React 单例。本次主树观察值为 React 19.2.7、radix-ui 1.6.7，不能用 ZCode 的声明范围覆盖它们。新增依赖写 Agent UI 自己的 package.json，再由 npm 生成 root lock；不要引入 bun/pnpm。

Streamdown 负责流式 Markdown，code 插件负责代码高亮，cjk 负责中日韩混排；不启用 math/mermaid，不直接依赖 Shiki 第二份版本。不引入 `ai`、`@ai-sdk/react`、Lexical、motion、Zustand、ZCode workspace 包。既有 `@assistant-ui/react` 留在旧消费者，不搬进新 Agent UI；本批不删除旧链依赖。

样式分两类：移植组件的 Tailwind 类人工映射为局部 `.aui-*` CSS；Streamdown 与 code 插件需要的工具样式由本插件私有构建生成。允许本插件 devDependency `tailwindcss@4.2.2` + `@tailwindcss/cli@4.2.2`，只扫描本插件及上述两个渲染包，不导入 preflight、不扫描其他插件、不修改 root/app 的 CSS 管线。生成规则限定在 `.aui-root` 后代；主题变量只在 `.aui-root` 映射现有平台 tokens。实施先做样式隔离 proof：外部同名 button/pre/table 的 computed styles 前后不变；做不到则该构建门失败，不通过向全局注入 reset 解决。

Markdown 所有链接/图片/原始 HTML 仍需本地安全 wrapper。库声明安全不等于 Ordessa 策略已经满足；必须测试不触发外部网络、危险协议不执行、下载/复制只有显式动作。禁用内建绕过业务的打开/下载操作；无授权图片显示文字占位。

公开依据：[Streamdown 官方仓库](https://github.com/vercel/streamdown)说明流式 Markdown、插件与 CSS 集成；[use-stick-to-bottom 官方仓库](https://github.com/stackblitz-labs/use-stick-to-bottom)说明手动脱离跟随与 ResizeObserver。具体安装版行为仍由 T002 验证。

## 4. 为什么不把多个项目拼成新框架

此前研究的 Codeg/Orca 可继续作为会话组织参考，本批没有批准从它们复制任何文件。ZCode 已有足够展示素材，多抄一套会再引入另一套模型和样式。问题表单、配置状态等薄胶水没有合适的纯组件证据，明确自写比声称“复用某项目”实际重造更诚实。

## 5. 许可证与来源落盘

ZCode 根 LICENSE 为 Apache-2.0；上述 ai-elements 文件头明确派生 Vercel AI Elements、Apache-2.0，ZCode THIRD-PARTY-NOTICES 同样如此。先前 `docs/zcode-borrow-points.md` 的 MIT 说法不适用于本快照，实施应以本记录及原始许可为准。若额外复制 shadcn 文件则另需其 MIT 文本，本方案优先直接用已有 Radix，不授权整搬 shadcn。

实施在 `plugins/agent-ui/THIRD-PARTY-NOTICES.md`、`licenses/`、`upstream-manifest.json` 落盘：repo/commit/path/原文件 SHA256/移植符号/目标文件/许可/Ordessa 修改摘要；保留来源 copyright/header。不复制与本批无关的 ZCode 产品宣传或隐私声明。Npm 依赖记录实际 lock 版本/integrity/license。许可不明的文件不可复制。
