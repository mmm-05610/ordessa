# Agent 源码模块组织对照与 Ordessa 插件目录建议

状态：讨论稿，不是新增实施任务。2026-09-27 只读研究；不改变正在执行的 010-platform-core 三条工作线，不移动源码、不修改其 Spec Kit 验收条件。

## 1. 取证范围

浅克隆官方仓库，阅读 package manifests、真实导入、服务注册、扩展契约与内置贡献实现。未安装或运行上游应用、未调用模型；不是完整架构或安全审计。

| 项目 | 本次源码 SHA | 主要取证面 |
|---|---|---|
| zai-org/ZCode | `29628c9acdb81b703bbd4080c207a0e7ce5e276e` | services/accessor、collection、descriptors，provider/provider-node，UI，architecture-policy |
| anomalyco/opencode | `b471c2b4495747353af768fbf2e0790c9d820ce2` | core、plugin API、TUI slots/builtins/sidebar-mcp、TUI 实际依赖 |
| earendil-works/pi（通过旧 badlogic/pi-mono 地址克隆） | `2b0a123de98318c2ff8069661721ce0c3794c34e` | ai/agent/tui/coding-agent 包，ExtensionAPI、loader |

## 2. 源码事实与可借鉴之处

### ZCode：按技术层分包，层内按业务域分模块

`packages/services/src/` 包含 session、model-provider、skills、credential、git、terminal 等业务目录。ServiceDescriptor 用频道名关联接口类型；ServiceCollection 注册实例并经 ProxyChannel 暴露。UI 使用 IServiceAccessor，后者集中列出许多业务服务：这是服务化模块组织，不足以证明独立安装/卸载。

Provider 的规则/视图在 `packages/provider`；文件仓储和运行时材料化在 `provider-node`；远程调用面在 `services/model-provider/providerFacadeServices.ts`。其中 ProviderSettings 与 ModelSelection 是不同接口。这证明一个业务域可以分出多个职责面，但不意味着 Ordessa 也要拆成三个独立插件。

`architecture-policy.yaml` 有公开入口、依赖、分层、禁止循环/深导入的规则，但 `managedOnly: true` 且大多模块 `managed: false`，不能把这些规则当作全仓已经达成的事实。UI 包还包含大量产品业务组件，不宜照搬成 Ordessa 的中性 Workbench。

源码：[服务注册](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/services/src/collection.ts)、[集中服务接口](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/services/src/accessor.ts)、[模型服务](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/services/src/model-provider/providerFacadeServices.ts)、[架构规则](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/architecture-policy.yaml)。

### OpenCode：独立展示包，内置功能也通过扩展点注册

仓内分别存在 desktop、app、tui、ui、core、server、sdk、plugin 等包。TUI 的 `feature-plugins/builtins.ts` 显式列出内置贡献；`sidebar/mcp.tsx` 从 TuiPluginApi 读取 MCP 状态，向 `sidebar_content` 注册显示组件，没有因此获得 MCP 连接所有权。`plugin/slots.tsx` 负责槽位注册和插件错误报告。

值得借鉴：业务服务所有权与“显示在某个宿主槽位”分离，内置功能也走扩展入口。不能照搬：core 本身包含 provider/session/permission/skill 等 Agent 业务，它不是 Pacthold 式中性治理内核。TUI manifest 与实际源码仍引用 core，不能用仓内无 core 依赖的设计目标代替当前事实。

