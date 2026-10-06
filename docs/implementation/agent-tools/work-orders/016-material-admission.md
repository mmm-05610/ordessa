---
id: "016"
slug: "material-admission"
batch: "agent-core-material-admission-20261006"
baseline: "215c503060"
baseline_status: "approved-continuation"
state: "done"
depends_on: [{"order": "015", "condition": "本实施树固定SHA 215c503060，合同14/coreAPI307/既有门106通过，用户已采用受权材料扩展"}]
write_paths: ["packages/backend/pacthold/src/pacthold/core/resource_admission.py", "packages/backend/pacthold/src/pacthold/core/registration.py", "packages/backend/pacthold/src/pacthold/environment.py", "packages/backend/pacthold/src/pacthold/agents/materials.py", "packages/backend/pacthold/src/pacthold/agents/public.py", "docs/implementation/agent-tools/evidence/agent-unit-model/test_material_provider_admission.py", "docs/implementation/agent-tools/evidence/agent-unit-model/material-admission-20261006.md", "docs/implementation/agent-tools/status.md"]
forbidden: ["其他树/**", "用户数据/服务/凭据/全局配置", "C1 DTO/签名更改", "资源作用/Usage/Assembly接线", "新authority/registry/ledger", "SecretPort/秘密正文", "wire/CLI/capability启用"]
ruling: "R-0004"
terminal: ["AT_016_ADMISSION_DONE", "AT_016_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014", "015"]
parallel_units: ["core_impl唯一五个生产文件写者；wire_impl唯一新增test文件；core_review只读攻击；root唯一账本/Git/串行验证"]
---
# AT-016 同Registry材料可选能力固定

## Objective

依用户已批准受权材料扩展，从原资源注册表发布固定可信能力元数据，保持核心不识别Harness品牌，不取得材料。

## Current state

本树固定215c503060，十五纯合同已核验14P/307P/106P。本片为持久协调前的准入接缝，完整材料作用仍PARTIAL。

## Scope

core_impl独占上列五个生产文件及原agents.public导出（五文件），wire_impl独占新test，core_review只读；root文档/串行测试/Git。无C1签名变化、无第二注册/索引/权限真值。只本树。

## Requirements

### Requirement: 同一资源提供者的显式能力

#### Scenario: 旧C1缺新声明

**WHEN** 原provider静态确无material_capability
**THEN** 原stage/commit/二元lookup兼容；新exact material view typed GuaranteeUnavailable，list省略，没有旧acquire填空。

#### Scenario: 声明无效或变化

**WHEN** getter异常、未知版本、缺方法、stage后增删改/原地篡改
**THEN** stage/commit整批发表前拒，read拒；不降为legacy，不隐瞒已发布或unknown。

### Requirement: 原Registry可信固定

#### Scenario: 固定快照

**WHEN** 同一provider、descriptor/support与纯MaterialCapability合法
**THEN** 原entry第五字段固定能力，原resource_provider二元与resource_provider_admission四元保持；新增同entry内部material getter，无第二字典/缓存。commit先重验全批，再写索引；unregister同批清除。

### Requirement: 独立读权与无作用视图

#### Scenario: 调用者无读权或owner失效

**WHEN** agents.resources read拒、未激活/停用/退役、owner歧义、原对象/descriptor/支持集/能力改变
**THEN** ACL先于registry/provider访问，原active Host校验；不返回raw callable，不触材料效果，list沿014省略inactive。

## Stages

- [x] 1. 多Luna实现同Registry快照与独立攻击，作者冻结。
- [x] 2. root串行新准入＋015合同＋014准入/旧C1/API回归，记录过程退出码。
- [x] 3. 独立终审、证据、账本、本地检查点，继续实际原操作步骤协调。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| Single registry | 原entry固定capability | Agent侧第二cache/索引 | 拒实现 |
| Immutable | stage/commit/read一致且复制 | 原地object篡改 | typed拒，无坏发布 |
| ACL | read先于所有registry/provider访问 | ACL拒仍describe | 失败 |
| Compatibility | 旧二元/四元/C1合同不变 | 动态假声明、unknown version降旧接口 | typed拒 |
| Scope | 只有元数据 | 获取/claim/Usage/宣称实际消费 | 失败，整体PARTIAL |

## Validation

新增test_material_provider_admission.py与015合同/014元数据串行；原pacthold、environment integration/API完整回归。全部source冻结后由root跑，不并发测试、不隐藏失败。新准入修改核心stage/commit，若出现产品组合影响再跑产品全套；资料校验不冒产品绿。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_material_provider_admission.py docs/implementation/agent-tools/evidence/agent-unit-model/test_material_contract.py docs/implementation/agent-tools/evidence/agent-unit-model/test_resource_provider_admission_view.py -q --tb=short
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
```

## DoD

独立正反例、单原Registry、版本/Host/原对象/独立ACL/变化拒绝、旧C1兼容、全部失败与未验范围记录。资源作用/持久Agent claim/真实消费下一片，M0/用户服务0。

## Acceptance

仅AT_016_ADMISSION_DONE，完整材料PARTIAL；不据声明支持冒真实获取可用。

## Batch report

门：同Registry/ACL/不可变声明/原C1及public方向通过；退出码：strict首1后0，测试全0；证据：material-admission-20261006.md，组合55P（新增20）、核心307P、产品788P；缺口：缺声明后重新激活重发现未实测，原材料作用/Usage/owner消费仍未实现，整体PARTIAL。本树依赖十五固定215c503060，本片done只AT_016_ADMISSION_DONE。
