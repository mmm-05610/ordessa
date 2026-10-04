---
id: "N007"
slug: "qwen-native-channel"
batch: "agent-tools-native-030"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved-base-with-uncommitted-implementation"
depends_on: [{"order":"N001","condition":"源码快照与接缝冻结已记录；资料/协议代码可先行，运行要求原队列真实接纳/input/fence门通过"}]
write_paths: ["plugins/harness/**", "products/agent-tools/**", "docs/implementation/agent-tools/night-harness-expansion/**"]
forbidden: ["其他树/**", "用户数据/认证/全局配置", "packages/backend/**", "apps/desktop/**", "真实模型调用", "push/main merge"]
ruling: "R-0001"
terminal: ["N007_DONE", "N007_PARTIAL", "N007_BLOCKED"]
waive: []
parallel_units: ["qwen-driver：仅N001钉定的本家族Harness驱动/配置与本家族测试，独立于客户端；公开合同只读","qwen-client：仅products内本家族原生消费者及其测试，独立于驱动，不写主CLI/registry/schema；合同只读"]
---
# N007 · Qwen Code原生通道接入

## Objective

接入Qwen Code的实际工作引擎，优先比较比较官方qwen serve HTTP/SSE、SDK与原生ACP，不是名称发现；用已冻结核心接缝发布实际使用/管理入口。

## Current state

官方资料已查：[正文](https://github.com/QwenLM/qwen-code/blob/main/docs/developers/architecture.md)，执行时钉release/SHA、许可、artifact/协议/SDK版本。本机该家族runtime尚未由本包验证。 本包材料准备时HEAD为adce734db21945181bf93da9720158d05e957654，有原执行者未提交成果。执行前重测，不沿用旧测试计数。依据030与原实施status，不声称本单已实现。

## Scope

家族qwen的Harness驱动、配置编译与消费者原生客户端/测试。N001先绑定准确现有目录，若新增目录记录在接缝表，不并存旧新两个写owner。共享catalog/registry/schema生成仅主执行者同步；原家族id存在则保持。 docs/implementation/agent-tools/night-harness-expansion/README.md定义本批执行纪律。遵守028/029唯一核心、配置owner、授权与unknown规则；不新增协议业务语义、不造第二注册/状态账、不执行模型。共享入口由主执行者独占。

## Requirements

### Requirement: 本单可观察交付

#### Scenario: 正向及前置核实

**WHEN** N001冻结的协议入口可用，且Qwen Code固定版本/许可/隔离启动方式已核实；运行验证另要求原生接纳前置已通过
**THEN** 实现实际qwen通道、实例隔离和唯一配置owner绑定；保留原生payload/回调/扩展，fixture反例与真实进程结果分别记录，缺认证/安装不发布runtimeReady

### Requirement: 原生身份与未知边界不可丢失

#### Scenario: 反例及资源缺席

**WHEN** serve与ACP谁持有workspace/runtime/权限；serve源码可能设计与实现不同；不让桥创建第二会话账，不把CLI输出当完整管理面。 另注入陌生event、失回执、重放callback、两node事件交叉和缺必需配置
**THEN** 测试必须抓到错误；不宣称ready，不重发，不假completed。未测或权限缺失保留PARTIAL/BLOCKED，继续其他不依赖项。

## Stages

- [x] 1. 核官方/上游源码和各候选通道，形成qwen决策报告与固定版本/许可；serve与ACP谁持有workspace/runtime/权限；serve源码可能设计与实现不同；不让桥创建第二会话账，不把CLI输出当完整管理面。— `evidence/qwen-decision.md`（家族单元产出+主执行者复核）：主通道`qwen serve`环回HTTP+SSE；归属钉定serve daemon持workspace/runtime、权限经客户端显式HTTP投票（无auto-approve）；**源码vs文档差异2项已登记**（prompt 202多`eventEpoch`字段；文档v0.16-alpha vs 包0.24.7漂移）；CLI stdout不当管理面
- [x] 2. 沿冻结接缝实现驱动与消费者，不重写agent loop；发前校验材料适用性、隔离home、权限、shared scope和请求关联 — `native_clients/qwen.py`（LoopbackHttpChannel）+`qwen/native_channel.py`；相对workspace发前拒、sessionScope/thread不建第二账
- [x] 3. 定向协议反例＋实际无模型进程验证可做部分；审批/取消/恢复/失回执/unknown扩展逐项核实，不把fixture当原生；回填矩阵与检查点 — 32用例（非环回拒、SSE未知保留、500不重发、投票前计数0、attached不伪造）；L2=未测（无本机CLI）

## Parallel units

- qwen-driver：仅N001钉定的本家族Harness驱动/配置与本家族测试，独立于客户端；公开合同只读
- qwen-client：仅products内本家族原生消费者及其测试，独立于驱动，不写主CLI/registry/schema；合同只读
主执行者冻结具体文件写权后才允许执行；不共享安装/全测试slot；子代理不写Git/status，不再开子代理。主执行者复跑结果。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| BASE | 真正源码快照与前置准确 | 旧HEAD当dirty全成果、借别人未验代码 | 不运行依赖，记BLOCKED |
| NATIVE | 实现实际qwen通道、实例隔离和唯一配置owner绑定；保留原生payload/回调/扩展，fixture反例与真实进程结果分别记录，缺认证/安装不发布runtimeReady | serve与ACP谁持有workspace/runtime/权限；serve源码可能设计与实现不同；不让桥创建第二会话账，不把CLI输出当完整管理面。 另注入陌生event、失回执、重放callback、两node事件交叉和缺必需配置 | 未测证据不能算通过，PARTIAL |
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

全部本单范围门实测通过才N007_DONE，并标具体L0–L4及家族产品终态；否则N007_PARTIAL或N007_BLOCKED＋精确缺口。不将工单DONE冒充整体PRODUCT_VERIFIED。批次整体真实任务门未测仍PARTIAL。

## Batch report

终态 **N007_PARTIAL**（CODE_READY＋L1；L2未测；管理绑定依赖阻塞）。家族切片子代理产出，主执行者复跑核实（18P+14P、runtimeReady仅否定语义、无observed-yes）。

- 门：BASE✓ NATIVE（serve通道/归属钉定/源码vs文档差异登记/不发runtimeReady✓） SAFETY✓（权限显式投票无auto、非环回拒、无凭据继承） EVIDENCE✓。
- 反例计数：32用例（驱动18+客户端14）。命令/退出码（主执行者复跑）：`pytest plugins/harness/tests/qwen -q` 18P/0F exit0；`pytest tests/native_clients/test_qwen_client.py -q` 14P/0F exit0。
- 证据路径：evidence/qwen-decision.md；源码SHA：b228983454 后本单提交；清理：fake upstream fixture内shutdown；成本：模型0、安装0（WebFetch多页含398KB大文档降级raw核读）。
- 未测项：L2/L3/L4；serve遥测/自动更新、load/resume真机、权限多策略真机=unknown；**待授权：安装qwen CLI（钉0.24.7或新）重钉digest补L2**。
- 家族终态：CODE_READY；管理绑定依赖阻塞；harnesses.toml基线无qwen block→登记同步归N012。

