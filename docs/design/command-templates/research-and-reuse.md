# 研究与逐模块复用裁定

日期：2026-09-28。官方页面说明**上游当前机制**，不是本仓固定运行版本的能力证明；实施 T00/T02 还要锁 native/ACP adapter pin 并做受控实验。第三方镜像不作品牌事实来源。

## 官方机制

- [Pi Prompt Templates](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/prompt-templates.md)明确 Markdown 扩为 `/` 命令，可带参数、来自个人/项目/包，项目项须信任；同名 extension command 可能先接管输入。其模板是用户消息展开，不等于扩展执行命令。
- [Claude Code Skills](https://code.claude.com/docs/en/skills)明确 custom commands 已并入 Skills，旧 `.claude/commands/*.md` 仍可用，但两种路径都生成 `/name`。所以 Ordessa 可以在**产品语义**上把短模板与 Skill 包分开，原生投影却不能让同一内容两次注册或误宣称不会自动加载。
- [Codex Custom Prompts](https://learn.chatgpt.com/docs/custom-prompts)明确此接口已 deprecated，旧 `~/.codex/prompts` 是显式 `/prompts:name`，建议使用 Skills。不能把已废弃本地目录当三品牌统一底座，也不能从旧文档推断当前 ACP bridge 可热加载。
- [Chat 输入契约](../chat-zcode-reuse/input-contracts.md)已有 `addInputSource` 设计和 `plus`/`slash` 两 surface，但 **main 尚未发布该类型与运行实现**；这是前置接缝，不是本插件可直接 import 的事实。

## 复用表（实施前补 SHA/许可核查）

| 模块 | 参考具体文件/接口 | 裁定 | 需剥离或新写 | 证据门 |
| --- | --- | --- | --- | --- |
| 模板库单文件修订/CAS | `plugins/server-compat/src/ordessa_server_compat/assets/records.py`、`catalog.py` 的内容地址/记录模式；`plugins/assets/skills` 方案的数据纪律 | **借鉴模式，不搬 Skill 仓**。模板与 Skill 版式/数据所有者不同 | 自写模板表、参数 schema、授权、修订及迁移；保存 ID 与摘要语义 | G01–G04 |
| 输入参数展开 | Pi 官方 `packages/coding-agent/docs/prompt-templates.md` 语法与案例 | **借鉴测试案例，不直接调用原生 parser**；Ordessa 需要跨品牌确定性语法 | 自写封闭 parser/renderer（无递归/动态命令）；golden fixtures | G05–G07 |
| 内容摘要 | Python 标准库 `hashlib`，本仓现有 `pacthold.resource_contracts.runtime_artifacts` tree digest 只适合树 | 单文件用标准库；不为模板引入 Skill tree store | UTF-8 NFC 策略、长度/换行规则冻结后 hash | G02/G05 |
| 通用命令能力 | `plugins/commands/shared/registry.ts` 与 `src/entry.ts`：前者薄贡献容器，后者 `execute(id)` 轻量回调分派 | **仅作为“打开管理/面板”动作可消费**，不是模板执行引擎 | 模板查询/渲染不能塞进 `execute()` | G08 |
| Chat `/`/`+` | `docs/design/chat-zcode-reuse/input-contracts.md` 的 `addInputSource`、`docs/design/chat-zcode-reuse/input-spec.md` 的 P01–P06 | 复用**未来经验证发布的**贡献入口和面板；当前只可设计，不可宣称实现 | 参数弹层与服务适配；如 action union 不够，走公开最小契约变更 | G08–G11 |
| Profile facet | `docs/design/profile-v2/contracts.md` `FacetDescriptor`/编辑贡献 | 复用经审定的贡献机制；Profile 不存正文 | 三态绑定、revision 选择 UI 与域校验 | G12–G14 |
| Harness 配置应用 | `docs/design/harness-v2/contracts.md` C2/C3/C5 | 原生投影时复用唯一应用事务；绝不自写文件/reload | 域内 Pi/Claude/Codex capability adapter（不支持须如实返回） | G15–G18 |
| Settings/基础控件 | 现有 Workbench 设置/overlay 契约；平台 `ui`/`ui-components` 在 `worktrees/platform-frontend` 尚非 main | 集成后使用已发布 API，**不从相邻工作树 import 未审产物** | 模板编辑器与预览业务组件自己写 | G19/G20 |

上游 Pi/Claude/Codex 的源码/文档仅**参考语义**，本包不计划 vendoring 它们的 parser/UI；不用承担未知许可证复制风险。若未来移植代码，先在实施 baseline 固定 upstream commit、文件、许可证和 NOTICE，再单独批准。旧 compat 的业务数据也不能为了“复用”在 main 新增第二服务；需显式清点调用方和迁移/删除账。

## 取舍

1. 不以原生命令文件为主路径：Claude 与 Skill 重叠、Codex 已废弃、Pi 的目录/加载细节与其它品牌不同。跨品牌可靠性来自 Ordessa 明文预览+原有用户消息提交。
2. 不用通用 Handlebars/Jinja：其控制流、include、helper 与本版“纯字符串 substitution”不一致，增加可执行语义和逃逸面。
3. 不把模板并入 Prompts：持久系统/开发者配置与一次性用户消息角色不同；共享 UI 样式不构成共享数据所有权。
4. 不把模板并入 Skills：Skills 目录/渐进加载/自动发现/脚本资源不应因普通短命令而启用；原生 Claude 重合需在适配层消歧，不改变 Ordessa 业务边界。
