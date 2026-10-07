# 旧→新迁移映射（执行清单）

状态：迁移进行中。本表是 plan.md §1 要求的逐模块映射，来源为三个只读勘察报告（2026-10-07）与固定整合起点 `665ef379819bc2bac3afa68486cf8377b73975d5`。每行给出去向与消费者；执行时逐项打勾并记录在 evidence/。

图例：`→迁` = 移动/合并到目标；`→删` = 删除（消费者切走）；`→拒` = 新链显式不可用；`历史` = 冻结证据不动。

## 0bis. Decision 整包迁入 Pacthold（2026-10-07 用户修订，替代此前"Jev 移插件、业务流程移产品"）

| 旧 | 处置 |
| --- | --- |
| `packages/backend/decision/src/ordessa_decision/`（contracts/runtime/providers/jev/flows/integrations/evidence/offline/public） | →整包迁 `packages/backend/pacthold/src/pacthold/decision/`；内部组织与行为不变，不拆分 Jev 提供者、决策流程或证据模块 |
| `packages/backend/decision/tests/`（359 项） | →`packages/backend/pacthold/tests/decision/`（Pacthold 发行内 Decision 模块隔离测试）；保留无 Jev 依赖时的通用离线流程、纯读、预算、取消及拒绝路径保障，不删断言换绿 |
| `checks/`、`evaluation/`、`examples/`、`lockfiles/` | →`packages/backend/pacthold/decision-tooling/` 同名子目录（离线验收与评估工具随包维护） |
| `ordessa-decision` 发行包 + pyproject | →删；pydantic-graph==2.54.0 并入 pacthold 主依赖，typesafe-sdk==0.7.2 作为 pacthold `jev` extra |
| 命名空间 `ordessa_decision` | →`pacthold.decision`，同步全部 src/tests/tooling import；无外部 Python 消费者（已核实） |
| 默认导入隔离 | pacthold `__init__`/public 不 import decision；守卫断言 `import pacthold` 与 agents 路径不加载 pydantic_graph/typesafe_sdk/pacthold.decision |
| `integrations/ordessa/facade.py`（读适配） | 仍只读；随 agents 目录重组切新 import，不新增权威/执行器/apply |
| specs/031 冻结证据、032 evidence | 历史，不改写；当前文档以新路径为准 |

## 1. plugins/agent/backend（ordessa-agent 0.1.0，无 entry-point）

| 旧 | 职责 | 处置 | 消费者 |
| --- | --- | --- | --- |
| `plugin.py` AgentDomainPlugin（14 个 `agent.*` wire 方法，PLUGIN_ID `ordessa.agent`） | Agent 域 wire 面 | →删；产品改绑 `pacthold.agents` 公开 wire（`agent_core_wire` 同源） | products/server composition.py、apps/server tests |
| `owners.py` ConfigOwner/SubmissionOwner | 配置修改/提交 owner（重复 pacthold.agents.management 账本） | →删（重复权威） | — |
| `owners.py` SessionOwner/RunOwner/InteractionOwner + AgentOwnerRegistry | 证据投影（冻结 wire_value、来源 provenance） | →迁 `pacthold/agents/evidence.py` | products/server wire |
| `config_repository.py`（私有 SQLite：agent_config/draft_targets/observed_records） | draft 目标引导 + 配置存储 | draft 目标规则 →迁 `agents/configuration/`；存储改走共享 DomainStorePort | products/server |
| `config_observation.py` | 配置快照订阅（cursor/gap/release） | →迁 `agents/configuration/observation.py` | products/server wire |
| `capture.py` CaptureTransaction | 提交捕获（GuaranteeLevel 深冻结） | →迁 `agents/submissions/` | products/server |
| `submission_journal.py`（MAC 指纹、mapped/possibly-submitted/completed） | 可靠提交日志 | →迁 `agents/submissions/journal.py` | products/server、controlled_native_fixture |
| `submission_service.py` | 提交协调（submit/query/capture_conditions） | →迁 `agents/submissions/service.py`（NativeSubmitPort 保持注入端口） | products/server |
| `contributions.py`（agent.configuration-intent/-observation 契约声明） | 贡献声明 | →删；契约声明并入核心贡献集 | products/server |
| `plugins/agent/contracts`（@ordessa/agent-contracts，~4k 行 TS） | 前端旧链契约词汇 | →评估：被 connections/sessions/chat/model-provider-chat 消费；本轮迁不动则保留包但标注退役候选（见 §7 决议） | 前端 4 插件 |
| `plugins/agent/sessions`、`connections`（前端插件） | 会话/连接视图 | 非本轮退役目标；保留（target-structure agent-ui 允许消费者插件） | desktop |
| pyproject `ordessa-agent==0.1.0` | 依赖声明 | →删 | products/server pyproject、build-deb.mjs、closeout-controlled.py |

