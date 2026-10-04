# 夜间执行状态

状态：EXECUTING（N001阶段1已收口）。以下为执行者细账；包准备者原记录见历史。

观察时间：2026-10-04（Asia/Shanghai）。批准基线 HEAD adce734db21945181bf93da9720158d05e957654。

## N001 阶段1 · 源码快照（2026-10-04）

- 029原会话未提交成果已按精确路径收口：提交 `0f786dfc34`（117文件 +12619/-10），来源/写权/凭据二进制扫描见 `evidence/N001-source-snapshot.md`。未stash/未改写原成果。
- 本夜材料（specs/030、night-harness-expansion）随后单独提交。
- 快照后前置核对（design§6）：节点准备=缺失、公开管理入口=仅Profile面、原生session reservation=缺失（OperationStorePort基础无生产调用）、InputAttempt=缺失、transport fence=缺失。运行接纳链标**依赖阻塞**；资料/协议/配置编译/fixture继续，不发布runtimeReady。
- 本机CLI发现（只读PATH+文件系统，未执行）：`pi` 已装（`~/.pi/agent/bin/pi`）；`@openai/codex` npm包已装（0.157.1，`~/.local/lib/node_modules/@openai/codex`，bin分发未在PATH）；其余8家未发现已装CLI。qoder/qodercli存在但不在十家候选。

## Queue（终态）

- [x] **N001 = N001_PARTIAL**（快照收口 0f786dfc34/8155c659e3；冻结接缝+30P定向测试；pi 0.86.1 原生RPC真实隔离纵向入口 L2 partial。缺口：029前置四项+transport fence缺失→运行接纳依赖阻塞）
- [x] **N002 = N002_PARTIAL**（codex CODE_READY 28用例；L2=BLOCKED：本机artifact截断损坏strace实证，重装待授权）
- [x] **N003 = N003_PARTIAL**（pi CODE_READY＋L2 partial 27用例）
- [x] **N004 = N004_PARTIAL**（opencode CODE_READY 20用例）
- [x] **N005 = N005_PARTIAL**（claude-code CODE_READY 16用例）
- [x] **N006 = N006_PARTIAL**（kimi CODE_READY 38用例）
- [x] **N007 = N007_PARTIAL**（qwen CODE_READY 32用例）
- [x] **N008 = N008_PARTIAL**（gemini-cli CODE_READY 16用例）
- [x] **N009 = N009_PARTIAL**（copilot CODE_READY 44用例）
- [x] **N010 = N010_PARTIAL**（goose CODE_READY 12用例）
- [x] **N011 = N011_PARTIAL**（vibe CODE_READY 13用例）
- [x] **N012 = N012_PARTIAL**（整合/矩阵/安全审查修复/wheel fresh安装验收完成；L2真实任务门未测→批次整体PARTIAL）

## 批次终账（2026-10-04）

**源码SHA**：基线 adce734db2 → 0f786dfc34（029收口）→ 8155c659e3 → aa0a35fcf4 → f8f23d57f2 → 344c85c49d → 2d9ceaf12b → 5132e0e284 → b4ff649a85/742f0ad076 → 04aa59979d → b228983454 → 4217b3d1f3 → 8d77ed88d9 → 95d8000213 → 20be628540；tags `checkpoint/agent-tools-native-030-N001{,-s2}` 等（本地，未push）。树收尾应clean（本账提交后以 `git status` 为准）。

**每家分账**（详见 `evidence/N012-family-matrix.xlsx` 四表与各 *-decision.md）：

