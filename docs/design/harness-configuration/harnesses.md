# 八家 Harness 配置面盘点

查询日期：2026-09-27。这里的“有”表示所引官方资料有明确入口，不表示 Ordessa 已适配。未写热更新的项目一律视为**生效方式未核定**，不是默认启动读一次，也不是默认动态读取。

字段详细索引见 source-index.json；以下按语义成组，避免把环境变量和配置键当成数千个独立业务模块。`待核`表示证据不足，不表示不支持。

## 1. Codex

入口：`CODEX_HOME/config.toml`、可信项目 `.codex/config.toml`、CLI 参数、管理员 requirements、独立原生 config profile 文件。原生 profile 与 Ordessa Profile 不是同一实体。

重要版本差异：官方 Advanced Configuration 明确 **0.134.0 起** `--profile` 使用 `<name>.config.toml`，不再读取 `[profiles.<name>]` 或顶层 `profile` 选择器。不能依据旧教程生成旧格式。项目层还有 provider/auth 等键的禁写清单。[官方高级配置](https://learn.chatgpt.com/docs/config-file/config-advanced)

| 面 | 已核到的配置入口/能力 | 应如何解释 |
| --- | --- | --- |
| 模型/供应商 | `model`、`model_provider`、`model_providers.*`、`openai_base_url`、catalog、认证 helper/header/env 引用 | 供应商定义与会话选择分开；认证材料不进 Profile |
| 推理与请求 | reasoning effort/summary、verbosity、service tier、context window、retry/stream timeout | 参数支持还受模型与 provider 限制 |
| 指令 | `model_instructions_file`、developer instructions、AGENTS/override、fallback filenames、字节预算 | 完整替换与增补区别；项目发现另计 |
| 工具与原生应用 | web search、shell、image、apps/tool enable 与 approval、browser/computer use 策略 | Desktop 专属功能不得推定 CLI/ACP 可用 |
| 权限/隔离 | approval policy、permissions profiles、filesystem/network、shell env、sandbox、Windows 实现选择 | 管理员 allowed/required 项不是普通预设可覆盖值 |
| 记忆/上下文 | memory 生成/使用及辅助模型、compaction、tool-output/context budgets | 生成的记忆与历史不是配置本体 |
| 运营/显示 | TUI、通知、history retention、OTel、analytics、更新、remote control | 大多进入 Harness 管理页，不进入每个 Chat Profile |

上述原生键以[官方配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)和本次 437 标识符索引为证。索引同时包含 managed、实验、弃用和 Desktop 字段，不能整体开放。

| 扩展面 | 已核到的机制 | 不能省略的差异 |
| --- | --- | --- |
| Skill | 资源发现与 `skills.config`、上下文预算 | 目录配置不等于已装载；需单独核对版本的 loader/协议 |
| 子代理 | roles、description/config 引用、默认模型/effort、并发控制 | 配置参考与专页需按目标版本对齐，不套用 Claude frontmatter |
| MCP | stdio/HTTP、启动/调用超时、required、工具 allow/deny、审批、OAuth、插件提供 MCP 覆盖 | deny 后于 allow；插件自带 server 的启动定义不由用户层随意改 |
| Hooks | 生命周期事件、matcher、command/MCP handler、同步/异步、输出约束 | 异步不能承担阻断；MCP hook 不负责建立连接 |
| 规则 | 命令执行规则与权限配置 | 不等于 AGENTS 中自然语言规则 |
| 原生插件 | marketplace/source、启用、插件工具策略 | 原生插件和 Ordessa 插件不同；必须独立授权加载代码 |

来源：[AGENTS](https://learn.chatgpt.com/docs/agent-configuration/agents-md)、[子代理](https://learn.chatgpt.com/docs/agent-configuration/subagents)、[MCP](https://learn.chatgpt.com/docs/extend/mcp)、[Hooks](https://learn.chatgpt.com/docs/hooks)。Skill/插件详细字段仍需目标版本逐项核定，不能仅凭参考表存在键作完整支持声明。

应用未决：thread/turn 参数与进程级设置的覆盖边界，特别是 provider/credential/插件变更，必须对 Ordessa 使用的 app-server/adapter 版本单独验证。本轮不重复先前“重启并恢复”的结论作为已验证事实。

## 2. Claude Code

入口：用户、项目共享、项目本地 `settings.json`、managed settings、CLI/SDK 选项、环境变量；`CLAUDE_CONFIG_DIR` 是配置根重定向，不是安全 sandbox。`~/.claude.json` 混有运行/账户等信息，不可整体作为 Profile 模板。

本次单独索引 settings-reference 的 234 个标题键、env-vars 的 371 个变量名。它们包含管理员、Desktop、实验与全局选项，不是全可写列表。[Settings](https://code.claude.com/docs/en/settings)、[Reference](https://code.claude.com/docs/en/settings-reference)、[Env](https://code.claude.com/docs/en/env-vars)

| 面 | 代表配置项/资源 | Profile 边界 |
| --- | --- | --- |
| 模型 | model/fallback/advisor、effort/fast、modelSettings/overrides、模型可选限制、provider 环境与认证 helper | 模型列表限制、云部署认证、API 参数分开 |
| 推理/缓存 | thinking、effort 限制、prompt/subagent cache TTL、摘要显示 | 不把思考 UI 与模型推理参数合成一项 |
| 工具权限 | allow/ask/deny、additionalDirectories、defaultMode、autoMode、bypass 禁用 | 上级策略与父 agent 权限仍约束子代理 |
| 原生 sandbox | 文件读写规则、网络域名/socket、excludedCommands、unsandboxed 例外、失败策略、credential injection | 需区分 shell sandbox 与其他工具；不是一个 sandbox 开关 |
| 上下文/记忆 | autoCompact、autoMemory 路径/启用、claudeMd/excludes、输出预算、plansDirectory | 自动记忆内容不可随预设覆盖 |
| 环境/运维 | env、shell、worktree、遥测 helper、更新、保留期、remote/SSH | 全局/机器/组织设置不能普通会话任意写 |
| 原生界面 | statusLine、theme、快捷键、输出 style、通知、语言 | style/language 可讨论入 Profile；TUI 布局不等同 Chat UI |

表内键见上述官方参考；每项默认值、最小版本与作用域尚未逐键裁定。

| 扩展面 | 官方现状 | 关键限制 |
| --- | --- | --- |
| 指令 | CLAUDE.md、local、imports、路径规则；新版本也支持 AGENTS | AGENTS 直接读取要求 v2.1.277+，默认是否读取受 CLAUDE 文件存在影响；早期版本/某些入口另有限制 |
| Skill/命令 | SKILL.md、资源/脚本、用户与模型调用开关、allowed-tools、skillOverrides | 文本与授权寿命不同；未知 frontmatter 不能当已执行限制 |
| 子代理 | Markdown 定义；model、tools、permissionMode、MCP、hooks、memory、skills、maxTurns、isolation 等 | **插件内 subagent 的 hooks/mcpServers/permissionMode 被忽略**，不能当文件型 agent 同等能力 |
| Hooks | 生命周期事件；command、HTTP、MCP、prompt、agent handler | 各事件支持的 handler/输出/阻断行为不同 |
| MCP | stdio/HTTP/SSE 与不同配置范围、认证、工具加载、组织限制 | 协议存在不代表 adapter 暴露了管理/重载接口 |
| 原生插件 | manifest、skills、agents、hooks、MCP、插件设置/市场 | plugin settings 与 Profile contribution 不同，需要业务适配 |

来源：[Memory](https://code.claude.com/docs/en/memory)、[Skills](https://code.claude.com/docs/en/skills)、[Subagents](https://code.claude.com/docs/en/sub-agents)、[Hooks](https://code.claude.com/docs/en/hooks)、[MCP](https://code.claude.com/docs/en/mcp)、[Plugins](https://code.claude.com/docs/en/plugins-reference)。模型恢复/覆盖另见[Model config](https://code.claude.com/docs/en/model-config)，隔离见[Sandboxing](https://code.claude.com/docs/en/sandboxing)。

应用未决：CLI 支持与 Agent SDK、claude-agent-acp 版本支持分开登记。不要把 `/config`、`/model` 的交互能力直接当 ACP API；也不把每个配置根的独立性推定为 OS keychain/OAuth 独立。

## 3. Pi

官方旧地址目前重定向至 `earendil-works/pi`。本轮固定研究提交 `2b0a123de98318c2ff8069661721ce0c3794c34e`；不能直接套到 Ordessa 旧 pin。

入口：agent dir（`PI_CODING_AGENT_DIR` / SDK `agentDir`）、项目 `.pi`、CLI/RPC/SDK。user settings、models、auth、extensions、skills、prompts、themes 分家。project 配置受 trust 控制，但指令文件发现另有规则。[Configuration](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/configuration.md)

| 面 | 具体配置/资源 | 注意点 |
| --- | --- | --- |
| provider/model | `models.json` providers、baseUrl/api、models/modelOverrides、headers、凭据引用 | 自定义协议可通过 provider extension；不是所有 endpoint 都兼容 |
| 会话模型 | `/model`、`/thinking`、session model/thinking 记录 | 官方区分会话切换与 Ctrl+S 保存默认；恢复记录不改全局默认 |
| 指令 | AGENTS/override/CLAUDE；SYSTEM.md；APPEND_SYSTEM.md | 项目 SYSTEM/APPEND 与用户同名文件不是累加；替换与追加必须分开 |
| Skill | SKILL.md 与附件；自动发现、`/skill:name`、调用开关、资源路径 | `/reload` 用于编辑后刷新；不同校验错误有 warning/skip 差异 |
| 命令 | `prompts/` 模板、extension command | 模板与可执行命令两种机制 |
| 工具 | defaultTools；extension registerTool / tool events | 工具列表不是安全隔离；扩展运行于进程权限下 |
| 扩展包 | packages/extensions/skills/prompts/themes 资源列表；npm/git 包与筛选 | reload 会替换 extension runtime，旧句柄不能复用 |
| 上下文 | compaction、branchSummary、工具消息、图像限制、context events | 模型切换不会重新编码历史图片 |
| 可靠性 | retry、provider timeout/retry、HTTP/WS transport/proxy、shell | 全局限定字段需保留；不能全写项目层 |
| 界面/存储 | theme/keybindings、通知、TUI、sessionDir、telemetry | 会话存储目录不是 Profile 内容 |
| MCP/子代理/权限 | 扩展机制可提供这些功能 | **本轮未证实统一原生 MCP/subagent/sandbox 配置接口**；不得把示例扩展当内置功能 |

来源：[Models](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/models.md)、[Skills](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/skills.md)、[Settings](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/settings.md)、[Extensions](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/extensions.md)。

应用：原生 RPC 有命令响应与事件流；命令处理 success 不等于后续模型请求成功。现有 ACP 包是否映射 reload、工具/资源变更须另验。[RPC](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/docs/rpc.md)

## 4. Hermes

入口：`HERMES_HOME`、config.yaml、环境/凭据、实例内容目录、原生命令与插件。官方文档有多种运行入口，CLI、gateway、Desktop 的刷新行为不得混用。[Configuration](https://hermes-agent.nousresearch.com/docs/user-guide/configuration/)

| 面 | 已核入口 | 重要区分 |
| --- | --- | --- |
| 模型 | 主 provider/model、fallback、reasoning/text verbosity、auxiliary 各任务模型 | 压缩/视觉等辅助模型不是主模型的别名 |
| 人格 | HERMES_HOME/SOUL.md、personality presets、agent.system_prompt | SOUL 是身份基础；personality 是会话覆盖，不应合并成项目 AGENTS |
| 项目指令 | AGENTS 等上下文文件及加载规则 | 内容限制/扫描不等于权限控制 |
| Skill | ~/.hermes/skills、外部位置、SKILL.md、技能配置 namespace、toolset requirements | 有可变的 skill 学习/更新内容；Profile 保存选择，不覆盖全部库 |
| 工具 | tools/toolsets、启用、工具发现与预算 | 可见性和运行时依赖可用性分别检查 |
| MCP | mcp_servers、command/url/env、工具 include/exclude、prompts/resources、认证/超时 | `/reload-mcp` 与 gateway 自动监视不同；工具变更通知与 prompt/resource 变更不同 |
| Hooks/插件 | Python plugin、manifest、enabled/disabled、tool/command/hook 注册 | gateway hooks 目录是另一种装载机制，不受普通 plugins.enabled 统一控制 |
| 原生子代理 | delegation 模型/provider/预算等 | 是 Harness 内部能力，不是 Ordessa 工单执行系统 |
| 记忆 | persistent memory 与 memory provider、启用/预算 | memory backend 与一般插件有不同发现/重名策略 |
| 压缩 | compression 策略、auxiliary.compression 模型、context engine | 阈值策略与摘要模型分开 |
| 执行环境 | terminal backend、local/SSH/容器等配置、持久 shell | 这可成为 Profile 环境引用，但不自动赋予操作员部署权 |
| 扩展服务/显示 | LSP、搜索、媒体后端、主题、gateway/telemetry 等 | 配置主体可盘点；gateway 部署和会话输入能力需分范围 |

来源：[SOUL/personality](https://hermes-agent.nousresearch.com/docs/user-guide/features/personality)、[Context files](https://hermes-agent.nousresearch.com/docs/user-guide/features/context-files)、[Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills/)、[Tools](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools)、[MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)、[Plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins/)、[Memory](https://hermes-agent.nousresearch.com/docs/user-guide/features/memory)。

最新插件说明明确一般插件需要启用，项目插件还需额外信任；memory/model-provider 等有专门 loader。**不能做一个“把所有 plugins 子目录复制进去”的安装器。** 上述官网与固定二进制的最小版本映射仍待完成。

## 5. OpenCode

入口：opencode.json/JSONC、用户/项目/.opencode、远端组织默认、环境内联与自定义路径、系统管理层；TUI 配置独立。层叠是合并，不是整文件简单替换。`OPENCODE_CONFIG_DIR` 不意味着屏蔽所有其他配置来源。[Config](https://opencode.ai/docs/config/)

| 面 | 已核配置/机制 | 注意点 |
| --- | --- | --- |
| 模型 | provider、model、small_model、enabled/disabled providers | model 用 provider/model 维度；provider 内 options/模型变体须按 schema |
| 指令 | instructions、AGENTS 与兼容发现 | 相对路径/URL/继承规则另核；不能一律当 SYSTEM 覆盖 |
| Skill | 原生、Claude-compatible、.agents 路径；skill 权限 | 官方只认指定 frontmatter；未知字段忽略；同名路径需处理 |
| Agent | primary/subagent、model/prompt/temperature/top_p/steps/permission/mode/hidden 等 | 旧 tools/maxSteps 与新语义有弃用差异 |
| 命令 | command 配置/Markdown、模板/agent/model 选择 | 命令不必是一份 Skill |
| MCP | local/remote、OAuth、enabled、工具权限 | stdio 进程与远程连接生命周期不同 |
| 原生插件/工具 | plugin 列表、TS/JS 插件、事件与自定义工具 | 执行代码，不是纯声明资源 |
| 权限 | 按工具/命令/路径规则 allow/ask/deny，external_directory 等 | 不能把 approval 等同 OS sandbox |
| LSP/formatter | server 定义、语言映射、命令与格式化配置 | 还依赖机器已安装可执行程序 |
| 上下文 | compaction、tool_output、附件图像、watcher ignore、references | 配置可以预设；历史、snapshot 数据不可复制为预设 |
| 运营/界面 | server、share、autoupdate、TUI keybindings/theme、实验项 | server 端口不属于会话模型配置 |

来源：[官方 Schema](https://opencode.ai/config.json)、[Agents](https://opencode.ai/docs/agents/)、[Rules](https://opencode.ai/docs/rules/)、[Skills](https://opencode.ai/docs/skills/)、[Plugins](https://opencode.ai/docs/plugins/)、[MCP](https://opencode.ai/docs/mcp-servers/)。两级 schema 索引不展开动态 agent/provider 子项的所有字段。

应用未决：多会话 server 级配置与单 session 设置的影响范围、ACP 暴露的变更面未实测。不能仅因为有 HTTP server 就断言配置天然按会话隔离。

## 6. dsh / DeepSeek Harness

研究固定官方 master `477b4f420553e8a52c2fbccc464d7561b239c443`，**没有认定已包含在 Ordessa 的旧版本中**。

入口是按原生 profile 装配的 Cordis 插件树：bundle patches → profile patch → home patch → CLI patches。目标行的 config 整体替换。ACP/headless 默认装配为启动读取；是否 HMR 取决于装配。原生 profile 更像产品组合，不可直接等同 Ordessa 预设。[CLI 行为](https://github.com/deepseek-ai/deepseek-harness/blob/477b4f420553e8a52c2fbccc464d7561b239c443/apps/cli/reference/README.md)

官方[生成配置目录](https://github.com/deepseek-ai/deepseek-harness/blob/477b4f420553e8a52c2fbccc464d7561b239c443/docs/config-catalog.md)按包给出 source、inject、引用类型。下面是语义归类，不是将全部 TS 类型视为可写 schema：

| 面 | 代表包/配置 |
| --- | --- |
| 模型 | agent-default-model；llm-pi-ai provider/model/compat/header/retry；DeepSeek account/API-key；replay |
| 指令 | agent-instructions 文件候选/预算/根发现；persona prefix/suffix；system-prompt 与 runtime context |
| Skills | skill-filesystem 默认/自定义 roots、watch 参数；skill/tool-skill；office 资源 |
| 工具 | tool-fs/bash/pwsh/web/lsp 等输出/超时；tools native/PTC 展现与并发 |
| MCP/LSP | mcp-client stdio/streamable-http、reconnect、startup failure、instruction budget；lsp-stdio |
| 权限/隔离 | permission-presets sandbox+approval；sandbox-policy、sandbox-local runner；本地/沙箱 fs/bash |
| Hooks | hooks-claude-code、hooks-codex 的 configPath、timeout 等 |
| 子代理 | subagent 数量/深度；ACP、Claude、Codex、dsh-sdk、进程内 fork/spawn provider |
| 上下文 | compaction-basic、tool-result-pruner、spill、session-reference、context projections |
| 执行环境 | shell-env、persistent bash、SSH、terminal、PTC Node/Python |
| 原生扩展 | bundles/package-manager、Cordis patches、plugin inventory、HMR |
| 运维 | session log、OTel、persistence/storage、web host、GUI 参数 |

这些包名/类型是查询入口；需进一步逐一用对应 runtime schema 筛除仅运行时注入的字段。例如 ACP `stream` 不是普通用户配置。动态 `Volatile` 不代表任意配置都支持无损热替换。

特别注意：官方 config dump 可能初始化 profile、解析模块，并非保证无副作用的静态读取；本轮没有执行。插件变更、HMR 与会话恢复要分别验证，不能把复制一份 patch 当完整接入。

## 7. Qwen Code

入口：用户/项目/系统 settings.json、system defaults、环境/CLI、资源目录与原生扩展。官网当前配置比仓库旧 pin 丰富，不认定向后兼容。

| 面 | 已核入口 | 关键差异 |
| --- | --- | --- |
| 模型 | modelProviders、model、fastModel/imageModel/voiceModel、fallback、pricing | provider 自身 generationConfig 不自动继承顶层；旧 auth apiKey/baseUrl 配置有弃用 |
| 指令 | QWEN.md、context.fileName/import/includeDirectories、规则文件 | 原生“memory”一词可能指静态指令，不等于自动记忆 |
| Skill | SKILL.md、paths、用户/模型调用、hooks、附件 | paths 激活与斜杠调用不是同一状态；其 Hook 可持续至会话结束 |
| Agent | Markdown model/tools/disallowedTools/approvalMode、模型 grades、executor | 可配置 Codex 等原生执行器；仍是内部委派 |
| 权限/sandbox | approval modes、工具策略、executionSandbox | Linux 操作员级 executionSandbox 不能被项目设置覆盖；需重启 |
| MCP | MCP server 定义、工具策略、环境/认证 | 作用域与连接池要按入口验证 |
| Hooks | 原生事件/命令、Skill scoped hooks | 与 Claude 相似名称不证明全部 ABI 等价 |
| LSP | `.lsp.json`、命令/语言映射、extension lspServers、实验开关 | 原生插件包格式不同，不能推定每种都支持 LSP |
| 扩展包 | qwen 原生 extension；Agent Plugins v1 | portable v1 只支持部分能力；commands/agents/hooks 等目录当前忽略 |
| 上下文/工具 | autoCompact、fileFiltering、idle tool pruning、读取/输出/搜索参数 | 缺省与旧键迁移要按版本核验 |
| 原生界面/运营 | UI/statusline/output style、语音、update、git attribution、遥测 | 部分交互命令会持久化；不适合直接当会话临时应用 |

来源：[Settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/)、[Model providers](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/)、[Skills](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/)、[Rules](https://qwenlm.github.io/qwen-code-docs/en/users/features/rules/)、[Subagents](https://qwenlm.github.io/qwen-code-docs/en/users/features/sub-agents/)、[Hooks](https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/)、[LSP](https://qwenlm.github.io/qwen-code-docs/en/users/features/lsp/)、[Agent Plugins v1](https://qwenlm.github.io/qwen-code-docs/en/users/extension/agent-plugins/)。

重要限制：Agent Plugins v1 文档明确 `allowed-tools` 虽识别为字符串，**不赋予 Qwen 工具预授权**；旧 SSE MCP 项可能直接跳过。统一资源管理必须输出兼容性结果，不能只报安装成功。

## 8. Kilo

研究对象是当前官方 CLI/共享配置，不能混用历史 Roo-based 扩展设置。入口：`~/.config/kilo/kilo.jsonc`、项目 kilo.jsonc / .kilo/kilo.jsonc，TUI 独立配置。官方说明旧文件名兼容限于 Kilo 配置目录，不继续把 OpenCode 目录当隐式来源。[Settings](https://kilo.ai/docs/getting-started/settings)

| 面 | 当前入口/键族 | Profile 处理 |
| --- | --- | --- |
| 模型 | provider/model、small_model、启用/禁用 providers | 供应商目录与选择分离；auth 状态不是预设 |
| Agent/指令 | agent/default_agent/subagent_depth、instructions、command | 不以旧 modes 教程代替当前 schema |
| Skill | skills.paths/urls、skill permission | schema 有字段不等于 loader 全部格式已核定 |
| MCP | mcp local/remote、command/env 或 url/header、OAuth、timeout、enabled | 进程/连接状态由 runtime 管，不放 Profile |
| 权限 | permission 对内置/MCP 工具规则、external_directory | 配置 allow 不等于 OS sandbox；原生隔离实现待核 |
| 原生插件 | plugin 列表；外部工具/事件 | ABI、reload 与支持版本待核 |
| LSP/formatter | lsp、formatter | 可执行文件与环境依赖需要显式可用性 |
| 上下文 | compaction、tool_output、attachment、snapshot、watcher/references | 历史快照不进入预设 |
| 隐私/运营 | privacy_mode、share、retention、autoupdate、remote_control、telemetry | 高影响设置应管理层控制，不因切 Profile 静默启用 |
| 展示 | reasoning/tool/edit display、TUI/theme/keybindings | 不作为 Ordessa UI 配置的直接来源 |

来源：[官方 Schema](https://app.kilo.ai/config.json)、[CLI](https://kilo.ai/docs/code-with-ai/platforms/cli)、[MCP](https://kilo.ai/docs/automate/mcp/using-in-kilo-code)。Schema 的字段存在仅作字段级证据，不足以证明 runtime/ACP 覆盖。

官方 CLI 文档要求修改配置文件后重启；是否能在 Ordessa 现有会话中通过 API 单独刷新、以及重启后的恢复能力，本轮未实测。MCP 文档存在不同格式示例并列，应以目标 CLI schema 和实际 parser 为准，不拼接为一种混合格式。
