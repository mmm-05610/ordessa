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

Main serial verification: runtime 23, evidence 17, provider 35, task/selection 44;
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

## 最终离线检查点

JD001–JD008 OFFLINE_VERIFIED；JD009 PARTIAL（真实家族配置能力未声明支持）；JD010 NOT_RUN。
codeReady 已验证；offlineVerified 67 个场景逐项通过；coreReadOnlyVerified 限真实临时核心+fake owner，原生效果 0。
liveJevValidated NOT_RUN；native effects OUT_OF_SCOPE；不得宣布全部完成。

最终完整套件 209 passed，固定基线/当前 40 个核心定向 ID 一致。
[逐场景证据与限制](evidence/implementation-20261005/README.md) 和 [机器回执](evidence/implementation-20261005/receipt.json)。
SDK fake HTTP、6 个真实子进程崩溃窗、ACK 未知/取消/预算/必须义务缺失反例都分别记录。
最终证据提交新增 journal terminal.commit 持久确认；rename 后目录 fsync 失败不能经重开 reader 升格为 committed。

真实评测准备：9 个脱敏标签样本、54 个 rubric 问题预编译，候选模型 jev-1.13.0；
提出但未授权的上限 64 attempts/300 seconds，费用未知，需单独确定成本额度和凭据来源。
没有真实模型质量成绩；不存在授权超时自动调用或凭据环境 fallback。
剩余门：真实 Jev 请求/凭据读取须另行授权；真实家族/Harness 能力不由本模块凭 fake owner 宣称完成。
完整 Server/Harness 继承失败集未重跑。现有服务、用户数据和其他工作树未触碰。

## 自动续轮授权审计
上一轮为进展：提交源码与 67 个逐场景回执。本轮补充原 Environment lifecycle/store seam 的 17 个离线测试；
默认离线入口与 T64 现在按 57 个固定基线/当前测试 ID 比对，两边全部 passed、结果一致。
[补充回归](evidence/implementation-20261005/additional-core-regression/README.md)。
JD007 没有要求旧家族必须新增能力：旧 provider unsupported 是验收缺席行为，仍如实保留 JD009 PARTIAL。
真实 JD010 尚未授权，模型/凭据/费用门未解除。已向用户提出具体授权范围问题；未读取任何凭据。

## 本地 Laya 授权评测（2026-10-05）
用户另授权“测试一下/继续”，限定本地 Laya 合成样本推理；原 Jev 云端授权门不改变。
[真实 Laya 证据](evidence/laya-local-20261005/README.md)：25 次完成推理/49 个问题，25 个模型场景中 9 个标签匹配；另 1 个硬规则零模型拒绝。
补充正确单维状态绑定后仍全部 unknown；候选排序/注入/未知配置/布尔正例有失败。不能把 Laya 调用写成 T60 通过，不能降低标签/阈值填绿；不接入默认 provider。
首个中断进程无回执、调用数未知，核实进程缺席后恢复一次；仅完整回执计数。既有快照文件 hash 不变。

## Zen 真实 Jev 与最终复验（取代上方旧 NOT_RUN 状态）

用户指定私有 opencode_zen、确切 free endpoint/model，另授权移出源码树。官方 SDK 请求模型和实际响应均 jev-1.13-free；provider 模型改为 host 配置，显式响应身份白名单受 digest 绑定，业务节点不能更改。正式协议/概率/标签门未降低，无模型/账号 fallback。

[真实 Jev 逐场景账本](evidence/jev-zen-20261005/README.md)：累计真实 HTTP 50 次，上限 64，重试 0、原生效果 0。保留答案的 23 个模型场景 22 匹配；单交付任务 clarify 与正例标签不符。首中文场景三次响应摘要已持久化，但收集器 KeyError 后答案未留存，未重发、质量未验证。原 66 选项命名不合规本地拒绝；正确 64+2 兜底 ID 的补充场景 10 秒超时，服务端完成/usage 未知。T60/JD010 PARTIAL，未将小样本成绩推广为质量成熟。原九样本 54 rubric 问题未全量运行；后续真实调用仍需独立预算/范围授权。

已知 reported usage：25,439 input + 2,002 output tokens；1 个超时请求 usage 未知，费用 UNKNOWN，没有账单证据。凭据迁至 /home/maoqh/.codex/private-vault/opencode_zen，目录 0700/文件 0600，源码树已无原文件；无凭据内容入日志/Git。

[新源码离线复验](evidence/zen-offline-20261005/README.md)：211 passed，67 场景分别通过，固定基线/当前 57 个核心 ID 一致。首次完整测试 210P/1F 为旧 wheel，保留失败，经正常离线重建后 211P；不删断言/skip。所有先前回执保留为历史，以最新 source_digest 为本次实现证据。

JD001–JD008 OFFLINE_VERIFIED；JD009 PARTIAL（真实配置家族 opt-out/unsupported），JD010 PARTIAL（真实质量与未验证项）；all_work_complete=false。完整 Server/Harness 继承失败未重跑、Python 3.10/断电/远程 FS/真实家族实际应用未验证。没有其他工作树写入、服务重启、DB 迁移、merge/push。

