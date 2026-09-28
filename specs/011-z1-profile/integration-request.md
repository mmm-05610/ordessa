# Z1 integration-request（交 C0 集成的清单）

按 011-plugin-rollout/plan.md：本线列待删旧文件、旧 writer/路由、调用方、
迁移与目标；公共旧 writer 退出后产品才算整体完成。

## 1. Wire / composition（C0 所有）

| 项 | 说明 |
| --- | --- |
| Profile wire registry 注册 | `ordessa_profile.plugin.ProfilePlugin.build` 返回 `contracts=(agent-box.profile@1,)+resource provider`；services 门面 `ProfilePluginServices`（register_v2_facet/describe_facets/resolve_preview/get·update_mechanism_policy）需宿主装配进 wire（contracts.md §3 的 17 个操作）。**不改 wire/handlers 本体**，按 server-plugin-api 贡献点接入。 |
| 契约声明仲裁 | loader 从 `registration.contracts` 推导 known contracts。若 harness 侧 `harness-profile-store` entrypoint 也声明 `agent-box.profile@1`，先加载者赢、后者 FAIL——需 C0 裁决唯一声明者。 |
| Profile 前端产品装配 | `@ordessa/plugin-profile-frontend` 的 settings/management 视图 + `@ordessa/plugin-profile-chat` 的 composer.toolbar 贡献需要 products/desktop（或 server 产品）装配入口；tooling/vitest-extensions.mjs 的 CONTRACT_SOURCES 需补 `ordessa.chat-api` 与 `ordessa.profile-api` 两行（本线 vitest 用本地 alias，不越权改共享 tooling）。 |
| 根锁 | 本线 workspace 包（plugins/profile/api、integrations/chat、frontend）的 lock 增量保持未提交；最终根锁请 C0 `npm install` 后生成提交。 |

## 2. 待删旧 writer（唯一 owner 替换）

| 旧文件/入口 | 所属 | 目标 |
| --- | --- | --- |
| `plugins/harness/src/ordessa_harness/generic/profile_store.py`（文件式 ProfileStore） | harness（C0） | 由 `plugins/profile`（本线）唯一拥有 Profile 持久化 |
| `plugins/harness/src/ordessa_harness/generic/profile_manager.py` / `profile_selector.py` / `profile_provider.py` | harness（C0） | 同上；原生会话配置的应用归 harness-api 的 HarnessConfigPort 实现 |
| `agent_box.plugins` 组的 `harness-profile-store` entrypoint | harness（C0） | 退出或改指向新所有者 |
| `plugins/harness/src/ordessa_harness/{claude,hermes,opencode}/profile*.py` | harness（C0） | 逐品牌裁决：能以 facet provider 表达的迁 `integrations/profile` 形态（归 Z3/各域 + 本线契约） |

## 3. 待 C0 的接缝（阻塞本线的真实全链项）

1. **harness-api 检查点**：`HarnessConfigPort`（inspect/plan/apply/reconcile，
   语义 = docs/design/profile-v2/application.md §2）真实实现。本线已冻结消费
   协议类型（ordessa_profile/contracts.py），端口缺席行为 typed blocked
   （APPLICATION_PORT_ABSENT，有反例）；真实全链 G09–G12 的端口半边待此发布。
2. **canonical SessionRef 服务端映射**：Server/连接归属 → realm + native key
   的稳定映射证据（data-model.md §1）。当前迁移用 legacy 映射（realm='local'，
   uid='legacy:<id>'），不冒充跨服务身份。
3. **下一轮提交准入门**：配置应用与消息发送的同一互斥点（G09 服务端半边），
   由会话所有者/C0 提供；本线 `begin_turn` 已按"应用成功才放行"实现 Profile 侧。

## 4. 本线不自改、请 C0 集成时处理的公共项

- `tooling/vitest-extensions.mjs` CONTRACT_SOURCES 增补（见上）。
- `products/desktop` manifest 增加本线三包（前端 settings/management/chat-glue）。
- server-compat 旧 `server_profiles` writer 若仍存活，指向 `ordessa_profile.migration.import_legacy`（保真导入已实现并有测试）。
