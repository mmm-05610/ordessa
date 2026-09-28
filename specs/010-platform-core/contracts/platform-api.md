# Platform Public Contract v1

## C1 Pacthold public entry — A

新增 pacthold.public 稳定入口，仅本包中性实现。第一检查点交付类型/签名/契约测试，无成功空桩。

```python
CoreRuntime(store: CoreStore)
CoreRuntime.stage(owner: str, contributions: CoreContributionSet) -> CoreRegistration
CoreRegistration.commit() -> None
CoreRegistration.rollback() -> None
CoreRuntime.owner_busy(owner: str) -> bool
CoreRuntime.unregister(owner: str) -> None
CoreRuntime.close() -> ShutdownReport
```

CoreContributionSet 只含 contracts/resource_providers/execution_providers。stage 校验冲突/版本/依赖、无外部副作用；commit 后可用。rollback 幂等撤销未被执行使用的本批。宿主冻结激活期间请求接纳，禁止半发布被消费。unregister busy 明确拒绝。
ShutdownReport 列 unresolved executions/leases 和 cleanup failures，close 不隐式杀运行；Store 关闭前落未解决事实。

```python
ResourceProvider.describe() -> ResourceProviderDescriptor
ResourceProvider.acquire(request: AcquireRequest) -> AcquireResult
ResourceProvider.release(request: ReleaseRequest) -> ReleaseResult
ResourceProvider.reconcile(request: ReconcileRequest) -> ReconcileResult
ExecutionProvider.start(request: StartRequest) -> StartResult
ExecutionProvider.observe(handle: RunHandle) -> Observation
ExecutionProvider.stop(request: StopRequest) -> StopResult
```

descriptor 明示 reconcile 能力，不支持 typed unsupported。请求含 operation_key、execution_id、声明的已解析输入；结果用成功/明确拒绝/未知判别类型。prepare/validate 禁 spawn；borrowed 不释放原对象。
运行入口 submit(plan)、query(execution_id)、request_stop(execution_id, operation_key)。使用既有 Work 关联，不默认建 Profile/Session。provider 不获得整个注册表。A 在契约检查点补齐 DTO 可导入字段与正反测试，B 不得自造类型。

## C2 Server contribution carrier — B

server-plugin-api 零运行依赖。Registration 增 contributions，每项 point_id/api_version/payload/required，owner 由宿主注入。处理器 stage/commit/rollback；required 缺失拒绝，optional 缺失可观测。
固定点 pacthold.contributions v1，payload 为 C1 CoreContributionSet。apps/server 的中性适配器是唯一 Core 注册接缝，同插件 build/dispose 一次。
服务查找按 requires 授权，新 carrier 不绕过冲突/依赖守卫。删除业务 runtime 门面，测试改合法服务注入。

## C3 Discovery / HTTP — B

宿主保留 serverId/protocolVersion/capabilities/auth；领域贡献 field/version/read-only projector。字段独占，基础字段不可覆盖。原 harnesses/nativeExecution 形状与缺席行为按基线 golden tests 保持，语义校验移插件。
HTTP 冻结 path/methods/owner/auth/请求签名。未挂载或不同形状 typed refusal，不换 App；请求从活跃注册表取 endpoint。保留 HTTP/WS 鉴权与错误清洗。

## C4 Frontend API — C

Workbench → packages/workbench；ordessa.workbench ID 保持；@ordessa/workbench/api 无 UI/业务副作用。Token 仅一处构造，消费者和 shared-module 打包映射同批更新。
平台仅通用协议；Agent 协议类型归 connectors/acp 轻量 API，Chat 贡献归 Chat，Server 客户端契约归 connectors/ordessa。Connections 通用契约及机制归 packages/desktop-platform/connections，旧 AgentConnections facade 归 plugins/agent/connections，详见 C6（connections-platform.md）。公共 API 不导入 runtime entry。
实现插件未启用时 API 仍能导入，不能通过需 enabled 才有的 URL 暗中强制启用。真实构建测试证明。Commands 本批不迁；native IPC 名称/授权不变。

## C5 Compatibility Ownership

A 迁旧 pacthold 领域模块到 runtime-compat 并列导入映射；B 更新现有 Python 插件消费者/产品装配。B 不往核心加 alias，A 不改现有 Harness/Profile；C 保持 main 前端，不并入其他树业务。
