---
id: "005"
slug: "cli-public-client"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "partial-profile-cli-and-distribution-verified"
depends_on: [{"condition": "001公开wire冻结；Profile命令依赖003，节点命令依赖004", "order": "004"}]
write_paths: ["products/agent-tools/**"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0001"
terminal: ["AT_005_DONE", "AT_005_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004"]
parallel_units: ["CLI输出与失败测试独占products/agent-tools/tests/test_cli_contract.py和test_transport_failures.py，独立于client源码", "公开wire客户端只写products/agent-tools/src，独立于测试文件；主会话复跑完整验收"]
---
# AT-005 独立CLI发现、Profile与节点消费

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
**THEN** 独立wheel与ordessa-agent入口，doctor/capabilities/发现、Profile CRUD/preview、节点管理。稳定JSON/退出码，经本树真实隔离服务验；不注册插件、不创建daemon。

### Requirement: 证据不足不能报成功

#### Scenario: 资源缺席或未知作用

**WHEN** 出现反例或缺席资源
**THEN** 服务/版本缺席退出4，权限拒绝3，冲突5，unknown/partial6；缺资源不得以mock代替服务验收。

## Stages

- [ ] 1. 获准SHA/依赖核对，固定具体接口、测试命令与资源。
- [ ] 2. 按固定契约实现并验证正向/反例，保留失败记录。
- [ ] 3. 主会话复跑单测、契约与真实隔离范围，分别记账并给检查点。

## Parallel units

CLI输出与失败测试独占products/agent-tools/tests/test_cli_contract.py和test_transport_failures.py，独立于client源码; 公开wire客户端只写products/agent-tools/src，独立于测试文件；主会话复跑完整验收

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| B 基线与依赖 | 明确用户授权固定SHA且依赖实测通过 | 移动分支/dirty代码当baseline | BLOCKED，不执行产品变更 |
| P 行为 | 独立wheel与ordessa-agent入口，doctor/capabilities/发现、Profile CRUD/preview、节点管理。稳定JSON/退出码，经本树真实隔离服务验；不注册插件、不创建daemon。 | 版本不兼容、授权不足、断连、同key异输入、revision冲突、unknown自动重发、token进入argv/log、私有import。 | 服务/版本缺席退出4，权限拒绝3，冲突5，unknown/partial6；缺资源不得以mock代替服务验收。 |
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

AT_005_DONE仅当本单全部门实测通过；否则AT_005_PARTIAL并列精确缺口。目前已分阶段实施/验证，未满足本单全量DoD，不记DONE。

## 2026-10-04 检查点

doctor/Profile/3Skills/wheel/bundle已验证；节点/原生任务/结果查询命令未交付。 数量/退出码与原始证据见../status.md；当前不得使用本单DONE终态。
