# 018 普通操作claim缺行保护（2026-10-06）

基线e4dc70aa5c，017冻结验证后在同文件继续018，故017/018联合本地检查点。三Luna独占源码/新测试/只读审查；root文档、指导、串行验证、Git。只有普通current-step完整性读取门与missing目标不晚于current的claim拒绝，不扩大历史prefix读门，不修改staged规则。

## 串行命令与结果

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_operation_claim_integrity.py products/agent-tools/tests/integration/test_staged_operations.py products/agent-tools/tests/integration/test_operation_store.py products/agent-tools/tests/integration/test_invocation_authority.py docs/implementation/agent-tools/evidence/agent-unit-model/test_pre_dispatch_refusal.py docs/implementation/agent-tools/evidence/agent-unit-model/test_operation_read.py -q --tb=short
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/persistence-sqlite/pyproject.toml packages/backend/persistence-sqlite/tests -q --tb=short
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q --tb=short
```

定向首150P/0F exit0 6.09s；独立读审指出空usages计数不能证明待写Usage仍零写，唯一测试作者窄补有效UsageMutation及当前step本身拒绝重领，源码未改。最终定向150P/0F exit0 5.93s，新5项，其余145旧；SQLite43P/0F exit0 0.96s；core/API307P/0F exit0 7.54s；全冻结产品826P/0F exit0 223.17s，session32626 terminal。重复快照不累计，所有suite无skip。runner worker/sidecar/ACP资产ABSENT不当资源齐全。

工单strict首次误把仓库根当目标，exit1报告AGENTS/README非工单；改正确work-orders目录后全18单strict exit0。git diff --check exit0。资料校验不能替产品使用证据。

## 正反例与限制

真实临时SQLite删除当前claim、删除已越过历史claim、注入current为空的孤立行；读/issuer query/claim typed拒，不重新创建step，带有效待写资源占用仍零step/Usage/revision变化。完整tail query走真实原Issuer/verify；历史缺行不隐藏tail但不能重新claim旧step。无claim reserved/refused精确重放、关闭重开、已有unknown不重新领用、正常顺序保留；旧pre-dispatch拒绝＋配置基准恢复及metadata read已纳入150组合。

新增为C级Store集成，不冒文件损坏自动修复、真实服务或原生Harness证据。无法恢复的记录保持拒绝/未知，不授权补造历史。材料作用与实际消费、CLI/Skill/隔离发行仍未完成；P新增0/M0，无用户数据/服务/凭据/全局配置/安装/push/主树合并。子代理账务以平台为准；.env不读不入库。
