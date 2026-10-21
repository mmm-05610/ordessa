# W8 进度：发行收敛（第一批，2026-10-21）

本轮完成"一个域一个发行"的前两步与安装器缺陷修复；改名的部分（agents/cli/plugin-api/元包/operation id）尚未做，如实列在 §4。

## 1. `ordessa_interfaces` 命名空间分裂（修复）

问题：`ordessa-interfaces` 与 `ordessa-interfaces-contracts` 两个发行共同提供 `ordessa_interfaces.*`，
editable 安装下只有一份片段可见 → `system_access` 解析到错误路径 → `ImportError ... (unknown location)`。

修复分两层：

1. **归属**：`ordessa_interfaces.system_access.contracts` 子包从 contracts 发行移入 interfaces 发行
   （源码仍在 `packages/interfaces/system-access/src/...`），contracts 发行只剩 `ordessa_interfaces_contracts`。
   根因规则：一个发行**可以**给自己的包加子包，但不能复制别的发行的父包。
2. **安装器**：`tooling/workspace/python_workspace.py --install` 对"包根跨多个源码树"的发行改用
   **wheel（非 editable）**安装（editable finder 只能让一个根回答父包，兄弟根在导入时不可见）；
   单根发行仍 editable。文件内注释写明原因。

验证：`python_workspace.py --install` 退出 0；`from ordessa_interfaces.system_access import RequestContext, CapabilityHost`、
`...contracts.refs`、`ordessa_interfaces_contracts` 全部可导入；`apps/cli/tests` 从 91+1 失败变为 **92 passed**。

## 2. environments：一个发行、三个包

- `ordessa-environments` 现在同时打包 `ordessa_environments`（owner）与
  `ordessa_environments_local` / `ordessa_environments_openshell`（provider，源码仍在 `plugins/environments/*`）。
- `openshell`/`grpcio`/`protobuf` 改为 `ordessa-environments[openshell]` extra。
- 删除 `plugins/environments/{local,openshell}/pyproject.toml`；workspace 项目数 52 → 50 →（含 decision）48。
- 验证：`packages/execution/environments/tests` + `plugins/environments/local/tests` → **181 passed / 1 skipped**；
  openshell 测试仍因缺失外部 `openshell` SDK 无法收集（环境依赖，非本轮回归）。

## 3. decision：一个发行、三个包

- `decision-runtime` → **`ordessa-decision` 0.3.0**，同时打包 `decision_runtime`（import 名本批保持不变）、
  `ordessa_decision_rules_cel`、`ordessa_decision_jev`（源码仍在 `plugins/decision/*`）。
- `cel-python` 升为核心依赖；`typesafe-sdk`/`httpx2`/`pydantic` 收进 `[jev]` extra。
- 四份 pin 更新：`apps/cli`、`apps/server`、`packages/engineering`、`system-access/bindings`；
  删除对已退役 provider 发行的 pin。
- 验证：`plugins/decision/rules-cel/tests` **2 passed**；`import ordessa_decision_jev` 成功；
  `packages/execution/decision/tests` 仍有 **7 个收集错误，但在 pristine HEAD 快照复现同样 7 个** → 既有问题，非本轮引入。

## 4. 本轮未做（W8 剩余）

- `ordessa_execution_agents` → `ordessa_agents`（613 处 import）、`ordessa_agent_tools` → `ordessa_cli`（35 处）、
  `server_plugin_api` → `ordessa_server_plugin_api`（259 处）仍未改名。
- `ordessa` 元包未建；`decision_runtime` import 名未改为 `ordessa_decision`（避免与发行改名同批叠加风险）。
- harness 品牌并入 `ordessa-agents`（H2）、operation id `profiles.* → agents.profiles.*` 未做。

## 5. 回归数字（同一 venv，48 个项目）

| 集合 | 结果 |
| --- | --- |
| packages_convergence 3 文件 | 6 passed / 0 skip（GREEN_NO_SKIPS） |
| S-09 安装闭包门 | 2 passed / 0 skip |
| `apps/cli/tests` | 92 passed / 0 failed |
| environments + local provider | 181 passed / 1 skipped |
| `python_workspace.py` 校验 | 48 same-source distributions |
| decision tests | 7 收集错误（pristine HEAD 同样 7 个，既有） |
| apps/server tests 收集 / architecture | 96 errors / 3 errors（均既有） |
