# AU001 公开 issuer 接缝／AU002 原票据关闭

2026-10-05，前置 HEAD `61bf9e7f5e82cc99d560ccbea33d37801c8f91f4`，working tree clean。主会话唯一源码、测试、Git、账本写者；Codex 子代理只读复核，没有测试或写入。上一状态答复是 no progress，本轮有实际源码和验证进展。

现有 InvocationIssuer、InvocationGrant、InvocationAuthorityPort、InvocationCurrentState、InvocationCurrentStatePort 直接导出到 `pacthold.agents.public`，保留 class identity，不新增协议、默认授权、registry、存储或 native 行为。

原 issuer 增加幂等 close，原锁撤销进程内票据，保留全部 durable claim。拒绝关闭后的 issue/query/continuation；在时钟回调和最终验证后检查关闭，禁止慢 state 重核返回迟到有效许可。最终 grant 序列化可能重入 close，发布票据前再检查。已返回许可的实际 IO 仍需原 owner/transport 写入屏障；此修改不承诺 native stop 或并发 store 关闭屏障。生产 deployment 尚未接入 owner/issuer。

测试放在本工单允许的 evidence 写域，直接复用原 integration fixture，不改原测试断言。新增 7 个公开面检查、7 个关闭反例。关闭测试使用真实临时原 SQLite，包含 effect/query 并发关闭、原 claim 保留、state 重入关闭、最终 grant 序列化重入关闭。

## 串行命令与结果

解释器 P=`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。所有运行均已 terminal；pytest 使用 `-c products/agent-tools/pyproject.toml -q`。

- P -m pytest evidence/test_public_invocation_seam.py + 原 test_invocation_authority.py + test_runtime_admission.py：81P，exit0，0.58s。
- 加入初 close 文件同组：86P，exit0，0.71s；加入 state 重入反例：87P，exit0，0.70s。
- reviewer 发现最终序列化窗口后，P -m pytest docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_close.py：6P/1F，exit1，0.20s。严格反例 DID NOT RAISE 保留并修源码，不删断言。
- 修正后最终同组：88P，exit0，0.66s。

最终定向完整命令：
```sh
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_close.py docs/implementation/agent-tools/evidence/agent-unit-model/test_public_invocation_seam.py products/agent-tools/tests/integration/test_invocation_authority.py products/agent-tools/tests/integration/test_runtime_admission.py -q
```

产品整合完整命令：
```sh
PYTHONPATH=plugins/harness/records/src:plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:plugins/harness/api/src:packages/backend/harness-transport/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q
```
初组311P/1F exit1 17.23s；最终修正后311P/1F exit1 16.97s。相同已登记失败：`test_three_independent_server_owners_share_registry_and_restart_identity`，当前 guard 拒绝无 durable generation 的冷重开；原 strict 断言不改。新 evidence tests 不在 integration 路径，88 与311分别记录，不累加冒全套。

五工单 strict 资料校验 exit0，只证明材料结构。最终源码/新增测试/本记录由主会话读核并显式纳入阶段提交。未全跑 Core/Server/品牌发行，无新增产品 readiness 声明。既有冷代次提案和 scope 外 Profile 一行 patch 待答复，production authority/current-state/native owner/完整生命周期/tasks/results/A18 继续 PARTIAL。C 证据，native P/M 无，M0，成本 unknown。未安装更新第三方、修改登录/用户数据库/凭据/全局配置、操作用户服务、push 或合并主树。
