---
id: "017"
slug: "staged-operation"
batch: "agent-core-staged-operation-20261006"
baseline: "e4dc70aa5c"
baseline_status: "approved-continuation"
state: "completed"
depends_on: [{"order":"016","condition":"本实施树固定e4dc70aa5c，55/307/788P通过，用户明确采用分阶段同一操作记录"}]
write_paths: ["packages/backend/environment-api/src/ordessa_environment_api/staged_operations.py", "packages/backend/environment-api/src/ordessa_environment_api/__init__.py", "packages/backend/persistence-sqlite/src/ordessa_persistence_sqlite/operation_records.py", "packages/backend/persistence-sqlite/src/ordessa_persistence_sqlite/store.py", "products/agent-tools/tests/integration/test_staged_operations.py", "docs/implementation/agent-tools/evidence/agent-unit-model/staged-operation-20261006.md", "docs/migration/agent-staged-operations.md", "docs/known-issues.md", "docs/implementation/agent-tools/status.md"]
forbidden: ["其他树/**", "用户数据库/凭据/全局配置/服务", "真实模型调用", "原OperationStorePort required面变更", "Assembly/material/provider作用接线", "新执行账/表/索引/权限真值", "旧steps/bindings/refs改写", "任意DAG/多阶段编辑", "wire/CLI/capability启用"]
ruling: "R-0004"
terminal: ["AT_017_STAGED_STORE_DONE", "AT_017_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015", "016"]
parallel_units: ["core_impl唯一四源文件；wire_impl唯一新test；core_review只读攻击；root唯一合同/文档/账本/串行验证/Git"]
---
# AT-017 同一原Store两阶段准备能力

## Objective

落实用户已裁定材料核实后原子补入后续准备步骤，原记录/请求不另建账。只Store可选接缝，材料/Assembly作用下一片。

## Current state

e4dc70aa5c；原Registry受权材料纯合同准入已验55P/307P/788P。原Store所有steps一次冻结，无法按028材料先→正式plan后，需要版本化可选staged能力。

## Scope

精确实现权威../staged-operation-contract-v1.md；core_impl四源文件，wire_impl新test，core_review只读，root文档/验证/Git。只本树自有tmp数据库；不碰用户数据/服务，不模型/安装。

## Requirements

### Requirement: 原操作记录原子分阶段

#### Scenario: 材料全核实后完整后续recipe封存

**WHEN** root全部steps明确concluded且CAS匹配
**THEN** 同env_requests一次追加step/binding/facts并seal；不改root身份/步骤/授权事实，不claim、不转Usage、不调provider。

#### Scenario: 未知、并发或不同phase

**WHEN** missing/possibly-dispatched/unknown/refused、旧revision/hash或同phase不同输入
**THEN** typed拒且全事务零部分变更；sealed不能追加，unsealed不能publish。

### Requirement: 旧调用面保持

#### Scenario: 新root重放与原普通记录

**WHEN** staged root同key同完整root或旧reserve调用
**THEN** 新reserve由Store计算root摘要返回当前扩展记录；旧调用仍严格完整intent相等并拒staged混用，不放宽旧语义。

### Requirement: 冷恢复及权限

#### Scenario: append前后原claim

**WHEN** coldrestart或持有旧授权
**THEN** 只读最新原recipe/steps，不能root重派发；旧context失效，新query核同claim，无新权限真值。

## Stages

- [x] 1. Luna源码＋独立反例＋只读攻击，root合同冻结与迁移说明。
- [x] 2. 全部冻结后root串行新staged/原Store/Invocation及core API/产品必要回归，记录失败/退出码/数量。
- [x] 3. 独立终审、账本、证据、本地检查点后继续材料协调，不停在纯Store绿。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| Original ledger | 同env_requests同事务 | 第二表/DomainWrite阶段真值 | 拒 |
| Freeze | 老step/ref/binding不变 | 重写已用摘要、unsealed尾步claim | 两阶段唯一append+seal |
| Unknown | 原root全concluded才推进 | lostreceipt也seal | typed拒/原hold保留 |
| Compatibility | 新可选port，旧reserve不改宽 | 旧intent相等忽略新增 | 拒混用 |
| Authority | 旧context失效/new query同claim | 追加签发或重派发 | 拒 |
| Resource | tmp SQLite | 用户DB迁移/真实模型 | 未授权，M0 |

## Validation

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_staged_operations.py products/agent-tools/tests/integration/test_operation_store.py products/agent-tools/tests/integration/test_invocation_authority.py -q --tb=short
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
```

缺真实服务/材料/owner消费不算产品绿。源四文件改SQLite交易规则，最后产品全套必要回归；全部测试root串行，不skip/删断言/fake成功。

## DoD

新root/phase规范校验、CAS/故障原子、版本与元数据损坏failclosed、旧/staged混用拒、pending/unknown/seal/publication、原context失效与query保原claim、迁移兼容说明、真实命令/退出/数量及未验范围。

## Acceptance

仅AT_017_STAGED_STORE_DONE，不冒材料/准备产品可用；阶段2/3实际资源与消费仍PARTIAL。

实测退出码/数量及未验证缺口见[017证据](../evidence/agent-unit-model/staged-operation-20261006.md)。下一片先修普通Store缺行重领风险，再继续材料协调。

## Batch report

AT_017_STAGED_STORE_DONE；120/307/43/821P均exit0，017冻结快照后018共享文件改动，最终联合检查点826P过；实际材料作用及旧缺列数据库迁移缺口见证据，产品PARTIAL。
