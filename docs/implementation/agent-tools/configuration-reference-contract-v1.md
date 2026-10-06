# 配置提供者与依赖覆盖纯合同 v1

基线4107c32678。依据只读028 contracts §3/§9；这是首片数据合同，不是可调用ConfigurationProvider、Registry准入或编译交付完成。沿独立配置贡献角色，核心不得导入任何Harness/plugin，也不解析配置payload。所有新客户端测试放products/agent-tools。

## 描述与未来可信准入身份

core/configuration_admission.py：`CONFIGURATION_PROVIDER_VERSION = agent-configuration-provider/1`，`CONFIGURATION_METHODS = describe, validate, extract_references, assess, compile, verify`仅方法名元数据，不发布未定义返回形状的Protocol。

`ConfigurationRoute(configuration_kind, schema_version, definition_refs, actions, field_claims)`：kind为小写组件式标识；schema为固定非latest/nonwildcard版本（可含一个/版本段）。definition_refs非空tuple，每项闭合environmentNamespace/definitionId/revision，精确固定，无通配或范围表达，全部同一环境，重复拒；actions非空且唯一，仅value/reset/disabled；field_claims非空唯一opaque符号标识，禁止路径/脚本或任意对象。核心仅把同一符号作为精确冲突键，不宣称能识别原生字段别名/父子覆盖；原生owner最终检查仍必须。

`ConfigurationProviderDescriptor(provider_id, contract_version, implementation_digest, routes, supported_methods)`：显式精确版本，sha256:64hex实现摘要，非空typed routes、无重复kind/schema路由、全部同env；supported_methods唯一且限以上六种，可为缺能力的显式子集，不把元数据存在当实现已验证。

`ConfigurationProviderPin(provider_id, contract_version, implementation_digest, owner_activation)`：复制原ActivationRef、由其派生environment与generation，provider_ref键沿Runtime同形。DTO可由代码构造但不构成准入/授权；只有未来原Registry固定它才是可信pin，本片不建第二registry。descriptor/pin保存/返回均不可变深快照，闭合from_dict/to_dict，无callable/额外字段或覆写序列化执行。

## 逐声明依赖结果

agents/configuration_references.py复用现有agents.materials.ResourceRef，core不反向import它。`ConfigurationReference(reference_id, resource_ref, purpose)`：唯一有界符号id、精确ResourceRef字段快照、显式非空有界purpose；同资源异用途允许但reference_id必须不同。

`ConfigurationReferenceExtraction(declaration_id, configuration_kind, schema_version, action, declaration_digest, definition_ref, provider_pin, coverage, references, error_code)`：固定当前声明及目标definition、provider pin，digest为64hex安全声明摘要；coverage仅complete/unknown，references为typed tuple。全环境一致、重复reference_id拒。complete要求error_code=None；unknown要求非空稳定大写错误码，可携已知refs。只有complete+空refs表示该提供者完整声明无依赖。含Secret或其他本片不能表达的引用必须保持unknown，不能悄悄删掉后返回complete。本片不扫描声明payload验证提供者所言完整。

纯`validate_reference_extraction(descriptor, extraction, *, expected_pin, expected_declaration)`返回字段复制快照；核provider id/contract/implementation、精确kind/schema/action/definition路由；与核心传入的expected_pin精确比对activation/generation/identity。expected_declaration为闭合六键Mapping：declarationId/configurationKind/schemaVersion/action/declarationDigest/definitionRef，同本次冻结声明逐字段一致才可接受，不只验证结果自洽。错pin/路由/声明typed拒。不自动提取/补空结果、不调用provider、不承诺缺provider自动生成DTO；后续组合遇缺provider须保unknown或unsupported，不得以空依赖冒覆盖。

RuntimeProvider身份与其认可端口的关联必须在后续同Registry接纳时由核心固定并验证，本片definition范围并不证明该关联存在/可信。validator另要求descriptor显式声明extract_references，不把缺能力描述当提取结果可用。核心保持requirement/action/路由/目标/版本、Operation/Step、授权/claim/query/replay以及停止释放协调；提供者输出不得改变这些冻结事实。纯DTO的expected_pin也只是调用方提供的比较值，不自行赋予可信性。

错误统一`ConfigurationContractError(ValueError)`。各种集合/引用均有界（route≤64，definitions≤64，claims≤256，references≤256，actions≤3，methods≤6），拒bool替代数值、非UTF8/control字符和非typed引用。输出映射可变副本不得反改DTO。沿现有safe_json/sealed_mapping与公共identity，不借用agents.materials私有helper、不新建truth或作用账。

编码固定：各DTO公开to_dict/from_dict，键为snake_case字段的camelCase；pin投影公开只读provider_ref属性，键沿Runtime同形，pin自身to_dict同该投影且from_dict核派生environment/generation一致。extraction的declarationDigest只64位小写hex，不加sha256:，不由纯validator重算payload；errorCode为`[A-Z][A-Z0-9_]{0,63}`。kind/provider id规则沿Runtime小写`[a-z][a-z0-9._-]{0,127}`；schema version沿Material固定版本形状；opaque reference id/claims `[A-Za-z0-9][A-Za-z0-9._:-]{0,191}`；declarationId/definitionId/revision非空有界≤128无control/首尾空白，definition id及revision拒latest/*；purpose≤256。typed DTO要求exact类，引用按字段复制不调用其方法；tuple集合不能直接接受任意generator或列表。definition和expected_declaration输入Mapping只接受普通dict或sealed MappingProxyType，拒任意自定义Mapping，归一深sealed copy；from_dict只接受闭合dict，list集合显式转换tuple后复验。

公共导出兼容：旧agents.public.ConfigurationContractError不变；新core.ConfigurationContractError在Agent公共面以ConfigurationProviderContractError导出，不替换旧错误类型。

## 本片验收与缺席

正例：route/pin/逐声明固定引用roundtrip，complete空依赖与unknown空依赖保差别，同资源异用途，输入/输出alias不污染。反例：额外键、重复路由/id、跨环境/definition/action/provider错配、latest/*、坏摘要、未知coverage、unknown无原因、complete带错误、可变或覆写序列化对象、未支持方法。

源码/独立测试作者各一Luna，第三Luna只读攻查；root唯一文档/Git/串行实测。原核心依赖guard须回归。资料validator绿只代表资料；纯合同绿只代表数据/校验，不等于引用真实提取、受权读取、编译/应用、Secret、三寿命或真实Harness可用。后续读取已用户批准但本片不实现；编译交付第二项仍待裁定。
