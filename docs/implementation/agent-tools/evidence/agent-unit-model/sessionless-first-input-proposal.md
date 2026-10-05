# Sessionless Unit 首次输入：已确认的授权与占用语义

用户已选择“采用提案，沿原机制扩展”。以下口径已确认；实现与验收尚未完成。

本树基线9e1a6db19b。只读盘点与代码确认：NativeInputState强制session_ref，
ManagedInputReservations固定Session授权target并在claim前重核。同一真实Unit在
Session尚未产生时不能合法接纳首输入；不能填default或将UnitRef伪装成Session。
新Unit确认只解决原start与process/pipe/init证明，未授首次输入作用权限。

## 建议裁决

1. 在现InputAttempt内增加明确版本的“已确认Unit、Session缺席”绑定；不重解释
   旧Session路径或旧已持久请求。使用完整原UnitRef作为首次submitInput授权目标。
   显式InvocationAuthorityPort必须单独授予该Unit目标的完整原生输入作用范围，
   包括该输入可能创建Session的效果；现有Session授权、Bearer、OS可访问或Unit
   start许可均不自动覆盖。缺Unit输入许可/当前owner证据则发前拒绝。
2. 原OperationIntent固定Unit、provider activation、epoch、DirectoryBinding、Unit
   confirmation来源、Session缺席观察、捕获输入摘要及原native correlation。
   沿原Issuer claim/continuation和owner writer fence派发一次，不新增输入引擎。
3. 复用同OperationStore/DomainStore/Usage事务，为同Node+Unit的首次关联预留
   唯一占用，阻止更换draft/requestId绕过unknown。占用不按draft单独计。
   未知输入仍保留原输入fence；仅观察到一个Session ID不能解除未知作用。
   释放或转移必须依据同原操作的受验证确认，并和原发布事务绑定。
4. 真实Session由原UnitRecords作record-only association：当前query授权与原
   InputAttempt request/op/step/digest、Unit/provider/epoch/native correlation
   都须匹配，并由owner持久原始native证据核实。原Session行的revision CAS
   记录真实Session；不再start、不发补ticket、不发送输入、不猜最近Session。
   association只证明Session身份，不当作任务完成或原输入效果已知。
5. 冷恢复只读同原input step与原owner证据，迟到/错来源/ACK拒绝或unknown。
   首次关联与正常Session输入两条路径不自动fallback；未知不能换路派发。

## 实施边界

本提案新增的是现有机制的显式绑定版本、授权目标与占用门；不建立第二输入
ledger、通用协议翻译、后台daemon或配置真值。保留原Session-only请求的含义，
不迁移用户DB、不调用模型。需验证同Unit不同draft并发、丢回执与冷query、
撤权/退役/目录/epoch变动、错输入摘要/原关联、晚到CAS和ACK不释放占用。

预留/claim已在e4714eba00检查点实现，原Session行只读association见de29fb04da及
input-session-association-port.md。双证据结论与原publication/Usage转移的核心接缝已补，
见first-input-publication-port.md；生产native owner/输入writer与公共消费仍未贯通，
该产品路径保持unsupported。不另开共享写者，不把C层接缝当产品验收。
