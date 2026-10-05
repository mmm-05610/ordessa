# 原 Unit journal 的无 Session 确认接缝

版本 `harness-unit-confirmation/1`。这是 Harness owner 内部证据投影，不改变
core agent-runtime/2、公开 wire 或 Session 身份合同。主会话持有共享写权。

`UnitRecords(..., native_unit_evidence=port)` 显式可选；缺端口时 `begin_unit`
在消费 start 前拒绝。沿同原 journal/UnitReservation/ScopeAuthority/Issuer：

- `begin_unit(unitId, original_start_context, input_digest=...)` 同事务预留 opening；
  原 start 只消费一次，并签发原 `_tickets` 中独立类型 UnitRecordTicket。
- `record_unit(ticket, expected_source_revision=..., state=unknown|confirmed, evidence=...)`
  重核原 Unit、epoch、关联和摘要；确认依赖下述 owner，unknown不释放占用。
- `read_unit_confirmation(unitId, query_context, input_digest=...)` 经原授权读取，
  返回 NativeUnitBinding；每次 confirmed 读取重新向原 owner 验证证据与当前存活。
- `reconcile_unit_confirmation(unitId, original_start_query_context, input_digest=...,
  expected_source_revision=..., evidence=...)` 只读核实原作用后更新观察；
  绑定原 request/operation/step/摘要并做原 revision 比较，不签发 ticket、不再次启动。

NativeUnitEvidencePort.verify_unit_binding(unit, original_creation_correlation, evidence)
必须核实实际受拥有的进程和同一运输、固定安装与隔离根、原 start、原 initialization
成功及当前存活；ACK、目录存在、SDK get_server_info 缓存或 requested session 均不足。
它只返回如下来源引用，不返回命令/路径/凭据/原生配置副本：
contractVersion、unitRef（原 public_ref）、creationCorrelation、processRef、transportRef、
initializationRef、evidenceRef。后四者沿已有来源形状：environmentNamespace、
ownerProviderRef、sourceRevision、ref，必须与同 Unit owner 相符且类型敏感。
引用结构校验不替代 owner 的实际证据验证；缺生产 owner 保持 unsupported/PARTIAL。

新增表 harness_unit_confirmations 在原 OperationJournal 内，原 UnitId 与 scope/key
不变；不新增数据库、操作系统、权限来源或可自行变化的 actual state。原
harness_unit_sessions、record_session 和实际 sessionId 验证保留。NativeUnitBinding
不是 NativeSessionBinding，确认无 session Unit 时原 Session 仍 notCreated。
两条 start 在同 SQLite BEGIN IMMEDIATE 下互斥，不允许 unknown 换路径重启。
notCreated 只能 revision1、opening 只能2、unknown/confirmed至少3；孤立digest与
损坏版本拒绝，不能切换 Unit/Session 路径重置。原 session codec 同步此完整性检查。

本次未迁移用户数据库。历史 Unit 若没有新确认行，不自动补造，新的 Unit 确认
入口拒绝证据不足；原 Session 仍按原合同读取。生产历史证据迁移未验证。

剩余接缝：sessionless Unit 后首次授权输入观察到真实 session，仍需沿原 InputAttempt
与 native 证据作 record-only association；不能再 begin_session/start 或制造 default ID。
本冻结不实现这项，也不证明首输入接纳、connect、配置、stop/release 或真实 Claude SDK。
新测试为真实临时 SQLite/Issuer 与受控 owner C，P/M未验证；精确结果记在 status.md。
