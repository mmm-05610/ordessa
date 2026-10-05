# Original preparation reconciliation evidence

2026-10-05；前置HEAD `deb39c19751621d2dc705f807a394a6185d56a46`，clean。
主会话唯一共享源码/Git/测试/账本写者；Codex只读接口核验与终审，无另一写者。

## Contract and ownership

`ordessa-agent nodes query-preparation ORIGINAL_REQUEST_ID --config services.json --service local --json`
薄绑定到核心既有 AgentAssembly.query。核心发布 agents.nodes.queryPreparation(requestId)，
精确返回 `{operation: operation_view | null}`；operation_view沿原四字段投影。
Server仅由catalog.request_key取得当前Environment/认证principal，正文不接受realm或principal覆盖。
仍是同store同操作；不reserve、dispatch缺step、publish Node或创建第二ledger。

query可通过原Invocation query权限核实已有claim并记录原Step，所以schema effectful=true，
丢失/坏回执按unknown6；不是无作用日志读。缺原操作4，不推断此前无效果、不授换键重发。
已published原结果可恢复，即使第一次operationRef丢失；未published原步骤即使已concluded仍6，
没有自动继续prepare或偷偷publish。配置操作的request-key lookup仍缺，不用这条prepare query替代。

## Exact identity prerequisite

真实SQLite新6反例先证实 assembly Python mapping equality 混认 true/1/1.0：
错provider observation能published，错Unit Usage被concluded，query错原Unit能记成running/concluded。
复用已有nodes._same_reference/safe_json精确比较，含当前provider、context/source/Directory引用、
原owner receipt/Usage/Unit关联；保留现有授权/claim/CAS/生命周期，不新造leaf schema或原生真值。
作用后错证据保unknown，不宣称native效果为零。

## Main-only serial verification

解释器 `PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。

- 修复前 `PY -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py -k numeric_reference_alias -q --tb=short`：0P/6F、23 deselected，exit1、0.65s。原断言保留，未skip。
- 修复后原assembly＋prepare CLI：`PY -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py products/agent-tools/tests/test_preparation_cli.py -q --tb=short`：61P/0F，exit0、17.15s，在query测试追加前快照。
- 新query定向 `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_preparation_cli.py -k query -q --tb=short`：14P/33deselected，exit0、10.61s；lost published receipt测试名称不含query，随后完整组合覆盖，不能把这14冒充全部。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_preparation_cli.py products/agent-tools/tests/test_distribution.py docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py -q --tb=short` 初81P/1F，exit1、36.88s；异kind测试误期待wire CONFLICT_REQUEST，CLI原映射是PRECONDITION_CONFLICT，修为准确既有客户端错误码，不改源码或削弱拒绝。补schema/realm注入3项后同命令85P/0F，exit0、37.44s。

新增22项CLI/契约与6项assembly，共28；原发行2项加强，不累加快照。fresh wheel/venv仅本产品
no-index/no-deps安装，独立CLI对原Core/SQLite/issuer受控HTTP执行prepare/replay/query，9请求，
provider仍唯一prepare/start。未知原Step被query核实但无start/publish；重复query不再观察已concluded步骤。
真实realm隔离、正文realm注入、异kind原key、读权不授prepare、Invocation权限撤销、缺method/port、
缺席不花key、作用后坏/丢receipt等反例实际执行。原迟到证据/CAS门保留并随assembly组合复跑。

首次完整产品＋全部AU证据收集：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests docs/implementation/agent-tools/evidence/agent-unit-model -q --tb=short`：exit2、0.57s，2 collection errors，缺测试closure的ordessa_harness_codex；不能算绿。源包本树存在，后续沿既有验证方式显式PYTHONPATH加入三家和公共运输，不安装依赖、不skip门。

## Limits

Core/SQLite/受控HTTP/owner与独立安装进程是C证据，不是production native Harness P或任务M；M0。
production授权/材料/SecretRef/capture/receipt/effect/Session owner、完整生命周期/原生冷恢复、
旧Model/Server装配迁移、connect/applyProfile/stop/release/tasks/results与全纵向验收继续PARTIAL。
未安装更新第三方、改登录/用户DB/凭据/全局配置、重启用户服务、push或合并主树。

补齐本树测试源码闭包后的完整命令：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests docs/implementation/agent-tools/evidence/agent-unit-model -q --tb=short`：999P/0F，exit0、177.80s；本轮全部产品与AU证据快照，不累加以前组合。三家/七家与现有门保留。

全Core：`PY -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q --tb=short`：269P/3F，exit1、7.08s、0skip；仍test_n4r1_kernel_direction.py kernel import与两项planted tripwire，既有test_closeout_environment_dispatch.py导入具体SQLite，未删断言/移走失败。worker/sidecar/ACP closure/Claude资源ABSENT继续。

管理Skill quick_validate、五工单strict、生成镜像检查与最终diff-check exit0仅结构门。diff-check中曾发现发行测试EOF多空行，已修正，不影响断言。

## New bundle installation

- `PIP_NO_INDEX=1 PY products/agent-tools/packaging/build_bundle.py --output products/agent-tools/dist/bundle-0.1.0a2-preparation-query-deb39c`：exit0，保留全部旧包不覆盖。
- `PIP_NO_INDEX=1 PY products/agent-tools/acceptance/install_use.py --bundle products/agent-tools/dist/bundle-0.1.0a2-preparation-query-deb39c --evidence docs/implementation/agent-tools/evidence/install-use-preparation-query-deb39c.json`：exit0，27命令/清理记录，M0，temporary_runtime_removed=true。
- wheel SHA256 `505dd96e8ea114961566cca60ab4094acedbe83be58145b1abac4070f5edf057`，ignored dist不入Git；回执hash/27条/临时entrypoint实际缺席再核验exit0。

此安装exercise是既有隔离Server/catalog/CAS/鉴权/离线/自有重启证据，不把它冒成新query生产正例。
新query的fresh installed独立CLI正例来自上述85/999发行C场景。所有测试/服务句柄terminal，自有临时目录已清理。
