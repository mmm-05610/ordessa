# Fixed preparation CLI evidence

2026-10-05；前置HEAD `a6d93c926dcfa7549e27bd303eb2421c2d8741f7`，clean。
主会话唯一共享作者、测试与Git写者；Codex只读审阅，没有另一写者。

## Public seam

`ordessa-agent nodes prepare --file preparation.json --config services.json --service local --json`
直接消费已有 `agents.nodes.prepare(profileRef, context, options, requestId)`。
文件必须完整四字段；使用完整ProfileRef、公开owner context/options及原RequestKey的local ID。
原requestId成为wire ID，没有另造UUID业务身份、计划、provider选择或原生真值。
客户端拒私有路径/命令/凭据、错误类型、额外字段及跨环境引用。

Core schema发布既有operation_view四字段投影（operationRef/revision/status/node），生成v2镜像；
v1/provider镜像保持不变。Server用既有safe_json映射冻结对象，不新建Environment或ledger。
新版精确v2 digest与旧镜像不匹配会拒绝，禁止fallback。

仅published接受有效Node，并精确匹配原Profile、context/options、operationRef与publication revision；
Node观察校验复用。runtimeVerified=false，不把publication称任务成功或native ready。
reserved/running/unknown与丢失/非法回执exit6、不自动重发；refused/cancelled不报告成功。
无安全确认回执不推导operationRef。既有core状态/授权/claim/Usage/owner确认不变。
没有公开preparation query或request-key lookup；不自创新wire，Skill/README明确恢复缺口。

## Commands and results

`PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`，主会话串行。

- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_preparation_cli.py -q --tb=short`：24P/0F，exit0、12.70s。
- 补同键改变context/options冲突与缺deployment port，并加强fresh发行实际prepare/replay后：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_preparation_cli.py products/agent-tools/tests/test_distribution.py products/agent-tools/tests/test_nodes_cli.py -q --tb=short`：57P/0F，exit0、36.62s。
- 补实际reserve未dispatch及四nonpublished/null DTO后：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_preparation_cli.py products/agent-tools/tests/contracts/test_profile_wire.py docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py -q --tb=short`：71P/0F，exit0、17.00s。新prepare模块32项，不累加快照。
- 新真实隔离服务负例与原v2场景：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_profile_service.py -k v2 -q --tb=short`：3P/2deselected，exit0、3.09s。真实自有Uvicorn进程创建真实catalog Profile，prepare因authority ports缺席拒4，Profile不变；这不是native Harness成功证据。

场景：唯一prepare/start作用与同请求重放；原prepare/start断连unknown；作用后坏/丢回执unknown；错误版本、operation、Profile、context、private/Token/假ready不确认；固定输入/外环境发前拒；授权拒/方法缺席/port缺席不花key；真实reserve保留未完成；不可用task与恢复不绕过。

fresh wheel/venv/no-index/no-deps安装本产品，独立CLI进程对真实Core/SQLite/issuer与受控HTTP owner完成两次prepare，六次HTTP请求，provider calls唯一prepare/start。没有第三方包/模型/用户配置/服务改动。不是production native P/M。

## Remaining scope

真实production Directory/Invocation/material/SecretRef/capture/receipt/effect/Session owner与三家native装配、
完整生命周期及冷恢复、旧Model/Server迁移、preparation recovery、connect/applyProfile/stop/release/tasks/results仍未完成。
M0；缺资源ABSENT不算绿。全Core三项已登记kernel_direction红不借此绿化。

公共CLI/契约/发行组合：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_preparation_cli.py products/agent-tools/tests/test_nodes_cli.py products/agent-tools/tests/test_configuration_cli.py products/agent-tools/tests/test_provider_cli.py products/agent-tools/tests/test_profile_cli.py products/agent-tools/tests/test_discovery.py products/agent-tools/tests/contracts/test_profile_wire.py products/agent-tools/tests/test_distribution.py products/agent-tools/tests/test_bundle.py -q --tb=short`：222P/0F，exit0、103.58s。没有pytest失败、删除断言或skip。

三Skill quick_validate各exit0；五工单strict、核心镜像校验及diff-check exit0，仅资料/结构门。
只读审阅无源码阻断，指出use Skill仍写停止任何prepare，已限定为缺失的task/native input并将独立明确授权prepare指向manage Skill。没有宣称真实Agent行为评估。

产品集成全组：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q --tb=short`：297P/0F，exit0、11.84s。
全Core：`PY -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q --tb=short`：269P/3F，exit1、7.72s、0skip。仍为 test_n4r1_kernel_direction.py 的kernel import及两项planted tripwire，来源是既有test_closeout_environment_dispatch.py导入ordessa_persistence_sqlite；没有删除或移走失败。worker/sidecar/ACP closure/Claude资源ABSENT继续。所有测试句柄terminal。