数据影响：`plugins/agent/config.sqlite`、`plugins/agent/submissions.sqlite` 为运行数据，不迁移不删除；新链经端口读旧数据的能力缺口显式登记。

## 2. plugins/profile（ordessa-profile 2.0.0a1，entry-point `profile`）

| 旧 | 职责 | 处置 |
| --- | --- | --- |
| `profiles.py` ProfileService（CRUD/revision/idempotency） | 重复 ProfileCatalog | →删；消费者切 `pacthold.agents.profiles`（缺失的 realm/facet 值/幂等账本规则迁入） |
| `core.py` ProfileCore 组合根 + HarnessCatalog | 私有组合根 | →删；组合经 `agents.public.agent_services` |
| `resolution.py` turn 有效配置解析 | 引用解析 | →迁 `agents/configuration/resolution.py` |
| `facets.py` FacetRegistry/FacetProviderV2 | 公共贡献契约 | →迁 `agents/facets.py`（契约）；model-provider/subagents/skills 具体贡献留各自插件 |
| `policy.py` per-realm 机制策略 | 策略 | →迁 `agents/configuration/policy.py` |
| `sessions.py` SessionService（overlay 状态机，HarnessConfigPort 确认） | 会话内配置选择 | →迁 `agents/sessions_overlay.py`（唯一权威随核心）；若与核心节点语义冲突则 →拒并登记缺口 |
| `application_journal.py` | 应用日志/回执（崩溃恢复） | →迁 `agents/configuration/journal.py` |
| `storage.py`+`repository.py`（私有 SQLite v1→v3） | Profile 存储 | →迁 `packages/backend/persistence-sqlite`（按现有持久化边界接线）；schema/数据标识不变 |
| `harness_port_adapter.py` | harness-api carrier → 配置端口适配 | →随 harness-api 归属调整（§3）；适配归品牌侧 |
| `contracts.py`（v2 契约 DTO） | 契约面 | →迁 `agents/configuration/contracts_profile.py`（并集后改名） |
| `migration.py`（旧 server_profiles 只读导入） | 旧数据导入 | →`scripts/migrations/`（离线，运行时不自动加载） |
| `ids.py`/`sensitive.py`/`errors.py` | profile id/sensitive 拒绝/错误码 | →迁核心对应模块（id/digest 语义并入 profiles） |
| `plugin.py` ProfilePlugin（entry-point）+ `server_plugin.py` ProfileServerPlugin | 注册与 wire 面 | →删；产品用核心公开绑定，不转发 |
| `api/`+`frontend/`+`integrations/chat`（前端三包） | Profile UI | frontend 编辑器 →迁 `plugins/profile-ui/`（target-structure）；chat picker 随迁；extension id 不变 |
| `plugins/skills` profile extra、`model-provider/profile-contribution`、`subagents/profile_facet` | facet 贡献者 | 切新 facets 契约 import |

数据影响：`profile-store.sqlite` schema v3 与 `profile_<32hex>` id 不变；persistence-sqlite 承接后由端口读。

## 3. plugins/harness（根 ordessa-harness 2.0.0a1 + api + records + 品牌包）

### 3.1 根包 src/ordessa_harness

