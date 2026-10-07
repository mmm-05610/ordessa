# 032 阶段交付：映射、退役证据、实际目录、验证与缺口

状态：**本轮达到 STRUCTURE_CLEAN 的候选集之外仍持有未退役旧链**（runtime-compat、server-compat、Go ACP 桥、legacy 命令适配器、遗留品牌运行时）。**不得报告 STRUCTURE_CLEAN / PRODUCT_READY**；以下为已完成的迁移与可复现证据。

起始 HEAD：`97b8ed5a4d2e8f38da545a2043b92409fc7a46f8`（工作树干净）。所有提交在 `codex/architecture-cleanup`，未 push、未合回 main。

## 阶段提交

| 提交 | 内容 |
| --- | --- |
| `3a68bbe` | 迁移映射（plan §1 清单）：`specs/032-architecture-cleanup/migration-map.md` |
| `1682d9ec` | Decision 整包迁入 `pacthold.decision`（用户 2026-10-07 修订） |
| `ee676c29` | agents 平铺 → 目标子目录（profiles/nodes/configuration/assembly/access/lifecycle） |
| `8c7b55a9` | agent 后端通用链（submissions/owners/observation）迁核心；`ordessa-agent` 退役 |
| `4399acb9` | profile Python 权威迁核心与 persistence-sqlite；`ordessa-profile` 退役；profile 前端三包留待归位 |
| `e3e85884` | 产品改绑核心（AgentDomainWirePlugin/ProfileWirePlugin，id 不变）；agent-ui/profile-ui 归位 |
| `1773423c` | harness API → `pacthold.harness_contracts`（184 消费者切换） |
| `a480e5f9` | 根 `ordessa_harness` 超级包退役（kit/product/brand 三分） |
| `a6c511ce` | 资源插件归位 `plugins/assets/` |
| `c32297ad` | extension-loader/extension-host 恢复独立叶子 |

## 旧 → 新映射（摘要；全量见 migration-map.md）

- `ordessa_decision` → `pacthold.decision`；`ordessa-harness-api` → `pacthold.harness_contracts`。
- `ordessa_agent`（owner/提交/观察）→ `pacthold.agents.submissions.*`、`agents/configuration/observation.py`、`persistence-sqlite.agent_config_repository`；wire 面 → 产品 `agent_wire_plugin.py`（`ordessa.agent` id 不变）。
- `ordessa_profile` → `pacthold.agents.{facets,profile_services,sessions_overlay,configuration/*}` + `persistence-sqlite.profile_{store,repository}`；旧数据导入 → `scripts/migrations/import_legacy_server_profiles.py` 离线脚本；wire 面 → 产品 `profile_wire_plugin.py`。
- 根 `ordessa_harness`：通用 → `pacthold.harness_kit`；品牌/宿主持有 → 产品 `harness_adapters`/`acp_channel`；品牌知识 → `plugins/harness/{codex,pi,claude-code,hermes,opencode,qwen,kilo,dsh,kimi,copilot,goose,gemini_cli,vibe,qoder}` 独立包。
- `plugins/agent/{contracts,sessions,connections}` → `plugins/agent-ui/`；`plugins/profile/{api,frontend,integrations}` → `plugins/profile-ui/`（包名/extension id/数据标识不变）。
- `plugins/{skills,prompts,mcp,model-provider,sandbox}` → `plugins/assets/同名`。
- `extension-runtime/loader|host` → `extension-loader`/`extension-host` 真身；runtime 仅保留 state/tasks/ui-storage。

## 实际目录（关键项，均存在于当前 HEAD）

`packages/backend/pacthold/src/pacthold/{decision,harness_contracts,harness_kit,agents/{profiles,nodes,configuration,assembly,access,lifecycle,submissions}}`；`packages/backend/persistence-sqlite/src/ordessa_persistence_sqlite/{profile_store,profile_repository,agent_config_repository}.py`；`products/server/src/ordessa_server_product/{harness_adapters/{registry,configuration/model,application,generic,adapters},acp_channel,agent_wire_plugin,profile_wire_plugin,native_materialization}.py`；`plugins/harness/*` 品牌包（14 个，无根包）；`plugins/assets/*`；`plugins/agent-ui/*`、`plugins/profile-ui/*`；`packages/frontend/{extension-loader,extension-host}` 独立叶子。

