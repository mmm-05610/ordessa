# 015 非秘密材料纯合同实现冻结（phase 1）

依据用户采用material-authorized-capability-proposal.md与028 contracts §4/7/9。本阶段只实现下述不可变DTO与同一资源provider对象的可选Protocol，不获取、不建立Usage、不接Assembly、不启capability。权限唯一使用现有InvocationIssuer/Verifier，不新增MaterialAuthorizationPort、authorizer或权限真值。

## 编码规则

模块agents/materials.py，版本常量AGENT_MATERIAL_CONTRACT_VERSION=`agent-material/1`，公开经agents.public再导出。MaterialContractError/MaterialUnavailable只给稳定安全原因，不拼接拒绝的原值。所有DTO frozen，严格from_dict/to_dict camelCase闭合字段；嵌套值深复制成冻结类型，不与调用者/宿主事实共享对象。所有namespace相等校验、非空/有界文本、整数禁止bool、版本精确非空、不允许latest/通配、digest使用原step的64位小写hex；内容摘要使用sha256:加64位hex。只接受下述字段，没有payload/正文/path/command/SecretRef/bytes/callable扩展口。

## 引用、固定来源和使用目标

- ResourceRef(environment_namespace, provider_id, contract_id, resource_id, revision)：稳定资源身份，contract_id使用原C1版本合同规则。不把易变activation放入Profile资产身份；不从任意payload猜路由。
- MaterialProviderPin(provider_id, provider_version, owner_activation: ActivationRef)：单独固定本次trusted host提供者来源；复制ActivationRef字段，不接受provider自报替代。pin ID与ResourceRef provider一致，环境也一致。
- MaterialUseTarget(node_ref: ParticipantInstanceRef, directory_binding_ref: DirectoryBindingRef, management_epoch: int, purpose: str)：首片消费目标为精确Node（prepare已有planned Node）；类型本身不证明Node已发布/有权使用，phase2须核对原intent。purpose不为空、参与授权与digest；管理epoch非负，目录/Node/资源同环境。Unit/configuration owner实际消费仍在领域侧，DTO不替代真实目标证据。
- MaterialCorrelation(operation_ref, step_id, recovery_correlation, input_digest)：同原Operation/Step的固定关联，input_digest为64hex；DTO不查询Store，phase2必须与原Step逐字段匹配。不得以新C1 execution账解释关联值。
- MaterialObjectRef(environment_namespace, material_id, revision)：授权局部交给owner的不透明不可变材料身份，不承载材料正文或原生路径。本文opaque id不会被核心当宿主路径/执行命令；不能声称能识别藏在合法opaque字符串里的秘密语义。
- MaterialEvidenceRef(environment_namespace, reference_id, revision)：provenance/evidence的安全引用，闭合编码referenceId，区别于可交付MaterialObjectRef；同环境、无正文、不是权限或实际消费证据的自动证明。

## 能力、描述及请求

- MaterialCapability(contract_version, lifetimes, query_acquire: bool, release_recovery)：contract_version必须本版本；lifetimes是非空无重复规范tuple，仅copyComplete/runtimeRequired/dynamic；query_acquire必须显式bool（不能缺省支持）；release_recovery仅queryable/idempotent/both/unsupported。query_acquire=true承诺即使获取回执丢失、无lease/handle，也按原request精确ref与step correlation覆盖查询；只有唯一核实receipt才success，无法证明原请求零作用时统一unknown，不把未找到当refused。这些是能力声明，phase1不据此宣称真实消费/恢复已证实。
- ResourceMaterialDescriptor(resource_ref, material_type, schema_version, content_digest, lifetime, access_mode, provenance_ref: MaterialEvidenceRef, evidence_ref: MaterialEvidenceRef)：只非秘密；lifetime取上表，access_mode只readOnly/effectful。descriptor_digest属性由上述安全to_dict规范哈希得64hex，不允许caller声称摘要替代内容。证据引用同环境；描述是纯描述，不创造材料。
- MaterialRequest(resource_ref, provider_pin, target, descriptor_digest, correlation)：resolve和原请求查询共用，query不要求lease/handle。input_facts()仅包含resourceRef/providerPin/target/descriptorDigest，input_digest属性为其safe_json规范SHA256；correlation.input_digest须等于该计算值。operation/step/recovery关联仍独立钉住，由原issuer与Store验证，不能用DTO自证已claim。

