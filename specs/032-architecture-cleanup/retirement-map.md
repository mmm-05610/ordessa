# 旧聚合包的接收与删除表

来源：固定 Agent Tools 提交 `20558870b3c1afaf62b1c1b585e6a0739f5acc95`，整合后复核。这里规定去向，不表示迁移已完成。“对照现有”意味着复用已有符号或迁入缺失规则，不能再创建一套同义模型。

## runtime-compat

| 原模块 | 处理 |
| --- | --- |
| api、ProfileEnvelope、旧 config alias | 公共重导出和旧模型删除；只接受核心 Manifest/Ref。必要旧数据转换离线化 |
| bootstrap、catalog | 产品选择/贡献 kinds 归 products/server；通用机制对照核心 catalog。删除正常启动自动 legacy migration 注册 |
| capability 的 ids/errors/documents/match/requirements/selection/slots | 通用规则对照核心已有机制；品牌能力声明归品牌；不新增 registry |
| credentials | 非秘密引用契约归公共 API、SecretStore 实现归 platform-services、品牌凭据解释归品牌 |
| resource_contracts 的 skill/prompt/credential/workspace | 对应资源或 Workspace 已有公开 API；不能将插件字段混入 Pacthold |
| harness_capabilities/runtime_artifacts/home_projection | 中性机制对照核心；品牌原生 Home/资产投影归品牌；旧实例投影删除 |
| runtime_composition assembler/coordinator/fake | 对照现有 core agents assembly 删除重复执行路径，保留必要拒绝保证，不保留第二 coordinator |
| runtime_composition protocol/sandbox_port | 公共环境端口对照 environment-api/core；外部 Sandbox 的具体能力归其插件 |
| storage/database、legacy_migrations、SQL | SQLite 机制对照 persistence-sqlite；旧领域 schema 仅用于显式离线转换，不能整个成为公共库运行时 schema |
| 空壳与重导出 __init__ | 删除，消费者直达新公开入口 |

## server-compat

| 原模块 | 处理 |
| --- | --- |
| plugin、facade | 旧超级 owner 删除，各域通过自己的公开端口服务；不换名保留超级 façade |
| composition | 纯装配归 products/server；品牌工厂与路径归品牌；旧 sidecar 组装链删除 |
| core_wire/wire_projection/wire_validators/http/error_families | 通用协议归 Server；业务方法只绑定领域公开入口。逐方法列退役与新入口，不整块换名保留 CoreWireHandlers |
| profiles | 清单/版本/权限对照 core ProfileCatalog；品牌 posture 解释归品牌；memory/subagents 贡献归其插件；旧记录转换离线 |
| sessions repository/service/queue | 通用输入/操作记录对照 core agents/operations；native 会话和历史操作归品牌。不能整体搬 SessionService 继续持有旧状态机 |
| approvals/records | 治理记录对照现有核心审批；持久化实现归现有持久化接缝 |
| assets catalog/records/plugins/skills/mcp/mcp_probe | 按资源域归对应资源插件；迁移验证禁止真实 MCP probe；已应用 Agent 配置不留资源副本 |
| assets/rendering | 中性材料描述归贡献契约，原生格式渲染归品牌 |
| model_configs | Provider/Model 定义和管理归 assets/model-provider；reasoning/native 映射归品牌；应用规则仍是核心操作+品牌端口 |
| hooks | 各域钩子回对应已有插件；通用规则复用核心。不得造一个新超级 hooks 插件填空 |
| accounts/credential_cli | SecretStore 接线归 platform-services；原生 login/账户解释归品牌；CLI 仅命令客户端，login_engine 不整搬核心 |
| execution/first_run_lock | 已转发核心唯一实现，删除转发并改消费者 |
| execution protocols/execution_contract | 必需中性契约对照 core execution/agents；旧 descriptor/registry 删除 |
| sidecar/sidecar_backend/local_channel | 中性通道对照 harness-transport；原生启动归品牌；旧 sidecar 第二执行器删除 |
| control_plane_sync/delegation/placement/inventory/state_capture/session_store_guard | 保证对照核心既有授权、运行和目录接缝；原拒绝断言保留，旧 store/第二调度器退役 |
| artifact_store/change_set/usage/usage_aggregate | 对照已有 Workspace/资源/core operation evidence；存储接对应领域端口，不重建 execution 状态总库 |
| persistence/ProductRepositoryView | 通用 SQLite 机制归公共持久化；产品域视图拼装留产品，不塞通用库 |

## Harness API 与 Go ACP 桥

- Harness API 中立接入类型对照 core agents 公共契约；模型资源字段归资源 API；硬编码 Pi retry/native 结构归 Pi。禁止整文件搬迁。
- Go codec/transport/中性 JSONRPC/ACP DTO：`packages/backend/harness-transport/adapters/acp-common/`，唯一公共 Go module。
- `internal/codex`、Codex schema/flags、`pkg/codexacp`：`plugins/harness/codex/adapters/acp/`。
- `internal/pi`、gate extension、`pkg/piacp`：`plugins/harness/pi/adapters/acp/`。
- 原 cmd/acp 拆成品牌命令，品牌 packaging 只构建自己入口；不得保留 `--adapter codex|pi` 的超级入口。
- `internal/acp/server.go` 当前 import Codex：先把 events/thread/turn/native 配置映射移 Codex，通过中性端口衔接公共 ACP 流程；Pi 改消费中性端口，不导入 Codex。
- `internal/bridge/session_state.go` 的原生 thread/turn 绑定归品牌 session bookkeeping，不当成 core 持久节点权威。
- 保留 cancel、terminal、prompt、turn-slot 原测试语义；更新 build/manifest/wheel/安装与路径守卫。不能隔离的旧桥能力显式不装配，且退役旧运行入口。

## 前端物理实现与兼容壳

目标叶子是 frontend 下独立 api/loader/host/runtime。实际映射如下：

| 现有内容 | 目标 |
| --- | --- |
| extension-api/src | 真实实现，原位保留；没有 runtime/api，不凭对称想象创建它 |
| extension-runtime/loader 的源码和清单 | 搬至 extension-loader，替换 forwarding 源码；合并为一份清单，保留包名和 extension id |
| extension-runtime/host 的源码、测试、配置和清单 | 搬至 extension-host，替换四个 forwarding 出口；顶层已有 surface-input-ticket 测试合并保留 |
| extension-runtime/src/state | runtime 自己的真实 stateStore/tasks/uiStorage，原位保留，host 正常依赖它 |

runtime 删除所有 host/loader exports；消费者改独立 host/loader 的公开导出。新增 host 自有 services/command-registry 与 services/surface 导出，不跨包深路径。修正源码、vitest alias 及产品测试中相对路径，删除 runtime 下旧 host/loader 目录及同名 manifests，刷新 workspace/lock 并核对 symlink 来源。

`extension-runtime/tests/migration-identity.test.ts` 的“转发壳与实现同对象”不再是目标：替换成独立叶子、旧嵌套目录缺席、无 forwarding exports 的守卫，并继续证明公共导出完整、对象唯一，不能只删除旧断言。

026 合入的 `legacy-commands-adapter` 是基线事实，不是迁移完成例外。命令消费者同步迁入唯一新 owner，最终删除旧命令 adapter 及转发出口；保留重入、生命周期失效和捕获围栏断言。

每一项必须补“接收符号/删除理由、消费者、测试”。没有明确接收/拒绝证据不得仅按目录名删除，也不得因工作量大继续让旧包活跃。
