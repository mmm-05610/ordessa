# Data model：定义不是连接，工具可见不是授权

## 实体

```text
McpDefinition
  serverScope, definitionId, nativeName, transport, archived, latestRevision
McpRevision
  definitionId, revision, canonicalDigest, source, approvalRecord,
  stdio { executableRef, argv[], cwdRef?, env: map<name, Literal|SecretRef> }
    | remote { url, header: map<name, Literal|SecretRef>, authRef? }
  protocolExpectation?, createdAt
McpAssignment
  serverScope, principal, scopeKind(user-default|project|profile|session),
  scopeId, harnessId|any, definitionId, decision(enable|disable),
  approvedRevision?, toolSelection(allowNames|allObserved), rowVersion
McpEffectiveSnapshot
  targetSession, runtimeGeneration, projectId, profileRevision,
  definitionRevisions[], assignmentRevisions[], credentialRefRevisions[],
  allowedToolNames[], laneByDefinition[], snapshotDigest, submissionId
McpConnectionLease
  leaseId, targetSession, runtimeGeneration, definitionId, revision,
  lane(native|managed), ownerId, principal, credentialRevision,
  endpointFingerprint, state, startedAt?, closedAt?, cleanupEvidence?
McpToolCatalog
  leaseId, observedAt, protocolVersion, serverInfo, toolNamesAndSchemaDigests[],
  catalogDigest, sourceEvidence, status
McpToolCallDecision (owned by Permission, referenced here)
  principal, sessionRef, leaseId, toolName, argsDigest, decision, policyRevision
```

`serverScope` 区分不同后端实例，同名项目或 Profile 不能跨实例串写。所有 mutation 以 principal、serverScope、目标、操作键和 payload digest 做 CAS/幂等；同键不同内容拒绝。ID 不通过名称/URL 推导。旧 `server_assets` digest 保持可验证，迁移时新旧 canonical 规则若不同则存旧摘要与迁移映射，不无声重算。

## 作用域合并

解析顺序与 Skills 一致：`user-default/any → user-default/harness → project/any → project/harness → profile → session override`。`inherit` 是无记录，`disable` 显式遮盖，`enable(revision)` 需批准的不可变修订。后一层可重启用前层禁用，但必须仍符合管理员禁令和项目权限。Profile 属于确定的 Harness；当前会话不换 Harness。一次显式 Profile 切换会清除本会话临时覆盖，选择待下次用户提交生效，不打断输出。

工具选择不是任意名字白名单盲传：`allowNames` 必须逐项属于本修订获准且实际发现的 catalog；新发现工具默认不可调用，catalog schema 变化使旧快照待重验。`allObserved` 仅适用于用户明确接受**当前 catalogDigest**，未来新增工具不自动加入；不能把新工具天然当允许。原生客户端若无法限缩暴露集合或调用权限，必须降格为“显示可见但安全策略未能执行”并在严格要求下拒绝应用。

## 托管权与隔离

一个 `(runtimeGeneration, sessionRef, endpointFingerprint)` 最多一条 active lease，且 lane 互斥。native lane 的 stdio 子进程由 Harness 原生 client 拥有，本插件无权限杀其 PID；managed lane 由本插件 process/transport manager 拥有，不能再下发 native MCP 配置。远端服务不属于 Ordessa，lease 只拥有本地 client/session；HTTP 连接关闭不代表远端服务被删除。

首版默认**不跨会话池化**，包括同一用户相同远端 URL。共享风险不仅是凭据，还包括 MCP 会话状态、roots、请求关联、工具目录和取消；今后若有收益再以 principal、项目授权、凭据修订、实例版本、能力事实和 server statefulness 的安全证据设计池化。不能用 URL 相同就共用 stdio 进程。

状态：`defined → selected → planned → connecting → connected → catalog-observed → closing → closed`，另有 `refused`、`unknown`。每个阶段单独事实与证据；失败后未知的连接/进程先 reconcile 再重试，不创建第二租约赌旧的已经退出。工具调用的许可不在此状态机内。

## 秘密与留存

`SecretRef` 引用既有受控 credential service，MCP 不建 vault。后端只在受控启动或请求瞬间解析；前端和持久定义只见 ref、状态与版本。普通 env/header literal 可保存，但不得含被显式标记为 secret 的槽；迁移旧版 `credentialRef` 原样保留。凭据轮换、撤销或服务切换使未应用 plan stale，活连接按服务能力受控关闭/重连；不把明文写入配置生成文件。持久审计只保留 ID、摘要、批准和结果，不保留环境/响应正文。

Profile/项目删除或插件 UI 卸载不删除 `McpRevision`；活 lease 和历史快照引用版本期间禁止物理清理。归档只阻止新分配。业务后端卸载时若有活 lease 必须 busy/refuse 或先完成可信 drain；不能卸载后留下无 owner 的进程。
