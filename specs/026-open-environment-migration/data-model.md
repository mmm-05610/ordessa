# L1 数据模型与权威

API名称候选以合同002冻结为准，语义以下不可弱化。

| 对象 | 最小字段/身份 | 权威与约束 |
| --- | --- | --- |
| Installation | sourceDigest/version/compatibleContracts | 装配选择，不等enable或实例 |
| Activation | environmentId/participantId/activationId/generation | Environment唯一创建；旧回调不得撤新贡献 |
| NativeInstance | activationRef/instanceId/instanceGeneration/ownership(owned或borrowed)/scopeEvidence | 原生事实由Harness；环境负责归属 |
| ObjectRef | realm/environmentId/type/ownerInstanceId/ownerGeneration/objectId/objectGeneration | locator非权；跨实例同ID不碰撞 |
| SurfaceRef | activationRef/registrationId/instanceRef/surfaceKind/contractVersion | capabilities原子发布；控制授权不来自纯输出 |
| Activity | activityId/requestId/principal/bindingSnapshot/guarantee/inputDigestRef/phase | 环境投递事实；原生effect不承诺exactly-once |
| Usage | usageId/owner/objectRef/purpose/releaseEvidence | stop新准入不释放既有责任 |
| Receipt | source/identity/sequence/payloadDigest/originalOutcome | 原始不可改，duplicate不解除conflict |
| FactView | authorityRef/revision/sourceCoverage/status | 新证据修订知识；不可伪改原Receipt |
| Closure | rootObligation/cutEpoch/originalScope/allowedRoles/dependencyRefs/budget | 必要收尾不可成为新任务通行证 |
| CanonicalFactTarget | realm/factDomainId/canonicalEntityId | schema版本和contract major不入唯一写槽 |
| OwnerRef | authorityKey/ownerInstanceId/generation/contracts | runtime登记唯一槽，不持业务值 |
| BindingSnapshot | bindingId/environmentId/consumerScope/providerActivation+generation/target/access/contractVersion/revision | 同Environment唯一管理；旧绑定不可写新provider；不返回裸实现 |
| Subscription | subscriptionId/bindingRef/consumerScope/providerGeneration/cursor/credits/status | 核心管理关系生命周期；领域provider负责快照/业务revision；gap须显式 |
| DataArea | areaId/namespace/ownerDomain/schemaEvidence/access/retention | 持久身份不随activation/源码路径变；句柄另绑scope，不内置业务schema |
| PersistentReference | relationId/sourceKey+revision/targetKey+selector/commitEvidence/coverageEpoch | 同Environment持久关系，不随插件停用删除；非Usage/权限 |
| ChangeReservation | operationId/target/changeContract/relationEpoch/phase | 与新关联同准入门，unknown不自动TTL释放 |
| SecretRef | namespace/opaqueId/revision | 不含明文/裸locator权限；可信执行侧借用、单独核权 |
| HostInteraction | operationId/callerScope/generation/purpose/result | UI选择/确认不等访问授权或native审批 |

以上新增行遵守contracts/relationships.md。authorityKind沿用CanonicalFactTarget.factDomainId，不增加平行的第二权威键；API命名002统一冻结。绑定/订阅不是第二份业务状态，生命周期复用Activation/Usage/Activity。

| 领域对象续表 | 最小字段/身份 | 权威与约束 |
| --- | --- | --- |
| ConfigOperation | opId/sequence/target/presentMask/unsetMask/schema/catalogRevision/applicability/payload | 选择时确定顺序；异步解析乱序不改顺序 |
| ConfigEvidence | binding/nativeGeneration/sourceRevision/knownMask/unsetMask/unknownMask/fields | 完整快照与版本链；不完整只lastObserved |
| Draft | draftId/revision/text/attachmentRefs/editorLease | 输入本地epoch与草稿revision分开 |
| Submission | submissionId/requestId/draftId+revision/text+attachments/opIds/baseRevision/target/binding/guarantee | capture后不可因UI切换路由；晚编辑保留 |

## 状态转移

活动：prepared→admitted→dispatching→accepted/known-rejected/unknown；accepted不等原生工作成功，cancel-requested不等stopped。失联只能改变知识状态。没有Store的原生入口可内存记录关联但标non-durable；不宣称重启可靠恢复。

配置操作：queued→resolving→ready→reserved→applied/partial/rejected/unknown/cancelled/stale。未知绑定不自动重新base；同Profile重选新opId。部分应用逐字段记录，不能整体回滚标签。

参与者：installed但inactive→staging→active→draining→retire-pending/retired。失败staging撤贡献但仍处理已产生外部责任。drain后仅批准已有closure角色，拒新任务；borrowed释放Usage而非destroy外部实例。

## 持久化与敏感内容

contracts/recovery.md规定同根writer、跨模式request namespace、域journal与环境Store的握手、附件不可变内容和密钥墓碑；它们是本模型的必需关系，不是可选实现建议。

环境Store的活动与请求占位一个事务/锁域；业务配置journal仍独立领域事实，用correlation衔接，不谎称跨库原子事务。canonical编码版本、算法版本、key_id与来源摘要一并记录。

可靠输入指纹对完整规范输入计算带域分离的受保护MAC（含附件内容摘要/配置捕获摘要/目标）；密钥只通过secret port引用。不能存裸低熵hash代替保护，也不能只裁剪“已知命令字段”。key轮换保旧核对能力，key缺失→未知不可重发，可靠新提交拒绝。具体密钥托管方案工单002/005冻结，不得自行新写明文密钥文件。

普通原生模式不要求该指纹能力，不自动升级到可靠模式；依然要求合法入口和稳定当前请求ID。模式是产品/调用合同显式选择，不在失败后从可靠降级偷发。
