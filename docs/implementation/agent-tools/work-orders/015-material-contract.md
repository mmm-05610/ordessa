---
id: "015"
slug: "material-contract"
batch: "agent-core-material-contract-20261006"
baseline: "52607c1e80"
baseline_status: "approved-continuation"
state: "done"
depends_on: [{"order": "014", "condition": "本实施树固定SHA 52607c1e80，metadata21/coreAPI307/product788通过，用户已采用受权材料扩展"}]
write_paths: ["packages/backend/pacthold/src/pacthold/agents/materials.py", "packages/backend/pacthold/src/pacthold/agents/public.py", "packages/backend/pacthold/src/pacthold/core/resource_admission.py", "docs/implementation/agent-tools/evidence/agent-unit-model/test_material_contract.py", "docs/implementation/agent-tools/evidence/agent-unit-model/material-contract-20261006.md", "docs/implementation/agent-tools/status.md"]
forbidden: ["其他树/**", "用户数据/服务/凭据/全局配置", "C1 DTO/签名/Registry更改", "资源作用/Usage/Assembly接线", "新authority/authorizer/registry", "SecretPort/秘密正文", "wire/CLI/capability启用"]
ruling: "R-0004"
terminal: ["AT_015_CONTRACT_DONE", "AT_015_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012", "013", "014"]
parallel_units: ["core_impl仅材料module/public导出及core纯能力DTO；wire_impl仅新合同test文件，依冻结contract独立验证；core_review只读攻查"]
---
# AT-015 非秘密材料受权扩展纯合同

## Objective

按用户已采用的受权扩展与material-contract-v1.md，实现不可变类型及同一provider的可选端口；是材料链的phase1，后续继续原Operation/Step/Usage及真实消费，不以纯合同当产品完成。

## Current state

52607c1e80，前片元数据已受控验收，素材作用仍不可用。三名Luna已只读审方案，明确首目标精确planned Node、稳定资源与volatile activation分离、无新Authorizer、摘要无自指、证据与交付材料分型；新代码尚未落。

## Scope

以../material-contract-v1.md为精确实现权威。源/测试唯一写者，主会话唯一工单/状态/验证/Git。只本树；不调用provider作用、不建租约/Usage、不解析秘密、不改旧C1。

## Requirements

### Requirement: 闭合身份、摘要及结果

#### Scenario: 纯安全合同正例

**WHEN** 精确同环境ResourceRef、Host pin、planned Node/Directory/epoch/purpose与原操作关联DTO齐备
**THEN** strict camelCase roundtrip，输入摘要绑定resource/pin/target/descriptor而不自指；复制引用，不共享调用方或宿主对象。

#### Scenario: 不接受猜测或秘密载体

**WHEN** 跨环境/错pin/错版本/损坏digest/额外字段/bytes/callable/path或command载体、receipt/lease关联冲突、unknown带receipt或正文
**THEN** typed安全拒绝，诊断不反射原值，不产生资源效果；opaque合法字符串的隐藏语义不作无法证明的承诺。

### Requirement: 可选受权Protocol与旧C1兼容

#### Scenario: 能力存在及缺席

**WHEN** 原C1 provider同一对象显式声明完整版本能力/四方法或缺声明
**THEN** helper返回复制纯能力或typed unavailable；不调用material方法、旧acquire、SecretPort或Usage，不返回provider、不用Protocol存在冒支持。

### Requirement: 数据不是权限或真实消费

#### Scenario: planned Node与未知结果

**WHEN** DTO含planned Node/租约/证据引用/生命周期声明
**THEN** 不自证发布/授权/已消费，不签发Context；query请求无需lease/handle，unknown不猜成功，不触发查询或重发。

## Stages

- [x] 1. 两名Luna实现纯合同与独立正反例，第三名只读；作者冻结。
- [x] 2. 主会话串行新合同、旧核心/C1/API/材料拒绝门回归，记录全部失败/命令/退出/数量。
- [x] 3. 终审、证据/账本/本地检查点，继续下一phase而不停止；完整材料PARTIAL。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| Shape | 闭合strict深复制身份/摘要结果 | 额外payload、跨环境、digest自指、alias篡改 | typed拒绝 |
| Authorization | 端口仅原InvocationContext，DTO不代权 | 新Authorizer、Context序列化、planned Node自授 | 失败、不接作用 |
| Capability | 显式版本/方法，不fallback | 缺property但旧acquire填空、只Protocol名义支持 | typed unavailable |
| Effects | 所有作用/Store/Usage调用0 | 合同构造偷偷resolve/建租约/启daemon | 失败，M0/服务0 |
| Evidence | phase1仅单元/合同 | 当真实材料可用或整体DONE | 整体PARTIAL，phase2/3未验 |

## Validation

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_material_contract.py -q --tb=short
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
```

纯合同及public导出变更优先上述回归＋已有材料拒绝门；只有发现新影响/失败才扩大或重跑产品全套，不为重复绿无谓重跑。本阶段未改生产运行链。

## DoD

精确contract实现、独立反例、原拒绝门保持、原public/C1接口边界不变、过程账、清理/费用和未验范围。禁止断言删除/skip/legacy、新权限真值、push/main合并。

## Acceptance

只AT_015_CONTRACT_DONE，不把phase2持久授权/原步骤、phase3真实材料消费/寿命填绿。

## Batch report

门：纯合同/原C1及公开方向/材料拒绝回归通过；退出码：首1、复1、最终0；证据：material-contract-20261006.md，14P、307P、106P，不累计重复场景；缺口：持久材料/权限/Usage/owner消费与隔离真实服务仍未验，完整产品PARTIAL。依赖014在本树固定52607c1e80，不追移动分支。本片done仅AT_015_CONTRACT_DONE。
