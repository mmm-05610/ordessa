---
id: "014"
slug: "resource-admission-metadata"
batch: "agent-core-resources-20261006"
baseline: "7f7b98fb73"
baseline_status: "approved-continuation"
state: "metadata-verified-materials-partial"
depends_on: [{"order": "009", "condition": "本实施树固定SHA 7f7b98fb73的同CoreRegistry与Host activation已接纳；本切片仅扩元数据，009完整材料仍PARTIAL"}]
write_paths: ["packages/backend/pacthold/src/pacthold/core/registration.py", "packages/backend/pacthold/src/pacthold/environment.py", "packages/backend/pacthold/src/pacthold/core/resource_admission.py", "packages/backend/pacthold/src/pacthold/agents/public.py", "docs/implementation/agent-tools/evidence/agent-unit-model/test_resource_provider_admission_view.py", "docs/implementation/agent-tools/status.md", "docs/implementation/agent-tools/evidence/agent-unit-model/resource-admission-metadata-20261006.md"]
forbidden: ["其他树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**", "C1 acquire/release/reconcile签名变更", "材料执行或秘密解析", "wire/CLI/capability启用"]
ruling: "R-0004"
terminal: ["AT_014_METADATA_DONE", "AT_014_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013"]
parallel_units: ["core_impl独占四个源文件；wire_impl独占新测试文件，基于冻结行为独立于实现；core_review只读审查，无文件写权"]
---
# AT-014 同注册表资源接纳元数据

## Objective

复用028 contracts §3、AU interface-map的同Registry/可信activation原则，为未来材料路由建立只读准入事实。不是材料获取实现，不广告材料支持。

## Current state

7f7b98fb73，初始tracked clean、.env未跟踪且不读。当前CoreRegistry只保留(owner,provider)，未保留ResourceProvider的stage descriptor/support快照；Environment仅有runtime准入视图。本单开始时未新增测试证据。

原public facade AST边界实测拒绝Environment反向导入agents业务模块。因此准入DTO归core/resource_admission.py，agents.public仅再导出；原边界断言不改，未提交的agents/resources.py撤去，不扩大公共链。

## Scope

按用户明确要求同树多个Luna非重叠文件写权，主会话唯一验证/账本/Git，不新开树。源/测试写者严格限frontmatter，其他树只读；不涉及材料作用授权或获取，不扩大发现为使用许可。

## Requirements

### Requirement: 单一准入事实

#### Scenario: 已提交活动贡献

**WHEN** 原C1资源provider在同Environment提交、唯一Host activation活动，当前描述及支持合同与stage快照一致
**THEN** 读取冻结descriptor、支持合同及可信activation元数据；返回不携带provider实现对象或callable。

### Requirement: 缺失、漂移与拒权

#### Scenario: 不能证明原准入

**WHEN** provider缺失/未提交/退役/正在drain、描述或支持合同变更、合同不存在、owner无唯一活动接纳或支持合同未声明
**THEN** 单项查询typed拒绝，不把当前自报内容当新准入；list不可广告draining/未提交项。未知支持声明仍允许原C1注册，但新发现拒绝，原C1方法签名不改。

#### Scenario: 权限检查先于provider读取

**WHEN** 缺 `${environment}:agents.resources` 的object read许可，仅有runtime发现许可或无Policy
**THEN** typed拒绝，不能describe/effect调用或泄露贡献元数据。许可仅发现，不授予材料获取权限。

### Requirement: 生命周期与无作用

#### Scenario: stage至commit间变更

**WHEN** 原ResourceProviderDescriptor或支持contract集合在stage后被替换
**THEN** commit前核验拒绝且不发布；rollback/unregister沿原batch清理。同Registry保留stage快照，原resource_provider返回二元值保持。

#### Scenario: 消费只读元数据

**WHEN** 调用资源发现或修改所返回元数据
**THEN** 不调用acquire/release/reconcile/SecretPort，元数据不可变；prepare必需材料仍发前拒，不把元数据绿冒装配可用。

## Stages

- [x] 1. 唯一写权编码和独立正反例；各作者冻结。
- [x] 2. 主会话定向/核心/C1与产品回归，记录命令、退出码、数量和过程失败。
- [x] 3. 跨作者审查、状态/证据及本地检查点；完整材料保持PARTIAL。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| Identity | 同Registry原stage事实＋唯一active Host activation | provider自报owner、stage后换descriptor、跨环境/退役 | typed拒绝，不广告 |
| ACL | 独立resources read先检 | 仅runtime read也允许、拒权仍describe | typed拒且零调用 |
| Contract | 原C1注册、二元lookup/调用签名保持 | 新元数据API使未声明支持的旧provider无法注册 | 原路径回归必须通过；新视图拒未知 |
| Effects | metadata无provider对象/作用调用 | 发现时acquire或静默启服务 | 失败，M0/服务0 |
| Evidence | C/原生P/M分开记 | 元数据/受控fixture绿当装配或产品完成 | AT_014_PARTIAL，不开启capability |

## Validation

主会话使用本树上层 `.venv-ordessa-py312/bin/python`；新测试单文件、原CoreRegistry/C1/API合同与完整核心、产品回归串行。每条实际命令及数字写独立 evidence 和 status；缺生产资源不算可用。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_resource_provider_admission_view.py -q --tb=short
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment -q --tb=short
```

## DoD

源/反例/回归及失败账齐备、跨作者复核、明确只读范围及未实现的材料授权载体与ResourceRef路由；不改原断言、不skip、不push/主树合并。

## Acceptance

本单只能确认元数据准入切片。完整009材料/秘密获取与授权步骤仍未验收，不升级整产品状态。

## Batch report

退出码：定向21、核心/API307、产品788均exit0；过程失败退出码与原因在evidence保留。

门：同Registry/身份/ACL/旧C1兼容/零作用已受控验证。缺口：完整资源路由/受权获取/真实材料消费/秘密解析未实现，不当本片完成。

元数据窄切片验证：新增21P/exit0；核心＋集成＋公开API307P/exit0；产品788P/exit0，无skip。过程17P2F、306P1F、20P1F均保留evidence原因，原断言不改。证据`../evidence/agent-unit-model/resource-admission-metadata-20261006.md`；无秘密/材料作用/原生P/M，完整材料仍PARTIAL。费用unknown/token以平台账为准，无用户资源操作/push/主树合并。按用户继续不停要求，下一015已裁定材料扩展先纯合同、再原Operation授权及真实消费，不把本检查点当停工门。
