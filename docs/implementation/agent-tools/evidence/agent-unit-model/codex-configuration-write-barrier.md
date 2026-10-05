# Codex 原配置 dispatch 的实际写入屏障（C / PARTIAL）

2026-10-05，起点8da9c5dad0d87767d6018cf49c47fd5242b03846。
沿原 `CodexRuntimeProvider.apply_configuration`、`UnitRecords.bind_configuration_dispatch`、
同 ConfigurationRecordTicket 与 native expectedVersion；不改公开 wire、scope、身份或 journal。

原 command_once 在 transport 锁外执行 before_send，随后 send_raw：即使原配置 owner 在
hook 内重核当前权限，也不能防止 hook 到实际写入之间 writer 切换。本次固定原 RPC
字节，在 send_frame 实际 stdin 锁与原 lease 校验内执行原 before_send。它仍收到 detached
完整 native request，不会修改写出的原字节。provider 的 revalidate→journal bind→revalidate
现在落在实际 IO 屏障内；原 canonical request digest 口径不改成输入帧摘要。

缺 send_frame/mark_input_unknown/acknowledge_frame 在分配 ID、调用 hook 前 typed拒绝。
明显无效 turn/start 目标在消费 journal 绑定前拒绝。hook 成功才登记本客户端 pending/ACK
等待及 admitted 标志；transport 原 live IO 登记仍在原锁内、guard后、实际write前。
已知 native error 必须来自 admitted 的原 ID/method 且原 pending/ACK 等待已由接受回执清除。
guard 抛 CodexRpcError 而 pending尚空不能误报已知回执。原异常保留，unknown cut 不清除。

新增12项客户端C，含缺三端口、同ID/foreign guard异常、已知原生拒绝、实际guard撤lease、
等待receipt中revoke＋late ACK，以及无效turn目标。原5项command_once测试改为观察实际
send_frame调用；仍核 bind→send顺序、同native ID/payload、无IO/empty pending、不可修改
实际payload、timeout保原ID与读回执不重发，另核late receipt不开放下次guarded write。

新 `test_codex_configuration_barrier.py` 三场景使用原真实 UnitRecords/SQLite journal 与
临时Python peer：guard内独立journal read确认原ID/digest已经commit且尚无native字节；
ACK-only仍不能确认配置效果，receipt-lost与bind-then-fence保原unknown。原 attempt1→
bind2→unknown3 保留原Unit/scope/操作身份，第二请求不能替换原scope占用；不保存actual值。
其授权/Session/native evidence owner仍是原受控fixture，不是Core真实Issuer/生产配置证明。
首跑三个新测试误用fixture的 evidence字段，而真实NativeConfigurationAttempt字段是
confirmation，3F已记录并改为核真实 confirmation=None，没有删除无确认断言。

真实Codex P/M、生产配置receipt/effect evidence、部署Directory/Invocation与lease绑定、
冷恢复仍未完成。本次只修现有配置 effect dispatch 接缝，不宣称所有native读RPC已持有
跨域权限fence。单独变更权限bool不撤销已持有IO，生产owner须协调显式writer cut。

下一输入owner盘点：生产capture保存/原字节读取与原持久receipt/effect owner尚缺实现，
不把ControlledInputCapturePort.inspect测试fixture当生产保存服务。当前Codex provider
start原生thread/start已创建thread，普通Session turn/start可沿原prepared路径接线。
若只initialize、不建thread，turn/start要求threadId，而先创建thread与原首次帧/correlation
的两步映射尚未冻结；保持sessionless Codex不支持，不把thread创建ACK当原turn作用证明。
