# Node publication JSON identity evidence

2026-10-05；前置 HEAD `962e290e36f34a487e5a621d5ca11f37c4eb8d14`，clean。
主会话唯一源码、测试、Git和账本写者；Codex子代理只读审阅，不运行测试。

## Problem and correction

原 Python mapping equality 把 `true`、`1`、`1.0` 混认。实际 SQLite 反例证实：
Node/Profile/context/provider/Unit owner/step provider/access owner 的数值错配仍能发布；
已发布记录的 reservation 与 sourceSteps 被数值错配篡改后仍能读出。

核心复用既有 `safe_json` 编码精确比较原引用，包括当前 provider 接纳、固定 lineage、
原 step receipt、Usage holder/target 与持久来源。没有新增协议、存储、授权来源、状态机或原生事实。
owner leaf 引用保持 opaque：整数引用可正常发布与重放，但不能与 bool/float 混认。
发前拒绝不发布、不转移 Usage；冷读拒绝不改既有 published 结论。
原 unknown、授权、CAS、唯一 publish_operation 事务路径保留。

## Serial commands and evidence

解释器 `PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。

- 修复前：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_node_publication.py -k json_numeric_alias -q --tb=short`：0P/18F、25 deselected，exit1、0.45s。全部因该拒而未拒失败；没有删除断言或 skip。
- 初修复：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_node_publication.py products/agent-tools/tests/integration/test_node_observation_wire.py -q --tb=short`：57P/0F，exit0、0.93s。
- 补 Unit target、step receipt、Node holder、当前 admitted provider 的 bool/float，以及 opaque 整数正例后，同命令：66P/0F，exit0、1.07s。新增27项，不累加快照。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q --tb=short`：296P/0F，exit0、10.72s。

## Scope

这是 Core/SQLite 与受控 owner 的 C 证据。没有真实 native Harness 进程或模型任务；M0。
真实 production 授权、材料、capture/receipt/effect/Session owner、完整生命周期、冷恢复、
旧 Model/Server 装配迁移、prepare/tasks/results CLI 与全纵向验收仍待完成。
既有全 Core 三项 kernel_direction 失败独立登记，不能用本切片绿代替。
没有安装更新第三方、改登录/用户数据库/凭据/全局配置、重启用户服务、push或合并主树。

调用方复跑：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_nodes_cli.py products/agent-tools/tests/test_configuration_cli.py products/agent-tools/tests/test_distribution.py -q --tb=short`：99P/0F，exit0、57.48s；发行测试包含 fresh wheel/venv/独立CLI对原Core与受控HTTP owner，没有真实 native Harness。

全核心：`PY -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q --tb=short`：269P/3F，exit1、7.83s，0 skip；失败仍是 test_n4r1_kernel_direction.py 的 kernel import 及两项 planted tripwire，来源是既有 test_closeout_environment_dispatch.py 直接导入 ordessa_persistence_sqlite。worker/sidecar/ACP closure/Claude资源ABSENT继续，不视作通过。本轮未修复或删移该测试。

五工单 `validate_order.py ... --strict` 与 `git diff --check` exit0，仅格式资料门。全部测试句柄terminal。

只读终审指出 admitted_provider 反例初稿同时改了Node generation，可能提前触发lineage拒绝；已限定修改provider引用而保Node/lineage，并断言确切currently admitted provider拒绝来源。修改后上述publication＋wire66P exit0、1.12s；再加错误来源断言后的 `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_node_publication.py -k opaque -q --tb=short` ：9P/43deselected，exit0、0.18s。296/99/全Core是这项测试定位改进之前结果，源码未再变，不称重新全跑。
