# 020 配置提供者与引用覆盖纯合同

基线4107c32678。三名Luna分别唯一源码、唯一新测试及只读攻击；root指导、合同/文档/串行测试/Git。源码三文件：core/configuration_admission.py、agents/configuration_references.py、agents/public.py。独立测试位于products/agent-tools/tests/integration/test_configuration_provider_contract.py。零原生进程/模型调用，无用户数据/服务/凭据/全局配置修改，.env不读不入库。

## 定向过程与结果

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_configuration_provider_contract.py -q --tb=short
```

首跑47P1F exit1 0.21s：空purpose引用在pytest.raises外构造，生产已正确typed拒。唯一测试作者只将构造纳入断言范围，跨环境及空用途两个参数意义保留，无删断言/skip。静态攻击先修coverage list/dict裸TypeError为type先行、定义id latest/*范围一致，公共错误别名保原类身份。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_configuration_provider_contract.py docs/implementation/agent-tools/evidence/agent-unit-model/test_material_contract.py docs/implementation/agent-tools/evidence/agent-unit-model/test_material_provider_admission.py products/agent-tools/tests/integration/test_material_operations.py -q --tb=short
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
```

组合108P0F exit0 1.53s（新48＋旧60，session47601终结）；core/API307P0F exit0 8.19s（session69460终结），无skip。worker/sidecar/ACP资产报告ABSENT，不能凭runner GREEN_NO_SKIPS宣称资源齐全。DTO属于纯单元/合同；旧材料部分临时SQLite受控provider，不是实际内容消费或Harness原生证据。

```bash
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q --tb=short
```

产品全套900P0F exit0 220.65s，session29408已终结，无skip。源/test冻结，48新参数化场景，非独立计数叠加。真实材料内容、同Registry配置贡献准入、编译/交付/实际应用、三寿命/Secret/冷owner恢复仍NOT_RUN或缺接缝，整体PARTIAL。

## 控制与职责

独立终审expected_pin完整activation/provider比对、声明六字段+路由精确匹配、extract_references声明门、深快照/序列化覆盖无阻断。实际信任来自未来原Registry准入，本片不自授权。用户要求Agent核心掌控调度，材料引用不转让控制权；现Assembly仅plan hash+粗prepare/start的效果范围缺口另记agent-control-boundary.md。domain-ownership-plan.md为下一阶段分域准备，目录存在不意味着贡献已接线。
