---
id: "004"
slug: "directory-and-node-lifecycle"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "waiting-directory-operation-and-runtime-provider"
depends_on: [{"condition": "003清单/provider验收；001DirectoryBinding、管理wire与授权合同冻结", "order": "003"}]
write_paths: ["packages/backend/pacthold/src/pacthold/agents/**", "packages/backend/pacthold/tests/**", "plugins/harness/**", "plugins/workspace/**", "apps/server/**"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0001"
terminal: ["AT_004_DONE", "AT_004_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "005"]
parallelism: "none"
parallelism_reason: "共享核心合同、事务或跨层接缝，先由主会话串行完成"
---
# AT-004 非Chat节点准备与管理纵向链

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
**THEN** 非Chat消费者固定Profile和DirectoryBinding准备真实节点、query/configuration/stop/recover；真实目标排他、权限闭包、lease运输fence、恢复同node与历史，配置只来自Harness owner。

### Requirement: 证据不足不能报成功

#### Scenario: 资源缺席或未知作用

**WHEN** 出现反例或缺席资源
**THEN** 缺目录授权/目标隔离/恢复资产明确拒绝；unknown保留资源与reservation。模型启动风险未授权拒绝。

## Stages

- [ ] 1. 获准SHA/依赖核对，固定具体接口、测试命令与资源。
- [ ] 2. 按固定契约实现并验证正向/反例，保留失败记录。
- [ ] 3. 主会话复跑单测、契约与真实隔离范围，分别记账并给检查点。

## Parallel units

本单核心步骤串行；子代理仅做只读独立复核。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| B 基线与依赖 | 明确用户授权固定SHA且依赖实测通过 | 移动分支/dirty代码当baseline | BLOCKED，不执行产品变更 |
| P 行为 | 非Chat消费者固定Profile和DirectoryBinding准备真实节点、query/configuration/stop/recover；真实目标排他、权限闭包、lease运输fence、恢复同node与历史，配置只来自Harness owner。 | 同路径不同host、symlink共享home、假session、TTL当fence、stop后迟到apply、以latest替旧历史。 | 缺目录授权/目标隔离/恢复资产明确拒绝；unknown保留资源与reservation。模型启动风险未授权拒绝。 |
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

AT_004_DONE仅当本单全部门实测通过；否则AT_004_PARTIAL并列精确缺口。目前已分阶段实施/验证，未满足本单全量DoD，不记DONE。

## 2026-10-04 检查点

Directory(006)、具名step(007)、RuntimeProvider及配置owner交接全部有证据才启用节点。 数量/退出码与原始证据见../status.md；当前不得使用本单DONE终态。
