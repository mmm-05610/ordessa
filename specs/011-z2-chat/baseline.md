# Z2 R0 基线冻结（2026-09-28）

## 环境

| 项 | 值 |
| --- | --- |
| 工作目录 | `/home/maoqh/projects/ordessa/worktrees/011-z2-chat` |
| 分支 / 起点 | `codex/011-z2-chat` @ `96fef2db47`（设计快照，父 main `cd7d31f3cf`） |
| Node / npm | 22.22.1 / 9.2.0（与 docs/baseline.md 一致），依赖由根 lockfile `npm ci` 安装（277 包） |
| 基线门实跑 | `npm run typecheck` 退出码 0；`npm test` 13 文件 146/146 通过；`npm run build` 9 扩展成功 |
| ZCode 固定源 | `29628c9acdb81b703bbd4080c207a0e7ce5e276e`（github.com/zai-org/ZCode，浅取至 `/tmp/zcode-src`，HEAD 复核一致）；未运行其产品，无像素基准 |
| 依赖检查点 | `foundation` / `harness-api`：截至 R0 **未发布**（无 `codex/011-foundation-ready` 等引用；C0 树尚在集成中）。按协议先做独立工作并发布 chat-api |

## C7/C8 对齐决定（chat-api 先行）

本树快照不含 platform-frontend 的 `@ordessa/ui-components` / `@ordessa/ui`（C0 发布 foundation 后并入）。chat-api v1 因此：

- 只依赖本树已有的 `@ordessa/extension-api`（Token/ResourceScope/Contributions），不复制平台 Token、不造 ServiceLocator。
- 组件 key 使用 Chat 自有 `defineChatComponentKey(id, major)` 构造，运行时形状与 C7 `UiComponentKey`（冻结的 `{id, major}`）一致；幻影 brand 提供 key↔props 编译期对应。foundation 可消费后以 chat-api 修订版把构造点切换为平台 `defineUiComponent`（id/major 不变，运行时对象同形，平台按 `(id, major)` 判同一性，chat-api 是 `ordessa.chat.*` 键的唯一构造点，无 identity conflict）。该限制记入 checkpoint `limitations`。
- `UiAction` 语义（accepted/refused/unavailable，accepted≠完成）按 platform-frontend `82b7ef1fc3` 的公开 API 对齐（只读依据，非本树可导入类型）。

## 旧实现盘点与 source→destination 迁移表

旧 `plugins/agent/conversation`（ext id `ordessa.agent-conversation`，manifest ID 保留，不因迁移改名）：

| 源文件 | 内容 | 去向 |
| --- | --- | --- |
| `src/view.tsx` | assistant-ui external-store 会话视图 + textarea composer | 被 `plugins/chat/frontend` views 替换；`@assistant-ui/react` 依赖随旧链退役（退役提交归集成） |
| `src/interaction-card.tsx` | 审批/提问操作卡 | 语义迁入 `plugins/chat/frontend/src/components/interactions/`（重写为消费 chat-api DTO，保留动作语义与测试 ID） |
| `src/styles.ts` | 面板样式 | chat 领域重写，不整体搬运 |
| `src/entry.tsx` | Workbench view 注册 `agent.conversation` | `plugins/chat/frontend/entry.tsx` 新注册；旧注册链在 CHAT-V08 关闭（保留 manifest ID） |

旧 `plugins/agent/sessions`：**只读**（共同 plan：是否迁移由 C0 裁决）。其 `model.ts` facade（draft/project gate/createAndSend 语义）是 Chat 消费的真实服务所有者；Chat 不复制其逻辑。

旧测试（apps/desktop/renderer，含 Chat 相关断言）：`agent-conversation.test.tsx`、`agent-sessions.test.tsx`、`agent-sessions-draft.test.ts` 等。旧链未关闭前保持原样全绿；chat 新测试放 `plugins/chat/**` 自带 vitest；旧文件退役列 `integration-request.md`。

## 复用盘点（ZCode → plugins/chat）

固定版本（沿 research-plan）：`streamdown@2.5.0`、`@streamdown/cjk@1.0.3`、`shiki@4.0.2`、`use-stick-to-bottom@1.1.3`、`lucide-react@1.17.0`、`radix-ui@^1.6.7`（用根锁已有版本）。不搬 Lexical、motion/react、Tailwind、ZCode store/协议栈。

| 目标 | 源（`packages/ui/src/`） | 关键适配 |
| --- | --- | --- |
| MessageLayout/MarkdownBody | `components/ai-elements/message.tsx`（1670 行） | 只取 Message/MessageContent/resolveMessageStreamdownMode 模式判定与错误 fallback；换本域 DTO |
| ReasoningBlock | `components/ai-elements/reasoning.tsx`（577 行） | 默认折叠、手动选择优先；删 test-id/intl/诊断依赖；耗时只用真实值 |
| ToolFrame | `ToolCallBlocks/ToolLayout.tsx`（363 行）+ `ToolSummaryRow.tsx` | **模块级 `toolLayoutOpenState` Map 必须改为视图会话级状态**（已核实 L16-L18 只增不减 + memoryDiagnostics）；Tooltip 错误补键盘可达替代 |
| CommandTool/Output | `ToolCallBlocks/renderers/execute.tsx`、`ExecuteOutput.tsx` + `components/ui/scroll-fade-viewport.tsx` | 上滚冻结/回底恢复；不搬 bashOutputDisplaySchema 多协议解析 |
| GenericTool | `ToolCallBlocks/renderers/fallback.tsx` | summary/detail + ToolFrame；不 JSON.stringify 任意服务对象 |
| ConversationScroll | `components/ai-elements/conversation.tsx` + use-stick-to-bottom | 跟随/暂停/回底；输入框在滚动视口外 |
| Composer 输入 | `components/ai-elements/prompt-input-textarea.tsx`（131 行） | Enter/Shift+Enter/IME/defaultPrevented 语义；删 upstream controller |
| 附件 | `components/ai-elements/attachments.tsx`、`v4/composer/useComposerAttachments.ts`（1108 行，只提逻辑不整体复制） | 选择/拖放/粘贴合流、准备态、移交后清理；删 whiteboard/ZCode store |
| +// 面板 | `SlashCommandPlugin.tsx`、`slashCommandPanelSections.tsx`、`mentions/components/MentionPanel.tsx`、`lib/promptInputTriggers.ts`（256 行）、`mentions/activePromptInputToken.ts` | token/query/分组/键盘/portal；业务组由 Chat input sources 声明；不引入第二编辑器 |
| 明确不移植 | QueuedSummaryContent 动画、CodeViewer/Mermaid、workflow/撤销/共享 | research-plan 已裁决 |

逐文件 SHA256、符号→目标、删改说明落 `plugins/chat/upstream-manifest.json` 与 `THIRD-PARTY-NOTICES.md`（ZCode Apache-2.0；ai-elements 含 Vercel 派生版权）。

## 红 ID / 回归账

- 本树基线 146/146 绿，无 Chat 相关红。
- 继承红（harness 2 npm-closure、server inherited-red ledger、acp_orchestration retirement）不在本线写入面，按 known-issues 追踪，不因本线变化。
- 服务端登记问题（stop unknown lease、旧库迁移 provider）归 C0/B，本线只消费。

## 待消费检查点（R1-late）

`foundation`（C0）→ 真实 C7/C8 包、Workbench composition；`harness-api`（C0）→ 命令目录/附件能力/提交语义。消费按协议固定 publication SHA merge 后复跑本线门。
