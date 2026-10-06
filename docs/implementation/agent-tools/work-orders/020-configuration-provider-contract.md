---
id: "020"
slug: "configuration-provider-contract"
batch: "agent-core-configuration-contract-20261006"
baseline: "4107c32678"
baseline_status: "approved-continuation"
state: "completed"
depends_on: [{"order":"019","condition":"固定4107c32678；定向146/core307/产品852P过，实际材料消费仍缺"}]
write_paths: ["packages/backend/pacthold/src/pacthold/core/configuration_admission.py", "packages/backend/pacthold/src/pacthold/agents/configuration_references.py", "packages/backend/pacthold/src/pacthold/agents/public.py", "products/agent-tools/tests/integration/test_configuration_provider_contract.py", "docs/implementation/agent-tools/configuration-reference-contract-v1.md", "docs/implementation/agent-tools/work-orders/020-configuration-provider-contract.md", "docs/implementation/agent-tools/evidence/agent-unit-model/configuration-provider-contract-20261006.md", "docs/implementation/agent-tools/status.md", "docs/implementation/agent-tools/agent-control-boundary.md", "docs/implementation/agent-tools/material-handoff-proposal.md", "docs/implementation/agent-tools/domain-ownership-plan.md"]
forbidden: ["其他树/**", ".env", "用户数据/服务/凭据/全局配置", "真实模型调用", "Registry/Environment贡献接线", "材料读取/编译交付/Secret读取", "Assembly/wire/CLI", "新authority/账/registry", "核心导入Harness/plugin", "Harness自行推进Agent流程"]
ruling: "R-0004"
terminal: ["AT_020_CONTRACT_DONE", "AT_020_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015", "016", "017", "018", "019"]
parallel_units: ["core_impl唯一三源文件；wire_impl唯一新产品测试；core_review只读攻查；root唯一合同/工单/账本/串行测试/Git"]
---
# AT-020 独立配置提供者与依赖覆盖纯合同

## Objective

沿028分立贡献建立有界不可变descriptor、pin及逐声明引用覆盖，不把配置领域归并进Harness或再建控制核心。

## Current state

4107c32678。材料获取/原query受控通过，配置贡献无DTO/准入。用户要求Agent核心掌握控制、Harness暴露原生控制端口；受权材料读取已批准，本片仍不实现。三Luna已只读核对，root已补本次声明/expected pin比对及后续Runtime认可关联的缺席边界并冻结合同。

## Scope

只纯DTO/闭合校验/公共导出及独立产品测试。core无agents反向依赖；原Runtime/Material DTO和Registry不改。

## Requirements

### Requirement: 固定身份与领域路由

#### Scenario: 合法配置描述及提取

**WHEN** provider/version/activation/声明摘要及kind/schema/action/definition完全匹配
**THEN** 返回不可变字段快照，核心不理解payload，不调原生控制端口。

#### Scenario: 错误或缺席

**WHEN** 错环境、路由、pin、额外键或未知能力
**THEN** typed拒绝或保持unknown；不得自动complete空依赖。

### Requirement: 覆盖不能冒授权

#### Scenario: 未完整识别引用

**WHEN** coverage unknown包含部分或空引用
**THEN** 保unknown及原因；不据此继续编译/运行，不取得材料或权限。

## Stages

- [x] 1. 三Luna只读合同→root冻结→源码/独立测试/只读攻击。
- [x] 2. 源test冻结后root串行新纯合同、旧材料/准入/core边界回归。
- [x] 3. 实测/失败/缺席分账、终审及本地检查点，继续同Registry准入与Agent-owned控制合同。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| Identity | 精确pin与声明/目标route | 跨环境/别provider | typed拒绝 |
| Coverage | complete与unknown分开 | unknown空refs冒零依赖 | 保unknown，不运行 |
| Snapshot | 字段复制闭合有界 | 修改输入/覆写to_dict | 不调用/typed拒绝 |
| Boundary | core无plugin或agents依赖 | 导入Harness私有adapter | 原guard红，不删断言 |
| Control | DTO不授执行/调度权 | 引用当授权或native成功 | 未实现，不冒绿 |
| Resource | 纯数据合同证据 | 用假provider冒真实消费 | 真实消费NOT_RUN |

## Validation

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_configuration_provider_contract.py -q --tb=short
```

root唯一串行runner；旧core/API与材料合同按019既有命令回归。资料校验非产品验收。

## DoD

纯合同实现、定向正反例、原依赖回归、退出码/数量/失败记录、独立终审、缺真实owner/材料消费明确PARTIAL。

## Acceptance

只DTO及route/coverage校验，非实际extract/compile/Registry或Harness执行。所有编码/新测试由Luna作者；root负责指导和验收。

## Batch report

AT_020_PARTIAL；纯契约切片已验证：新48/组合108P、core307P、产品900P均exit0。首跑47P1F已保留证据；无skip，实际Registry贡献/内容读取/编译应用仍缺。详见../evidence/agent-unit-model/configuration-provider-contract-20261006.md。职责分域11项已准备，未跨域立即实施。
