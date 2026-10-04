# AT-008 InvocationContext 授权来源提案（来源口径已批准，具体合同冻结中）

## 缺口证据

028 agent-assembly-core/contracts.md §5要求有作用调用的Context由核心可信边界签发/验证，含operation/step、principal/delegation chain、actions/target scope、authorityRevision、provider activation、dispatch claim、management epoch、有效期；correlation不是权限，查询也要当前读授权。§9的CleanupContext只能核实/停止/释放已取得对象，不能启动或应用。

现有 environment-api/ports.py PolicyPort.admit_invoke仅返回bool；Harness application/configuration_service.py PermitVerifier.verify同样仅bool，owner_application可走独立owner路径。它们不能提供上述事实。R-0004只解决Workspace目录用途授权，不授予Harness启动、配置、管理权限。Bearer认证也不补此缺口。

## 建议裁定

复用现有Environment可信宿主配置，显式提供可选InvocationAuthorityPort（名称为本树待冻结端口），由部署权威给出有界grant事实；核心结合当前provider接纳身份、持久step claim、节点management epoch和DirectoryBinding重核后签发只可用于该步的不可变InvocationContext。端口缺席或任何重核不满足即拒绝有作用方法，保留已有claim/unknown事实，不换键重试。现有Policy bool继续负责其原表面准入，不能代替grant。

提出的逻辑端口：

- authorize(request: InvocationAuthorizationRequest) -> InvocationGrant | None
- revalidate(grant: InvocationGrant, request: InvocationAuthorizationRequest) -> InvocationGrant | None

请求由核心从固定operation/step及可信principal上下文构造，包含完整Environment、operation/step、provider activation/generation、动作、完整target scope、management epoch、DirectoryBinding（需要时）及用途；客户端不提交grant或Context。

grant固定principal、delegation chain、允许actions、完整target scope、authorityRevision、有限有效期、authority来源引用；不含秘密。核心Context额外绑定真实dispatch claim标识及固定input digest。每次provider作用前重核grant一致性和当前claims/epoch/目录权限；旧epoch不能继续start/apply。provider通过显式注入的同可信验证边界检查Context，不允许普通调用者构造一个同形状dict获得权限。

查询采用独立当前读上下文。Cleanup是受限动作子集，只针对已取得对象，更新epoch不改变待核实关系身份；不借cleanup路径复活旧start/apply能力。授权端口不管理native session、配置journal或任务状态。

## 实施边界

批准后先冻结具体DTO/签名及可信发布路径，使用受控假authority测试授权不足、撤销、revision改变、过期、scope/epoch/provider/claim不匹配、cleanup越权；这些只是合同测试。没有生产授权来源配置时nodes仍false。真实模型调用、用户配置/凭据与服务更改仍未授权。

Unit/Session配置目标的既有journal迁移与原生correlation映射仍需按028逐项核实，本提案不豁免它们，也不以端口存在宣称实际transport fencing。

## 用户裁决

来源口径已按R-0005批准。尚未接入生产；具体DTO/可信验证边界由主会话冻结，独立审阅后实施隔离合同测试。

## AT-008A 具体基础合同冻结

仅 core `agents/invocation.py` 与隔离合同测试；不增加网络方法或发布nodes能力。以下API是进程内可信端口，不是客户端JSON授权协议。

- InvocationGrant：principal_scope、delegation_ref、actions、target_ref、authority_revision、有限expires_at、完整issuer_ref。引用及嵌套JSON深冻结；issuer/delegation/target须同Environment。
- InvocationAuthorityPort：可信issuer_ref；authorize(request, actions, target_ref, delegation_ref)、revalidate(grant, request, actions, target_ref)。重核必须精确保留principal/delegation/actions/target/issuer/revision/expiry；不能扩大动作或延续旧ticket寿命。
- CurrentStatePort.inspect：返回完整provider_ref、provider_active、management_epoch、DirectoryBindingRef及directory_permitted、已取得target/acquisition_evidence_ref。生产实现必须从可信provider接纳、当前目录authority及持久取得关系核实；bool本身不是外部声明可供给的许可。
- Issuer构造只接部署可信的同OperationStore、authority、CurrentStatePort。issue读取完整RequestKey固定operation/step，核当前provider/epoch/目录与grant，再claim；只首次claimed=True签发Context。claim后重核失败保留花费事实，不制造原生拒绝/零派发证据。
- 固定operation.context_ref使用内部invocationBindings[step_id]，精确冻结action、targetRef、delegationRef、cleanup；context_ref.directoryBindingRef固定完整目录绑定。issue参数必须镜像，不能由调用者临时扩大目标/动作。provider/input digest/epoch来自固定step/operation。
- Cleanup仅stop/query/release，且可信当前状态必须返回匹配的已取得目标和非空完整acquisition evidence；不能传“已取得=true”取代证据，不能借Cleanup start/apply。
- provider只获得受限verify_and_consume面。Context采用issuer私有精确对象身份、不可变内容快照与锁内一次资格消费；拒绝同形dict/构造副本/copy/replace/跨issuer/篡改。验证重新读取实际持久claim及当前grant/目录/provider/epoch；并发只能一个获准。无跨进程密码学认证声明。
- issue_query单独取当前读grant，目标/delegation仍固定step绑定，可读旧epoch的unknown但Context绑定当前读epoch；不能提交作用或消费effect claim。进程重启旧Context拒绝，已claim不重签执行许可；身份内存为空不证明notDispatched。

CurrentStatePort生产取证、provider原生作用前持久correlation、实际运输fence和配置journal仍是后续必需门。受控authority测试不满足这些生产门。
