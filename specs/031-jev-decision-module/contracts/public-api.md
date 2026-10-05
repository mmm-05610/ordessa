# 公开接口与调用契约
以下是目标接口，不是已有源码导出。所有 I/O 端口为 async；受控上下文由组合根注入，不序列化，不由模型生成。

## 运行入口
```python
async def run_decision(
    request: DecisionRequest, *,
    flow: TrustedFlow,
    services: DecisionServices,
) -> DecisionResult: ...
```
调用者显式提供已审查流程，flowRef 与实际版本摘要不一致时发前拒绝。
services 提供 read、candidateSource、proposalSource、validator、decisionProvider、evidence、policy；
runtime 创建本次受控 gateway，仅把 gateway 而非 raw SDK 注入节点。
校验通过后分配 runId；run.started取得持久ACK后才视为启动成功并进入业务。校验拒绝只记安全摘要，不伪造模型尝试。

TrustedFlow 提供 flow identity、图构建/引用、new_state(request)、outputSchema；
只能从显式装配的代码取得，禁止正文选择任意模块或下载执行脚本。
图定义可共享但不可变，state 每 run 新建。public DTO 不暴露 GraphRun/GraphTask。
read_result(runId, readContext) 只返回安全结果与证据；不存在无授权全局运行目录。

## 只读事实接口
ObservationPort.observe(query, readContext) -> ObservationBatch。
query 为版本化、注册于组合根的类型及有界参数，不是任意 URL/SQL/wire 方法。
来源服务仍按受控调用上下文授权。不能把同一服务返回的 mutable对象交给节点。
失败返回类型化 unavailable/refused/unknown，不返回冒充完整结果的空数组。

## 候选与组合接口
CandidateSource.list_candidates(task, observationRefs, policyRef, readContext) -> CandidateBatch。
ProposalSource.compose(task, candidateRefs, configurationOfferRefs, constraints, cursor, readContext)
-> ProposalCandidateBatch。
两者都只读、不 prepare/apply；候选页包含 complete、cursor、descriptor digest、excluded/unsupported 说明。
Jev 不负责自由生成组合。组合器可使用外部模板/枚举器/额外提案生成器，但额外模型必须显式接入同一预算，
不能藏在“只读校验”中无授权收费。首版使用确定性有界组合器，不引入额外生成模型。

## 校验接口
ProposalValidationPort.validate(draft, basis, readContext) -> ValidationReceipt。
只能核查描述、版本、权限范围、能力、组合合法性，不启动进程、不创建 lease、不写用户文件。
核查需要有作用探测时返回 unverifiable 和具名缺口，不自行探测。
PreconditionChecker.check(preconditions, readContext) -> CheckBatch；
CheckBatch含conditionResults(id、passed/failed/unknown、checkerId/version、sourceVersions、evidenceRefs)、complete、unverifiedIds；缺must项或未知checker不能整体passed。
检查入口与应用执行属于消费者，决策端不带 mutation 权限。
不同观察源没有全局快照事务时必须声明校验范围及限制，不能声称整体原子通过。
validationReceipt必须覆盖ProposalDraft的requiredValidationObligations，不将仅结构valid当完整方案valid。

## 模型入口
DecisionProvider.decide(question, modelContext) -> DecisionAnswer。
ModelCallContext是runtime构造的不可序列化内部对象：runId/callId/attemptNo/questionDigest/
providerSettingsDigest/monotonicDeadline和单次消费的opaque permit；正文/模型不能构造。
先取得本run并发slot，再原子核对deadline/取消/预算，预留attempt并持久写call.intent，
provider入口单次claim许可；重复/cross-run/摘要不符/过期零HTTP。等待slot也计入总时间。
permit仅进程内防误用，不是第二个持久lease/任务队列或网络沙箱。
raw provider 仅运行器网关持有；业务节点通过 DecisionGateway.decide(question) 请求。
网关在发前原子预留 attempt，保存 call.intent，限制并发和时间。SDK 隐藏重试禁用。
调用未知不自动重复；可解析回答但不合法时默认 failed；只有外部业务明确规定的
下一轮修正且预算足够时才开始新的具名判断，不当作无成本重试。

## 证据接口
EvidenceSink.start(runMeta)、append(event)、finish(terminal)；
EvidenceReader.read(runId, context)。
承重写使用append_durable并返回seq/digest/durability ACK；memory sink仅offline，不允许real模式。
finish单终态原子幂等：同terminalDigest返回已提交ACK，不同摘要terminal_conflict，不覆盖旧终态。
finish ACK丢失只能查询核实，未知不写相反终态。完成已提交后外部取消仍向调用方传播，查询保持completed。
Reader返回completed/running/interrupted/unknown/not_found/refused/unavailable，不能把拒绝或损坏当无历史。
证据实现只记录事实，不提供派发、恢复、自动重试、待办队列或 Agent state API。
完成事件保存失败时不能向调用者报告可信 ready。已经收到响应但证据失败不能重发请求。
安全摘要、引用、长度限制是契约，非任意字符串日志。敏感响应/异常须过滤。

## 实际应用交接
本版只交提案，不提供 apply_decision。消费者从提案选择明确动作，
重新核对 task/flow/provider/profile/node/config/authority/availability 前置，
再通过现有核心公开管理入口调用实际操作。
请求 key、lease 与原生效果记录由原机制管理，不用 runId 代替效果幂等 key。
真实修改遇到 unknown 仍 query/reconcile 原操作，不返回决策模块换 run 再发。
