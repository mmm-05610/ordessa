# 品牌适配与证据门

本文所有“原生机制”是上游官方当前文档事实，不等于 Ordessa 当前固定 native/ACP adapter 版本已支持。实施 T02 必须填 pinned version、入口、作用域、隔离、reload/reset、调用、观测的逐格矩阵。

| Harness | 官方定义机制 | 本包默认目标 | 当前不能擅称 |
| --- | --- | --- | --- |
| Claude Code | 项目/用户 `.claude/agents/*.md` YAML frontmatter+正文；工具、模型、MCP、skills、permissionMode 等字段有各自限制，plugin-scope 子代理某些字段会被忽略 | 由本域编译受管定义，Harness 私有配置 generation 并用目标版本的加载/调用探针确认 | 当前 Ordessa Claude ACP adapter 已暴露热更新、同会话实例隔离或所有字段均生效 |
| Codex | 项目 `.codex/agents/*.toml`、个人 `~/.codex/agents/*.toml`；name/description/developer_instructions 与支持的 config 键 | 受管 TOML generation，Harness 解析/启动/恢复；限定已证字段 | 当前 Go Codex 桥/app-server 会发现私有根、重读定义或原生子代理在 ACP 路径可调用 |
| Pi | 官方 `examples/extensions/subagent/` 是可选 extension，示例启动独立 `pi` 进程；Pi 核心没有与前两者相同的内建 agents 文件机制 | **条件支持**：Harness 明确依赖、审核和隔离 extension-backed 子代理入口；本域只提供定义内容和受控 adapter | Pi “内建子代理”、装一个 Markdown 就可用、示例扩展的权限/取消/恢复符合 Ordessa 治理 |

## 格式映射

通用 record 只覆盖跨品牌可信交集：稳定名称、短调用描述、角色正文、**引用**模型/工具/MCP/Skill、可选资源限额声明。品牌独有的 frontmatter/TOML 字段以 typed native extension 保存，未校验目标版本时不编译；不能把复杂字段丢弃却报“已应用”。

Claude：使用固定 pin 的解析器验证 camelCase 字段及文件名/名称限制；特别验证 `permissionMode`、`mcpServers`、`skills`、`hooks`、`isolation` 的入口差异。官方明确 plugin subagents 会忽略 `hooks`/`mcpServers`/`permissionMode`，所以不能选其 plugin-scope 入口承载这些承诺；私有配置根是否等价项目/用户作用域需实测。Codex：只编当前 TOML schema 支持的键；`sandbox_mode` 不是对 Ordessa 外层 sandbox 的授予，MCP/skill 引用须各属主授权。Pi：不复用示例调度器来替代 Ordessa 派工基础设施；若需执行扩展，该扩展必须由 Harness 作为可执行运行适配的一部分单独审计、pin、授权、隔离、取消和日志，不把整个示例连 workflow presets 原样搬入业务插件。

## 应用闭环

1. 解析完整受管集合 + 独立原生发现项，按目标解析器检验 slug/名称、冲突、数量、字段和引用可用性。
2. 业务 adapter 纯编译整个集合为 Harness C3 的 `MountContent/RemoveOwnedContent/SetField/InvokeAction` 等有限意图；不能用绝对任意路径或 shell。受管目标名称/内容带 digest，目标目录由 Harness 所有。
3. Harness 将 generation 投放实例私有位置，保证同一原生进程/会话不会读取其他 Profile 的定义；项目 cwd/父目录额外发现不得被忽略。
4. 适配器解释目标加载器的独立观测：可发现、可调用与一次实际调用分开。若只有文件摘要，停在 projected/unknown。
5. 下次提交需要更新时走已证 reload 或重启+同 native session resume；无法证实不串会话/不能 reset 的版本返回 unsupported/unknown，不建新空会话。

`disable` 只控制本插件受管项；无法遮蔽的项目原生项仍可见，不能把“受管列表里没有”写成“角色已禁用”。调用的权限/工具实际裁决在运行时，不由 YAML/TOML 保存时的一次检查替代。原生字段若能影响审批、注入自有 MCP 或额外工具，要么被锁定到更窄权限并观察确认，要么直接拒绝；不能仅凭 UI 警告通过。

## 证据分级

L1：DTO/格式/schema/版本测试；L2：锁定 native CLI/解析器 + 受控装载器/子进程；L3：Ordessa Server→Harness→既有 ACP owner→受控下游，证实同一会话内发现/显式调用/更新/撤销与 A/B 隔离；L4：真实模型（未授权、不要求）。无可用 L2/L3 探针时相应格保持 unknown，不拿 L1 冒充端到端。Pi 必须显示 `extension-backed` 标识并有独立扩展审计，才能进入 L3。
