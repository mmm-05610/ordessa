---
id: "N001"
slug: "foundation-and-snapshot"
batch: "agent-tools-native-030"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved-base-with-uncommitted-implementation"
depends_on: []
write_paths: ["plugins/harness/**", "products/agent-tools/**", "docs/implementation/agent-tools/night-harness-expansion/**"]
forbidden: ["其他树/**", "用户数据/认证/全局配置", "packages/backend/**", "apps/desktop/**", "真实模型调用", "push/main merge"]
ruling: "R-0001"
terminal: ["N001_DONE", "N001_PARTIAL", "N001_BLOCKED"]
waive: []
parallelism: "none"
parallelism_reason: "共享接缝、Git及总验收由唯一执行者串行处理"
---
# N001 · 收口源码快照、核前置、冻结适配接缝

## Objective

先保证夜间消费的是实际成果，明确同一核心、原生carrier与配置owner接缝；资料盘点可完成，运行前置缺失不得掩盖。

## Current state

CLI源码只读见init/Profile入口，native_clients目录未存在；原status报告AT-013初步完成，nodes/tasks仍缺。不得由用户“初步完成”推断运行接缝已完成。 本包材料准备时HEAD为adce734db21945181bf93da9720158d05e957654，有原执行者未提交成果。执行前重测，不沿用旧测试计数。依据030与原实施status，不声称本单已实现。

## Scope

只核查既有原队列008–012已批准工作与carrier公开合同；核心若未交付继续原队列，030自身不能绕过或扩大核心写权。本单可写Harness/products内既定接缝的必要测试与冻结材料。 docs/implementation/agent-tools/night-harness-expansion/README.md定义本批执行纪律。遵守028/029唯一核心、配置owner、授权与unknown规则；不新增协议业务语义、不造第二注册/状态账、不执行模型。共享入口由主执行者独占。

## Requirements

### Requirement: 本单可观察交付

#### Scenario: 正向及前置核实

**WHEN** 原执行者确认无人竞争本树、收口属于自己的原成果、记录准确源码SHA/dirty摘要并检查原队列依赖
**THEN** 写出已存在/缺失公开签名、provider注册/原生session/配置owner/input/fence接缝表；有真实证据才开放后续运行，缺口登记而研究可继续

### Requirement: 原生身份与未知边界不可丢失

#### Scenario: 反例及资源缺席

**WHEN** 重复core/registry、裸CLI绕owner、假session、未经实际fence就发新lease、运行依赖没交付
**THEN** 测试必须抓到错误；不宣称ready，不重发，不假completed。未测或权限缺失保留PARTIAL/BLOCKED，继续其他不依赖项。

## Stages

- [ ] 1. 核Git/status/原队列写权，确认原成果来源并建立本夜源码快照，不stash或巻入别人改动（主执行者阶段检查点，精确路径提交）
- [ ] 2. 盘点已有家族和新家族id，不删原8项；冻结最小接缝与目录owner，整理许可/版本/授权门（主执行者阶段检查点，精确路径提交）
- [ ] 3. 亲跑一个可得家族的隔离纵向入口；没有原生接纳则登记依赖、后续仅研究/协议代码，整包PARTIAL（主执行者阶段检查点，精确路径提交）

## Parallel units

本单串行，不同时改共享合同、schema、registry、CLI入口和总账。
主执行者冻结具体文件写权后才允许执行；不共享安装/全测试slot；子代理不写Git/status，不再开子代理。主执行者复跑结果。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| BASE | 真正源码快照与前置准确 | 旧HEAD当dirty全成果、借别人未验代码 | 不运行依赖，记BLOCKED |
| NATIVE | 写出已存在/缺失公开签名、provider注册/原生session/配置owner/input/fence接缝表；有真实证据才开放后续运行，缺口登记而研究可继续 | 重复core/registry、裸CLI绕owner、假session、未经实际fence就发新lease、运行依赖没交付 | 未测证据不能算通过，PARTIAL |
| SAFETY | 隔离home/realm、无认证继承、仅owned清理 | auto-approve、读取全局Token、pkill借用进程 | 发前拒，登记待授权 |
| EVIDENCE | L0–L4/回归/安装/清理独立分账 | fixture当真实进程、握手当任务成功 | PARTIAL，不累加DONE |

## Validation

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python /home/maoqh/.agents/skills/incremental-work-order/scripts/validate_order.py docs/implementation/agent-tools/night-harness-expansion/work-orders --strict
git diff --check
```

以上仅资料门。阶段1由主执行者在本账写本单实际定向测试文件、命令、反例命令、退出码与计数；必须可复跑且文件缺席报失败，不用“pytest零发现”冒成功。当前产品测试未跑，真实模型预算0。

## DoD

实现/定向反例/实际上游证据/回归计数与退出码/账务清理/产品状态六项齐；每家记录实际通道与版本、残余未知、下一步。资料工单不替代运行门；没有原生实际验证或前置即PARTIAL。

## Acceptance

全部本单范围门实测通过才N001_DONE，并标具体L0–L4及家族产品终态；否则N001_PARTIAL或N001_BLOCKED＋精确缺口。不将工单DONE冒充整体PRODUCT_VERIFIED。批次整体真实任务门未测仍PARTIAL。

## Batch report

阶段结束填：门与反例计数、命令/退出码、证据路径、源码SHA、清理、调用成本、未测项。阶段复选框不得提前勾选。

