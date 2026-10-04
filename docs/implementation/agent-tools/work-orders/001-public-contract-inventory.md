---
id: "001"
slug: "public-contract-inventory"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "profile-face-verified-native-contracts-open"
depends_on: [{"condition": "基线与切换方式明确获准；028 V2.1设计摘要复核；固定tree SHA adce734db21945181bf93da9720158d05e957654", "order": "BASELINE"}]
write_paths: ["docs/implementation/agent-tools/**"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0001"
terminal: ["AT_001_DONE", "AT_001_PARTIAL"]
waive: []
serialize_with: ["002", "003", "004", "005"]
parallel_units: ["核心/持久端口只读盘点，独立于Harness/目录和wire盘点", "Harness/目录只读盘点，独立于核心与wire盘点", "CLI wire只读盘点，独立于核心与Harness盘点"]
---
# AT-001 固定公开消费合同与缺口

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
**THEN** 对固定源码导出、wire/schema、认证、版本协商、发现、局部配置与输入查询逐项给源码和测试定位；未决语义报告，不自创新协议。

### Requirement: 证据不足不能报成功

#### Scenario: 资源缺席或未知作用

**WHEN** 出现反例或缺席资源
**THEN** 端口或契约缺席标GAP；冻结前不启用相关消费路径。

## Stages

- [ ] 1. 获准SHA/依赖核对，固定具体接口、测试命令与资源。
- [ ] 2. 按固定契约实现并验证正向/反例，保留失败记录。
- [ ] 3. 主会话复跑单测、契约与真实隔离范围，分别记账并给检查点。

## Parallel units

核心/持久端口只读盘点，独立于Harness/目录和wire盘点; Harness/目录只读盘点，独立于核心与wire盘点; CLI wire只读盘点，独立于核心与Harness盘点

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| B 基线与依赖 | 明确用户授权固定SHA且依赖实测通过 | 移动分支/dirty代码当baseline | BLOCKED，不执行产品变更 |
| P 行为 | 对固定源码导出、wire/schema、认证、版本协商、发现、局部配置与输入查询逐项给源码和测试定位；未决语义报告，不自创新协议。 | 旧服务包装新API、裸名称跨服务路由、私有模块导入均不得被登记为支持。 | 端口或契约缺席标GAP；冻结前不启用相关消费路径。 |
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

AT_001_DONE仅当本单全部门实测通过；否则AT_001_PARTIAL并列精确缺口。目前已分阶段实施/验证，未满足本单全量DoD，不记DONE。

## 2026-10-04 检查点

Profile、Directory与具名step存储合同已冻结；Invocation基础在008A，RuntimeProvider宿主接纳继续核实。 数量/退出码与原始证据见../status.md；当前不得使用本单DONE终态。
