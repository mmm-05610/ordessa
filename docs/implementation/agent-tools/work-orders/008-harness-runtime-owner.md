---
id: "008"
slug: "harness-runtime-owner"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "invocation-foundation-verified-native-absent"
depends_on: [{"condition": "同journal具名claim存储基础实测", "order": "007"}, {"condition": "目录授权签发/重核基础实测；生产资源仍需显式提供", "order": "006"}]
write_paths: ["plugins/harness/**","packages/backend/pacthold/src/pacthold/agents/**","products/agent-tools/tests/integration/test_invocation_authority.py"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0005"
terminal: ["AT_008_DONE", "AT_008_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012"]
parallelism: "none"
parallelism_reason: "先冻结本单合同及依赖，再按不交叉文件派切片"
---
# AT-008 Harness原生单元/会话目标及core correlation

## Objective

RuntimeProvider版本化端口、Unit/Session显式目标、InvocationContext、原生owner作用前固定core correlation、queryStep覆盖与独立证据。

## Current state

已完成只读接缝核查，InvocationContext授权来源获R-0005批准，具体最小基础合同已冻结于../invocation-authority-proposal.md；AT-008A仅实施invocation.py及隔离合同测试，不触Harness作用。旧ApplicationTarget/Confirmed/native evidence与journal排他索引均绑定session，需要带kind目标迁移；不能随机session占位。公开Profile数据切片可用不证明本单成立。

## Scope

只写frontmatter本实施树；主会话独占合同/status/Git，其他树只读。跨域知识留本领域，不引入第二核心、通用翻译层或daemon。

## Requirements

### Requirement: 固定合同及实际证据

#### Scenario: 正向

**WHEN** 依赖/许可/资源实测具备
**THEN** RuntimeProvider版本化端口、Unit/Session显式目标、InvocationContext、原生owner作用前固定core correlation、queryStep覆盖与独立证据。

### Requirement: 缺席及未知不得假成功

#### Scenario: 反例或资源缺席

**WHEN** 随机/草稿session充RuntimeConfirmed，PreparedMap丢失=零作用，core与Harness双journal，未持久mapping便start
**THEN** 缺可信目标/InvocationContext/恢复覆盖拒绝，无真实模型授权不调用。

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
| P | RuntimeProvider版本化端口、Unit/Session显式目标、InvocationContext、原生owner作用前固定core correlation、queryStep覆盖与独立证据 | 随机/草稿session充RuntimeConfirmed，PreparedMap丢失=零作用，core与Harness双journal，未持久mapping便start | 缺可信目标/InvocationContext/恢复覆盖拒绝，无真实模型授权不调用 |
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

全部门实测通过才AT_008_DONE；缺资源/未测则AT_008_PARTIAL。

## AT-008A 执行单元

写权仅core agents/invocation.py与products测试test_invocation_authority.py；主会话独占合同/status，两个审阅者只读。显式可信Authority/CurrentState＋实际SQLite OperationStore；对象身份绑定、有限ticket、一资格消费、并发与重入拒、固定授权binding、当前读许可与受限Cleanup。不增加网络协议或核心执行账。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_invocation_authority.py -q
```

只有合同基础；生产authority/provider/目录取证、transport fence及native journal尚未满足，本单保持PARTIAL。AT-008B迁移准备见../harness-target-migration.md，缺scope映射拒作用，尚未执行用户数据迁移。

AT-008A基础主会话全目录240P exit0；本单53项authority合同，生产接线/native作用缺席。不得记AT_008_DONE；独立复查结论后续追加status。
