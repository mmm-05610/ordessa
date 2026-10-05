# AU001 接口冻结映射（AU-1）

工作基线为接纳检查点30c4ef5ac0，原观察3086825a61保留历史。仅主会话共享写；旧三执行者已结束。此文件是实施映射，不改用户合同。

| 已有接缝 | AU-1映射与保证 | 不足时行为 |
| --- | --- | --- |
| AgentContributionSet / CoreRegistry | 同registry stage/commit/rollback/drain/retire；新增管理方法使用agent-runtime/2，明确拒新接纳/1，supportedMethods默认空、按项显式声明 | typed拒，不fallback旧ExecutionProvider |
| RuntimeProvider inspect/plan/prepare/start/query | 原签名保留；Unit由provider持有，prepare/start各自InvocationContext和持久step claim | missing/unknown不再次创建 |
| RuntimeProvider.describe_access/connect | unitRef与平台授权lease，保持原生payload；平台必须覆盖入口全部副作用 | 不能fence或权限不足拒入口 |
| describe_configuration(unit_ref) | tuple[ConfigurationDescription]：kind/schema/inputSchema/actions/scope/modes/confirmation/supportStatus；没有品牌枚举 | unsupported/unknown显式，方法存在不报supported |
| inspect_unit(unit_ref) | UnitInspection只读owner来源：unit/provider/配置target、DirectoryBinding、epoch、owned/borrowed/unknown及观察证据；不建立原生状态机 | 缺完整来源拒管理，不默认owned |
| inspect_configuration(unit_ref) | ConfigurationSnapshot：owner实际unit/scope/sourceRevision/observedAt/facts/unknown/evidence/comparisonGuarantee | 不可观察字段unknown；不从Profile填空 |
| apply_configuration(unit_ref, change_request, invocation_context) | ConfigurationChangeRequest→ConfigurationChangeResult；实例及principal在context，requestId/expected native revision/declarations/policy在正文 | ACK不构造applied；unknown只query |
| query_change(unit_ref, operation_ref, authorized_read_context) | 返回同操作ConfigurationChangeResult；只核实，不执行/创建/重发 | 无原生核实能力返回unknown |
| 核心stop/release/recover | 原InvocationContext、OperationStore、Usage与Directory重核；stop/disconnect/release分别处理 | borrowed不kill，未知不释放破坏资源 |
| ProfileCatalog | 旧harnessDefinitionRef/declarations、双revision不变；配置修改复用同声明校验 | Profile改动不自动apply；unit改动不保存Profile |
| ConfigurationAdapterDescriptor / intents | 现Harness API的claims（file/directory/field/action）及validate/compile/verify用于provider内部落地；独立provider持有自己的adapter集合 | 未满足claims必拒，不共享大Harness registry作为新核心 |
| C1 ResourceProvider | CoreContributionSet.contracts/resource_providers、supported_contracts，describe/acquire/release/reconcile与原AcquireRequest/ReleaseRequest/ReconcileRequest | acquire须具名step与授权；unknown不猜lease或盲release |

资源及配置kind接纳复用同CoreRegistry的版本化frozen contract和ResourceProvider.supported_contracts；不新增ConfigurationMaterialProvider注册中心。Agent装配直接协调原具名OperationStore steps，不另调CoreDispatch启动第二执行引擎。required/optional与owner配置schema关联；缺required资源发前拒，optional省略逐项明确。AU002实现必须核查C1 resource调用前的Invocation授权与固定acquire参数，不能把旧execution_id当新Node/Unit身份。

## scope / CAS保证

| source comparisonGuarantee | 可承诺范围 | 不能承诺 |
| --- | --- | --- |
| nativeAtomic | owner声明且版本匹配的native compare与写 | 未实测版本/安装不能声明nativeAtomic |
| ownerSerialized | 同一owner规范target内管理写串行、写前检查已确认revision | native外部修改者不受锁约束，不能称强CAS |
| unavailable | 只有不完整/不可比较观察 | 拒绝要求expectedConfigurationRevision的作用；不合成版本 |

sourceRevision作为不透明owner确认版本，未知可为null且comparisonGuarantee必须unavailable；不能用catalog/manifest/Node publication revision替代。迟到证据必须由owner判断可比性；不可比保持独立证据及unknown，不按接收顺序覆盖当前观察。核心存操作结果/来源，不能运行第二actual配置库。

## Python及wire版本

Python唯一定义在pacthold.agents.configuration，经pacthold.agents.public导出。agent-configuration/1不可变DTO支持value/reset/disabled、required/optional和SecretRef；applicationPolicy默认allowDeferred=false/allowRestart=false。applied item必须包含operationRef/unitRef/scopeRef/requestDigest/evidenceRef；部分结果overallOutcome=partial，逐项保留unknown/conflict等，不自动补偿。

唯一wire定义仍为agents/schema.py::wire_contract(version)。原默认agent-assembly/1的Profile合同与digest保持；显式agent-assembly/2才包含新管理面，AU004将按v2生成客户端镜像及接宿主。未接线时capabilities保持false。新版本注册不改已有provider/family/data-root/DB标识；历史v1引用可读取，不能隐式改成v2或用新Provider冒旧native实例。

| CLI冻结命令 | wire/1方法 |
| --- | --- |
| providers list / describe | agents.providers.list / describe |
| nodes prepare / list / inspect | agents.nodes.prepare / list / read |
| nodes configuration describe / inspect / apply / query | agents.nodes.configuration.describe / inspect / apply / query |
| nodes apply-profile | agents.nodes.applyProfile |
| nodes connect | agents.nodes.acquireAccess；获得授权入口后通用连接，不解释品牌 |
| nodes recover / stop / release | agents.nodes.recover / stop / release |

apply参数只有nodeRef＋change；change精确包含requestId/expectedConfigurationRevision/declarations/applicationPolicy。其它副作用方法按schema使用requestId；调用者身份来自认证realm，正文不含grant/principal。NodeRef保持environmentNamespace/instanceId/generation。附着资格不是provider owner身份；disconnect仅关闭连接，不提交stop/release。

## 证据门

结构测试只证明编码、不可变性及拒绝反例；不能证明提供者应用成功、scope竞争、原生版本CAS或迟到读回。AU002接真实OperationStore及InvocationIssuer，AU003接各家生产owner，AU005分别记录C/P/M。当前AU001不满足整体A15（品牌客户端尚未迁出），不发布Agent任务可用。
