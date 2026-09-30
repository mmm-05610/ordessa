# 多 Harness 产品的内部组织：源码对照

2026-09-30。仅源码研究，不是实现完成或能力验收。浅取公开仓库 HEAD，未安装依赖、运行上游产品或调用模型；Ordessa 根 main、host 和用户服务未动。

## 固定来源与实际读取入口

源码下载目录：`/tmp/ordessa-harness-structure-XLNZbm/`。下列链接固定 SHA，不把后续 main 变化当成本次证据。

| 项目 | SHA | 主要读取入口 |
| --- | --- | --- |
| Codeg | `5a4925f4bac3fed070a817aa2ee927eb0b7726a0` | `src-tauri/src/acp/{mod,manager,registry,agent_process,preflight}.rs`；`commands/model_provider.rs` |
| Orca | `85f8d6b5f507df795cd3cef1cdea08124cf801ee` | `src/main/runtime/{structured-agent-session-runtime,structured-claude-runtime-adapter}.ts`；`native-chat/agent-session-wire/{structured-agent-session-adapter,structured-agent-session-adapter-router}.ts`；`native-chat/agent-model-catalog/agent-model-catalog-fingerprint.ts` |
| T3 Code | `c2fa9fc911daeac97df4760f95fc57dca42b84c8` | `apps/server/src/provider/{ProviderDriver,builtInDrivers}.ts`；`Services/{ProviderAdapter,ProviderAdapterRegistry,ClaudeAdapter}.ts`；`Drivers/ClaudeDriver.ts` |
| ZCode | `29628c9acdb81b703bbd4080c207a0e7ce5e276e` | `packages/services/src/{node.ts,zcode-agent/zcodeTaskServiceAdapter.ts,model-provider/providerFacadeServices.ts}` |

## 事实与借鉴分别记录

### Codeg：共享 ACP 管理，品牌差异散列成专属模块

[`acp/mod.rs`](https://github.com/nobug-project/codeg/blob/5a4925f4bac3fed070a817aa2ee927eb0b7726a0/src-tauri/src/acp/mod.rs) 列出共享进程、连接、会话、预检、生命周期与品牌专用 catalog/compat 模块。不是每个品牌一个完整目录。`manager.rs` 通过连接命令提供 `set_config_option`，追踪 spawn 配置指纹与 stale 状态；`registry.rs` 集中发行版本、启动参数和发行方式。`commands/model_provider.rs` 仍有 Claude/Codex 特定校验，品牌细节并未完全封闭在 ACP 层。

借鉴：共用 ACP 传输与会话操作，标准协议支持的配置不另造路径。限制：本快照 manager 9394 行、registry 3486 行；不要复制成 Ordessa 的巨型总管，也不能把 stale 提示当作已应用 Profile。

### Orca：共享会话路由，原生品牌实现分开

[`structured-agent-session-adapter-router.ts`](https://github.com/stablyai/orca/blob/85f8d6b5f507df795cd3cef1cdea08124cf801ee/src/main/native-chat/agent-session-wire/structured-agent-session-adapter-router.ts) 按会话保存实际 adapter 所有者；Claude/Codex 各自实现原生 session adapter、launch resolution、model catalog。`structured-agent-session-runtime.ts` 是明确组合点，当前直接构造两个品牌，并非完全动态注册发现。模型目录身份钉在 durable record 中启动时的 account home/host，不采用当前全局选择。

借鉴：共享层按实例/会话路由，不重新按 UI 选择猜所有者；恢复和原生进程行为由品牌负责。限制：PTY 支持不能当结构化能力；本次读取的结构化组合主要是 Claude/Codex，不证明其它品牌同等可用；账户目录机制也不要求 Ordessa 为每个 Profile 复制 HOME。

### T3 Code：品牌 Driver 工厂与运行 Instance 分离

[`ProviderDriver.ts`](https://github.com/pingdotgg/t3code/blob/c2fa9fc911daeac97df4760f95fc57dca42b84c8/apps/server/src/provider/ProviderDriver.ts) 区分 driver、instance、adapter；工厂由配置和基础设施创建实例，契约要求不同实例无共享可变状态，实例资源随 scope 关闭。`ProviderAdapterRegistry` 只查找实例 adapter，不拥有会话生命周期；`ProviderAdapter` 声明模型切换等能力；Claude driver 使用实例配置构造实现并将探针缓存按 binary/HOME 区分。`builtInDrivers.ts` 仍是显式静态组合清单。

借鉴：品牌注册的是工厂/能力实现，而不是一个全局可变 adapter 单例；运行身份、资源和配置查询归当前实例。限制：这里 Provider 指 Harness 驱动，不等于 Ordessa ModelProvider 模型供应商；源码接口目标不替代隔离实测，不移植其 Effect 体系或服务框架。

### ZCode：业务分层可参考，不作为当前多 Harness 驱动模板

[`providerFacadeServices.ts`](https://github.com/zai-org/ZCode/blob/29628c9acdb81b703bbd4080c207a0e7ce5e276e/packages/services/src/model-provider/providerFacadeServices.ts) 区分 ProviderSettings 与 ModelSelection。源码中 `node.ts` 与 `zcodeTaskServiceAdapter.ts` 明确提及第三方/legacy ACP 下线；后者仍有 Claude 历史导入，不等于运行多 Harness。

借鉴：供应商管理与会话模型选择的业务面分开。不能据旧文档宣称这份源码仍是完整多 Harness 实现，更不能因此搬运其后端作为模板。

## 对 Ordessa 的建议（待实现，不创建空目录）

1. 复用已有 `ordessa_harness/pi`、`codex`、`claude` 品牌目录；在各目录加入按能力划分的 `configuration/`，不为了新增 `brands/` 中间层搬迁全部已工作的运行代码。
2. 每个品牌的显式 registration 汇聚 runtime 与配置适配贡献。同品牌 model/skills/mcp/prompt 等实现共享当前实例的版本、私有配置位置、原生会话、generation 和受控动作通路，不各自管理进程。
3. 共享 `application/`、贡献注册、ACP transport/registry 继续复用。纯编译逻辑产出计划；副作用统一应用，重启/resume 由对应品牌运行实现执行。原生同一配置文件不出现多个独立写者。
4. 业务插件只提供资源管理、配置选择和引用解析；不提供品牌文件 renderer、原生 option 字符串猜测、重启策略。Harness 不反向导入 ModelProvider/Skills 的实现或存储。
5. 不设计包含所有资源方法的大 adapter 类。一个品牌显式注册多个配置能力；共享上下文、生命周期和计划执行，而非强迫未支持的能力有假实现。
6. 当前支持按实例版本和观察事实判定，不按“品牌通常支持”宣告；缺席/不支持/未知均明确。保持现有 adapter/facet 等外部标识，物理迁移不改变账本身份，不留旧 import shim。

目标草图：`application/` 与通用 `runtime/`、`server_acp/` 共享机制；`pi|codex|claude/registration.py` 加各自 `configuration/{model,skills,mcp,prompt,...}.py`。只有有真实实现与消费者的模块才落盘。工厂/实例区分是语义边界，不要求再加一层新框架。

## 最低验证要求

品牌与能力注册冲突明确拒绝；一个实例的配置变更/释放不影响同品牌另一个实例；并发资源更新统一计划且原生文件单写者；busy 时不打断输出；unknown 不自动重试/重建；卸载贡献不留下旁路；重复新旧导入路径不存在。原生 setter 返回 ACK 不等于已应用，仍须独立读回。源码研究不能关闭产品 Profile、Skills 或 Codex/Claude 真实切换待办。
