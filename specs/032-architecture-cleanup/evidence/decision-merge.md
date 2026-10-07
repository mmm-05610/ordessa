# Decision 整包迁入 Pacthold — 验证证据

日期：2026-10-07。依据：用户 2026-10-07 修订（替代此前"Jev 移插件、业务流程移产品"）。

## 变更

- `packages/backend/decision/src/ordessa_decision/` → `packages/backend/pacthold/src/pacthold/decision/`（contracts/runtime/providers/jev/flows/integrations/evidence/offline/public 内部组织不变）。
- `packages/backend/decision/tests/` → `packages/backend/pacthold/tests/decision/`（Pacthold 发行内 Decision 模块隔离测试）。
- `checks/`、`evaluation/`、`examples/`、`lockfiles/` → `packages/backend/pacthold/decision-tooling/` 同名子目录。
- 命名空间 `ordessa_decision` → `pacthold.decision`（src/tests/tooling 全部 import 已切换；无外部 Python 消费者，git grep 复核）。
- `ordessa-decision` 发行包及 pyproject 删除；`pacthold` pyproject 增加 `pydantic-graph==2.54.0` 主依赖与 `jev = ["typesafe-sdk==0.7.2"]` extra；package-data 增加 decision 的 JSON 载体；pytest 增加 `asyncio_mode = "auto"`（decision 异步测试所需）。
- 隔离守卫新增 `packages/backend/pacthold/tests/decision/test_module_isolation.py`（4 项）：默认导入与 agents 路径不加载 decision/pydantic_graph/typesafe_sdk；decision public 导入不拉 Jev SDK；Jev provider 仅随可选依赖加载；模块 `__file__` 落在本树。
- N4-R1 内核方向守卫：扫描显式豁免 `tests/decision/`（迁入的 Decision 集成测试合法消费 codex 纯读扩展与 persistence-sqlite，属消费者方向），`src/`（含 `src/pacthold/decision/`）仍全量扫描；文档化于 `test_n4r1_kernel_direction.py`。
- 品牌自产 wheel 闭包测试（codex/pi/claude-code 各自 `test_acp_model_distribution.py`、claude-code `test_acp_attachments_distribution.py`）：pacthold 主依赖新增 pydantic-graph 后，闭包补齐固定内核链（由运行环境重打包 9 个固定版本 wheel，无网络）；own-wheel 计数断言保留并更新。
- `decision-tooling/checks/offline_acceptance.py`：ROOT 深度修正（目录加深两级）；prepare 增建 `ordessa_environment_api` wheel 并入 find-links（pacthold 主依赖闭包）；wheel 名改 `pacthold-2.0.0a1`。
- T63 断言按新现实改写（替代断言）：wheel 成员校验改 `pacthold/decision/` 前缀；METADATA 断言 pydantic-graph 主依赖 + jev extra + `ordessa-environment-api` 主依赖（替代旧 `extra == "ordessa"`）；base wheel 脚本改为"默认导入不加载 decision、SDK 缺席、decision opt-in"；核心方向源码扫描排除 `pacthold/decision/` 自身。

## 实测（.venv-cleanup，CPython 3.12.14，串行）

| 命令 | 结果 |
| --- | --- |
| `pytest packages/backend/pacthold/tests/decision -q` | **363 passed**（原 359 + 新增 4 项隔离守卫），VERDICT=GREEN_NO_SKIPS |
| `checks/offline_acceptance.py --scenario T64` | T64 PASSED + baseline/current 各 57 passed；live Jev NOT_RUN（未授权，不改）；receipt `.decision-tmp/acceptance-run/receipt.json` |
| `pytest plugins/harness/pi/tests -q` | 318 passed |
| `pytest plugins/harness/claude-code/tests -q` | 255 passed |
| `pytest plugins/harness/codex/tests -q` | 278 passed |
| `pytest packages/backend/harness-transport/tests -q` | 107 passed |
| `pytest tests/boundaries -q` | 9 passed |
| `import pacthold` / `pacthold.agents.public` 后 `sys.modules` | 不含 `pacthold.decision`/`pydantic_graph`/`typesafe_sdk`（守卫固化） |

## 已知边界（如实登记）

- `products/agent-tools/tests/integration/test_directory_binding.py` 在 `.venv-cleanup` 收集即 `ModuleNotFoundError: ordessa_workspace`——该包本就未装入此 venv（基线验证边界外的既有缺口），非本次回归。
- 三个品牌套件不能合并为一次 pytest 调用（跨包同名测试文件无 `__init__`），与基线运行方式一致，分开执行均绿。
- `packages/backend/pacthold/build/` 为 wheel 构建产物目录（未跟踪），来源手工验证步骤。
