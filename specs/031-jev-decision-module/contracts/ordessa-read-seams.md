# 原Agent公共只读接缝增量
状态：拟议接口。以JD007开工盘点为准，若同语义入口已存在则复用，不重复新增。

## 接口及职责
在原Pacthold Agent公共服务提供：
1. describe_configuration_offers(definitionRef, readContext) -> OwnerConfigurationOfferBatch。
2. assess_configuration_proposal(proposalData, sourceRefs, readContext) -> OwnerProposalAssessment。
精确Python符号与现有公开命名风格在JD002冻结映射，语义不得让执行者自由改变。

输入是原核心DTO，不依赖ordessa_decision。包含namespace/definition/provider generation、
固定描述版本和清单/材料引用，不包含model choice分数或策略规则。
核心复用现有准入registry/授权/引用，路由到已接纳owner的纯读端口；
不建立新的provider字典、Environment、operation dispatcher或配置owner。

## 输出
OwnerConfigurationOfferBatch：ownerRef/definitionRef、descriptorRevision/digest、offers[]、
完整性、纯读保证、未知项、证据范围。
OwnerProposalAssessment：inputDigest、相关sourceVersions、valid/invalid/unverifiable、
issues、安全摘要、evidenceRefs、pureReadGuarantee。
Owner回执绑定原核心版本化DTO的inputDigest算法，不假设与decision.proposal摘要相同；adapter同时核对sourceInputDigest和decisionProposalDigest映射。每个必须义务返回具名结果/证据，不只给总体valid。
使用现有ConfigurationDescription语义，额外的组合限制由owner返回；
Unknown配置不能由schema验证升级为实际支持。
pureReadGuarantee是版本化契约声明，不是实测；spy/真实测试证据单列。旧provider不支持新增契约即unsupported，禁止duck-typing私下调用。JD002冻结原核心DTO/摘要向量和版本协商，JD007只按冻结合同实现。

## 安全与生命周期
访问经过当前调用主体的读取授权。读上下文与mutation权限分开；不能任意传principal字符串。
只读评估不调用网络收费模型、不创建实例/目录/临时配置/lease；
如果原生必须启动才能验证，明确unverifiable，不偷偷probe。
提供者退役/换代失效旧描述；核心读取同一公开准入状态，不能cache绕过退役。
跨服务检查不声称原子；返回检查范围，实际应用仍执行owner自己的最终检查。

## 注册扩展
若RuntimeProvider当前只声明assess_configuration但未定义纯读保证，
在原契约新增可选、版本化只读能力声明及对应端口；旧provider不冒称支持。
拒绝从decision外部直接访问admitted.provider；核心内部路由仍归原核心。
新增方法/保证带兼容测试，不能放宽旧prepare/apply事务或unknown规则。

## 验收
不存在owner/权限/版本/材料时明示拒绝或unverifiable；
spy证明原核心和provider的mutation方法/文件进程副作用计数为0；
至少一个fake提供者证明真实转发、版本和权限拒绝，不只检查接口存在。
真实provider支持范围逐家列，不把fake支持写成Pi/Codex/Claude都完成。
