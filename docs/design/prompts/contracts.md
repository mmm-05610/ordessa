# Public contracts and registration

以下为目标 API 语义，非已经存在的导出。Python/TS DTO 以同一 schema 测试校验；不复刻平台 Token/ServiceLocator。

## 1. Prompts service

服务端口 `prompts.service`，wire 前缀 `prompts.*`，逐方法通过 Server 注册表发布，标准鉴权/shape/error envelope。请求不接受任意本地路径。

| 操作 | 输入/输出 |
| --- | --- |
| list/get/getRevision | server 上下文、scope/kind/query/cursor；分页默认 50、上限 100；列表不返正文 |
| create | kind/scope/title/description/body + operationKey → id/version/revision |
| update | id、expectedVersion、expectedRevision、patch、operationKey → 新版本 |
| clone | sourceId/revision、目标 scope/title、operationKey → 新实体 |
| archive/restore | id/expectedVersion/operationKey → 元数据版本 |
| importText | 显式选取并上传的 UTF-8 内容、文件名提示、kind/scope → 普通创建；不解引用路径 |
| exportText | id/revision → 正文及安全建议文件名；客户端经既有文件对话框保存 |
| resolveSnapshot | 已授权目标 Profile/selection + 来源修订 → 不可变内容快照；无运行副作用 |
| preview | 与 resolve 同源 → 文本组成/修订/诊断，不声称原生完整 system prompt |

所有写入键作用域 = 调用主体+操作+目标+key，携带 payload digest；复用 key 不同内容拒绝。身份从服务上下文取，不信客户端自报 owner。Profile scope 校验经公开 Profile 授权端口，Profile 缺席时拒绝此类创建/读取，不影响公共库功能。

`resolveSnapshot` 可在后端返回正文给获准应用者；元数据查询/UI 未经内容权限不得由 preview 绕过。日志仅 ID/revision/摘要和诊断码，不记正文。没有“正文不含秘密”的假设。

错误至少有 NOT_FOUND、REVISION_CONFLICT、INVALID_CONTENT、LIMIT_EXCEEDED、REF_KIND_MISMATCH、SCOPE_REFUSED、ARCHIVED_SELECTION、DEPENDENCY_UNAVAILABLE、NATIVE_SEMANTICS_UNSUPPORTED；按领域映射注册已有 error-family 接缝。

## 2. Profile 配置贡献

facet `assets.prompts`，schemaVersion=1，effect=instruction：

| item | schema | 默认 | 覆盖 |
| --- | --- | --- | --- |
| instructions | 有序 PromptRef[]，不重复、kind=instruction | [] | 整个列表 item |
| persona | PromptRef或null，kind=persona | null | 单 item |
| systemReplacement | PromptRef或null，kind=system-replacement | null | 单 item |

validate 检查引用、scope、版本/授权、大小与用途；applicability 取 Harness 实际能力。Profile compile 只组织已解析的领域 payload；品牌编译只有 Prompts 的 Harness adapter 一处实现，不能 Profile glue 再生成另一份 native intent。

前端通过 `ProfileContributions.forScope(scope).addEditor(...)` 注册该 facet 的编辑组件，props/actions 使用 Profile v2 契约；后台 provider 缺席时隐藏但保存既有字段，实际 apply 独立拒绝缺失能力。

首版没有 Prompts 机制设置，故不注册空的 `.addSettingsSection(...)`。以后有真实本域设置时可接 Profile 自身设置区，不改变 Profile 核心。

## 3. 前端页面与组件

- Workbench Settings 注册“指令与人格”管理页，不注册新的顶层主模块。
- 平台 ui-components 注册 `prompts.library-editor.v1`、`prompts.profile-selector.v1`；组件 key 的轻量契约在本域，使用同一平台注册和 Outlet。
- 管理页只依赖 Prompts 公共服务；Profile selector 可选启用，声明其 Profile API 依赖。不 import Profile/Harness 实现。
- 不注册 Chat 常驻控件、slash command 或附件菜单；首版配置使用 Profile 路线。
- scope dispose 撤销本域 UI 贡献，旧异步请求按 server/profile/provider generation 防串写；草稿 dirty 的导航确认使用平台 overlay。

## 4. Harness 配置贡献

注册 `harness.configuration-adapters` v1，facet=`assets.prompts`；各品牌一模块。输入为 ResolvedPrompt 快照+三类选择语义，无用户目录路径和可执行脚本。

assess 检查 native/adapter 版本、入口、作用域、模式组合、大小、reset 与 resume 支持；compile 返回 Harness typed intents；verify 解释 Harness 提供的受控观察事实，不自己启动进程。

对同一原生系统字段的 persona+instructions 由本 adapter 一次组合，其他插件争同字段按 Harness 冲突规则拒绝。systemReplacement 与其他两类同时存在，只在原生机制允许同语义组合且有测试时接受；不能自行移动到另一个消息角色。

整个贡献域拥有 native 输出字段/文件，不按单个内容注册全局字段 owner。移除某项重新合成完整目标；全移除恢复 adapter 记录的合法 before baseline，非“设空字符串就是恢复默认”。
