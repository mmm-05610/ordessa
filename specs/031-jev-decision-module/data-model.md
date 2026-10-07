# 数据模型 · decision/1

## 编码与身份
DTO 使用不可变数据结构，嵌套字典/列表同样封存。传输仅允许有限 JSON；拒绝 NaN/Infinity、非字符串键、任意 Python 对象、执行表达式和未经授权的外部引用解析。
默认限制：请求 256 KiB、单份观测 256 KiB、观测总量 2 MiB、输出 256 KiB、JSON 深度 32、单字符串 64 KiB、候选最多 64、配置组合最多 64。这些是初版保守产品默认，不是性能保证。调用方可要求更紧限制，不能超过宿主批准的上限。
规范编码必须有测试向量：稳定键序、UTF-8、无NaN；本版采用decision-json/1：Python JSON sort_keys=true、ensure_ascii=false、separators=(',',':')、allow_nan=false，拒绝重复键和非有限数，保留合法小数，包括外部配置/schema/payload。不声称RFC8785兼容；跨语言消费者须通过字节向量，不得自行换编码算法。身份/版本/计数字段仍禁止浮点。
摘要为sha256(domain + '\\n' + codecVersion + '\\n' + canonicalBytes)；domain分别为decision.request/decision.proposal/decision.result/decision.descriptor/decision.runmanifest，互不复用。

ExternalRef = sourceNamespace + identity（来源原生完整公开引用）。
FlowRef = flowId + version + contentDigest，装配时与可信图绑定；输入不能提供 URL/Python 路径自动加载代码。
RunId 是一次判断身份，requestId 是调用关联，不承诺幂等收费或模型 exactly-once。
版本引用与 digest 分开：digest 证明内容，不能冒充提供者的并发控制 revision。

## 输入
DecisionRequest：
- contractVersion=decision/1，requestId，task，flowRef，limits。
- priorOutcomeRef 可选，只作来源关联，不自动续跑。
- extensions 只能为具名命名空间数据，顶层未知字段拒绝。
- 不接收 principal、Token、allowWrite、自授权限、执行 lease。
宿主提供PolicyRef(policyId/version/contentDigest)集合，正文不能自选未审查policy。RunManifest绑定requestDigest、flowRef、effectivePolicyRefs、effectiveLimits、codecVersion、providerBindingRef；run.started和所有结果覆盖manifestDigest。requestDigest覆盖请求全部编码字段；proposalDigest覆盖ProposalDraft全部字段（不含回执）；resultDigest覆盖完整结果去除自身resultDigest；descriptorDigest覆盖描述全部字段去除自身digest。所有域/缺字段/null/数值均有固定向量。

TaskBrief：
- taskId/taskRevision、goal。
- inputs[]：来源引用、描述、信任分类、可选内容摘要。
- boundaries[] / acceptanceCriteria[]：id、statement、must/preference、依据引用。
- contextRefs[]、continuationRef 可选。
结构有效但目标/边界/验收为空是可审查任务，返回 clarify/revise；不能在 codec 层拒绝所有不完整任务。
输入来自用户/文件/第三方的文本都是数据，不成为系统指令。

TaskGate 策略 v2 用 input_projection 外部配置选择字段、信任分类、引用身份字段白名单、条数与字节上限。结构化 task_evidence 摘要、contextRefs、continuationRef 同时进入每维问题 bounded_state 与相关任务签名；来源版本变化触发复评。display 元数据不成为业务证据，显式业务证据字段不完整则拒绝。引用不被自动解引用，不读取引用文件；凭据键、URL 凭据参数及未知引用身份字段拒绝。正文摘要仍由宿主提供脱敏数据，字段白名单不意味着自动发现任意文本中的秘密。信任标签和第三方自称授权不能改变宿主 requires_confirmation 事实。

## 观测
VersionedObservation：
observationId、subjectRef、sourceVersion|null、contentDigest、observedAt（含时区）、validUntil|null、
freshness=current/stale/unknown、data、evidenceRefs[]。
current 仅指来源观察时的声明，不保证应用时有效。版本未知不能用本地时间、到达顺序或 digest 推导较新版本。

ObservationBatch：
queryRef、observations[]、complete、pagination、scopeDescription、unobservedItems[]。
complete=false 或权限过滤范围未知时，空列表不证明不存在单元/配置。

