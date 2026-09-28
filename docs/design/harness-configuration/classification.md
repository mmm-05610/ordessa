# 分类：先按用户目的组织，再按应用机制实现

本文是 Ordessa 的设计建议，不是某个上游提供的统一接口。

## 一、用户看到的能力分类

| 类别 | 要盘点的内容 | Profile 应保存什么 | 不应混入什么 |
| --- | --- | --- | --- |
| 1. 模型与推理 | provider/model、认证方式引用、endpoint、模型目录、effort/thinking、采样、输出上限、上下文窗口、fallback、辅助模型、缓存与请求选项 | 选择关系和有效参数；供应商定义引用 | 明文密钥、OAuth token、所有 provider 都支持同一参数的假设 |
| 2. 指令与人格 | system/developer 指令、AGENTS/CLAUDE/SOUL、路径限定规则、输出风格、提示词导入、长度限制与发现规则 | 内容引用、追加/替换方式、适用范围 | 擅自覆盖项目已有文件；把自然语言“禁止”当硬权限 |
| 3. Skill 与快捷命令 | SKILL.md、附件/脚本/依赖、发现路径、启用、用户/模型可调用性、路径触发、命令模板和参数 | 资源引用、启用与调用限制、配置值 | 已执行历史；把所有斜杠命令当 Skill |
| 4. 工具暴露与行为 | 内置工具开关、toolsets、allow/deny、搜索/读取/输出大小、并发、超时、发现预算 | 工具选择及参数 | 暴露列表等同于权限隔离；把资源存在当可用 |
| 5. 外部服务 | MCP、LSP、搜索后端、浏览器/CDP、图像/语音后端 | 连接定义引用、可用工具子集、超时、凭据引用 | 连接进程、OAuth 状态、跨会话共享连接的隐含假设 |
| 6. 权限与审批 | 自动/手动审批、命令/路径/域名规则、工具授权、计划模式的实际限制、管理员策略 | 期望规则与模式；受更高策略约束 | 笼统 yolo 布尔值；将各家同名模式当等价 |
| 7. Harness 原生隔离 | 原生 sandbox 文件/网络策略、例外、backend、挂载与环境暴露 | 原生可配置的隔离选项和环境引用 | Ordessa 自己的执行资源租约；认为配置目录隔离就是安全沙箱 |
| 8. Hooks 与可执行扩展 | 事件、匹配器、command/HTTP/MCP/prompt handler、超时、异步、插件包、自定义工具/provider | 已批准版本引用、启用、声明参数 | 任意代码当普通文本；观察性 Hook 冒充强制约束 |
| 9. 原生子代理 | 角色、提示词、模型、工具、权限、MCP、记忆、并发/深度、执行器/隔离 | 模板和选择、预算 | 外层多 Harness 派工/通信系统；正在运行的子代理 |
| 10. 上下文与记忆 | memory 开关/后端/作用域、压缩阈值/模型、裁剪、索引、上下文文件和附件规则 | 策略、后端引用与预算 | 自动生成记忆正文、会话全文、当前压缩摘要 |
| 11. 运行环境与可靠性 | env、shell、cwd 解析、代理、重试、传输方式、超时、持久 shell、日志与存储策略 | 允许的执行参数、机器资源引用 | 全量复制 HOME/PATH；Profile 决定产品监听地址或安装版本 |
| 12. 界面、隐私与运营 | 主题/快捷键、通知、语言、遥测、反馈、更新、远程入口、数据保留 | 仅明确与 agent 行为相关的偏好；其余进入 Harness 管理设置 | 把原生 TUI 偏好强行映射成 Ordessa Chat；在切 Profile 时静默开启遥测 |

这十二类是盘点/设置导航的候选分组，**不是十二个必须创建的插件**。例如 Skill 插件同时拥有包管理设置和向 Profile 注册的启用字段，避免拆成内容插件与选择插件。

## 二、实现只需要讨论六种处理机制

