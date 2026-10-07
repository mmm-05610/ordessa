# Codex 原 owner 纯只读扩展冻结 v1

用户2026-10-05明确授权按 downstream-next.md 扩展 Codex 纯只读接入。它覆盖 python-freeze.md 原有 Existing providers stay unsupported 的 Codex 单家族限定；Pi/Claude 仍不扩展。无真实 Harness 启动／实际应用、收费调用或其他凭据授权。

实现归原 CodexRuntimeProvider，不加 owner／投影／执行器。原 describe_configuration 的默认配置 schema 与新 offer 共用一个原 owner helper，原实例支持状态逻辑保持不变。新增两个版本化公开纯读端口，descriptor 声明 agent-configuration-read/1。

## 固定输入及语义范围

OwnerProposalInput.proposal_data 精确结构为 {declarations:[原 Profile 配置声明]}；使用原 ConfigurationChangeRequest 进行已有 DTO 检查，复用原 _compile_change 编译约束。内部 request_id 用 input_digest、expected_configuration_revision 用 descriptor_revision，仅作为本地 DTO 容器，不调用操作机制／native RPC／journal消费或写入。

唯一已知 checker 为 codex.defaults.compile，版本为原 DEFAULTS_SCHEMA（当前0.157.1）。只证明当前原 owner 编译器接受必需声明；不证明模型存在、安装可用、会话状态、权限、实际可应用或生效。未知 checker/version 或其他 must 义务 => unknown/unverifiable，不猜测实现；advisory unknown 不升级为 mandatory。

原DTO格式拒绝／必需声明 unsupported／必需控制字符／重复字段等原编译实际拒绝 => invalid；optional不支持项沿原compiler具名skipped，不整单改判invalid；编译通过且所有 must 是确切已知 checker/version => valid，validation_scope 固定 codex.defaults.declaration-compile/0.157.1。其余 semantic unknown => unverifiable。若编译有效但没有任何 must 义务，也不能靠空集合成为 valid：返回 unverifiable。

must 回执 sourceVersions 至少绑定 descriptor，输入来源版本从 source_refs 原值得到，使用原 canonical 标识。evidenceRefs 是同 namespace 的版本化、输入摘要绑定的纯读计算回执引用，明确非持久 native 操作证据，不创建 evidence registry。整体 sourceVersions 精确含 descriptor 和输入来源，bool 不当数字版本。

OwnerReadContext 必须是公开 DTO，并与 namespace／providerId／implementationDigest／contractVersion／definition 引用一致；input.provider_ref 与 context.provider_ref 精确 canonical 一致，descriptor_revision 一致。不得接受裸 principal/context，schema或model产生的元数据不授予权限；实际准入和来源复查仍由原核心提供。

## offer 范围

仅提供原 codex.defaults 描述，结构沿原 schema，value/reset 是编译器接受的声明动作；scope instance，native application_modes 不凭静态 schema断言、confirmation none，support_status unknown。complete=false，unknown_items 明示 installation/runtimeReady/unit/application/effect/credentials。已有 describe_configuration(unit_ref) 的真实 supported/unsupported 逻辑不变。

## 验收及代理写权

正例编译／格式反例／必需未知／无must／advisory／权限／来源换代／类型／映射／零副作用由主会话串行验证。只读端口不得调用 inspect_configuration、_read_configuration、start、prepare、connect、apply_configuration、_facts 或 verifier消费；不得网络/文件/进程/UnitRecords写。

执行代理仅修改 plugins/harness/codex/src/ordessa_harness_codex/provider.py 与该家族新纯读测试；不改共享契约、Decision装配、Git、账本。不测试／安装／读凭据／调用模型或再派代理；主会话负责复验。

reset沿原DTO：禁止payload/resourceRefs，编译为全部DEFAULT_FIELDS的null；不是单字段reset。空declarations是DTO invalid，与无must义务unverifiable不同。通用组合器保留原schema并显式支持minProperties/maxProperties、minLength/maxLength和enum-only，其他未知关键字仍unverifiable。
