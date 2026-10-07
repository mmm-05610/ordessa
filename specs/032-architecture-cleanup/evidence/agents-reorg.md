# agents/ 平铺→目标子目录重组 — 验证证据

日期：2026-10-07。对应 plan.md §2「整理 agents 子目录，公共导出统一更新」；target-structure.md 的 agents/ 六子目录。

## 映射（git mv，无文件+包并存）

| 旧模块 | 新位置 |
| --- | --- |
| `agents/profiles.py` | `agents/profiles/catalog.py`（包 `profiles/`） |
| `agents/nodes.py` | `agents/nodes/publication.py` |
| `agents/directory.py` | `agents/nodes/directory.py` |
| `agents/configuration.py` | `agents/configuration/change.py` |
| `agents/management.py` | `agents/configuration/management.py` |
| `agents/read_configuration.py` | `agents/configuration/read.py` |
| `agents/configuration_references.py` | `agents/configuration/references.py` |
| `agents/assembly.py` | `agents/assembly/agent.py` |
| `agents/staged_assembly.py` | `agents/assembly/staged_assembly.py` |
| `agents/preparation_effects.py` | `agents/assembly/preparation_effects.py` |
| `agents/materials.py` | `agents/assembly/materials.py` |
| `agents/material_operations.py` | `agents/assembly/material_operations.py` |
| `agents/material_consumption.py` | `agents/assembly/material_consumption.py` |
| `agents/invocation.py` | `agents/access/invocation.py`（目标 access/：使用/管理入口公共契约） |
| `agents/lifecycle.py` | `agents/lifecycle/lifecycle.py` |

平铺保留（现有通用模块按职责）：`contracts.py`、`schema.py`、`runtime.py`、`providers.py`、`operations_read.py`、`inputs.py`、`public.py`、`__init__.py`。

## 导入切换

- 各新子包 `__init__` 以 star-import 重建公开面；全部消费方改为具体模块路径（53 个文件机械重写 + `tests/boundaries` 别名修正）。
- agents 树内相对 import 全部规范为绝对（`pacthold.agents.*` / `pacthold.core.*`）。
- **字符串标识符不随代码搬迁**：策略 admit 键与指纹键（如 `pacthold.agents.configuration.apply`、`pacthold.agents.nodes.prepare`、`pacthold.agents.profiles.{kind}`）及 wire 契约 id（`pacthold.agents.profiles@1`）保持原值（数据兼容规则 5）；首轮脚本误改后已全量还原并复查 diff（仅 import 行变化）。
- `docs/implementation/agent-tools/evidence/agent-unit-model/*.py`（20 个）裁决：它们被现行 agent-tools 套件经 `sys.path.insert` 实时导入提供 fixtures，属"活的代码"而非只读历史收据；其 `pacthold.agents.*` import 随迁移更新，断言未动。只读收据（specs/**、.decision-tmp、其余 docs 证据）未触碰。

## 实测（.venv-cleanup，串行）

| 套件 | 结果 |
| --- | --- |
| `pytest packages/backend/pacthold/tests`（不含 decision） | 261 passed |
| `pytest packages/backend/pacthold/tests/decision -q` | 363 passed |
| `pytest tests/boundaries -q` | 9 passed |
| `pytest plugins/harness/codex/tests -q` | 278 passed |
| `pytest plugins/harness/pi/tests -q` | 318 passed |
| `pytest plugins/harness/claude-code/tests -q` | 255 passed |
| `pytest packages/backend/harness-transport/tests -q` | 103 passed |
| `pytest products/agent-tools/tests`（除 test_directory_binding 收集缺口） | 1101 passed, 1 failed |
| `pytest products/server/tests -q` | 223 passed, 84 failed — 与重组前基线逐位一致（stash 对比验证，继承红） |

## 已知边界

- `test_installed_provider_service.py::test_installed_cli_observes_three_independent_server_providers` 的失败在重组前基线同样出现（stash 对比），非本次回归；登记于 known-issues 候选。
- `test_directory_binding.py` 收集缺 `ordessa_workspace`（venv 装齐后已解）；products/server 的 84 失败为基线继承红（"Migrated Harness runtime requires explicit independent provider admission" 等），属 Phase 2c/5 处理对象。