## 退役证据（已删除/不可达）

`plugins/harness/{pyproject.toml,setup.py,MANIFEST.in,src/,api/}`；根 entry points（harness-profile-store/opencode/hermes）；`plugins/agent/backend/`（plugin/owners/repository）；`plugins/profile/src/` 与 pyproject；`ordessa-decision` 发行、`packages/backend/decision/`；`plugins/profile` 与 `plugins/agent` 目录；前端四个转发壳文件与嵌套 loader/host 目录；`extension-runtime` 的 loader/host 导出。守卫固化：`test_core_identity`（kit 唯一源码 + retired 树缺席）、`test_core_boundaries`（根超级包退役、品牌独立发行、无自动注册）、`test_single_distribution`、`test_family_dialect_tables`（品牌包存在与单一实现）、`migration-identity.test.ts`（嵌套目录缺席、无转发导出）、N4-R1/T009 内核方向守卫（具名例外已登记）。

## 验证（2026-10-07，.venv-cleanup；串行；tmpfs 清理后）

| 套件 | 结果 |
| --- | --- |
| `pytest packages/backend/pacthold/tests` | 2093 passed, 6 failed, 27 errors, 3 skipped（失败/错误全部 ⊆ 基线集合） |
| codex / pi / claude-code 品牌套件 | 278 / 318 / 255 passed（各自 wheel 闭包含离线内核链） |
| `plugins/harness/records` | 1 passed |
| `plugins/assets/{skills,mcp,sandbox,model-provider,prompts}` | 437+1f / 526 / 299 / 270+36f / 191+1f（失败与基线一致） |
| `plugins/{permissions,lsp,extensions,memory,subagents,runtime-preferences}` | 628+14f+21e / 42 / 101 / 129 / 889+1f / 151（失败与基线一致） |
| `packages/backend/harness-transport/tests`、`tests/boundaries`、`persistence-sqlite` | 103 / 9 / 43 passed |
| `products/server/tests` | 223 passed, 84 failed（与基线逐位一致） |
| `apps/server/tests` | 1307 collected，1202 passed / 98 failed / 2 errors（基线为 13 收集错误不可运行） |
| npm workspaces（extension-runtime/host/loader、workbench、native-bridge、connections、ui-components、agent-sessions/connections、profile-api/frontend/chat、chat、model-provider-chat、skills、asset-mcp、sandbox-settings） | 全绿（5/127+12f→127、86、16、29、114、47、13、10、17、94、95、18、104、27、11） |
| desktop `foundation.test.tsx` 1 项 | 基线红（stash 对比确认） |

## 功能缺口（明确不可用/未完成，已登记 docs/known-issues.md §Spec 032）

1. runtime-compat、server-compat 未退役（plan §5 未执行）；Go ACP 桥未拆品牌；server_acp 中性抽取未做。
2. 核心 agent 配置模块直接 import `ordessa_persistence_sqlite`（端口注入待做；N4-R1 具名例外）。
3. 品牌包内遗留 legacy 运行时模块无消费者（AU003 拒绝），逐项删除与替代测试说明待做；根 deploy/harnesses/packaging/runtime 资产未逐品牌拆。
4. `legacy-commands-adapter` 未删；消费者待迁 C07（plugins/commands、connectors/acp、agent-ui/sessions）。
5. 继承红：harness_kit 6、pi_live_runtime 27 errors、products/server 84、apps/server 98、model-provider 36、skills/subagents 各 1、permissions backend 14+21、prompts citation 1、apps/server 沙箱 provider 类。
6. 未调用真实模型、未安装品牌二进制、未迁移真实数据、未重启用户服务、未 push。

## Phase 5a 进展（2026-10-07 续，runtime-compat 拆解第一步）

`pacthold_runtime_compat` 由 7.5k 行缩至 3.3k 行（提交 `2e434f79`、`dfab0c8c`）：

