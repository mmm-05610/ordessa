# 多 Harness 产品源码对照：ZCode、Codeg、Orca

状态：2026-09-27 只读研究；为后续 Spec Kit `research.md` 提供输入，不是实施或合并授权。没有运行上游应用、调用真实模型或修改三个进行中的核心工作树。源码事实以固定提交为准，不能把项目官网宣传或源码注释直接当成 Ordessa 已有能力。

## 1. 对象与证据边界

| 项目 | 固定 SHA / 许可 | 本次关心的问题 |
| --- | --- | --- |
| [ZCode](https://github.com/zai-org/ZCode) | `29628c9acdb81b703bbd4080c207a0e7ce5e276e`，Apache-2.0 | 展示组件、模型/供应商业务分层；核对当前多 Harness 源码状态 |
| [Codeg](https://github.com/xintaofei/codeg) | `2774a7e02cb8da15211c373802faa44bcd5f8b0c`，Apache-2.0 | 多 ACP Agent 注册、安装/预检、连接/重连、配置生效与选择 UI |
| [Orca](https://github.com/stablyai/orca) | `27b823f934f739bc85914dd717b776835f60bcf7`，MIT | CLI/PTY 与结构化会话双路径、worktree 启动、进程与模型目录身份 |
| [araa47/orca](https://github.com/araa47/orca) | `f9efbb42947febfba5827c1045d0aa1e2a8407c6` | 同名但不同产品：工作树、tmux、消息/事件、唤醒；只供未来工作系统参考 |

这里的“Orca”以 stablyai/orca 为主，因为它是桌面多 Agent 产品。另一个 araa47/orca 是编排器，不把两个项目的能力拼成一个产品。仓库 `orca-cli/orca` 虽有 adapter/registry 接口，但本次快照更多是脚手架，未用它作为生产行为证据。本次仅抽查关键源码和测试/文档，未做完整质量、安全或许可审计；源码移植前仍需按文件核对依赖与声明。

## 2. 关键发现

### ZCode：适合借展示，不适合作为当前多 Harness 路由样板

[官网文档](https://zcode.z.ai/en/newdocs/agent-framework)仍介绍 ZCode Agent、Claude Code、Codex、Gemini CLI、OpenCode 等多框架；但所读源码在 [node.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/services/src/node.ts) 提到“清理第三方 ACP”，在 [zcodeTaskServiceAdapter.ts](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/services/src/zcode-agent/zcodeTaskServiceAdapter.ts) 提到“legacy ACP 下线”。这是**文档与快照之间待核实的版本差异**；未运行产品，不能据此断言发行版完全不能接多 Harness，但不能把这份快照当可直接移植的多 Harness 后端。

仍可逐组件研究消息、思考、工具调用、审批展示；移植时剥离服务 accessor、状态仓储、RPC 和品牌策略，落到 `plugins/agent-ui` 的数据/回调组件。模型 UI 可借信息架构，但不能照搬其服务总接口。此前详见 [上游模块组织研究](agent-source-module-organization-research.md)。

### Codeg：ACP 多 Agent 经验最直接，但宿主集中过重

[注册表](https://github.com/xintaofei/codeg/blob/2774a7e02cb8da15211c373802faa44bcd5f8b0c/src-tauri/src/acp/registry.rs) 为 Agent 记录发行方式（npx、binary、uvx）、版本、平台文件/校验、预检与能力例外（如 `supports_mcp`）。[连接管理器](https://github.com/xintaofei/codeg/blob/2774a7e02cb8da15211c373802faa44bcd5f8b0c/src-tauri/src/acp/manager.rs) 对同 Agent/目录/会话的并发连接去重，区别复用活连接和恢复会话；追踪正在退出的子进程，并比较运行时有效配置指纹，向会话提示“配置变了、需重启”。[前端 Agent 列表 hook](https://github.com/xintaofei/codeg/blob/2774a7e02cb8da15211c373802faa44bcd5f8b0c/src/hooks/use-acp-agents.ts) 从后端读取权威列表，订阅变更，保留短暂故障前的列表，并防旧请求覆盖新结果。[选择器](https://github.com/xintaofei/codeg/blob/2774a7e02cb8da15211c373802faa44bcd5f8b0c/src/components/chat/agent-selector.tsx) 区分用户显式选择与自动回退。

值得借：版本钉死+预检+能力例外、按会话键去重、未知启动结果不能盲重试、配置有效指纹与“需重启”状态、前端仅消费后端权威可用列表。不能照搬：巨型静态 registry 与 manager 同时承载品牌、进程、会话、审批和供应商业务；[自定义 Agent 注册](https://github.com/xintaofei/codeg/blob/2774a7e02cb8da15211c373802faa44bcd5f8b0c/src-tauri/src/acp/custom_registry.rs) 为复用静态 API 将动态字符串泄漏为 `'static`，恰是插件动态性不足的警示。Ordessa 应让品牌描述与生命周期归 `plugins/harness`，通用宿主只消费注册契约。

### Orca：明确分开“结构化会话”与“终端运行 CLI”

[启动模式](https://github.com/stablyai/orca/blob/27b823f934f739bc85914dd717b776835f60bcf7/src/main/agent-launch/agent-launch-mode.ts) 先依据用户偏好、workspace/host 支持能力判结构化或终端路径；[执行器](https://github.com/stablyai/orca/blob/27b823f934f739bc85914dd717b776835f60bcf7/src/main/agent-launch/agent-launch-executor.ts) 先正确创建 worktree，再问执行 host 是否可建结构化会话；只有“明确拒绝且尚未创建”才安全降级到终端，未知结果不能自动再建一个 Agent。其源码也坦承目前只有一部分入口共用这一执行器，不能宣称全产品已经统一。

[模型目录指纹](https://github.com/stablyai/orca/blob/27b823f934f739bc85914dd717b776835f60bcf7/src/main/native-chat/agent-model-catalog/agent-model-catalog-fingerprint.ts) 由 Agent、启动时绑定的账户配置目录、执行 host/WSL 身份组成；会话看的是**启动时绑定的配置目录**，不是此刻全局选择的账户。这对 Ordessa 的 Profile/provider 会话隔离很有用，但只证明 Orca 针对 Claude/Codex 的这个目录机制，不证明所有 Harness 都能任意热切换。Orca 的“任意 CLI Agent”覆盖面首先来自 PTY；不等于每个 Agent 都有统一的结构化会话、模型和审批能力。[官方支持说明](https://www.onorca.dev/docs/agents/supported)应与这两条路径一起阅读。

可借启动阶段的“明确拒绝/结果未知”分界、worktree 与会话创建先后、进程所属和模型目录身份；不能把 PTY 通路冒充 ACP 通路，也不复制其宽松的权限启动默认值。araa47/orca 的 [架构说明](https://github.com/araa47/orca/blob/f9efbb42947febfba5827c1045d0aa1e2a8407c6/ARCHITECTURE.md) 可留给未来工作系统参考 worktree/state/events/wake 的分界，不作为当前 Chat/ACP 能力证明。

## 3. 对 Ordessa 的逐模块复用裁定

| Ordessa 模块 | 首选来源与使用方式 | 必须自己拥有的部分 / 禁止照搬 |
| --- | --- | --- |
| `plugins/agent-ui` 消息、思考、工具/审批展示 | ZCode：逐组件源码审计后限量移植/改造 | 只接收数据和回调；不带 ZCode accessor、store、RPC、连接器 |
| `plugins/harness` 品牌/启动描述 | Codeg registry：借字段与预检方法；Orca：借结构化/PTY 判定原则 | 动态插件注册、品牌能力的真实证据、进程/适配器所有权；不建静态 mega-registry |
| `plugins/connectors/acp` 协议会话 | Codeg manager：借按键去重、复用活连接/恢复持久会话、退出进程追踪 | 保留 Ordessa 已有 run/approval/取消时序规则；不把品牌或 provider 配置塞进 ACP 客户端 |
| Chat 的 Harness 选择 | Codeg 列表 hook/选择器：借权威列表、乱序防护、显式选择/回退区分 | 列表由 Server/Harness 提供；前端不推算安装或可用性。展示可用 `agent-ui` 组件 |
| `plugins/assets/model-provider` | Codeg 的有效配置指纹与会话陈旧提示、Orca 的启动账户目录绑定：借设计 | Provider/model 实体、Profile 贡献、Chat 选择 UI；实际应用/重启/resume 由 Harness 适配器负责，不写宿主全局配置 |
| `plugins/profile` | 本项目规格自行实现 | 配置片段注册、每会话覆盖和 Profile 切换规则；不借上游“覆盖全局配置”策略代替会话隔离 |
| `plugins/assets/{skills,mcp,hooks,…}` | 优先各 Harness 原生能力的官方契约；上列三产品仅供交互与生命周期参考 | 每域明确内容/运行所有权、缺席/卸载语义；不因“都可配置”而混成一个插件 |
| 将来跨 Harness 工作系统 | araa47/orca 的状态/事件/唤醒模块仅作架构参考 | Pacthold 资源/执行治理与业务策略分开；不预置固定 DAG 或自动批准策略 |

## 4. 实施前还欠的核查

1. 对每个拟移植的 ZCode 组件，列固定源码路径、实际导入闭包、许可证声明、要删除的 service/store 依赖及视觉回归；“Apache-2.0”不等于任意文件可直接拷而不保留声明。
2. 对 Pi、Codex、Claude 等每个品牌，分别列结构化/ACP/PTY 支持、配置目录作用域、模型切换时机、恢复路径、审批与取消能力；Codeg/Orca 的公共字段不能取代品牌证据。
3. 配置变更的指纹只包含**实际影响运行实例**的值。展示名等纯 UI 修改不触发“需重启”；正在运行的会话不能悄悄应用全局变化。
4. 明确拒绝才可在同一 worktree 降级/重试；未知结果必须保留并让用户看见，防止创建双 Agent、双通道或双会话。
5. 核心三工作线交付后再核对真实契约并形成 Spec Kit `research.md`/`contracts/`；本文件不修改现有工作树、验收或开发分支。
