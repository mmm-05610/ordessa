# 原首输入双证据结论与发布转移

前置 de29fb04da；沿已批准 sessionless-first-input-proposal.md。主会话独占共享写权，Pi/Codex只读审阅；未提供生产输入 owner，产品仍 PARTIAL。

## 公开核心接缝

ManagedInputReservations 的可选 first_input_observation_port 是显式部署的
FirstInputObservationPort.observe(original_operation, opaque_query)。其职责是
只读核原 journal association 与另一份原 input effect 证据，分别证明实际
Session 身份与原输入作用已知；后者不要求任务完成。owner必须核同原实际
capture/native bytes/correlation/receipt、Unit/process/transport/root与当前权限。
core不解析原生协议、不维护Session或模型真值。引用结构/claim/ACK不能代替
实际owner证明；生产端口缺席即 typed unavailable，不默装测试fixture。

FirstInputObservation 固定原 request/op/step/inputDigest/provider/完整Unit/Node/
epoch/nativeCorrelation/Unit确认/历史Session缺席/CapturedInputRef；associationRef、
SessionRef、effectEvidenceRef 都是同owner的带sourceRevision引用。effect与association
须为不同来源。Session原sourceRevision为整数且至少2，不接受bool。Usages只描述
原receipt的固定Mutation，不建立另一资源登记表。

reconcile_first_input(request, original_issuer) 只签原query，不签作用ticket、不claim、
start或输入。部署owner须核query；原issuer随后verify_claimed_query核同Store的原
managed-input/native-input完整Unit submitInput claim，原epoch不重解释。原Core policy、
registry、published Node/Unit与query当前权限在观察后和发布前再次核验。权限/owner
失效不把旧观察提升为成功。

## 原结论事务

采用原OperationStorePort.record_operation_step；现有environment-api只增加兼容的
可选keyword require_complete_usages=False，没有新共享包/持久表/ledger。首次结论
显式True；只允许concluded且必须是bool。SQLite在原结论事务中、任何写入前核所有
non-released operation-held Usage均在active mutations中，再沿原holder/target/rights/
revision CAS写Usage与step。缺项或冲突整次回滚，原unknown和资源不改。完整性选项
纳入原result digest，弱口径不能冒认强口径结论，旧默认调用行为保留。

原step evidence固定双证据、完整身份以及每项Usage结论后的原revision/target/
rights/payload。可补齐漏报的原receipt再只读恢复；不能先冻结缺项结论然后增补。
未知Usage仅沿同原concluded事务成为active。不释放资源来绕过完整性检查。

## 原发布事务与重放

step concluded并不解除首次占用。原publish_operation原子CAS operation revision、
FIRST_SESSION_ATTEMPTS原revision1→resolved2，以及全部operation-held Usages→同固定
Node active。原Store仍核全部required steps与全部保留Usage。Domain/任一Usage CAS
冲突，marker、publication result和转移整体回滚；step可已concluded，fence仍held。

原结果采用内部managed-first-input-result/1，保留Node/op/input/association/Session/
Session sourceRevision/effect引用；这是原Core结果投影，不新增wire或原生翻译协议。
重复发布从原step evidence重建原CAS1 DomainWrite和原Usage转移，不按最新revision、
现已转Node资源集合或最新Session重新生成。owner冷观察须与原结论完全一致，否则
typed conflict，不能重写原recipe。store publication digest继续核原写入/Usage/result。

resolved marker须有原published Operation、原concluded evidence及同publication result，
保留原holder/绑定/完整身份。held+published视为损坏，不能用历史published回执假修复
marker。后续普通Session输入只接受同原Unit/owner/Session引用和原Session revision。
Sessionless状态遇resolved仍拒第二次首输入；held、terminal或只看到Session从不放行。

## 崩溃和缺席

owner journal与Core Store是两文件，不声称跨库原子事务。association已commit但Core
未写：Core unknown/fence held，只读原源恢复。Core concluded未publish：不再record已
终结step，沿原recipe数据发布。迟到观察使用观察前原step revision，不刷新后覆盖。
owner/权限/epoch不满足、完整证据或Usage未知则保留占用。旧代码/外部弱口径已经冻结
的不完整concluded recipe不能追溯改写，本接缝拒绝它，未做用户数据迁移。

## 证据边界

50项新增C：45项原Core/SQLite/Issuer正反例，5项真实Registry/Node/ManagedInput/
UnitRecords及两原SQLite文件的纵向场景。native receipt/effect/capture/authority仍受控，
无生产writer/进程/模型。纵向cold_owner重开Harness journal，沿用Core Store/Environment/
Issuer，不等于完整Core/Issuer进程重启验收。覆盖缺双证据/ACK/错来源/bool、撤权、
late CAS、结论后崩溃、Domain/Usage冲突、unknown与active漏报后恢复、强结论重放、
原发布重放、伪resolved和后续错Session。命令/exit/最终扩大回归见status.md。

真实三家owner、原生writer fence与receipt持久回查、完整进程冷启动/生命周期、材料/
SecretRef、公共服务绑定和薄CLI/Skill/发行闭包仍未完成；P未验证、M0，不报AU002_DONE。
