---
id: "018"
slug: "operation-claim-integrity"
batch: "agent-core-claim-integrity-20261006"
baseline: "e4dc70aa5c"
baseline_status: "approved-continuation"
state: "completed"
depends_on: [{"order":"017","condition":"冻结017快照821P、307P、43P通过，当前与018联合保存检查点"}]
write_paths: ["packages/backend/persistence-sqlite/src/ordessa_persistence_sqlite/operation_records.py", "products/agent-tools/tests/integration/test_operation_claim_integrity.py", "docs/implementation/agent-tools/evidence/agent-unit-model/operation-claim-integrity-20261006.md", "docs/known-issues.md", "docs/implementation/agent-tools/status.md"]
forbidden: ["其他树/**", "用户数据库/服务/凭据/全局配置", "模型调用", "staged语义放宽", "第二账", "wire/CLI", "重建丢失claim", "删除旧断言"]
ruling: "R-0004"
terminal: ["AT_018_CLAIM_INTEGRITY_DONE", "AT_018_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015", "016", "017"]
parallel_units: ["core_impl唯一operation_records源文件；wire_impl唯一新测试；core_review只读；root文档/串行验证/Git"]
---
# AT-018 普通操作缺行不得重领

## Objective

修复原Store普通操作记录损坏时可能重新占用旧发送步骤的缺口，不重建历史，不扩大到第二执行账。

## Current state

017冻结快照产品821P；普通路径仅检查current属于recipe，current或已越过claim缺行可能重新INSERT。known-issues已登记，真实临时数据库反例待验。

## Scope

同树非重叠Luna写权；root串行验证与账本。最窄current读取完整性门＋missing目标在current或之前的claim拒绝；不复制staged完整前缀读取门。

## Requirements

### Requirement: 缺行不表示从未发送

#### Scenario: 当前或已越过的claim缺失

**WHEN** current row缺失或重新claim已越过且无row的步骤
**THEN** typed GuaranteeUnavailable，零Usage/step/receipt写，不重建、不重派。

### Requirement: 旧读取与拒绝恢复保持

#### Scenario: 完整tail但较早row缺失

**WHEN** 只查询完整当前tail记录
**THEN** 保持普通只读行为，但较早缺行目标不得重领；下一步骤仍须所有前序明确结论。

#### Scenario: 无claim合法拒绝

**WHEN** current为空且step表空的reserved/refused或同证据恢复重放
**THEN** 保持原合法行为；current为空但有孤立行则拒。

## Stages

- [x] 1. Luna源码、独立临时数据库反例及只读攻击。
- [x] 2. 全冻结后root串行定向/旧拒绝恢复/staged/SQLite回归，必要产品全套。
- [x] 3. 记录命令、退出码、数量、缺口，明确017与018联合检查点后继续材料接线。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| No resend | missing past/current拒 | 删除step0后重claim | 保留未知占用、不得补造 |
| Read | 当前有效可读 | current损坏仍读 | typed拒 |
| Compatibility | 无claim拒绝恢复不变 | 全prefix读门误拦tail | 不扩大读门 |
| Evidence | 原SQLite事务零写 | Usage先写再拒 | tmpDB真实故障反例 |
| Resource | 不碰用户DB | 真库删行 | 缺临时资源即失败、M0 |

## Validation

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_operation_claim_integrity.py products/agent-tools/tests/integration/test_staged_operations.py products/agent-tools/tests/integration/test_operation_store.py products/agent-tools/tests/integration/test_invocation_authority.py -q --tb=short
```

原拒绝恢复与读取文件从既有证据确认后同一串行runner补入；真实服务/模型缺席不能算绿。

## DoD

最窄实现、current/过去claim缺行反例、零写、旧合法保留、原staged反例回归、退出码/数量/未验范围及known-issues更新。

## Acceptance

只认受控Store修复，不宣传材料、Harness或产品完成。

## Batch report

AT_018_CLAIM_INTEGRITY_DONE；150/43/307/826P均exit0，命令、反例与缺口见[证据](../evidence/agent-unit-model/operation-claim-integrity-20261006.md)。只Store C级收口，产品PARTIAL，资源缺席不算绿。
