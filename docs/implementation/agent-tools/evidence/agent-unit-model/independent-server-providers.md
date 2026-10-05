# AU003 独立 Server 提供者装配原型（PARTIAL）

基线478643a80a1aa6eeb0c54864f83a628adff2efc1，clean。主会话唯一共享源码/测试/Git/账本写者，Codex只读接缝攻击与终审。新增三家可选 `server_plugin.py` 和server extra，原owner为codex/pi/claude-code；Claude provider ID仍claude。Server API lazy import，基础wheel无Server依赖。factory一次接受本EnvironmentId，须是可信、无native IO的部署构造，返回本家Provider且definition namespace一致。沿原CoreBinding和AgentContributionSet stage/commit/retire，wrapper不自行install/enable/activate或建ledger/授权。

Server既有pacthold.contributions默认exclusive使第二家无法发布。改为multi-owner point，重复provider/definition仍由唯一CoreRegistry拒绝。其他C2点默认独占未改变。此公共共享接缝主会话串行补齐，不另开接口写者。

AgentToolsDeployment新增显式tuple provider_plugins，默认空，非空要求agent-assembly/2；不添加client依赖/品牌协议，不发布 native ready 或任何权限。首轮可以真实Server/Core/SQLite启动、三家公开registry发现；默认provider没有start。旧 root冷激活代次缺持久分配，因此临时guard在storage takeover前拒非空provider选择的既有root。该guard只约束此部署；其他composition选择wrapper仍受现存Core generation缺口影响，不准将原型当生产冷恢复完成。

## 主会话串行命令

`PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`，前缀 `PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src`；均 `$PY -m pytest -c products/agent-tools/pyproject.toml ... -q --tb=short`。

- 新 `products/agent-tools/tests/integration/test_independent_server_providers.py` 首轮：3P/4F、exit1、0.34s。三家独占点拒第二owner；三个foreign负例错误将build期拒绝写成start期，调整调用位置，拒绝断言仍保留。
- point改multi-owner后同文件：6P/1F、exit1、0.25s。冷重开generation仍等于旧代次，真实反例不能删除或放宽。
- 补wrong family、v2/tuple、重复CoreProvider回滚＋Claudefresh wheel无ServerAPI导入：12P/1F、exit1、5.04s。冷代次断言继续失败。
- 加既有root拒绝、首轮三家公开发现与独立codex退役后，同新文件＋`apps/server/tests/platform/test_closeout_core_binding_environment.py`＋`plugins/harness/tests/test_agent_unit_source_ownership.py`：26P/1F、exit1、0.53s。原fullcold测试现因明确typed拒而失败，仍保留重开成功且新generation不复用的目标断言。资源检查worker/sidecar/ACP/Claude ABSENT、0skip，不算绿。
- 完整 `products/agent-tools/tests/integration`＋`plugins/harness/claude-code/tests/test_acp_attachments_distribution.py`：311P/1F、exit1、16.87s。新文件14项，原integration297项，fresh发行1项；快照不累加。

新三家模块基础依赖无ServerSDK；Claudefresh四自有wheel/venv no-index/no-deps中 `server_plugin_api` 明确缺席仍可import可选wrapper模块。只验证import/转换闭包，不实例化Server descriptor或误称能使用未安装的extra。

## 冷代次未决与限制

Environment当前 `_activation_generations`仅实例dict，现有合同未定义cold高水位初始化。提案见 `activation-generation-proposal.md`，已按用户规则先请求裁定fresh证明/历史缺证据拒绝。不自行seed1、扫描历史max或自动迁移用户DB；尚未实现counter。原failed assertion保留，已登记known-issues。只读审阅确认实现范围，无新增源码阻断，但不能报可重启服务/production owner完成。

以上是C/自有安装进程，未启native进程，M0。production权限/材料/receipt/config/lifecycle、native P/M、sidecar/旧model迁移和tasks/results仍PARTIAL；本轮未全Server/Core回归，前轮Core三红与旧Server正向红保留。无用户DB/凭据/全局配置/登录/第三方更新/模型/用户服务/push/主树合并。费用unknown。
