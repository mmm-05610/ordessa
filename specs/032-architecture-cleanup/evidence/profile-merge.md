# Profile Python 权威迁入核心 — 验证证据

日期：2026-10-07。对应 plan.md §2 与 migration-map §2；`ordessa_profile` Python 侧整体退役，前端 TS 三包（api/frontend/integrations，extension id 不变）暂留原位待 2c 归位 profile-ui。

## 迁移映射（git mv）

| 旧（ordessa_profile） | 新 |
| --- | --- |
| `facets.py` | `pacthold/agents/facets.py` |
| `policy.py` | `pacthold/agents/configuration/policy.py` |
| `resolution.py` | `pacthold/agents/configuration/resolution.py` |
| `application_journal.py` | `pacthold/agents/configuration/journal.py` |
| `contracts.py` | `pacthold/agents/configuration/profile_contracts.py` |
| `ids.py` / `sensitive.py` / `errors.py` | `pacthold/agents/configuration/profile_ids.py` / `profile_sensitive.py` / `profile_errors.py` |
| `sessions.py` | `pacthold/agents/sessions_overlay.py` |
| `core.py` | `pacthold/agents/profile_services.py`（组合根归核；新增 kernel 版 `ProfilePluginServices` facade，原 plugin.py 内实现迁入） |
| `profiles.py`（ProfileService） | `pacthold/agents/configuration/profile_service.py`（与 `ProfileCatalog` 分属节点目录与配置服务两域；写入口各一，均归核） |
| `harness_port_adapter.py` | `pacthold/agents/configuration/harness_port_adapter.py`（ordessa_harness_api import 保持，Phase 3 切） |
| `storage.py` / `repository.py` | `persistence-sqlite/ordessa_persistence_sqlite/profile_store.py` / `profile_repository.py`（schema v3、`profile_<32hex>` id、profile-store.sqlite 标识不变） |
| `migration.py` | `scripts/migrations/import_legacy_server_profiles.py`（离线显式运行，运行时不加载） |
| `plugin.py` / `server_plugin.py` / `__init__.py` / pyproject | 删除（wire 面由产品绑定核心服务替代，2c） |

## 消费者切换

- `plugins/skills`（profile_contribution/{provider,port,__init__}、plugin.py）：imports → `pacthold.agents.configuration.profile_contracts` / `profile_services`；pyproject `profile` extra 删除。
- `plugins/model-provider/profile-contribution`（profile_glue.py）：contracts/errors/FacetRegistry → 新路径。
- `plugins/subagents`（profile_facet.py 惰性 import）：→ 新路径；`tests/test_boundaries_t03b.py` 的 T10 许可改为点级路径（`pacthold.agents.profile_services`/`pacthold.agents.configuration`），`pacthold` 顶层仍禁（src 不变），`import ordessa_profile` 保持必败断言。
- 边界/依赖方向测试同步：prompts/extensions/harness/skills 的退役名断言保留（负向），活导入全部切换。

## 测试迁移

- 25 个测试文件 + goldens/brand_matrix + boundary_check.sh/run_counterexamples.sh → `pacthold/tests/agents/profile/`；import 重写；`test_c20_extension_boundary` 按新布局改写（替代断言：retired 树必须缺席；publication surface = profile_contracts.py + facets.py；plugin.py 无替代面）。
- 4 个纯 wire 测试不迁移（替代断言：products/server wire 绑定测试覆盖同面，2c 验证）：test_plugin_entry、test_plugin_registration_v2、test_server_plugin、test_native_session_wire。

## 实测（.venv-cleanup，串行）

| 套件 | 结果 |
| --- | --- |
| `pytest packages/backend/pacthold/tests/agents/profile -q` | 223 passed, 6 failed — 6 项全部 `test_harness_real_service`，经产品 `default_plugins()` 组合（仍引用 ordessa_profile.server_plugin，2c 处理）；C20 等结构测试全绿 |
| `pytest plugins/skills/tests plugins/subagents/tests -q` | 1327 passed, 1 failed — `test_confirmed_overlay_cleanup…` 基线即失败（stash 对比），非本次回归 |
| `pytest plugins/model-provider -q` | 270 passed, 36 failed — 与基线逐位一致（stash 对比），均为依赖产品组合的 server 套件（2c 范围） |
| `import ordessa_profile` | ModuleNotFoundError（退役生效） |
| `plugins/profile/` 残留 | 仅 api/frontend/integrations（TS）与 README；src/tests/pyproject 全部消失 |
