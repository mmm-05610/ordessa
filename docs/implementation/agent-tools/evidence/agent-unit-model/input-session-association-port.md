# 原 InputAttempt 的只读 Session 关联

前置 e4714eba00；用户已批准 sessionless-first-input-proposal.md。主会话唯一
共享作者，Pi仅只读审阅。本接缝不证明生产输入可用或任务完成。

## 原 claim 查询

InvocationVerifier.verify_claimed_query(context, provider_ref, target_ref,
input_digest, operation_kind=...) 是原 issuer 的只读核验，不是新授权来源。
调用者须先成功验证原 query；核验前后使用同 opaque query continuation，读取
同原 OperationStore 的原 step，核 intent/digest/opIntentDigest/provider/原 epoch
及 operation kind。关联还核原step为完整Unit的submitInput、非cleanup、无另行
delegation的既定绑定，不能将prepare/stop的claim当首输入。query 的当前 epoch
不得重解释旧输入 epoch。无 claim、
未核验 query、异操作/step/输入、旧授权与复制 context 都不产生关联许可。
方法不 claim、不签 ticket、不派发；返回同原 query facts，claimRevision仍None。

普通 query 仍可读取未 claim 的步骤，原合同没有收窄。关联入口额外要求已存在
原 managed-input/native-input claim；claim存在本身不证明原生输入已发生。

## 原 owner 的证明

UnitRecords.input_association_evidence 是显式可选
NativeInputAssociationEvidencePort.verify_association(unit, identity, evidence)。
缺该 owner、原 claimed-query 核验或 Unit 确认来源即拒绝，不 fallback oldstart。
identity固定原 request/op/step/inputDigest、完整 provider/Unit/Node/epoch、
nativeCorrelation、Unit confirmation来源、输入前Session absence来源及原
CapturedInputRef。absence是历史输入前观察；真实 Session 出现后不要求现仍缺席。

owner须独立核原真实捕获输入与原生提交/receipt 字节来源、实际进程/运输与原
correlation、当前存活和固定安装/根、历史absence及同Unit实际Session身份。
core参数摘要或claim不能代替原生字节证明，ACK/最近Session/当前值相同均不足。
本切片没有提供生产owner；测试owner只提供受控事实，不安装到产品装配。

owner返回显式内部 `harness-input-session-association/1` 投影：identity、nativeBinding、evidenceRef、
associationRef。nativeBinding保留原nativeRealm/sessionId/evidenceRef三字段，
不允许default或ACK替代真实Session。两个来源引用必须带同environment、完整
ownerProviderRef、sourceRevision/ref。未知版本、额外字段与错类型拒绝。
这是原journal证据codec，不新增网络或原生协议翻译。

## 同一 Session 行

query_input_session(unit_id, query_context, input_digest=...) 仅读原输入观察。
reconcile_input_session(..., expected_source_revision, evidence) 在原 journal
BEGIN IMMEDIATE 内核原 Unit 当前 confirmed、原输入与 owner证明，再重核 query
权限，CAS原 notCreated/revision1 → confirmed/revision2。没有新表、输入ledger、
Session真值或 ticket；完整identity/proof进入同harness_unit_sessions.native_json
及原digest，creation_correlation固定原request/op/step。

只有该显式新codec且owner重核通过时允许confirmed2；旧三字段confirmed2仍拒绝。
旧 start 的 opening2/unknown或confirmed>=3仍走原 NativeSessionEvidencePort。
native_facts只投影原三字段，association_facts提供已核的完整新证明。同源读取/
重复关联保持原行；错原输入/晚到CAS/新Session/新证据不能覆盖。缺owner的冷读
失败且原行不改，不补造历史Unit来源、不迁移用户数据。

关联仅证明Session身份，不等于原输入作用已知/任务完成。原Core input unknown、
first-session Domain held及Usage完全不由该方法修改；后续双证据确认/出版必须
另沿原core事务完成。

## 提交与恢复边界

观察中撤权/epoch改变和SQL失败发生在commit前，原行保持notCreated。
commit后的返回值还会重核owner；若这时失败，关联行已经持久，调用失败不能被
描述成整次回滚。此时当前观察不可用、core unknown/fence held；恢复只查询原
输入来源。用旧revision1再关联会冲突，不补ticket/输入/重新start。

owner journal与core Store不是同一事务，尚未接入跨库恢复后的数据发布。原占用
一直held，所以关联后仍不能接受后续输入。这个明确缺口不能通过删占用补齐。

## 验证

test_input_session_association.py的53项C使用真实临时SQLite/Issuer，native receipt
owner受控，无真实进程/模型/输入writer/出版。覆盖未claim、query未核、异请求/
kind/step/digest/native关联/capture、错误版本/ACK/default/来源、CAS/bool、授权/
activation/目录/epoch/过期、观察中撤权、owner缺席、冷读取、两原journal实例
并发、SQL失败、commit后观察失效、晚到与旧start codec。原unknown/fence逐项保留。
实际命令/次数/退出码及扩大回归在status.md。C绿不证明P/M或生产装配；AU002仍PARTIAL。

## 后续核心接缝

原双证据结论与publication/Usage转移现已补齐核心C接缝，见
first-input-publication-port.md；本文件以上是de29fb04da阶段的关联边界，不把
association本身提升为输入确认。生产owner/原生writer、完整冷启动和产品消费
仍未贯通，整体PARTIAL。
