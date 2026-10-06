---
id: "019"
slug: "material-operations"
batch: "agent-core-material-operations-20261006"
baseline: "a94d54639a"
baseline_status: "approved-continuation"
state: "completed"
depends_on: [{"order":"018","condition":"固定a94d54639a，150/43/307/826P通过；已裁定受权材料原账与分阶段"}]
write_paths: ["packages/backend/pacthold/src/pacthold/agents/material_operations.py", "packages/backend/pacthold/src/pacthold/environment.py", "packages/backend/pacthold/src/pacthold/agents/public.py", "products/agent-tools/tests/integration/test_material_operations.py", "docs/implementation/agent-tools/material-operation-contract-v1.md", "docs/implementation/agent-tools/evidence/agent-unit-model/material-operations-20261006.md", "docs/implementation/agent-tools/status.md", "docs/known-issues.md"]
forbidden: ["其他树/**", "用户数据/服务/凭据/全局配置", "真实模型调用", "材料释放/Node转移/实际消费保证", "Profile/payload引用解析", "SecretRef", "Assembly/wire/CLI", "新authority/账/registry", "旧C1作用fallback", "InvocationIssuer/Store契约改宽"]
ruling: "R-0004"
terminal: ["AT_019_MATERIAL_OPERATIONS_DONE", "AT_019_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015", "016", "017", "018"]
parallel_units: ["core_impl唯一三源文件；wire_impl唯一新产品测试；core_review只读攻查；root唯一合同/文档/串行验证/Git"]
---
# AT-019 原步骤非秘密材料获取与核实

## Objective

把已固定原MaterialRequest接到同原provider、服务器唯一issuer、原Step/Usage事务，不另建执行核心或翻译层。

## Current state

a94d54639a；合同/准入/分阶段Store已验，但没有受权材料协调。Profile配置引用提取/编译交接缺席，本单不猜路由。实施合同../material-operation-contract-v1.md正接受三Luna只读审查，未冻结前不得编码。

## Scope

非秘密已reserved原Operation内的acquire与原request query。两原Usage持有，持久receipt同原step。source/test独占如frontmatter；root唯一串行执行。

## Requirements

### Requirement: 同一提供者和服务器权限

#### Scenario: 完整固定材料请求

**WHEN** 原Registry/Host pin、资源版本/用途/Node/目录/epoch与step/binding全部一致且原issuer许可
**THEN** 同原provider最多一次resolve并校原verified_consumption，安全receipt同step/Usage事务记录。

#### Scenario: 缺资源或权限

**WHEN** 缺能力/issuer/Usage/固定事实、pin变更或目录拒绝
**THEN** 发前typed拒；claim后变更保未知占用；不旧C1fallback、不重领。

### Requirement: 原请求只读恢复

#### Scenario: 回执丢失或持久失败

**WHEN** 原claim存在但获取结果未知
**THEN** 仅原request query且当前读取授权，无lease也可精确核原receipt，不再次resolve；query缺覆盖保unknown。

## Stages

- [x] 1. 三Luna只读审合同→root冻结→源码/独立测试/审查。
- [x] 2. 全冻结后root串行定向单元/契约/临时SQLite、旧材料准入/Store/issuer回归及必要产品全套。
- [x] 3. 命令/退出码/测试数/失败/缺口分账，本地检查点继续配置domain材料交接依赖核实。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| Identity | 原entry可信host pin | caller提供另一provider | typed拒，零作用 |
| Authority | 原固定issuer/context | 只metadata read或错目录 | 拒，无第二authorizer |
| Once | 原claim最多一次resolve | 同key重复/新票 | 返回原记录不派 |
| Recovery | query原请求无lease | 换key/reacquire | unknown保hold |
| Atomic | 原step＋Usage同事务 | provider成功corecommit失败 | 无部分写、不得报绿 |
| Resource | tmpDB受控provider合同 | 声称生产消费 | 未验/P0/M0 |

## Validation

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_material_operations.py products/agent-tools/tests/integration/test_staged_operations.py products/agent-tools/tests/integration/test_invocation_authority.py docs/implementation/agent-tools/evidence/agent-unit-model/test_material_contract.py docs/implementation/agent-tools/evidence/agent-unit-model/test_material_provider_admission.py -q --tb=short
```

core/API及产品suite按018同串行命令；真实consumer/服务缺席不算绿，费用以平台账。

## DoD

exact原记录/两holds/原provider重核、一次resolve与当前query、完整receipt校验、未知占用、故障原子、冷恢复、旧拒绝门不回归、账本及资源缺席行为。

## Acceptance

只受控核心非秘密acquire/query接缝；不认Profile消费/三寿命/释放/CLI完成。

## Batch report

AT_019_PARTIAL；受控core定向146P/core307P/产品852P均exit0，实际命令/失败/数量见[证据](../evidence/agent-unit-model/material-operations-20261006.md)。真实服务/消费/原activation冷query依赖缺席，不认产品完成。下一配置domain先契约后接线，未知不重发。
