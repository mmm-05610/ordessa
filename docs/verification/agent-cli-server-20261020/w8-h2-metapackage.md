# W8 进度：harness 并入 agents（H2）+ `ordessa` 元包（2026-10-21）

## 1. H2：品牌 provider 并入 `ordessa-agents` 一个发行

- `ordessa-agents` 现在同时打包：`ordessa_agents`（29 个包）+ 15 个品牌包
  `ordessa_harness_<brand>`（源码仍在 `plugins/harness/<brand>/src`）。
- 15 个 `ordessa.harness_providers` entry point 改由 `ordessa-agents` 的 metadata 声明；
  15 个 `plugins/harness/*/pyproject.toml` 删除；workspace 项目数 48 → **33**（+元包 = 34）。
- `apps/server`、`default-product`、`apps/cli` 对 `ordessa-harness-*` 的依赖全部移除。
- 品牌 import 名保持 `ordessa_harness_<brand>`（未改，避免与本批改名叠加）；core 仍然只经
  entry point + allowlist 加载，不 import 具体品牌。

验证：

| 项目 | 结果 |
| --- | --- |
| 安装后 `entry_points(group='ordessa.harness_providers')` | 15 个，name 与 value 与旧声明逐一相同 |
| `import ordessa_harness_kilo` / `_pi` | 成功（由 `ordessa-agents` 提供） |
| `plugins/harness/pi/tests` | **71 passed**（原 70 passed/1 failed；失败用例改为从安装 metadata 断言 entry point 归属 `ordessa-agents`，断言未削弱） |
| kilo / codex 测试收集 | 1 / 16 个收集错误 —— 与 pristine HEAD 快照完全一致（既有缺模块，非本批引入） |
| packages_convergence 3 文件 | 6 passed / 0 skip（GREEN_NO_SKIPS） |
| S-09 安装闭包门 | 2 passed / 0 skip（闭包仍不含 units/engineering/bindings） |
| `apps/cli/tests` | 92 passed / 0 failed |
| environments + local | 181 passed / 1 skipped |

## 2. `ordessa` 元包

`apps/product/ordessa`（无代码，`packages = []`）：

```toml
dependencies = ["ordessa-server==2.0.0a1", "ordessa-server-product==2.0.0a1",
                "ordessa-cli==0.1.0a3", "ordessa-agents==0.1.0",
                "ordessa-environments[openshell]==0.1.0", "ordessa-decision[jev]==0.3.0"]
[project.optional-dependencies]
upper = ["ordessa-units==0.1.0", "ordessa-engineering==0.1.0", "ordessa-system-access-bindings==0.1.0"]
```

安装器同步扩展：允许"无 import 包的元包"（不派生源码根），且只有**单源码根**发行保持 editable；
多根发行与元包一律 wheel 安装。`ordessa 2.0.0a1` 已在本 venv 安装成功。

## 3. 本批未做（W8 最后一项，转 T04-B）

**operation id `profiles.*` → `agents.profiles.*` 未做**，原因不是工作量大（约 30 个文件），而是它与
T04-B 的能力组装耦合：现在 Server 只注册一个 capability（id `profiles`）；T04-B 要把 profiles /
instances / native / harness 合成**一个** `agents` 能力组，届时 operation id 前缀、capability id、
CLI 映射、默认 grants 需要同批改一次。在此之前改成 `agents.profiles.*` 但 capability id 仍是
`profiles` 会造成"前缀与归属不一致"的中间态，故推迟并登记。

## 4. 当前发行表（34 个项目）

`ordessa`（元包）・`ordessa-server`・`ordessa-cli`・`ordessa-agents`（含 15 品牌）・
`ordessa-environments`（含 local/openshell）・`ordessa-decision`（含 cel/jev）・
`ordessa-interfaces`・`ordessa-interfaces-contracts`・`ordessa-server-plugin-api`・
`ordessa-system-access-client`・`ordessa-infrastructure` + 其余 plugins/workbench 等；
`ordessa-units`/`ordessa-engineering`/`ordessa-system-access-bindings` 仅 `[upper]`。