| 机制 | 典型对象 | 可以复用的共同工作 | 不能统一掉的部分 |
| --- | --- | --- | --- |
| A. 类型化参数 | effort、预算、超时、模型选择 | schema 校验、默认值、合并、版本判断、回读 | provider 协议含义、单位、范围、缺省/删除语义 |
| B. 内容资源 | Skill、指令、命令模板、子代理说明 | 来源/版本/附件、内容编辑、引用、安装清单 | 发现路径、frontmatter、触发、继承与加载优先级 |
| C. 服务绑定 | MCP、LSP、provider、搜索后端 | 定义、secret reference、健康状态、启停与撤销 | 传输协议、OAuth、工具过滤、进程所有权 |
| D. 可执行扩展 | Hook、原生插件、自定义工具 | 来源与哈希、依赖、批准、版本 pin、装载/卸载 | 执行 ABI、事件、阻断语义、资源清理与权限 |
| E. 强制策略 | 权限、审批、原生 sandbox | 可解释规则、上级策略约束、冲突检查、负例验证 | 操作系统支持、原生规则引擎、fail-open/fail-closed |
| F. 运行偏好 | 压缩、记忆策略、shell、重试、显示 | 声明作用域、参数表单、重启计划 | 状态迁移、缓存污染、跨会话影响 |

一个对象可涉及多个机制：Skill 正文属于 B，内附 Hook 属于 D；MCP 定义属于 C，工具权限属于 E。不能因“都能写 JSON”而合并成一个通用透传器。

## 三、每项能力必须另外标记的维度

- **证据层**：官网声明 / 固定版本源码 / 受控运行证据 / 当前 Ordessa 通路证据。
- **作用域**：组织、机器、用户、项目、进程、会话、单次请求。上游层级与 Ordessa 层级分开。
- **所有者**：原生 Harness、原生扩展、Ordessa 业务插件、宿主管理员。谁有权写，谁能撤销。
- **生效方式**：请求参数、原生会话 API、显式 reload、替换进程并恢复原会话、只允许新建、未知。不得从“可改文件”猜热更新。
- **合并方式**：覆盖、深合并、集合追加、按名称替换、deny 优先、整行替换。`false`、空数组、删除、继承必须区别。
- **隔离与外部影响**：专用配置根是否仍扫描项目/用户资源；凭据、keychain、缓存、记忆、扩展是否共享。
- **真实性**：解析成功、写盘成功、运行时装载成功、行为生效是四种证据，不互相代替。

## 四、共同处理不代表相同语义：已查到的反例

1. **同为 Skill，字段不兼容**：OpenCode 明确只识别指定 frontmatter；Qwen 的 Skill 有路径激活和 Hook 生命周期。复制成功不代表限制生效。[OpenCode](https://opencode.ai/docs/skills/)、[Qwen](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/)
2. **同为指令，位置不同**：Hermes 的 SOUL 是实例人格，不是项目 AGENTS；Profile 不应把它们作为同一个文件槽覆盖。[Hermes](https://hermes-agent.nousresearch.com/docs/user-guide/features/personality)
3. **同为 MCP 更新，入口不同**：Hermes CLI 的显式 reload 与 gateway 的配置监视不是同一种应用策略；不能自动推广到 ACP。[Hermes MCP](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp/)
4. **同为 Hook，失败不一定阻断**：Codex MCP Hook 的错误或缺失服务不阻断操作。用它承载必须执行的安全检查会产生错误承诺。[Codex Hooks](https://learn.chatgpt.com/docs/hooks)
5. **同为权限配置，不一定允许用户写**：Qwen 的 executionSandbox 是操作员层约束；Profile 只能表达允许范围内的要求，不能写项目配置绕过它。[Qwen settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/)
6. **同为合并，算法不同**：dsh patch 的目标行 config 整体替换，不能使用通用 JSON 深合并实现。[dsh CLI](https://github.com/deepseek-ai/deepseek-harness/blob/477b4f420553e8a52c2fbccc464d7561b239c443/apps/cli/reference/README.md)
