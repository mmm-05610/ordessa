# Server 下层闭包与上层保留清单（2026-10-21）

本文件记录本次"下层正式链不再默认依赖上层装配"的精确范围。它**不**宣称 Units/Engineering 已在全仓退役；退役工单与退出条件见 §3。

## 1. 已做的依赖切割（源码事实）

`apps/server/pyproject.toml` 的 `[project.dependencies]` 已移除：

- `ordessa-units==0.1.0`
- `ordessa-engineering==0.1.0`
- `ordessa-system-access-bindings==0.1.0`（该发行自身硬依赖 units + engineering）

三者改为可选 extra：

```toml
[project.optional-dependencies]
upper = ["ordessa-units==0.1.0", "ordessa-engineering==0.1.0",
         "ordessa-system-access-bindings==0.1.0"]
```

默认安装闭包即不再需要它们；`upper` 是**退役/待重设计代码的临时容器**，不得新增消费者。

## 2. 上层保留清单（仍在源码树，默认不可达）

保留（不删除、不修改）的旧装配代码，全部只在安装了 `upper` 时才可导入：

| 组 | 数量 | 代表路径 |
| --- | --- | --- |
| import `ordessa_units` | 24 个文件 | `apps/server/src/ordessa_server/composition/{unit_runtime.py,unit_admission.py,product_unit_admission.py,runtime.py,...}` |
| import `ordessa_engineering` | 32 个文件 | `apps/server/src/ordessa_server/composition/engineering*.py`、`configuration/*` |
| import `ordessa_system_access_bindings` | 13 个文件 | `composition/{agent_tools/owner_ports.py,configuration/request_integrity.py,...}` |

精确清单以 `grep -rl "ordessa_units" apps/server/src` 等三条命令的输出为准；本文件不复制易漂移的逐文件列表。

其它保留项：

- `apps/server/deployment/default-product/src/ordessa_server_product/cli.py`：旧产品 CLI 语法/路由（legacy flags），新 composition **不**暴露它。
- `packages/engineering/**`、`packages/execution/units/**`、`methods/**`：冻结面，本批未改。

## 3. 退役工单与退出条件

| 工单 | 范围 | 退出条件 |
| --- | --- | --- |
| U-01 Units 物理退役 | 上表 24+13 个 server 模块的消费者切换；`bindings` 与 engineering 的可选 extra；相关测试迁移 | 三个 grep 归零 + 旧测试迁移完成 + `upper` extra 删除 |
| U-02 Engineering 归属 | 等待用户的重设计结论 | 用户确认后另立工单 |
| U-03 CI 修复 | `.github/workflows/ci.yml` 仍引用 `packages/pacthold`、`products/server`、`plugins/server-compat` 等已退役路径 | 按现结构重写并真跑 |

## 4. 未完成的验证（必须显式承认）

本文件**只**证明源码依赖声明已切割、且默认产品链不再 import 上层模块（见 `docs/verification/agent-cli-server-20261020/w1-zero-config.md`）。**尚未**完成：

1. 在"只装默认闭包"的独立 venv 中启动 Server 并跑 Profile 生命周期（安装门）；
2. 植入反例：旧链模块在该环境必须 `ModuleNotFoundError`，把依赖加回去时测试必须变红；
3. `pip check` 在该闭包内干净。

这三项属 T04-A 发行门，留给下一轮实施；在此之前不得宣称"发行闭包已脱开 Units/Engineering"。

## 5. 已知环境缺陷（阻止按文档安装）

`ordessa_interfaces` 命名空间由 `ordessa-interfaces` 与 `ordessa-interfaces-contracts` 两个发行共同提供（后者供 `system_access/contracts`）。**editable 安装**下两份片段互斥可见，导致 `ImportError: ... (unknown location)` 与 7 个测试模块无法收集。本轮用 **wheel 非 editable 安装**规避；源码层修复（把 `system_access` 子树收敛到单一发行）归入 W8 发行收敛，已登记 `docs/reference/known-issues.md`。
