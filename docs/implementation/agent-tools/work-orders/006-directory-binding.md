---
id: "006"
slug: "directory-binding"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "foundation-verified-production-absent"
depends_on: [{"condition": "既有依赖的已验证基础切片；不豁免未完成原生门", "order": "001"}]
write_paths: ["plugins/workspace/**","products/agent-tools/tests/integration/test_directory_binding.py"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0004"
terminal: ["AT_006_DONE", "AT_006_PARTIAL"]
waive: []
serialize_with: ["002", "003", "004", "005"]
parallelism: "none"
parallelism_reason: "合同先冻结；主会话与执行者分路径，不并写同一核心合同"
---
# AT-006 Workspace目录授权交接

## Objective

R0004显式authority纯授权；同store原子issue；完整Ref/项目revision/realm/dev-inode/许可重核；缺端口不授execute。

## Current state

20项真实临时Workspace DB/同Store/目录事实测试通过；生产realm映射、宿主接纳、wire及节点use-site未接入，不记AT_006_DONE。

## Scope

只写frontmatter本树路径；主会话独占合同/status/Git，其他树只读。无真实模型调用。

## Requirements

### Requirement: 固定公开合同先行

#### Scenario: 正向与故障可复现

**WHEN** 本单合同和可选端口已冻结
**THEN** R0004显式authority纯授权；同store原子issue；完整Ref/项目revision/realm/dev-inode/许可重核；缺端口不授execute。

### Requirement: 不伪造资源与保证

#### Scenario: 缺资源或未知结果

**WHEN** 缺authority/host证据/DirectoryBinding明确拒，绝不改用户目录
**THEN** 保留证据并返回typed拒绝，不自动重发，不隐藏测试失败。

## Stages

- [ ] 1. DTO/端口冻结与来源核实。
- [ ] 2. 定向实现及真实临时SQLite/文件系统反例。
- [ ] 3. 主会话复跑与status记录。

## Parallel units

本单合同串行；存储与Workspace不同文件可并行实现。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| B | 消费固定adce及R0004 | dirty/moving branch | 不消费 |
| P | R0004显式authority纯授权；同store原子issue；完整Ref/项目revision/realm/dev-inode/许可重核；缺端口不授execute | Bearer或OS.access代替execute许可、同path跨host、过期自动续租、alias变更、项目归档仍用 | 缺authority/host证据/DirectoryBinding明确拒，绝不改用户目录 |
| E | 命令/退出码/数量/未测分账 | fixture称原生完成 | PARTIAL |

## Validation

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest products/agent-tools/tests/integration/test_directory_binding.py -q
git diff --check
```

资源缺席计失败/未测，不skip。命令、退出码、数量留status及evidence。

## DoD

实现与反例通过；核心/真实service/原生范围各自证据，不混称。仅同核心/既有服务，不改外树、不push/main merge。

## Acceptance

全部门实测通过才AT_006_DONE；缺生产接纳/原生证据则AT_006_PARTIAL。

## 本轮精确验证

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_directory_binding.py -q
```

主会话全目录联跑及退出码/类别/限制记status；本单不豁免上层生产保证。
