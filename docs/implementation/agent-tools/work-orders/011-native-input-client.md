---
id: "011"
slug: "native-input-client"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "native-contracts-input-reservation-in-progress"
depends_on: [{"condition": "010与006授权接缝验收；不得豁免资源缺席", "order": "010"}]
write_paths: ["products/agent-tools/**","plugins/harness/**","packages/backend/pacthold/src/pacthold/agents/**"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0004"
terminal: ["AT_011_DONE", "AT_011_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012"]
parallelism: "none"
parallelism_reason: "先冻结本单合同及依赖，再按不交叉文件派切片"
---
# AT-011 持久输入及原生协议CLI使用/结果

## Objective

受控DraftCapture与单session creation reservation、InputAttempt持久claim，原生协议独立客户端，wait/inspect/result证据。

## Current state

2026-10-05继续原单：三家真实原生结构消费者修复已落源码；managed transport写屏障执行者31P。核心inputs.py在同OperationStore预留draft fence与dispatch claim，正在加真实SQLite反例及独立审阅，未验收。三家客户端未接CLI，生产capture/native owner、结果投影和断连恢复链未完成，managedInput能力保持false。不是AT_011_DONE。

## Scope

只写frontmatter本实施树；主会话独占合同/status/Git，其他树只读。跨域知识留本领域，不引入第二核心、通用翻译层或daemon。

## Requirements

### Requirement: 固定合同及实际证据

#### Scenario: 正向

**WHEN** 依赖/许可/资源实测具备
**THEN** 受控DraftCapture与单session creation reservation、InputAttempt持久claim，原生协议独立客户端，wait/inspect/result证据。

### Requirement: 缺席及未知不得假成功

#### Scenario: 反例或资源缺席

**WHEN** 未知换key重建session/重发，CLI退出没人持callback却detach，自动审批，raw socket冒observe
**THEN** 缺真实持有者仅wait或unsupported；模型未授权不调用；原生query不覆盖保持unknown。

## Stages

- [ ] 1. 冻结完整DTO/签名、真实owner/资源与本单精确pytest命令。
- [ ] 2. 实现最小正向与上述反例，不修改断言掩失败。
- [ ] 3. 主会话复跑，分账证据、成本、清理与未测范围。

## Parallel units

本单先串行；合同冻结后非交叉叶子/原生/客户端测试可派多agent，登记具体路径。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| B | 固定adce和依赖验证 | 移动branch/dirty源码 | 不消费 |
| P | 受控DraftCapture与单session creation reservation、InputAttempt持久claim，原生协议独立客户端，wait/inspect/result证据 | 未知换key重建session/重发，CLI退出没人持callback却detach，自动审批，raw socket冒observe | 缺真实持有者仅wait或unsupported；模型未授权不调用；原生query不覆盖保持unknown |
| E | 三类测试分账 | mock/材料当实物 | PARTIAL |

## Validation

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python /home/maoqh/.agents/skills/incremental-work-order/scripts/validate_order.py docs/implementation/agent-tools/work-orders --strict
git diff --check
```

上述只结构/资料；阶段1补本单精确测试，不计产品绿。模型/用户服务测试需另行授权，当前0调用。

## DoD

实际实现与反例证据；所有命令/退出/数量/限制记status。禁止push/main merge、全局设置与未经授权模型调用。

## Acceptance

全部门实测通过才AT_011_DONE；缺资源/未测则AT_011_PARTIAL。
