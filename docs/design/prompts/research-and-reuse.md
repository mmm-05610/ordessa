# Research and module reuse

核查日期：2026-09-28。官方文档描述当前机制，实施必须另固定本仓 native/adapter pin；不把官网当前版本替换成运行版本。本次无真实模型调用、无用户配置扫描。

## 官方事实与本设计的取舍

| 来源 | 已确认事实 | 设计影响 |
| --- | --- | --- |
| [Pi configuration](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/configuration.md) | SYSTEM 与 APPEND_SYSTEM 分工不同；项目同名文件优先；agentDir 可独立配置 | 保留追加/替换区分；检查项目覆盖，不直接改项目文件 |
| [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference) | developer_instructions 是追加；model_instructions_file 是内建指令替换入口 | 分别绑定用途，不使用保留字段 instructions 冒充能力 |
| [Codex AGENTS](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | 项目指令有专门发现/作用域机制 | 受管 Prompts 不等于接管 AGENTS |
| [Claude SDK system prompts](https://code.claude.com/docs/en/agent-sdk/modifying-system-prompts) | preset append 保留原生基础；CLAUDE.md 属项目上下文而非同一 system slot | 不把 CLAUDE.md 文件存在当 system prompt 配置确认 |
| [Claude memory](https://code.claude.com/docs/en/memory) | 原生文件能展开 imports，作用域影响确认行为 | 禁止将导入正文自动转成外部文件读取授权 |
| [Hermes personality](https://hermes-agent.nousresearch.com/docs/user-guide/features/personality) | 基础 SOUL 与会话人格覆盖分离 | 人格不能默默替换完整系统基础；只借鉴语义，不搬 HOME 管理 |

本包只依赖上述机制判断，不复制官方正文。更宽盘点见 [Harness 配置调研](../harness-configuration/README.md)。Claude 当前官方机制能否穿过本仓 0.81.2 ACP adapter、Codex/Pi 已锁版本能否动态重读，本轮尚未验证，纳入 T01/T07。

## 模块级复用单

| 模块 | 具体来源 | 方式与边界 |
| --- | --- | --- |
| 基础 UI | platform-frontend 观察 SHA `82b7ef1fc3`，packages/desktop-platform/ui/src/index.ts：Panel/Toolbar/ScrollArea/Field/Input/Textarea/Select/Button/Notice | 直接用最终验收公共出口；已读出口有 Textarea，不需要自造编辑器平台 |
| 组件装载 | 同树 ui-components/react/index.ts 与公开 API；Profile v2 editor contract | 消费既有 Outlet/scope，禁第二注册器；精确 API 随最终 SHA 冻结 |
| Markdown 预览 | 已集成且公共的安全 renderer（如有） | 首选直接消费公开组件；若不存在，首版用平台纯文本预览，不复制 Chat 私有 renderer、不为了预览新造 Markdown 框架，UI 标明“文本预览” |
| 修订与导入纪律 | Skills 分支 `752f148b1b`，plugins/assets/src/ordessa_assets/server/store.py：SkillRevisionStore.install/verify | **参考模式，不复制类**；其 Skill 目录/frontmatter/文件树语义不适合本域；本域采用 SQLite 正文事务+sha256 |
| CAS/幂等 | Profile 分支 `b77f9f23cb` 领域服务的既有模式 | 复用经核验的公共中性 helper 才 direct-import；不依赖 Profile DB、私有 storage 或复制整类 |
| Profile 引用、覆盖与贡献 UI | [Profile v2 契约](../profile-v2/contracts.md) | 直接消费，Prompts 不再实现会话覆盖算法 |
| 原生配置与恢复 | [Harness v2 契约](../harness-v2/contracts.md)，现有 access/Claude 官方 adapter | 消费同一应用服务，不复制 journal、重启器或 ACP client |
| 三品牌提示文本映射 | 官方机制 + 当前 pin 的原生入口 | 本域自写薄纯函数，固定 golden tests；不搬完整上游配置服务 |

平台观察 SHA 不是实施批准 SHA。所有 direct-import 必须在干净构建中验证；上游可见但本仓未导出的组件不算“已经可以复用”。不新增通用内容仓、AssetsService 或 UI-component 总插件。

## 许可证与取材账

首版本方案不批准新增外部源码复制或新 Markdown/editor 依赖。内部复用记来源 SHA/符号与保留测试；确需外部依赖先核版本/许可/NOTICE，再更新本表经审阅。禁止执行者泛搜一个提示词管理项目后整套搬入。

Spec Kit 结构沿用本仓 [Harness 实施包的方法来源](../harness-v2/research-and-reuse.md)，本包是原创领域设计，不是已经通过的 Spec Kit 自动检查。
