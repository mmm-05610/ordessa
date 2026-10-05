---
id: "010"
slug: "node-publication-management"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "publication-foundation-in-progress"
depends_on: [{"condition": "009与006授权接缝验收；不得豁免资源缺席", "order": "009"}]
write_paths: ["packages/backend/pacthold/src/pacthold/agents/**","apps/server/**","products/agent-tools/src/**"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0004"
terminal: ["AT_010_DONE", "AT_010_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012"]
parallelism: "none"
parallelism_reason: "先冻结本单合同及依赖，再按不交叉文件派切片"
---
# AT-010 节点准备、原子发布与stop/recover

## Objective

完整DirectoryBinding＋ProfileRef，单operation steps，core-owned稳定ParticipantInstanceRef，原子binding/Usage/终态，真实配置owner投影与epoch fence。

## Current state

2026-10-05继续原单：NodePublication内部primitive复用ParticipantInstanceRef、既有OperationStore/Usage及同SQLite原子发布，执行者20P、主会话含接纳/Invocation组合94P exit0。完整Profile manifest核验、生产NodeEvidencePort、实际prepare/start/stop/recover与public wire尚缺，nodes能力保持false。不是AT_010_DONE。

## Scope

只写frontmatter本实施树；主会话独占合同/status/Git，其他树只读。跨域知识留本领域，不引入第二核心、通用翻译层或daemon。

## Requirements

### Requirement: 固定合同及实际证据

#### Scenario: 正向

**WHEN** 依赖/许可/资源实测具备
**THEN** 完整DirectoryBinding＋ProfileRef，单operation steps，core-owned稳定ParticipantInstanceRef，原子binding/Usage/终态，真实配置owner投影与epoch fence。

### Requirement: 缺席及未知不得假成功

#### Scenario: 反例或资源缺席

**WHEN** 同home/alias两node假独立，commit失败ready，latest冒历史，stop回执忽略迟到apply，ttl冒transport fence
**THEN** 不足拒节点/lease；unknown保留目标和资源，不重装最新材料。

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
| P | 完整DirectoryBinding＋ProfileRef，单operation steps，core-owned稳定ParticipantInstanceRef，原子binding/Usage/终态，真实配置owner投影与epoch fence | 同home/alias两node假独立，commit失败ready，latest冒历史，stop回执忽略迟到apply，ttl冒transport fence | 不足拒节点/lease；unknown保留目标和资源，不重装最新材料 |
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

全部门实测通过才AT_010_DONE；缺资源/未测则AT_010_PARTIAL。
