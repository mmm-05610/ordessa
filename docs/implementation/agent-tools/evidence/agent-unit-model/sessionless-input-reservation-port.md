# Sessionless 首输入预留与 claim 接缝

依据用户批准的 sessionless-first-input-proposal.md，在 AU003 Claude 检查点
d637a65946 后串行进入 AU002。共享实现与 Git 仅主会话持有。

本切片只完成预留和原 InvocationIssuer claim；不宣称首次输入闭环可用。

## 原 owner 观察

NativeInputState 的已有 Session 路径及持久 context 含义保留。
NativeInputStatePort.inspect 可显式返回 SessionlessNativeInputState：完整
Node/provider/原 UnitRef、unit_confirmation_ref、session_absence_ref、epoch、
DirectoryBinding 和 before_configuration_evidence。引用来自原 owner，并非
客户端提供路径或第二份 native 真值。owner 必须逐次核原 Unit 已确认、仍存活、
对应原进程/运输/安装与根，且 Session 确实缺席。DTO 形状检查不能证明这些事实。
缺实际 owner 端口仍拒绝，CLI/wire 未因此宣告 managed input 支持。

原 OperationIntent.contextRef 的新 sessionlessInputBinding 使用内部版本
harness-sessionless-input/1，固定 unitRef/unitConfirmationRef/sessionAbsenceRef。
该版本是受保护的操作绑定，不新增 wire 或原生协议翻译。没有 nativeSessionRef
或假 Session ID。首次 submitInput 的授权目标为完整原 UnitRef；部署 authority
必须授予完整原生输入（包括创建 Session）作用范围。原 Session/start/Bearer
授权不覆盖这一目标。issuer 在 claim 前/后及 owner continuation 逐次重核。

## 同一原 Store 的占用

agents.first-session-attempts 是原 DomainStore 内的占用投影，不建立输入库。
ID 固定为 NodeRef＋完整 UnitRef 摘要，不含 draft/requestId。reserve_operation
同事务写原 draft 占用、首次占用和 OperationIntent；任何 Domain CAS 或操作写
失败均回滚。占用保存原 principal/request/op/inputDigest/provider/epoch/native
correlation 与版本绑定。claim 重读同一原操作占用，再交原 issuer claim 一次；
核心不读输入文本、不发送原生输入。

原请求重放读取已固定操作，不刷新 native 观察或创建新输入。其他 draft/key、
refused/cancelled terminal、仅观察到 Session，均不释放占用。Session 路径也检查
同 Unit 占用，不能把 unknown 首输入改成常规 Session 输入。错/损坏来源 typed拒绝。

## 下一切片及崩溃窗

当前所有首次占用仍 held。尚缺原 UnitRecords record-only Session association、
原输入作用已知证据的验证与原 publication/Usage 转移。不得通过删除占用或仅
检查 old.status==published 代替这些缺口；因此本阶段不是可继续多输入的产品。

后续复用原 record_operation_step/publish_operation，不扩存储协议：owner 的
association 与输入作用证据分别核同原 attempt；concluded step 时保留占用；
publish 同事务 CAS 原操作和占用、将全部 operation-held Usage 转固定 Node，
写原 Session 关联来源。后续输入核对原出版结果/step/association。仅 Session
身份证明不算原输入作用已知，更不算任务完成。

owner journal 与 core SQLite 不是同一事务。owner association 写入后崩溃、
step concluded 后出版前崩溃都必须保留占用，只读原 query 恢复数据出版，不重发。

## C 反例与边界

test_sessionless_input.py 使用真实临时 SQLite/Core/Issuer，capture/native观察/
authority 仍受控，无输入 writer、owner association、实际进程或模型。
覆盖完整 Unit 目标、Session-only grant 拒绝、跨 draft 占用、terminal 不释放、
Session 观察不改路、来源/epoch/目录变化、bool 冒充来源、原请求重放与回滚。
两个独立 Environment/连接使用同一个显式测试 writer owner，先同步读 absent
再竞争原 Domain CAS，只有一个操作及两种占用持久；不同 writer 被原锁拒绝。
该测试不授权生产 second writer/takeover。

新 bool 反例证明原 InvocationIssuer provider/grant target 字典比较接受 True==1，
现用 safe_json 保留完整引用 JSON 类型；可空引用用 mapping 包装编码，原 grant
与 cleanup 来源及 admission/continuation 语义保持。没有删除原测试断言。

命令、计数、退出码及中间失败见 status.md。P 未验证，M0；生产 owner/authority、
原生 writer fence、association 和发布仍缺，整体 AU002 PARTIAL。
