# W8 进度：命名收敛（第二批，2026-10-21）

本轮完成四个 import/发行改名。全部一次到位、无 alias；改动后重装 + 回归通过。
仍未做：harness 品牌并入 agents 发行（H2）、`ordessa` 元包、operation id 迁移 —— 见 §5。

## 1. 改名对照

| 旧 | 新 | 影响文件（tracked 引用） |
| --- | --- | --- |
| import `ordessa_agent_tools` + 发行 `ordessa-agent-tools` | `ordessa_cli` / `ordessa-cli` | 35 + 包装名 |
| import `server_plugin_api` | `ordessa_server_plugin_api`（发行名 `ordessa-server-plugin-api` 不变） | 259 |
| import `decision_runtime` | `ordessa_decision`（发行 `ordessa-decision` 0.3.0 已于上一批） | 131 |
| import `ordessa_execution_agents` + 发行 `ordessa-execution-agents` | `ordessa_agents` / `ordessa-agents` | 613 + 34 个 pyproject pin |

配套：CLI 入口点 `ordessa = "ordessa_cli.cli:main"`；`AGENTS.md` 中 agents 发行描述随源码名更新；
`python-workspace.json` 发行名同步。**未保留任何旧 import 别名**。

## 2. 过程中发现并修复的三个问题

1. **二次替换**：对同一批文件跑了两轮 `server_plugin_api → ordessa_server_plugin_api`，产生
   `ordessa_ordessa_server_plugin_api`（256 个文件）。已反替换并全仓复检（带词边界正则，残留 0）。
2. **旧构建产物污染**：`apps/server/build/`、`default-product/build/` 等 in-place 构建残留会把旧包名带进 wheel；
   已清理，并让 `installed_server_fixture` 在构建前删除 `build/ dist/ *.egg-info`（它现在因"一个发行多个包根"
   改成就地构建 + 外部 build-base）。
3. **测试内的 `extra_projects`** 仍引用退役发行名（`ordessa-agent-tools`），已改为 `ordessa-cli`。

## 3. 验证

| 项目 | 结果 |
| --- | --- |
| `python_workspace.py --install`（48 个项目） | exit 0；`import ordessa_agents` / `ordessa_cli` / `ordessa_decision` / `ordessa_server_plugin_api` 全部成功 |
| `ordessa` 控制台 | `--help` 正常 |
| packages_convergence 3 文件 | 6 passed / 0 skip（GREEN_NO_SKIPS） |
| S-09 安装闭包门 | 2 passed / 0 skip |
| `apps/cli/tests` | 92 passed / 0 failed |
| environments + local provider | 181 passed / 1 skipped |
| `packages/execution/agents/tests` 收集 | 1008 collected / 36 errors —— **pristine HEAD 快照同为 1008/36**，均为既有 `pacthold` 遗留引用 |
| `packages/execution/decision/tests` 收集 | 7 errors —— pristine HEAD 同样 7 个（既有） |

## 4. 诚实边界

- 改名只覆盖 `apps/ packages/ plugins/ tests/ tooling/ python-workspace.json`；`docs/` 与 `specs/` 中的历史收据
  保持原文（旧名只作历史标识），本文件的表是当前名的权威说明。
- 发行名改动后，任何**外部**消费者（不在本仓）若 import 旧名会失败——这是设计要求（不留兼容层），已登记。

## 5. 下一轮（W8 剩余）

1. harness 品牌并入 `ordessa-agents`（H2）：15 个插件 pyproject 退役、entry points 移入 agents 发行、
   workspace 再减 15、`ordessa-server`/`default-product`/CLI 的 harness-* 依赖移除。
2. 新建 `ordessa` 元包（server + cli + agents + environments[openshell] + decision[jev]）。
3. operation id 迁移：`profiles.*` → `agents.profiles.*`（能力描述符、CLI 映射、默认 grants、测试同批）。
