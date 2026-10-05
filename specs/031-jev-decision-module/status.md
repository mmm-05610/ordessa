# 材料状态与权限
本轮：设计整合、第二轮交叉攻击与定向复核完成。设计子代理仅只读研究并向主会话返回方案，无文件写权、Git写权、真实模型调用权或递归派工权。
根树观察提交：b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0。
Agent 实施树只读观察提交：9e1a6db19bd54df5d6508eaa71098ca96b59bcd9。
后续固定只读参考：577014c450b275faaf35d1e9c4b6cdbf9b6183de；不是授权实施基线。
根树存在用户既有未提交文件及方案目录，全部保留。本包以新目录新增，不 stage/commit。

现有 AGENTS.md 中的目录说明仍包含旧布局；本包不以目录名替代新树源码核查，也不授权执行者改写旧主树历史基线。
实施前必须确认工作目录和准确基线。不得自动在根 main 实施或抢占另一个会话的实施树。

## 授权矩阵
| 行为 | 本轮 |
| --- | --- |
| 只读源码/官方资料研究 | 允许 |
| 子代理独立设计与攻击 | 允许 |
| 本包文档与材料校验器 | 允许 |
| 安装/执行第三方候选 | 未授权 |
| 产品实现/新增树/接入其他会话 | 未授权 |
| 真实模型调用/秘密读取/服务重启 | 未授权 |
| commit/merge/push/云端修改 | 未授权 |

## 证据分级
源码观察≠受控运行；材料检查≠产品运行；假 Jev≠真实 Jev；fake core≠真实核心；真实只读核心≠Agent实际应用。
缺访问或依赖时登记 PARTIAL，不用 skip、空候选或 mock 填成产品完成。

## 本轮实际结果
6名独立子代理分别设计6个模块；主会话整合，3名审查者第二轮交叉攻击提出11项P1，已修入合同/任务/反例。
M01/M03审查者最后定向复核原反例闭合；M02建议由主会话逐项核对整合，不冒称产品运行。
材料结构检查：6模块、10任务、68验收、14需求，全链指针与映射零错误。
材料校验器：正常包通过，8个内存注入反例被抓住，命令退出0；它不是图、SDK或核心测试。
第三方安装/运行、真实Jev、真实核心只读集成及原生效果均未执行。实施树/精确基线/安装授权待用户确定。
费用：真实模型调用0；子代理平台费用不可由本会话精确读取，不编造金额。

## Implementation run 2026-10-05 (supersedes design-only authorisation above)

User /goal authorises this worktree only: implementation, isolated installation,
offline tests and checkpoint commits. Baseline HEAD e4714eba00a78ba04c5b53318830a0d409e76bbe;
initial dirty state only untracked spec materials. No other tree or live service touched.
Main owns contracts, assembly, Git, ledger and all serial installs/tests.
Subagents runtime/Jev/evidence have disjoint write scopes, depth one, no Git or test/install rights.

JD001: real pydantic-graph 2.54.0, typesafe-sdk 0.7.2 installed in .venv-decision;
release metadata/wheel+closure hashes in packages/backend/decision/lockfiles.
Python 3.12.14. Model candidate jev-1.13.0 not live verified; protocol tolerance 1e-6
matches upstream generated fixture examples, not a guarantee about all live responses.
JD001 compatibility: 5 passed, exit 0 (real graph three-round feedback, cancel,
invalid graph, official SDK success/429/500 each one HTTP). First graph probe failed
on mistaken .matches usage; corrected to public match(..., matches=...). No private API fallback.
JD002 initial contracts: 5 passed exit 0; finite JSON/deep freeze, namespace/digest vectors,
terminal union, obligation coverage/payload drift, unknown revisions and text authority rejection.
Python symbols/native DTO mapping frozen in contracts/python-freeze.md.
Not all JD002 full scenarios verified yet; remaining schema/DTO vectors checked before final acceptance.
Material checks: 6 modules/10 tasks/68 scenarios/14 requirements; 8 injected negatives passed.

Spend: real model/Harness requests 0; credential reads 0. Subagent calls 3;
platform cost unavailable, no invented monetary totals. T60 NOT_RUN pending separate authorisation.
Readiness: codeReady IN_PROGRESS; offlineVerified IN_PROGRESS; coreReadOnlyVerified NOT_RUN;
liveJevValidated NOT_RUN; native effects OUT_OF_SCOPE.

## P2–P4 checkpoint

Main serial verification: runtime 23, evidence 17, provider 36, task/selection 44;
public native seam initial 4, strengthened counterexamples 14; current vertical
examples and actual graph+SDK/durable sink verification included in checkpoint-tests.txt.
Subagent reports were not accepted as test evidence; main reran their suites.
True three-round graph repair reaches dynamic 0.7; unchanged proposal/feedback stops;
all seven actions are controlled offline proposals, no real family action usability claim.
Temporary SQLite-backed Environment+public services+fake owner: offer→graph→owner validation
verified, native effect calls 0. Profile preview unresolved, filtered list incomplete,
provider installation/node availability unknown retained.

Independent review found malformed receipt evidence, mutable DTO metadata/policy refs,
refused/unsupported laundering and invented material policy targets. Fixed with tests.
Material sources now reuse exact Profile/Node/definition public read checks; unknown
reference schemes unsupported. Owner must bind input digest and descriptor/source versions.
No new Environment, provider registry, effect operation/lease or dispatcher created.
Old providers opt out; no real Pi/Codex/Claude support claimed.

Fixed-baseline/current targeted Pacthold direction+public surface regression both 40 passed;
per-ID JUnit comparison will be recorded at final acceptance. Initial baseline copy lacked
runtime-compat guard resource and failed 2 tests; populated tracked baseline source and reran,
not skip or assertion deletion. Full server/Harness inherited-red suites are not covered by
this narrow regression; registered baseline failures remain inherited and unverified here.