ConfigurationOffer：
offerRef、providerRef、descriptorRevision/digest、configurationKind、schemaVersion、
inputSchema、supportedActions、scopeDescription、applicationModes、supportStatus、
constraints[]、evidenceRefs[]。
configurationKind 非固定枚举；unknown/unsupported 不自动变成 supported。
schema 为纯数据，使用明确支持的 dialect；不联网解析远程 $ref，不执行模板代码。无法验证 required 项时阻止 ready。

CandidateOffer：
candidateRef、candidateKind、observation、capabilityClaims、compatibilityEvidence[]、uncertainties[]。
不包含活对象、callable、lease、凭据或使用通道。按来源真实引用去重，不按显示名称。
Agent 业务候选的语义由 M05 定义，公共契约不内建所有可能业务类型。

## 判断问题与回答
DecisionQuestion：
questionId/version、kind=choice/score/noul、boundedState、questionText、
选项/量表/判定定义、evidenceIds[]、allowedAnswerIds[]、policyRef。
只允许可信流程创建问题。业务文本被标记为观测，不能改变问题 schema 或预算。
Choice 候选映射固定 optionId，返回合法集合外答案即失败；不得默认选第一项。
Score 可以为非整数，不把 confidence 或概率当作真实正确率。具体提供者字段归 M03，公共模型无必需 confidence。
DecisionAnswer 包含类型化答案、providerReceipt、usageEvidence、answerDigest；不得从回答拼接 Python、SQL、命令或 wire method。

## 提案
ProposalDraft：
proposalId、proposalKind、payload、basisObservationIds[]、preconditions[]、rationaleCodes[]。
另含requiredValidationObligations[]：obligationId/subjectRef/must-or-advisory/validatorKind/versionConstraint，由可信策略和接入产生。
M05 定义本版 agent.assignment/1 payload，Jev 仅选择候选 ID，业务代码从候选映射取完整 payload。
提案摘要不包含 validationReceipt，避免递归摘要；审核回执绑定该摘要。结果摘要另覆盖提案和回执。

Precondition：
id、kind、subjectRef、expectedVersion|null、expectedDigest|null、must/advisory、
checkerId/checkerVersion、description。
必须条件由可信接入/策略生成，模型不可删改降级。消费者必须认识 checker 并重新检查；
不认识或版本不可核实就拒绝实际应用。TTL 不替代版本/权限检查。

ValidationReceipt：
validatorId/version、proposalDigest、validatedObservationVersions[]、
status=valid/invalid/unverifiable、issues[]、checkedAt、validationScope。
obligationResults[]逐项包含obligationId、passed/failed/unknown/notApplicable、checkerId/version、sourceVersions、evidenceRefs。ready要求决策时全部must义务覆盖并passed；notApplicable须可信policy给出豁免依据，模型不能自行免除。结构valid不能升级为配置语义valid。
valid 仅代表这份提案在已声明的只读校验范围内成立，不是已应用或授权。
模型分数不代替外部校验。修改提案或依据后必须重新校验，不复用旧 receipt。

## 终态
运行结果是判别联合：
- completed：仅此分支有 disposition=ready/revise/clarify/blocked。
- failed：安全错误码、失败阶段、known/unknown 调用证据。
- budget_exhausted：耗尽维度与已消费值，不携带可应用半成品。
- cancelled：本地显式取消调用得到的查询记录；外部协程取消仍向上传播，不吞异常返回成功。

ready 至少有一份 valid 提案和全部必须前置；不需要外置单元可为 noDelegation。
revise 是要求主 Agent 重拆/缩范围/补约束；不自动执行拆分任务。
clarify 含有阻塞关系的具体问题/证据缺口，未获用户确认的选择不报 ready。
blocked 表示判断完成且现有能力确实无法满足，附可解除条件；与技术失败分开。

每份结果含 runId/requestId/taskRevision/flowRef/resultDigest/evidenceSummaryRef。
还必须绑定runManifestDigest/effectivePolicyRefs，换策略不得只刷新版本号复用旧结论。
interrupted 是宿主/独占离线查询者对可靠 started 无终态记录的投影，不是死进程自行返回。
没有记录或无法确认运行是否仍活着时显示 unknown，不推断 interrupted。
