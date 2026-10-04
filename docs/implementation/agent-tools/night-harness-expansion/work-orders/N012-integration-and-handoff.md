---
id: "N012"
slug: "integration-and-handoff"
batch: "agent-tools-native-030"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved-base-with-uncommitted-implementation"
depends_on: [{"order":"N001","condition":"本夜快照及接缝前置明确，未知前置不宣称运行验收"}]
write_paths: ["plugins/harness/**", "products/agent-tools/**", "docs/implementation/agent-tools/night-harness-expansion/**"]
forbidden: ["其他树/**", "用户数据/认证/全局配置", "packages/backend/**", "apps/desktop/**", "真实模型调用", "push/main merge"]
ruling: "R-0001"
terminal: ["N012_DONE", "N012_PARTIAL", "N012_BLOCKED"]
waive: []
parallelism: "none"
parallelism_reason: "共享接缝、Git及总验收由唯一执行者串行处理"
---
# N012 · 十家整合、独立分发与明晨交接

## Objective

合并可验证切片，安装实际wheel核命令与生成目录，形成十家真实分账报告而非十家全绿口号。

## Current state

原bundle仅0.1.0a2 init/Profile快照；新适配是否进入安装包、运行与恢复都需本单实测，不能沿用原260P计数。 本包材料准备时HEAD为adce734db21945181bf93da9720158d05e957654，有原执行者未提交成果。执行前重测，不沿用旧测试计数。依据030与原实施status，不声称本单已实现。

## Scope

独占共享CLI/schema/registry/catalog生成、产品测试打包文档；不得改核心协议/旧标识。子代理产物由主执行者复跑后纳入，失败原ID登记不删除。 docs/implementation/agent-tools/night-harness-expansion/README.md定义本批执行纪律。遵守028/029唯一核心、配置owner、授权与unknown规则；不新增协议业务语义、不造第二注册/状态账、不执行模型。共享入口由主执行者独占。

## Requirements

### Requirement: 本单可观察交付

#### Scenario: 正向及前置核实

**WHEN** 十家均已给明确研究/代码/原生验证/阻塞结论，至少一条已批准真实接入链可运行；若无则仅整合资料并保持BLOCKED
**THEN** fresh client安装实际wheel并通过公开入口使用已接入家族，未支持/未授权显式拒绝；给十家矩阵、精确命令和缺口及明晨验收步骤

### Requirement: 原生身份与未知边界不可丢失

#### Scenario: 反例及资源缺席

**WHEN** 代码没进wheel、模拟进程当真实上游、未支持新命令硬报成功、fixture合计成产品全绿、丢失继承失败
**THEN** 测试必须抓到错误；不宣称ready，不重发，不假completed。未测或权限缺失保留PARTIAL/BLOCKED，继续其他不依赖项。

## Stages

- [x] 1. 逐家复核证据、损失/不支持面与许可；同步唯一catalog生成镜像，移除假ready声明但不删原家族（主执行者阶段检查点，精确路径提交）— 10份decision.md+矩阵逐家复核；catalog生成器验证 exit0（8家族镜像一致，无假ready声明可移除——全部runtimeReady语义本为否定）；5新家族registry块**defer登记**（需dialect/物化合同冻结，P-A②等价pin先例，见status待决）；原7+qwen家族未删
- [x] 2. 真实fresh client wheel安装，接口/冲突/unknown/恢复/跨node隔离反例复跑，记录每类回归和固定继承失败（主执行者阶段检查点，精确路径提交）— wheel 0.1.0a2 fresh venv安装+init/doctor实测（G10零宿主内部依赖）；native_clients反例146P/0F、家族驱动86P+49P；固定继承失败4F记录于docs/known-issues.md
- [x] 3. 列产品能力/每家L0–L4/安装清理/调用花费/未测项；打不覆盖tag，给明晨操作与授权清单（主执行者阶段检查点，精确路径提交）— `evidence/N012-family-matrix.xlsx`（4表）+status.md终账（成本0/清理/明晨5步/待授权清单）；tag checkpoint/agent-tools-native-030-N012（不覆盖既有tag）

## Parallel units

本单串行，不同时改共享合同、schema、registry、CLI入口和总账。
主执行者冻结具体文件写权后才允许执行；不共享安装/全测试slot；子代理不写Git/status，不再开子代理。主执行者复跑结果。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| BASE | 真正源码快照与前置准确 | 旧HEAD当dirty全成果、借别人未验代码 | 不运行依赖，记BLOCKED |
| NATIVE | fresh client安装实际wheel并通过公开入口使用已接入家族，未支持/未授权显式拒绝；给十家矩阵、精确命令和缺口及明晨验收步骤 | 代码没进wheel、模拟进程当真实上游、未支持新命令硬报成功、fixture合计成产品全绿、丢失继承失败 | 未测证据不能算通过，PARTIAL |
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

全部本单范围门实测通过才N012_DONE，并标具体L0–L4及家族产品终态；否则N012_PARTIAL或N012_BLOCKED＋精确缺口。不将工单DONE冒充整体PRODUCT_VERIFIED。批次整体真实任务门未测仍PARTIAL。

## Batch report

终态 **N012_PARTIAL**（整合/分发/矩阵/交接齐；L2真实任务门未测→按acceptance批次整体PARTIAL）。

- 门：BASE✓（快照链完整） NATIVE（fresh wheel公开入口可用✓；接入家族使用=适配层可导入可调用，运行接纳依赖阻塞） SAFETY✓（safety-reviewer全批复查+2严重7中低修复+遗留登记） EVIDENCE✓（十家L0-L4分账矩阵、不累加DONE）。
- 反例计数：native_clients 146用例＋驱动 86+49+64等（含安全钉测11例）；产品全量 402P/0F。
- 命令/退出码：validate_order 12/12 OK exit0；git diff --check exit0；generate_harness_catalog verify exit0；pip wheel+fresh install+init exit0。
- 证据路径：evidence/N012-family-matrix.xlsx、N012-safety-review.md、status.md终账、各 *-decision.md。
- 源码SHA：至 20be628540 + 本单提交；tag `checkpoint/agent-tools-native-030-N012`。
- 清理：/tmp scratch（pi/codex/wheel/fresh/matrix-png）收尾删除；真实~/.pi/~/.codex/~/.vibe零接触。
- 调用成本：真实模型0；安装0（LibreOffice因sudo/apt授权边界未装，登记待授权）；文档WebFetch约12次。
- 未测项：L2全运行面（pi partial除外）、L3/L4；registry登记defer；安全遗留3项。

