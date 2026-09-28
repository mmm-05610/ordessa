# Z1 platform bindings（实施树内证据）

树：`/home/maoqh/projects/ordessa/worktrees/011-z1-profile`
分支：`codex/011-z1-profile`；冻结起点 HEAD：`96fef2db47`（设计快照，父链含 main `cd7d31f3cf`）。
冻结时间：2026-09-28。环境：Python 3.12.14（本树 `.venv`，pacthold 2.0.0a1 editable 安装于本树）；
Node/npm 沿用根 lock（22.22.x），node_modules 本树独立。

## 只读输入冻结

| 输入 | SHA | 用途 |
| --- | --- | --- |
| 本树基线 | `96fef2db47` | 实施起点（干净） |
| 旧 Profile 实现 | `b77f9f23cb`（branch feature/plugin-profile-impl） | 只读择取移植 |
| 前端平台观察点 | `54c2ef4110` / `82b7ef1fc3` | 只读；以 foundation 检查点发布为准 |
| workbench 侧栏 | `2b22e1608f` | 只读 |
| Hermes | `8c9fe964` | 许可未核实：仅参考，禁止复制（reuse-map 裁决） |
| Roo | `b867ec91` | Apache-2.0 根 LICENSE 已核；仅校验思路参考 |
| 共同规格 | specs/011-plugin-rollout @ `96fef2db47` | 所有权/检查点协议 |

## 实际可导入平台事实（本树已验证）

- 插件 SDK：`pacthold.extensions`（`packages/pacthold/src/pacthold/extensions/api.py`）。
  `PluginDescriptor(id, display_name, version, config_namespace)`、`PluginContext(agent_box_version, agent_box_home, plugin_data_dir)`、
  `PluginRegistration(contracts, resource_providers, execution_providers, resource_selectors, host_controls, harness_managers, continuation_routes, credential_materializers, transport_operations, ...)`。
  入口组名保留 `agent_box.plugins`（兼容表面，plugins/harness/pyproject.toml 同款）。
- 注册表：`pacthold.work_core.registry.ExtensionRegistry / ResourceProvider / ExecutionProvider`。
- Profile 旧包依赖 `pacthold==2.0.0a1`，与本树 pacthold 版本一致，直接可装。
- TS 平台契约（本树已有，foundation 之前）：`@ordessa/extension-api`（Token/ResourceScope/IDisposable）、
  `packages/desktop-platform/contracts/workbench`（WorkbenchComposition.addModule/addSettingsSection、WorkbenchOverlay）。
  供 TS 轻量 API 与管理器入口绑定。
- Harness 公开配置端口（inspect/plan/apply/reconcile）：**本树不存在**，归 C0 harness-api 检查点 → api-requests.md 登记。
- Chat 贡献注册表（ChatContributions）：**本树不存在**，归 Z2 chat-api 检查点 → api-requests.md 登记。
- `@ordessa/ui`（Panel/Toolbar/Button/Input/Select/Checkbox/Field）、`@ordessa/ui-components/react`
  （ComponentOutlet/useUiBinding）：**本树不存在**，归 C0 foundation 检查点 → api-requests.md 登记。

## 检查点状态（2026-09-28 R0 时点）

`git for-each-ref` 无 `codex/011-foundation-ready` / `codex/011-harness-api-ready` / `codex/011-chat-api-ready`；
`specs/011-plugin-rollout/checkpoints/` 为空（本树与 C0 树同）。C0 树有未提交在制文件
（`plugins/harness/api/`、products lock 脏项），按协议不读、不消费、不接管。

## 最小编译/调用验证

- `python3.12 -m venv .venv && .venv/bin/pip install -e packages/pacthold` → `import pacthold` OK（本树）。
- 后续每项绑定以可运行测试/编译命令落证据，不接受“读过即绑定”。