源码：[内置贡献清单](https://github.com/anomalyco/opencode/blob/b471c2b4495747353af768fbf2e0790c9d820ce2/packages/tui/src/feature-plugins/builtins.ts)、[MCP 侧栏贡献](https://github.com/anomalyco/opencode/blob/b471c2b4495747353af768fbf2e0790c9d820ce2/packages/tui/src/feature-plugins/sidebar/mcp.tsx)、[槽位](https://github.com/anomalyco/opencode/blob/b471c2b4495747353af768fbf2e0790c9d820ce2/packages/tui/src/plugin/slots.tsx)、[实际依赖](https://github.com/anomalyco/opencode/blob/b471c2b4495747353af768fbf2e0790c9d820ce2/packages/tui/package.json)。

### Pi：可复用库与具体 Agent 产品分开，扩展接口面向具体能力

本次树中有 ai、agent、tui、coding-agent 等包，也有其他新增包；这里不将其简化为完整的四包架构。tui manifest 不依赖 Agent 产品；agent 使用 ai；coding-agent 组合 agent、ai、tui。ExtensionAPI 提供注册工具/命令/供应商、订阅事件，以及 UI widget/header/footer 等具体能力。

值得借鉴：底座库不反向依赖具体展示产品；扩展使用清楚的操作，不需要自己拼内部对象。不能照搬：Pi 的 Agent 内核负责模型调用循环，Pacthold 不应因此接管各 Harness 的模型循环；Pi 扩展可访问相当丰富的能力，也不能据此宣称权限隔离或任意安全热卸载。

源码：[TUI 包依赖](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/tui/package.json)、[Agent 实现](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/agent/src/agent.ts)、[扩展接口](https://github.com/earendil-works/pi/blob/2b0a123de98318c2ff8069661721ce0c3794c34e/packages/coding-agent/src/core/extensions/types.ts)。

## 3. 对 Ordessa 的建议

目录、发布包、运行时插件是三个不同边界：族目录不加载任何东西；一个业务域可拥有前后端多个入口；只有确需独立启停、独立依赖/生命周期的部分才拆成独立插件。普通内部模块只需守住接口与导入边界。

目标导航草图（非本轮搬迁清单，未实现目录不建占位）：

```text
plugins/
├── connectors/                 # 协议接入族，不拥有会话/业务配置
│   ├── ordessa/
│   └── acp/
├── agent/                      # Agent 业务族；不是第二个执行内核
│   ├── harness/                # 品牌发现、原生适配、配置应用/重启恢复
│   ├── sessions/               # 业务会话身份、历史、会话与执行关联
│   └── chat/                   # 对话 UI、输入与对话扩展槽
├── configuration/              # 配置业务族
│   ├── profile/                # 配置集合、字段贡献、会话覆盖规则
│   └── model-provider/         # provider/model 配置、目录与选择 UI
├── workspace/                  # 项目/工作目录；git/worktree 先按内部模块分
├── assets/                     # 资产业务族
│   ├── catalog/                # 仅在确有共享资产模型时独立
│   ├── skills/                 # Skill 资产管理，不执行工作制度
│   └── prompts/                # 有独立需求时才实现
├── server-compat/              # 临时迁移出口，非最终设计组成
└── runtime-compat/             # 本轮历史兼容出口，非最终设计组成
```

通用 Connections 在 desktop-platform，Workbench 在 packages；不回迁到上述目录。MCP 不先归为纯资产：配置资产与实际连接/工具服务不同，确定运行所有者后再定目录。commands 按命令所有者归属，不仅因都是命令便全部迁到 chat。

以上 agent 家族是建议归类，不承诺需要新建 sessions 插件。必须先核对已有 agent/sessions、ACP sessions 服务与后端会话管理：原生会话操作属于 ACP/Harness，跨执行持久身份属于会话域，显示状态属于 Chat，禁止三份权威状态。旧 agent/connections 的业务部分也先按所有权归属，不能因通用连接迁走就全部删除。

## 4. 业务域内部结构与依赖规则

例如 model-provider 可有 `contracts/`、`backend/`、`frontend/`、`tests/`。backend 内再分规则、存储与宿主注册，frontend 内分服务客户端、UI 与贡献注册。只在体量需要时建目录，不强制每层各发一个包。跨 Python/TS 的公开传输形状须有权威规范与一致性测试，不能只放两个同名类型即认为一致。

- Profile 不内置模型/Skill 等字段实现；配置面提供者注册字段和校验。
- Model-provider 拥有供应商模型配置，可以对 Profile 贡献配置面，对 Chat 贡献选择器；两者都是可选接入，不能倒逼 Chat/Profile 依赖 Model-provider 的具体实现。
- Harness 负责把配置应用到原生进程，含能力校验与必要的重启/resume；不知道 Profile 的保存结构，也不拥有模型设置表单。
- 可选贡献需要双方都存在才注册：使用宿主已有机制或域内窄集成入口，不再发明一个总协调层。硬依赖、可选贡献必须分别声明。
- 卸载配置面提供者隐藏入口但保留数据；未知字段不得错误地下发。卸载 Chat 不影响模型设置；卸载模型配置插件不应破坏使用 Harness 现有原生配置的基础对话。
- Pacthold 管执行与资源生命周期；Server 管注册、传输及插件生命周期。两者均不出现 Profile/模型/聊天字段。

## 5. 何时才值得拆插件

先回答数据与副作用归谁、公开什么能力、消费什么能力、缺席时剩余系统能否继续、卸载后资源如何回收。仅有 UI 插槽或单一配置字段，不自动成为独立插件。

固定公开契约下，一个功能修改原则上落一个业务域；需要协议演进时跨域修改正常。跨包改动数量不是合并包的唯一标准；长期同步改相同细节、双方互相读取内部状态才说明边界有问题。

## 6. 与进行中任务的关系

当前只形成后续业务插件整理的参考。等 Qoder 交付后，以实际导出契约和现有数据所有者对照再定迁移清单；不改三个工作树、不追加任务、不切分支、不合并。本次研究不证明已有插件符合上述目标，也不取代其实现验收。
