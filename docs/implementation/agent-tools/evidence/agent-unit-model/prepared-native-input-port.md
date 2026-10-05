# 原生输入预分配与实际写入接缝（C / PARTIAL）

2026-10-05；实现起点 ffe569dee03c5a5d9d9467824e71f0a8399df89a。
沿 AU003 家族原生通道及已批准 sessionless 首输入裁决，不新增 wire 方法、核心或输入 ledger。

Codex/Pi 在自己的原生客户端分配真实 `req-N`，分别冻结原生 JSON-RPC / Pi RPC JSONL。
共享 Harness transport 的 `PreparedFramePool` 只管理该客户端有界、不可序列化、一次性 handle；
原生协议与字段仍属于家族。handle 暴露准确 UTF-8 LF 字节、原生 ID、协议与 SHA-256，
这些是 capture 素材，绝不是授权、输入作用证明或 Session 真值。复制、跨客户端、篡改、
关闭后使用和已消费 handle 均拒绝。准备时没有发送、pending RPC 或 durable claim。

可信 owner 的顺序为：家族 prepare → 原 capture 保存完整帧摘要 → 原 Core reserve 固定
capture/nativeCorrelation/完整 Unit → 原 claim 一次 → 家族 dispatch_prepared。
家族消费原 handle，然后在实际 stdin write-lock 和原 writer lease 校验内执行
`before_write(actual_wire_bytes)`。owner 必须核实际字节的 capture 摘要、原生 ID/协议，
并核消费原 opaque InvocationContext、完整 Unit/Provider/input digest 和当前权限。
仅核 Context、不核实际帧会允许把合法 claim 用于别的输入，不能作为生产 binding。
失败也消费 handle，不补 claim、不换原生 ID重发。原 input Operation/首占用保持原未知事实。

transport 在同实际写锁内、guard 成功后、stdin.write 前登记原 `(ID类型, ID) → writer`
的 live IO 项；不是持久表/第二份操作真值。验证原生 RPC receipt 的家族 owner 才可
`acknowledge_frame` 原 ID。裸 channel、ACK 和 writer lease 是可信 owner 内部能力，
不能交给产品调用者。ACK 只清 live IO 项，不确认输入作用、创建 Session 或发布 Core。
原生已知拒绝保持原 error；guard/event callback 抛同一异常类不能冒充已接受的原回执。

等待回执时撤销 writer，即使尚未超时，也在原 transport 锁内 latch unknown，拒绝新 writer。
partial write、guard 失败/在 guard 内 revoke、receipt 丢失等也保持 cut；原 stale lease 的
迟到已知回执允许只移除自己的 IO 项，不清 unknown、不开放接替或重发。初始无效 lease
在进入 guard 前拒绝，不能毒化另一个合法新 writer。unmanaged raw/request/notify 同样受
unknown cut 限制。Pi 的便利输入与 raw prompt/steer/follow_up 不得绕门；迟到 settled
作为原事件保留，但不能把缺原输入 receipt 的 unknown 改为 settled。

`test_prepared_input_claim.py` 使用实际 Core/SQLite/Issuer 与实际临时 Python pipe，
peer 独立计算收到的原字节摘要和大小。capture/Unit/native 状态与 authority 是受控端口。
验证原 capture/claim/native ID/实际 bytes 同一性、claim 后撤权、合法 claim 换帧拒绝、
丢回执不重发。ACK 后原 Core step 仍 possibly-dispatched，首占用 held、跨 draft/key 仍拒绝。
这是 C，不是 Codex/Pi native P 或模型 M，也没有装配生产 owner/effect/Session proof。

仍需生产 capture 与原 UnitRecords/Operation journal receipt/writer/lease 接线、家族 owner
原输入只读证明、Directory/Invocation 部署权限、冷启动核实与完整生命周期。Claude 原生
user input 没有当前 Core 要求的 native request-id；保持不支持，不补造字段或翻译协议。
能力声明不扩张，AU002/AU003 不标 DONE，产品完整 CLI/Skill/发行验收仍继续。

终审补充：纵向反例分离正确 SHA＋错误 ID/ID类型/协议、bool correlation 在 reserve 前拒绝、
正确帧＋异 issuer Context。另验证 guard 核验后由 owner 显式同步撤销 writer，实际写入被阻止。
这证明核验入口及 transport 屏障，不宣称 Core authority 与跨域原生 IO 全程原子：单独改变
授权 bool 不等于撤销已持有的 IO 能力，生产 owner 必须协调显式 writer cut；外部 cut 与
正在运行 guard/写入按原 transport 锁串行，不能声称撤权可倒销已写出的输入。