## 正确逐维绑定补充（检查点后不停工）

继续使用剩余额度，对 vague/single-result 各以原编译器逐问题 bounded_state 发 6 次请求；规则/任务/标签/阈值不变。vague clarify 符合标签，single-result 仍 clarify，问题 acceptance_unknown/delegation_unknown。原失败保留，T60 仍 PARTIAL。真实请求累计最终 62/64，reported usage 更新为 32611 input + 2540 output；1 个超时的 usage/服务端完成仍未知。正确状态输入、原脚本/配置快照和答案已保留在 Jev 证据 bound-state-controls。剩余 2 attempts 不足跑另一个六维场景；追加真实评测须另定预算。

## 继续实施与完整复验

修复 TaskBrief 业务输入遗漏：外部策略 v2 的有限摘要/引用投影进入问题及签名，来源变化重新判定；不解引用、不授予第三方权威。JD007 未新建核心，补公开观察期间退役/替换反例和已有文件写入检测。

完整套件 232 passed；67 个离线场景、固定基线/当前 57 个核心 ID 再次全部通过。[继续实施证据](evidence/completion-offline-20261005/README.md)。收集器首次 3F/3P 原因是缺失 durable 目录，修复后 6P，失败日志保留。假传输不计作真实模型。

原 single-result 泛化验收不足，不能断言模型错误；保留旧失败与标签，冻结新增完整任务、单维控制及各领域 23 场景/42 请求。新 plan hash f10594450f29ff5f4dccbc8363915d192976007c963965943827a1bef2036e01，预检 credential_reads=0。此前 62/64 额度不足新增批次，已提出最多额外42请求/300秒/每请求30秒/无重试/无付费fallback的具体授权，等待答复；此前私有 key 读取和迁移授权仍有效。

JD009 交付与离线行为已验证，真实家族 opt-out/unsupported 仍 PARTIAL；JD010 真实质量仍 PARTIAL。检查点不停工，all_work_complete=false。

## 新增42请求授权批次完成

用户明确授权上述冻结计划。实际42请求/38.8973秒，重试0，原生效果0；23个run持久终态独立复验通过。22个模型场景中21个有有效答案、20个符合固定标签；另1个零模型硬拒绝符合。完整单交付新 TaskBrief 六维通过，不追认原泛化样本通过。英文流失正例0.40未达0.50；64+2场景HTTP200后protocol_invalid，具体字段原因未留存/未验证。T60/JD010保持PARTIAL。

[新真实逐场景证据](evidence/jev-domain-v2-20261005/README.md)。新增usage已知29819输入/1707输出，1个未知；累计104请求、已知62430输入/4247输出、2个未知，费用UNKNOWN。原raw回执凭据计数误保留0，实际脚本读授权私有文件一次，summary审计修正1，旧原件不改；后续收集器计数已修复。

新离线默认入口包含完整套件再逐场景运行，补充反例不会因缺场景标签而遗漏。JD009真实家族能力、上述真实质量/协议失败、继承失败与未验证范围全部保留，不宣布全部完成。

## 原目标实施交付审计

主执行者按R01–R14、40个JD子项、68场景复核当前源码与证据，两个命名示例再次运行completed/ready（controlled offline）。[审计与范围解释](completion-audit.md)及[机器追踪矩阵](completion-audit.json)。没有发现未交付的必需离线实现项；JD009缺家族能力、JD010模型未达标保持原合同要求的PARTIAL报告，不能提升为产品全面就绪。对应已知问题已补入docs/known-issues.md；原始失败和未验证项不删除。

## 用户要求继续后的实际诊断进展

此前将交付审计作为结束条件停得过早，用户要求继续。原目标继续推进；用户另授权同一免费Jev合成诊断累计调用无上限，每次运行仍有限预算且无SDK重试/付费fallback/Harness。增加固定安全诊断代码，不放宽任何协议或阈值。定向53项、完整242项、67场景与57基线/当前核心ID通过。

[新诊断证据](evidence/protocol-diagnostic-20261005/README.md)：新增23调用；容量单条成功，8次重复有1次概率总和错误；旧英文条件正例4次仍不匹配；新的明确意图规则v3中英文8对照全部符合，不追认旧标签成功。23个终态独立验证。累计127调用、已报告86255输入/10005输出，3次usage未知，费用UNKNOWN。正推进真实SDK接入原业务图的完整提案/反馈回环；未重新宣布全部完成。

## 真实SDK贯穿原业务图与最终复验

补上此前仅有领域问题调用、缺少原业务图真实模型贯穿的证据。原图明确任务、受控拒绝后的Repair回环、模糊澄清、独立多目标修订共36请求/6run符合冻结标签；模糊与多目标零组合/校验。另21请求/3run经过原assignment.rank：偏好位置反转均选中确切提案，证据不足返回clarify且无payload。探针不复制执行器，不新建owner；受控资料不代表原生家族能力。源码/计划/FlowRef与9个持久终态独立复验通过。

