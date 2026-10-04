---
id: "012"
slug: "release-acceptance"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "queued-on-dependencies"
depends_on: [{"condition": "011与006授权接缝验收；不得豁免资源缺席", "order": "011"}]
write_paths: ["products/agent-tools/**","docs/implementation/agent-tools/**"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0004"
terminal: ["AT_012_DONE", "AT_012_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012"]
parallelism: "none"
parallelism_reason: "先冻结本单合同及依赖，再按不交叉文件派切片"
---
# AT-012 完整CLI三Skill安装与阶段验收

## Objective

最终CLI/Skill命令一致，isolated wheel/bundle＋服务实物，单测/契约/真实进程/真实模型分账，安装命令/示例/验收明确。

## Current state

当前未开执行；公开Profile数据切片可用不证明本单成立。具体缺口来自028 V2.1及固定源码，不能自创新协议。

## Scope

只写frontmatter本实施树；主会话独占合同/status/Git，其他树只读。跨域知识留本领域，不引入第二核心、通用翻译层或daemon。

## Requirements

### Requirement: 固定合同及实际证据

#### Scenario: 正向

**WHEN** 依赖/许可/资源实测具备
**THEN** 最终CLI/Skill命令一致，isolated wheel/bundle＋服务实物，单测/契约/真实进程/真实模型分账，安装命令/示例/验收明确。

### Requirement: 缺席及未知不得假成功

#### Scenario: 反例或资源缺席

**WHEN** 材料/fixture称产品完成，缺资源绿，全局偷偷安装，私有imports或旧compat绕核心
**THEN** 未跑清楚标注，不报整产品DONE；MCP留后续不阻CLI＋Skill。

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
| P | 最终CLI/Skill命令一致，isolated wheel/bundle＋服务实物，单测/契约/真实进程/真实模型分账，安装命令/示例/验收明确 | 材料/fixture称产品完成，缺资源绿，全局偷偷安装，私有imports或旧compat绕核心 | 未跑清楚标注，不报整产品DONE；MCP留后续不阻CLI＋Skill |
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

全部门实测通过才AT_012_DONE；缺资源/未测则AT_012_PARTIAL。