## 回执、租约及闭合结果

- MaterialLeaseRef(lease_id, resource_ref, provider_pin, target, acquisition_correlation)：固定原获取关系，全环境/identity交叉校验，不是权限。只携带安全opaque lease ID。
- MaterialReceipt(resource_ref, provider_pin, target, correlation, descriptor_digest, immutable_material_ref: MaterialObjectRef, content_digest, material_type, schema_version, lease_ref: MaterialLeaseRef, provenance_ref: MaterialEvidenceRef, evidence_ref: MaterialEvidenceRef)：全部来源/获取关联/lease关系一致，同环境，content_digest有效。receipt只证明provider报告了固定材料关系；实际消费独立，不能据receipt自动release。
- MaterialResult(outcome, correlation, receipt=None, error_code=None)：success必须receipt且correlation一致，无error；refused只有稳定安全error_code且无receipt，承诺零作用；unknown两者皆无，不造租约/空材料。error_code为最多64字符的大写字母/数字/下划线稳定码。不默认unknown为success。
- MaterialReleaseRequest(lease_ref, correlation)：释放是新的具名step关联；lease仍保存原获取关联。input_facts()精确返回{'leaseRef': lease_ref.to_dict()}，不含新release correlation，input_digest属性为safe_json(input_facts())规范SHA256的64hex，correlation.input_digest须精确匹配；权限使用原action=release、cleanup上下文，不能复用获取票据。本阶段不签发该上下文。
- MaterialReleaseResult(outcome, correlation, error_code=None)：success/unknown无error，refused仅稳定安全code；该result不修改Usage，不宣称资源已释放。

## 唯一可选端口

AuthorizedMaterialProvider是同一原C1 ResourceProvider对象的结构可选能力，无新注册中心。property material_capability返回上述MaterialCapability。方法：describe_material(resource_ref, principal)->ResourceMaterialDescriptor；resolve_material(MaterialRequest, InvocationContext)->MaterialResult；query_material(MaterialRequest, InvocationContext)->MaterialResult；release_material(MaterialReleaseRequest, InvocationContext)->MaterialReleaseResult。采用原InvocationContext类型，provider作用前必须用原Verifier验证；phase1只声明签名，不实现任何假成功body。

read_material_capability(provider)仅读取声明并检查版本/四方法callable，缺声明typed MaterialUnavailable，声称能力但形状错typed MaterialContractError，不能fallback旧C1 acquire。复制能力DTO避免别名，不返回provider对象。它不是注册准入事实；phase2将声明加入014同Registry原stage snapshot、commit/read重验，不以此helper绕过Host身份或授权。缺query_acquire或release恢复不足由后续保证门拒绝所请求保证，不在纯DTO层偷偷升级声明。

## 反例、分级和下一阶段

结构正例/roundtrip、深冻结/无别名、跨环境/错pin/错目标/损坏digest/多余字段/secret或path/command载体拒绝；refused/unknown禁止带receipt或错误正文，query无需已知lease、不得调resolve；旧C1对象无新能力仍旧注册/二元lookup正常，新helper缺席拒；假声明/缺方法/未知版本拒。原Invocation接口参数同一性有合同检查。以上只单元/纯合同，不冒持久授权、实际获取或消费。

phase2才接同Registry能力准入、原Agent Operation/Step/Invocation/Usage和原correlation查询；phase3按copyComplete/runtimeRequired/dynamic分别以真实owner消费/停止/切换证据验证生命周期。不得用当前元数据绿或纯DTO绿填这两阶段。
