# 品牌映射与能力矩阵

## 共通门

Ordessa 的**必达**路径是“用户显式选模板→参数校验与完整文本预览→插入普通用户草稿→现有 ACP submit”。它不依赖品牌支持命令模板文件；但必须经真实目标上的受控对端验证字节与消息角色。任何品牌原生投影需另过 `assess`：固定 native/adapter 版本、发现路径/优先级、项目额外发现、名称冲突、同会话 reload、重启恢复、卸载和独立观察。文件投放只叫 `projected`，原生命令被加载须有独立证据。

| 品牌 | 官方机制事实 | 首版裁定 | 原生投影验收缺口 |
| --- | --- | --- | --- |
| Pi | [官方 Prompt Templates](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/prompt-templates.md)：Markdown `/name`、参数、个人/项目/包来源，项目内容需信任；同名 extension command 有先处理路径 | 通用 Chat 展开必达；原生候选是受管 prompts 目录或 resource loader，**不直接改用户/项目目录** | 固定 pin 的实际解析器、同名优先级、reload、参数语法无损映射、当前会话确认 |
| Claude Code | [官方 Skills 文档](https://code.claude.com/docs/en/skills)明确 `.claude/commands/*.md` 与 Skill `SKILL.md` 都形成 `/name`，custom commands 已并入 Skills | 通用 Chat 展开必达；默认 **不做** native 投影，以免和 Skills 双重加载/自动发现语义混同 | 只有能证明单一所有者、显式用户调用、不自动触发、参数/角色等价并与 Skills 排他，才单独开放 |
| Codex | [官方 Custom Prompts 文档](https://learn.chatgpt.com/docs/custom-prompts)说明本地 custom prompts 已 deprecated、建议 Skills；旧目录 `~/.codex/prompts` 且显式 `/prompts:name` | 通用 Chat 展开必达；**不以已废弃接口作为新增核心依赖** | 若固定 pin 保留私有 prompt 接口，须证明可控、可移除、不会把共享模板误存用户 HOME；否则 unsupported |

上述是官网机制，不等于 Ordessa 当前固定版本/ACP 入口已经支持。证据表需逐格记录 native SHA/版本、adapter 版本、安装入口、原生发现、reload/resume、撤销、同名、用户消息角色与具体受控测试 ID；未测写 unknown，不从官网推断 L3 成功。Hermes/OpenCode 等以后按同一个注册点加模块，不预置假适配器。

## 与原生命令/Skill 的冲突

首先通过当前会话的真实目录拿到 built-in、extension command、Skill、native prompt 项。Ordessa 菜单条目始终 namespaced；显示名可以重合并显来源，但直接键入裸 `/review` 如果命中多个来源，必须交互选择或拒绝；不能按注册/文件发现顺序分配赢家。Pi 原生 extension command 与模板优先级不可作为 Ordessa 的冲突解决策略。Claude commands 等同 Skill 时不得既由 Skills 插件装载同一文件，又由模板插件装载。Codex deprecated custom prompt 不保证可被项目/其他用户共享。

若目前 ACP 只回传用户输入文本而不公开原生命令目录，展示 Ordessa 模板可以先做；“已确认无冲突”不可成立，不能承诺直接裸命令的独占。原生目录接口应由会话/Harness owner 提供只读投影，业务插件不私开第二 ACP client 或读取用户 HOME 猜测。

## 原生投影应用

1. 业务解析已批准固定修订，检查同名和额外原生发现项。
2. 适配器对目标给出纯 intent，Harness 投放到实例私有 generation。
3. 原生固定版本加载后以可观察目录/资源加载结果验 digest 和命名；无观察端口就保持 projected/unknown。
4. 变更只在下次用户输入前由唯一提交闸门应用；输出中不 reload。需要重启则由 Harness 恢复同一原生 session，失败不以 `session/new` 代替。
5. reset 只清除本贡献者拥有的文件/配置；原生用户文件不动。

不能证实 native 语义等价时返回 NATIVE_SEMANTICS_UNSUPPORTED，Chat 展开仍可独立使用；不能自动退成注入 system/developer 消息。