[原参考图证据](evidence/reference-flow-20261005/README.md)，[原排名证据](evidence/rank-flow-20261005/README.md)。累计184次真实Jev请求，已报告141209输入/12613输出，3次历史usage未知，费用UNKNOWN，无重试/付费fallback/原生效果。旧协议与标签失败保持原记录。

[最终离线证据](evidence/original-graph-final-offline-20261005/README.md)：260项全套、67逐场景、固定基线和当前各57核心ID通过。新增排名取消与截止反例通过，已发attempt不返还、不重用。JD009家族缺能力与JD010模型协议稳定性/旧标签失败仍PARTIAL；不把局部通过提升为产品全就绪。

## 原图边界补齐与授权范围交付

[新增边界证据](evidence/edge-flow-20261005/README.md)：无候选clarify、显式主Agent处理noDelegation（零候选/组合/校验）、新配置结构合法但必需owner语义unknown而clarify、v2第三方注入贯穿原图和受控组合/校验，共24真实请求/4run全部符合先冻结预期。四个终态/source/plan/FlowRef与计数独立复验通过。配置schema/字段外部定义，字段改名反例通过；首DTO字段预检失败和审计排序错误留档，无key/HTTP重试填绿。

最终269项全套、67逐场景、57固定基线/当前ID通过；累计208次真实免费Jev调用，已报告164315输入/13689输出，3次历史usage未知，费用UNKNOWN。原计划9类样本没有未跑类别，但不把有限样本、受控owner或新规则通过推广为整体成熟。源码实施与规定验收报告已交付；产品就绪仍PARTIAL，JD009家族能力缺席、JD010历史标签失败/概率和协议错误仍开放。实际Harness应用不在本轮，不扩大授权、不改其他工作树、不merge/push。

## 用户要求继续：下游边界两轮反例与修复

此前“已授权交付结束”不能作为停工依据。继续实施实际攻击反例，修复来源撤权／换代、义务来源版本／类型、提案摘要与task revision、隐藏schema分支、可信owner映射缺检查、策略别名、吞异常重发、ACK重放／假终态、写者锁替换／重复start及close EIO。失败与修复逐项见 [本批证据](evidence/adversarial-20261005/README.md)，不删除旧失败。

最终320全套、67逐场景、固定基线／当前各57核心ID、独立wheel离线重建安装通过。新增6次真实Jev原图合成注入复验通过，归档终态／source／plan／FlowRef独立核验；累计214请求、已报告170771输入／13958输出、历史3次usage未知，费用UNKNOWN，重试0、原生效果0。单个样本不能证明全面抗注入。

原生家族仍按冻结合同unsupported，真实Harness／实际应用未运行，JD009／JD010保持PARTIAL；历史模型标签与概率协议失败、继承Server/Harness红、Python3.10及真实断电等未验证项不关闭。原目标保持active，all_work_complete=false；已准备 [后续家族扩展的具体方案](downstream-next.md)，扩展冻结范围和真实Harness动作须单独授权，不把Jev无上限授权扩大解释。

## 已批准 Codex 原 owner 纯读扩展

用户明确答复同意扩展。实施与冻结范围见 contracts/codex-pure-read-extension.md，复用原CodexRuntimeProvider/ConfigurationChangeRequest/_compile_change，声明编译范围的公开纯读端口；owner/状态/原生操作仍归原核心，未新增执行器。Codex不再笼统标unsupported，但offer/runtimeReady/application仍unknown，Pi/Claude保持unsupported。

[本批逐场景与失败证据](evidence/codex-pure-read-20261005/README.md)：Decision352项、Codex家族147项、67离线场景、57基线／当前核心ID及独立wheel通过。继承客户端夹具退役import的16失败已在固定基线复现，改为现有公开Message类型且保留断言后通过；内部异常误报和offer身份／证据错绑定的RED记录保留。

新6真实Jev＋实际Codex纯读owner贯穿原图，compile passed、应用mandatory unknown，clarify无payload；无重试/原生效果。归档独立复核question/answer/hash chain/terminal/manifest/source/plan/FlowRef/native input双摘要/义务通过。累计220调用、已报告176303输入／14227输出，历史3次usage未知，费用UNKNOWN。模型质量及协议旧失败、其他继承红／未验证项不关闭。

真实Harness及实际配置应用未授权／未运行。已准备 harness-smoke-next.md 的具体有限协议烟测方案；原目标仍active，all_work_complete=false，不宣布全部完成。

## Codex纯读效果接缝补验

补上实际owner三状态的文件／进程／网络直接监测与四项吞guard故障注入，计数独立于回执，fd写入反例也覆盖。SQLite只读查询变化仅限官方WAL-index读者标记；DB/WAL、目录项、其他文件和SHM其余字节严格相同。初版3F/15P及修订依据保留，不能声称OS级sandbox或任意未监测瞬时效果已证明不存在。

[本批证据](evidence/codex-effects-20261005/README.md)：Decision359P、Codex147P、67场景、基线／当前各57P、独立wheel安装通过，T57/T62逐场景纳入新反例。真实Jev旧归档独立复验通过；本批无新模型调用，累计220与费用UNKNOWN不变。待答复原有限Harness烟测授权；目标active，all_work_complete=false。