- `storage.Database`（产品 schema v21 facade）→ `ordessa_persistence_sqlite.product_database`，75 个消费文件切换；混同内核原语的导入拆为两条诚实导入。
- `resource_contracts` 整包拆解：`AgentSkillV1` → skills 插件；`PromptFragmentV1`/`WorkspaceV1`/`CredentialRefV1`/`AgentBoxProfileV1`（保留但新链拒绝）→ 内核公开契约边 `pacthold.harness_contracts.*`；`harness_capabilities`、`runtime_artifacts` → 同一契约边（`RuntimeArtifactRejected` 去掉 compat 基类，消费方本就直接捕获具体类）；`home_projection` → 其唯一消费者 server-compat；旧聚合包（`CONTRACT_TYPES`/`contract_type`，无活消费者）删除；契约身份测试随主体迁移（内核 + skills 套件）。
- `credentials.py` 改读内核契约；`sandbox/` 兼容 shim（0 消费者）删除。

全仓验证：pacthold 2093 过（6 失败 ⊆ 基线）、品牌 278/318/255、products/server 85（与基线集合逐位一致）、apps/server 1202 过/98 失败（同基线）、skills/mcp/permissions/subagents/records/runtime-compat 均与基线一致。

Phase 5c（提交续）：`capability/` → server-compat（其唯一活消费者）；`api.py`/`profile_envelope.py` → 产品 `harness_adapters/generic/`（legacy 插件 SDK 面，随 legacy 清理）；`catalog.py`/`bootstrap.py`/`cli/` → server-compat（同向依赖：产品→server-compat 保留）；runtime-compat 现为 2.1k 行（`credentials`、`legacy_migrations`+SQL、`runtime_composition`）。

**Phase 5b 依赖说明（精确阻塞）**：`legacy_migrations` 离线化不能独立于 5d 完成——`LegacyCoreBinding` 是当前产品数据库文件的初始化/链应用路径，`sealed_migrations` 与 apps/server 拓扑测试（S1c/T015/T023、stage_a_server）共同编码了"运行时可连历史库"这一现状；只有与 server-compat/新 DB 归属一起切换为"仅离线转换 + 历史根显式拒绝"才不破坏产品。已登记，不恢复旧链绕行。

Phase 5c（续）：`runtime_composition/protocol.py`（605 行中立运行时组合契约：RuntimeHostV1/SandboxV1/TerminalSessionV1、组合错误族、摘要工具）→ environment-api（stdlib-only，冻结契约包守卫通过；`PreparedSecretMount` 降为 TYPE_CHECKING 注解，具体值仍随 compat credentials）；compat 组合包从新家再导出同对象；capability 测试随主体迁入 server-compat，协议测试迁入 environment-api。runtime-compat 现为 520 行（`credentials`、`legacy_migrations`+SQL、`runtime_composition/{assembler,coordinator,fake}`）。

Phase 5c（续二）：`credentials.py`（SecretMount/PreparedSecretMount/ResolvedCredential 中立契约）→ 内核契约边 `pacthold.harness_contracts.secret_mounts`（品牌唯一可导入的边；env-api 仅 TYPE_CHECKING 类型引用，运行时不加载）。runtime-compat 现为 471 行（`legacy_migrations`+SQL、`runtime_composition/{assembler,coordinator,fake}`）。

**仍待完成（Phase 5 剩余）**：`legacy_migrations`+SQL 离线化（消费：apps/server bootstrap 预检与装配、products/server sealed_migrations、3 个 apps 测试、docs/migration 说明）；`capability/`（消费：server-compat、apps 测试）；`api.py`/`profile_envelope.py`/`catalog.py`/`cli/`/`bootstrap.py`（消费：产品 legacy `harness_adapters/generic`、server-compat）；`runtime_composition`（protocol/sandbox_port → environment-api；assembler/coordinator/fake 删除）；server-compat 18.5k 行的逐域再归属与删除。

## 结论

旧链退役为**部分完成**：Decision、agent、profile、harness API、harness 根包、前端转发壳已完成退役并有守卫与实测；runtime-compat/server-compat/Go 桥/命令适配器/遗留品牌运行时仍未退役。因此只可声明 **PHASE2–4 CLEAN**，不得声明 `STRUCTURE_CLEAN` 或 `PRODUCT_READY`。