| 旧 | 处置 |
| --- | --- |
| `contributions.py` HarnessContributionRegistry + RUNTIME/CONFIGURATION_POINT | →迁 `pacthold/agents/providers/`（或 `agents/contributions.py`）；产品绑定不变语义 |
| `generic/`（factory、ProfileStore/Selector/Manager、GenericExecutionProvider） | factory/build_registration →删（entrypoint 一并删）；ProfileStore/Manager 通用规则对照核心后 →迁或删 |
| `registry/`（loader/schema/definitions/validation/capability_claims + harnesses.toml + launch-descriptors.json） | 声明式注册：loader/schema 通用 →迁 `agents/providers/registry/`；品牌事实（harnesses.toml、launch-descriptors.json）→逐品牌拆入 `plugins/harness/<brand>/` |
| `adapters/`（HarnessAdapter 契约 + ADAPTERS map + GenericCliAdapter） | 契约 →迁 harness-transport（中性通道契约）；ADAPTERS map →删（品牌自注册） |
| `resources/`（resolve_executable/canonical_json） | →迁 harness-transport 或核心 util |
| `application/`（configuration_service/action_execution/native_evidence） | 通用准入/执行缝 →迁 `agents/configuration/`（service）与核心；journal 消费切核心 |
| `configuration/model/`（backend/bridge/catalog/plugin/live_service/restoration/common） | NativeModelServices/catalog →迁 `agents/configuration/`（品牌无关）；bridge 的品牌 Adapter 注册 →逐品牌入品牌包（经贡献点） |
| `materialization/`（intent_merge/private_generation） | 纯准入/合并规划 →迁 `agents/configuration/`（materialization 语义） |
| `importers/` | →迁 `agents/configuration/`（只读值对象） |
| `server_acp/`（registry/transport/access_entry/runs/history/instance_directory/executors/profile_owner/plugin） | 中立通道/instance directory/run 台账 →迁 `packages/backend/harness-transport/`；品牌动作执行（native_action_executor→codex、pi_action_executor→pi）→品牌包；AcpChannelServerPlugin →产品装配（products/server 或 server-plugin-api 接线），PLUGIN_ID 不变 |
| `codex/` `pi/` `claude/` `hermes/` `opencode/` `qwen/` `kilo/` `dsh/` `kimi/` `copilot/` `goose/` `gemini_cli/` `vibe/` `qoder/` | 逐品牌 →`plugins/harness/<brand>/`（codex/pi/claude-code 与既有独立包逐项合并，不得两套 provider）；轻品牌各自建独立最小包或显式不装配（保留 deploy 模板与 native_channel 知识） |
| `plugin.py`（历史 facade create_plugin=create_codex）| →删 |
| `native_materialization.py`（读 deploy/<family>/ 模板） | 拆品牌（各品牌包内物化模板读取） |
| `verifier_deployment.py` | →随品牌部署事实拆分 |
| entrypoints `harness-profile-store`/`opencode`/`hermes` | →删；opencode/hermes 由各自品牌包提供新 entry-point（同函数语义搬迁） |
| `runtime/*.mjs`（native-driver/access-entry/profile_extensions/subagent-bridge 等） | →`packages/backend/harness-transport/runtime/`（中立）+品牌专属随品牌；路径引用（setup.py/packaging/apps/server tests）同步 |
| `deploy/<family>/`、`harnesses/<family>/launch.mjs`、`packaging/<family>/` | 逐品牌拆入 `plugins/harness/<brand>/deploy|packaging/`；builders 共享工具留 harness-transport 或 tools |
| `third_party/harness_remote/` | 保留位置待品牌归属裁决（默认随 codex 或中立 tools，不新增聚合包） |
| `tests/`（根包测试） | 随模块迁移；过时装配测试改写或删除需在提交说明替代断言 |
| 根 `pyproject.toml`/`setup.py`/`MANIFEST.in`/`src/` | →删；plugins/harness 只留品牌目录 + 组 README |

### 3.2 api（ordessa-harness-api 1.0.0a1，158 消费文件）

