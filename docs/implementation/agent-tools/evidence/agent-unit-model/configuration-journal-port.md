# AU003 原 UnitRecords 的配置回执接缝

本接缝是提供者侧私有部署接口，不增加wire方法、Registry、DB或配置真值。扩展原OperationJournal同SQLite事务，表名harness_unit_configuration_attempts；只有新隔离数据根会使用，未修改用户数据。

- `begin_configuration_change(unit_ref, context, *, input_digest, expected_revision)`：消费原核心applyConfiguration Context，target为Unit的CanonicalConfigurationScopeRef，epoch仍按原Node核实。只有confirmed native session可接纳；持久opening与原request/operation/step/digest/expectedRevision后发进程内不可复制ticket。重复原correlation不给ticket，其他key遇opening/unknown也拒绝。
- `bind_configuration_dispatch(ticket, *, native_request_id, native_request_digest)`：在真实transport pre-send回调中固定原RPC id及sha256摘要，必须在写入前成功完成；只允许一次。此处不替代每次write授权重核。
- `record_configuration_change(ticket, *, expected_source_revision, state, evidence=None)`：state为unknown或confirmed；revision是本attempt证据版本，不是native实际配置版本。confirmed需要原部署configuration_evidence.verify_configuration；不能传ACK或当前值冒充原回执。unknown保留ticket用于原生迟到证据，不释放scope。
- `query_configuration_change(unit_ref, operation_ref, context, *, input_digest)`：消费原步骤的query Context，核对完整correlation与digest。只读原attempt；重启不发新dispatch ticket、不推断当前值相同等于原操作成功。

原生证据端口 `verify_configuration(unit, identity, native_request_id, native_request_digest, evidence)` 返回且只返回operationRef/unitRef/scopeRef/requestDigest/nativeRequestId/nativeRequestDigest/evidenceRef；UnitRecords核对每项固定身份。提供者负责证明该原RPC原生receipt及有效readback、native expectedVersion前置与作用范围，ACK不能通过此端口。原native evidence必须由同owner持久保存且独立核实，不能调用者造一个相同字典即授权。缺端口时begin发前拒绝；confirmed读回也重核证据。

本切片一次batch对应一个native write；Pi多setter不能把不同write伪装成同一个RPC。本接缝先接Codex config/batchWrite，后续须在原核心固定步骤下逐项扩展原生dispatch捕获。无actual配置值、秘密或完整payload入表，只有固定身份、版本与摘要/证据引用。配置当前实际版本由实例owner串行读取和比较，journal不推算。

Codex独立包新增私有部署端口（不改变上述journal方法）：projection.revalidate_configuration(unit, original_context) 每write重核原已消费事实；显式configuration_evidence须与records.configuration_evidence同一实例。其 capture_configuration(unit, invocation_facts, native_request, native_receipt, before_readback, after_readback, result) 只保存白名单defaults原生请求/确认，返回evidenceRef；read_configuration_result(unit, attempt) 仅读取同原attempt已持久结果。不得把secret或完整native配置日志化；thread与defaults不同事实，不以默认值填补当前thread未知。

共享接缝验证：首跑新＋原UnitRecords 29P/15F exit1、0.63s，原因safe_json拒绝直接整数RPC id；修为requestId字段映射后44P/0F exit0、0.34s。补并发scope、新已确认操作后可接纳、损坏binding拒绝，最终新配置24项＋原UnitRecords23项＋原OperationJournal9项共56P/0F exit0、0.45s。所有断言保留，C层真实临时SQLite及受控可信端口，P/M未验证。

补真实核心Issuer贯通：新增5项，首跑56P/5F exit1、0.71s，fixture未结论记录prepare/start，真实OperationStore正确拒绝后续步骤。按实际有序执行补原步骤concluded（保留门/断言），最终配置29＋UnitRecords23＋journal9=61P/0F exit0、0.66s。验证same原core claim成功消费、原步骤query、重复claim拒绝；授权/activation/Directory/epoch在issue之后撤销，配置attempt没有新增，原possibly-dispatched claim保留。并非真实提供者或实际模型证据。
