# Codex 提供者与原 UnitRecords 的 C 层纵向验证

工作基线 e157765da846b41720fe288df9837eda1058c625，主会话唯一共享作者。
`test_codex_assembly.py` 使用真实独立 CodexRuntimeProvider、Environment/CoreRegistry、
ProfileCatalog、AgentAssembly、InvocationIssuer、NodePublication 和 UnitRecords。
核心与原 Harness journal 使用各自现有 SQLite owner，不增加操作系统、配置真值或注册中心。
原生客户端、authority、directory/scope 和观察端口是明确的受控 fixture。

固定 Profile → 原 prepare claim → 原 Unit 预留 → 原 start claim → opening →
受控 initialize/thread/start/thread/read → 原 session ticket 确认 → Node 发布。
发布的 Unit 引用及配置目标直接来自原授权 journal，两个占用沿原核心事务转移。
读取由同一 fixture 已认证 request 的原 Issuer.issue_query 授权，并经 UnitRecords 原入口核对；
这些测试端口不能作为生产部署实现，不授权以原创建者身份代理其他当前调用者。

十项场景：正常发布及同请求重放；丢回执后的 unknown 与原查询不重发；
同 request 改 options 冲突；thread/read 替代身份拒绝；initialize 后 authority、
activation、directory、epoch 四种失效均阻止下一个原生调用。
epoch 失效也阻止旧 ticket 写 unknown，因此原 opening 占用保持。
prepare 已持久预留后丢回执，原 query 可确认同 Unit 而不派发 start；显式 prepare
才继续未派发步骤。另一个合法请求访问同物理 scope 时，实际进入原 UnitRecords
并因 scope 已预留被拒，原 unknown 保留；不以 fixture request 断言代替该门。

不证明真实 Codex 进程、官方版本兼容、OS 隔离、真实模型任务、生产原生 writer fence、
持久 native receipt 冷恢复、跨 principal 授权、stop/release/connect 或材料/SecretRef 接线。
fixture 的 source() 原生证据引用不作为生产签发算法，受控回执不当作真实 P/M。
完整命令与失败过程记在 status.md，AU003 仍 PARTIAL。