| 家族 | chosenChannel | version | L0 | L1 | L2 | L3/L4 | 终态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| codex | app-server JSON-RPC | 0.157.1 | ✓ | 28P | **BLOCKED（artifact损坏）** | 未测 | CODE_READY |
| pi | 原生RPC JSONL | 0.86.1 | ✓ | 27P | **partial已观察** | 未测 | CODE_READY＋L2 |
| opencode | HTTP+SSE | unpinned | ✓ | 20P | 未测 | 未测 | CODE_READY |
| claude-code | SDK/stream-json | unpinned | ✓ | 16P | 未测 | 未测 | CODE_READY |
| kimi | Wire JSON-RPC | 1.52.0 | ✓ | 38P | 未测 | 未测 | CODE_READY |
| qwen | serve HTTP+SSE | 0.24.7 | ✓ | 32P | 未测 | 未测 | CODE_READY |
| gemini-cli | ACP v1 | unpinned | ✓ | 16P | 未测 | 未测 | CODE_READY |
| copilot | CLI server JSON-RPC v3 | SDK1.0.16/CLI1.0.91 | ✓ | 44P | 未测 | 未测 | CODE_READY |
| goose | ACP stdio | unpinned | ✓ | 12P | 未测 | 未测 | CODE_READY |
| vibe | ACP | unpinned | ✓ | 13P | 未测 | 未测 | CODE_READY |

**测试命令与计数**（主执行者实际复跑）：products全量 `pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q` **402P/0F exit0**；native_clients修复后 **146P/0F exit0**；harness家族驱动 **86P+49P等全绿**；harness全量 **1031P/4F/3S**（4F=029遗留继承红，登记于docs/known-issues.md）；work-order validate_order **12/12 OK exit0**。

**fresh安装入口（G10已验）**：`pip wheel products/agent-tools` → `ordessa_agent_tools-0.1.0a2-py3-none-any.whl`（66KB）→ fresh venv 安装 → `ordessa-agent init --json`（8家族发现、runtimeReady全unknown）、doctor/帮助正常、`native_clients` 可导入且零宿主内部依赖。

**成本与清理**：真实模型调用**0**（预算0，未授权）；第三方安装/更新**0**；用户服务0重启、用户数据/凭据0变更（~/.pi/~/.codex/~/.vibe未读）；临时loopback/scratch仅/tmp自建，收尾删除；borrowed进程零kill。

**明晨3–5步验收**：
1. `ordessa-agent init --json`（fresh wheel安装后）看8家族PATH发现与runtimeReady=unknown；
2. `python -m pytest products/agent-tools/tests -q`（402P）与 `pytest plugins/harness/tests/pi plugins/harness/tests/codex ...` 复跑；
3. 读 `evidence/N012-family-matrix.xlsx` 与各 *-decision.md 核对十家分账；
4. 授权后按各家族"下一步"安装CLI重钉版本补L2（codex优先：本机artifact损坏需重装）；
5. 真实模型任务验收需另行授权scope+cost（L4）。

**待决/待授权**：
- **待授权**：重装/更新 @openai/codex（恢复codex L2）；安装 opencode/claude/kimi/qwen/gemini/copilot/goose/vibe CLI（补L2并重钉版本/digest）；LibreOffice安装（矩阵渲染QA用，今晚sudo/apt被授权边界禁止）；真实模型L4（scope+cost）。
- **待决**：5新家族 harnesses.toml registry块（需payload_schema/codec/dialect物化合同冻结，P-A②等价pin先例）；安全遗留3项（replay围栏窗口L2、wait关联校验L3、启动pin残留L5）见 N012-safety-review.md；029前置（AT-009/010/011）仍是运行接纳的硬依赖。
- **环境异常**：子代理报告幻觉1例（落盘经审查正确）、子代理失败3例（由主执行者补完/改派）、视觉judge供应商不可用（降级自检渲染）——均如实登记。

## Questions

真实模型授权范围/成本未提供，预算0。第三方Harness额外安装、认证和新核心语义均不能靠本包自动扩大权限。若前置未交付，继续原已批准队列或记录依赖；不新造第二实现。

## Spend / cleanup

包准备者真实模型调用0、服务启动0、安装0、Git提交0、用户数据变更0；官方网页研究不算原生运行验证。原会话实施成本不在本包重算。

## 执行者交接格式

源码SHA与dirty清单；每家chosenChannel/version/L0-L4/终态/证据；测试命令与退出码/数量；fresh安装入口；成本与清理；明晨3–5步测试；待决事项。