| 旧 | 处置 |
| --- | --- |
| `contracts.py`/`schema.py`/`intents.py`/`application.py`/`errors.py`/`participant.py`/`command_discovery.py`/`native_evidence.py` | 中立接入契约 →迁 Pacthold 公共入口（`pacthold/agents/contracts_harness.py` 或 `pacthold/harness_contracts.py`；发行包 `pacthold` 直接提供） |
| `model_compilation.py`（RequestParams retry 形状来自 deploy/pi/settings.json） | Pi 原生形状 →`plugins/harness/pi/`（`ordessa_harness_pi.model_compilation`）；中性 TargetHandle/AdapterContext 对照核心 |
| 包壳 `ordessa_harness_api` 发行名/包名 | →删；消费者 import 改 `pacthold.…` / `ordessa_harness_pi.…` |

### 3.3 records（ordessa-harness-records）

| 旧 | 处置 |
| --- | --- |
| `operation_journal.py`/`unit_records.py` | 通用节点/操作/配置记录 →核心端口 + persistence-sqlite；原生会话记录 →品牌。消费者：根包 application/*、live_service、native_action_executor、pi/configuration/service、agent-tools owner_ports |

### 3.4 独立品牌包（codex/pi/claude-code）

- 保持独立发行包；补 entry-point（或产品显式准入保持现状，二选一后删除另一路径的"自动发现"歧义——按 AU003 注释维持显式准入）。
- 合并旧根包 `src/ordessa_harness/{codex,pi,claude}` 中仍活跃的部分（app_server/interactive provider、remote、sessions、configuration/live runtime）入对应 `ordessa_harness_<brand>`；不保留两套 provider。
- `pi/configuration/service.py` 消费 records → 切核心端口。
- 品牌间禁止 import；Pi 不得经 Go 桥 import Codex（§3.5）。

### 3.5 Go ACP 桥（plugins/harness/adapters/acp-adapter）

| 旧 | 处置 |
| --- | --- |
| `internal/acp/server.go`（5729 行，import internal/codex） | 拆：events/thread/turn/native 配置映射 →codex 品牌包装；中性 ACP 流程经中立端口；Pi 消费中立端口 |
| 中性 codec/transport/JSONRPC/ACP DTO | →`packages/backend/harness-transport/adapters/acp-common/`（唯一公共 Go module） |
| `internal/codex`+schema/flags+`pkg/codexacp` | →`plugins/harness/codex/adapters/acp/` |
| `internal/pi`+gate extension+`pkg/piacp` | →`plugins/harness/pi/adapters/acp/` |
| `cmd/acp --adapter codex|pi` 超级入口 | →拆品牌命令；品牌 packaging 只构建自己入口 |
| `internal/bridge/session_state.go` | 原生 thread/turn 绑定 →品牌 session bookkeeping |
| `internal/config`、`internal/observability`、testdata、test/integration | 中性部分随 acp-common；品牌测试随品牌 |
| 构建 `packaging/acp-adapter/build-acp-adapter-round-h.sh` | 拆品牌构建清单；pin（Go 1.24.13）保留；不提交二进制 |
| 无法隔离的旧桥能力 | 显式不装配 + 退役旧运行入口（登记缺口） |

## 4. runtime-compat（pacthold-runtime-compat 0.1.0）

| 旧 | 处置 |
| --- | --- |
| `storage/database.py`（schema 校验 SQLite facade） | →迁 `packages/backend/persistence-sqlite`（公共持久化实现，不拥有领域权威） |
| `migrations/*.sql` + `legacy_migrations.py` | 旧领域 schema →仅显式离线转换：`scripts/migrations/`（产品 sealed_migrations 改为引用离线脚本产物或明示退役）；运行时启动不再自动注册 legacy migrations（apps/server bootstrap/runtime.py 切走） |
| `api.py`（PluginRegistration/ProviderHostControl/ProfileEnvelope/HarnessProfileManager） | 通用注册/宿主控制对照核心 extensions/agents；ProfileEnvelope →拒（只接受核心 Manifest/Ref） |
| `bootstrap.py`/`catalog.py` | 产品选择/贡献 kinds →products/server；通用目录机制对照核心 catalog |
| `capability/`（ids/errors/documents/match/requirements/selection/slots） | 通用规则 →核心（agents/providers 或 extensions）；品牌能力声明归品牌 |
| `credentials.py`（SecretMount 协议） | 非秘密引用契约 →`packages/backend/platform-services` |
| `resource_contracts/`（AgentBoxProfileV1/AgentSkillV1/CredentialV1/PromptFragmentV1/WorkspaceV1/harness_capabilities/home_projection/runtime_artifacts） | 对应资源公开 API：skill→skills 插件包、prompt→prompts、workspace→workspace、credential→platform-services、ProfileV1 →拒（核心 Manifest）；home_projection/runtime_artifacts 中性机制 →harness-transport 或核心；品牌原生投影归品牌 |
| `runtime_composition/`（assembler/coordinator/fake/protocol/sandbox_port） | 对照 core agents assembly 删重复执行路径；protocol/sandbox_port 中立环境端口 →`packages/backend/environment-api`；外部 Sandbox 能力归其插件；不保留第二 coordinator |
| `sandbox/`（已退役协议 shim） | →删 |
| `profile_envelope.py` | →拒 |
| 包壳发行名 | →删 |

## 5. server-compat（ordessa-server-compat 2.0.0a1，console script 1）

| 旧 | 处置 |
| --- | --- |
| `plugin.py`/`facade.py` 超级 owner（PLUGIN_ID ordessa.server-compat，59 wire 方法） | →删；各域经自己公开端口服务；不换名保留 façade |
| `composition.py`（两条 build_runtime_from_*） | 纯装配 →products/server；品牌工厂/路径归品牌；sidecar 组装链 →删 |
| `core_wire.py`/`wire_projection.py`/`wire_validators.py`/`http.py`/`error_families.py` | 通用协议归 apps/server（wire/transport 已有）；业务方法逐方法绑定领域公开入口（逐方法退役表见 evidence）；`wire_validators.assignments` 消费者 model-provider 切新入口 |
| `profiles/`（repository/service/clone/permissions/posture/memory/subagents） | 清单/版本/权限对照 core ProfileCatalog；posture 解释归品牌；memory/subagents 贡献归其插件；旧记录转换离线 |
| `sessions/`（service/queue/repository） | 通用输入/操作记录对照 core agents/operations；native 会话/历史归品牌；不整体搬 SessionService |
| `approvals/` | 治理记录对照核心审批；持久化接现有持久化边界 |
| `assets/`（catalog/records/plugins/skills/mcp/mcp_probe/rendering） | 按资源域归对应资源插件（skills/mcp/model-provider）；已应用 Agent 配置不留资源副本；真实 MCP probe 禁止 |
| `model_configs/` | Provider/Model 管理归 `plugins/assets/model-provider`（现有 server 包）；reasoning/native 映射归品牌 |
| `hooks/` | 各域钩子回对应插件；通用规则复用核心；不造超级 hooks 插件 |
| `accounts/` + `credential_cli.py` | SecretStore 接线归 platform-services；原生 login/账户解释归品牌；CLI 仅命令客户端 |
| `execution/`（sidecar/sidecar_backend/local_channel/control_plane_sync/delegation/placement/inventory/state_capture/session_store_guard/first_run_lock/protocols/execution_contract） | first_run_lock 已转发核心→消费者直达；中性契约对照 core execution/agents；sidecar 中性通道→harness-transport；授权/运行/目录接缝对照核心既有保证；旧 store/第二调度器退役 |
| `artifact_store.py`/`change_set.py`/`usage.py`/`usage_aggregate.py` | 对照 Workspace/资源/core operation evidence；存储接领域端口；不重建 execution 状态总库 |
| `persistence.py` ProductRepositoryView | 产品域视图拼装留产品；通用 SQLite 机制归 persistence-sqlite |
| 包壳发行名 + console script | →删 |

## 6. 前端

| 旧 | 处置 |
| --- | --- |
| `extension-runtime/loader/{src,plugin.manifest.json,package.json}` | →搬 `extension-loader/`（替换转发壳；合并清单，包名/extension id 不变） |
| `extension-runtime/host/{src,tests,vitest.config.ts,tsconfig.json,plugin.manifest.json,package.json}` | →搬 `extension-host/`（替换四个转发出口；顶层 surface-input-ticket 测试合并保留；新增 `services/command-registry`、`services/surface` 公开导出） |
| `extension-runtime/src/state` | 原位保留（runtime 真实 stateStore/tasks/uiStorage） |
| `extension-runtime/package.json` exports | 删 `./loader*`、`./host*`，保留 `./state|./tasks|./ui-storage` |
| `tests/migration-identity.test.ts` | 重写为守卫：独立叶子、旧嵌套目录缺席、无 forwarding exports、公共导出完整且对象唯一 |
| 壳消费者（apps/desktop 7 文件、native-bridge、workbench 4 测试、host 内自引 extensions.ts） | specifier 不变（解析目标变真身）；host/package.json 显式声明依赖 `@ordessa/extension-loader` |
| `legacy-commands-adapter.ts` + 转发出口 | 命令消费者迁唯一 C07 owner 后删除；保留重入/生命周期失效/捕获围栏断言 |
| `plugins/harness/contracts`（@ordessa/harness-contracts） | 品牌契约 →归 harness 品牌组（消费者 desktop）；移至 `plugins/harness/` 下品牌组说明允许的位置或 `packages/frontend/contracts/` 命名空间（执行时按最小移动定） |
| Agent/Profile wire 类型 → `frontend/contracts` 领域命名空间 | agent-contracts/profile-api 契约迁 contracts 领域空间（能力缺口允许显式不可用） |
| sessions/connections 视图 → agent-ui；Profile 编辑/chat 选择器 → profile-ui | `plugins/agent/{sessions,connections}` →`plugins/agent-ui/`；`plugins/profile/frontend` →`plugins/profile-ui/`（extension id 不变） |

## 7. Assets 归位（路径移动，包名/extension id/存储标识不变）

`plugins/{skills,prompts,mcp,model-provider,sandbox}` → `plugins/assets/{同名}`；同步改动：root package.json workspaces 显式条目、package-lock、packaging/build-deb.mjs PRODUCT_PACKAGES、.github/workflows/ci.yml、scripts/verify-clean.sh、tooling TS 相对深度（build.mjs/vitest/tsconfig）、apps/desktop tsconfig exclude、harness 测试路径门表、products/desktop 测试路径、文档路径。`workspace/` 亦为资源域但退役表未列——保留原位（target-structure plugins/assets 未列 workspace；不为之扩大范围）。

## 8. 产品

| 旧 | 处置 |
| --- | --- |
| products/server pyproject：ordessa-server-compat/ordessa-harness/ordessa-profile/ordessa-agent/pacthold-runtime-compat 依赖 | →删；新依赖 = core + persistence-sqlite + harness-transport + 品牌包 + 资源插件 |
| `ordessa_server_product/composition.py` default_plugins/compatibility_plugins | 重写为核心公开绑定 + 明确品牌/资源插件选择；EXPECTED_PLUGIN_IDS 测试同步 |
| `native_configuration.py`/`turn_application.py`/`profile_preparation.py`/`profile_sessions.py`/`skills.py` | 切核心/品牌新入口 |
| apps/server `bootstrap/runtime.py` legacy migrations 注册 | →删（离线化） |
| agent-tools：`deployment/composition.py` provider_plugins 显式准入 | 保持（新链品牌包同函数）；test_distribution 边界保留 |
| products/desktop extensions.json | agent-ui/profile-ui id 同名替换路径；插件源目录改名 |

## 9. 测试与守卫

- 随职责迁移的测试：agent-core（pacthold tests）、brand（各品牌包）、wire（apps/server）。
- 过时装配测试改写为新语义或删除并登记替代断言（提交说明）。
- 新增守卫（plan §6 表 7 项）落 `tests/boundaries/`；反例必须失败。
- tests/boundaries/test_integrated_agent_capabilities.py 等既有守卫保持通过。

## 10. 冻结不改

- `specs/*/evidence/**`、`docs/implementation/agent-tools/evidence/**`（历史证据；若 pytest 发现路径覆盖需排除，登记）。
- `.decision-tmp/baseline/**` 基线快照。
- 运行数据目录与用户数据一律不动。
