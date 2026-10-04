---
id: "003"
slug: "profiles-and-providers"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "partial-profile-data-verified"
depends_on: [{"condition": "002真实持久接缝验收；001完整Configuration/Material端口冻结", "order": "002"}]
write_paths: ["packages/backend/pacthold/src/pacthold/agents/**", "packages/backend/pacthold/tests/**", "plugins/harness/**", "plugins/skills/**", "plugins/model-provider/**"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0001"
terminal: ["AT_003_DONE", "AT_003_PARTIAL"]
waive: []
serialize_with: ["001", "002", "004", "005"]
parallel_units: ["Harness侧适配只写plugins/harness，独立于叶子材料适配", "叶子材料适配只写已固定插件目录，独立于Harness；共同契约由主会话先冻结"]
---
# AT-003 核心Profile清单与叶子交接

## Objective

基线已获准；按依赖逐单解除执行门；遵循R-0001及029 plan。

## Current state

当前固定基线为adce734db21945181bf93da9720158d05e957654；用户go已获准。028契约是拟议设计，不是已有导出。依据见../baseline-review.md。

## Scope

写权见frontmatter，仅在本树使用。主会话独占合同/status/Git；其他树只读。所有客户端、Skill、产品测试与分发只进products/agent-tools。保留持久标识与原生协议；不做Desktop/MCP入口/环境编排/DAG/团队，不恢复legacy可写链。

## Requirements

### Requirement: 可核实的实际交付

#### Scenario: 正向与故障都能复现

**WHEN** 获准基线与依赖都具备，执行本单范围
**THEN** 双revision CAS与不可变清单；preview纯读；可信贡献generation；叶子解释schema与显式引用，核心组织纯编译，Harness保持唯一配置owner。实际叶子路径按固定基线确认，MCP/Prompt缺席不造占位。

### Requirement: 证据不足不能报成功

#### Scenario: 资源缺席或未知作用

**WHEN** 出现反例或缺席资源
**THEN** 可保存unresolved定义；不能准备不可用节点；optional只显式省略并记录。

## Stages

- [ ] 1. 获准SHA/依赖核对，固定具体接口、测试命令与资源。
- [ ] 2. 按固定契约实现并验证正向/反例，保留失败记录。
- [ ] 3. 主会话复跑单测、契约与真实隔离范围，分别记账并给检查点。

## Parallel units

Harness侧适配只写plugins/harness，独立于叶子材料适配; 叶子材料适配只写已固定插件目录，独立于Harness；共同契约由主会话先冻结

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| B 基线与依赖 | 明确用户授权固定SHA且依赖实测通过 | 移动分支/dirty代码当baseline | BLOCKED，不执行产品变更 |
| P 行为 | 双revision CAS与不可变清单；preview纯读；可信贡献generation；叶子解释schema与显式引用，核心组织纯编译，Harness保持唯一配置owner。实际叶子路径按固定基线确认，MCP/Prompt缺席不造占位。 | rename改配方、Profile编辑自动apply、provider缺席当空材料、optional静默忽略、preview暗启进程。 | 可保存unresolved定义；不能准备不可用节点；optional只显式省略并记录。 |
| E 证据 | 单测、契约、隔离服务分别报告 | 材料/mocks称产品完成 | PARTIAL，未跑项不计通过 |

## Validation

```bash
python3 /home/maoqh/.agents/skills/incremental-work-order/scripts/validate_order.py docs/implementation/agent-tools/work-orders --strict
git diff --check
git status --short
```

以上仅工单结构检查；具体产品命令在阶段1按获准基线的测试入口记录，不能把此检查计作产品测试。

## DoD

实现、定向正反例、真实环境证据、回归数量/退出码、费用与清理、status分账齐全。模型未授权范围保持untested。每阶段记录改动/命令/退出码/数量/已知问题/未测；基线批准后才按路径提交检查点，不push/main merge。

## Acceptance

AT_003_DONE仅当本单全部门实测通过；否则AT_003_PARTIAL并列精确缺口。目前已分阶段实施/验证，未满足本单全量DoD，不记DONE。

## 2026-10-04 检查点

Profile纯数据及隔离服务通过；完整Configuration/Material/Runtime提供者接纳缺席，preview仍unresolved。 数量/退出码与原始证据见../status.md；当前不得使用本单DONE终态。
