# ordessa.incremental-engineering@2.6.0 — unsupported owner-binding candidate

父任务认可request→等待→真实结果、组合生成实施包与原子采纳的方向后形成独立数据/流程候选。方向认可不等于发布、产品Grant或真实验收。旧2.4保持字节冻结。

## 明确身份与来源

release_version 2.6.0；manifest schema1；完整原47个资源沿2.4，另增独立审核Unit skill，包含DID/决定/提案/摘要/apply receipt/完整Spec Kit包/反馈/标准profile/confirmation的schemas/templates/skills和全部标准。本轮还在未发布2.5内更新submission方法正文schema2、模板/skills与acceptance标准revision2.5.0的Unit审核输入来源；2.6.0新增独立Decision结果到方法既有有限nominal映射的策略声明：完整、精确且满足证据/来源/版本/独立审核与当前权限约束的supported答案可按criterion政策进入pass；contradicted/insufficient按原block处理，unknown/tie/missing/incomplete/truncated/unmapped仍unknown/manual。此修订不把Decision正文当Grant或真实性证明。source-review的claim_support仅在2.6.0显式改为supported→satisfied/pass；其余来源完整性和coverage规则保持。提案来源 docs/proposals/request-wait-composition-v1 与原软件工程Harness设计；父最新指示明确不得额外增加不必要审批。

2.5.0 曾由主协调者实际使用 public loader、validation 与 compiler 检查：19 项 requires 与原型 descriptor 精确匹配，并保留 fixture-trust warning；这不构成 production source registration、snapshot 或发布。2.6.0 的较早 source78 字节曾由 public loader/validator/compiler 在 fixture-trust descriptor 下受控检查，并保留 FIXTURE_CAPABILITIES_ONLY warning；本次90阶段更新了工作流、工作输入和方法绑定声明，该早期收据不覆盖当前字节，当前候选尚未重新校验。其 method.yaml 当前含59项manifest resources和19项requires，并按本版本资源摘要声明。复制的 `validation.json` 与 revision notes 是2.5历史资料，不是2.6验收。原型 descriptor 不等于 production catalog，也没有 MethodRef snapshot。候选 **未封存、未发布、不可执行**；candidate-index 仅列字节，不证明运行或注册。

## 实际与待绑定的数据边界

method.yaml现在绑定13个由EngineeringService.operation_capabilities()实际导出的operation descriptor（原11项加`engineering.packages.freeze`和`engineering.submissions.record_report`）、1个conditional `engineering.executions.dispatch` owner descriptor，以及2个MechanicalReviewCheckSource descriptor。`contracts/implemented-owner-contracts.json`记录实际detached descriptor的schema/version/digest/outcomes；dispatch descriptor要求execution-dispatch composition，且不属于19个core查询/操作自描述中的core command集。以上均不是production catalog注册或认证声明。freeze和record_report使用core命令的completed/rejected outcomes；report的completed语义仅为`submitted`、`pending_review`、`accepted: false`。Dispatch描述提供completed/failed/unknown；真正推进原MethodRun step log的是独立`engineering.work.record_dispatch_step`，它核验原terminal dispatch row并在同一UoW/CAS内把completed/failed路由到方法结果。unknown在该入口以`WORK_OPERATION_OUTCOME_UNKNOWN`拒绝推进，不能靠workflow的stop: unknown伪装成已处理结果。该 operation 尚无production native catalog descriptor，且`dispatch_input`仍无权威来源绑定。

reviews.request输入仅plan；completed进入专属审核wait，不进入passed分支。approvals.prepare_intent输入intent；approvals.request输入intent_id/intent_digest；completed进入pending challenge等待，不出现granted分支。changes.apply输入approval_ref。主Agent通过原artifacts.create/append_revision记录完整材料；真实reviews.record及record_conversation由各原来源入口在等待期间调用，业务原owner重新查记录和gate。

pending-bindings.yaml记录generic Decision与deterministic schema/submission check descriptors已可由真实owner函数提供；三个语义专用ID由方法question sets调用generic Decision，没有新增具名业务checker。freeze与record_report有精确core descriptors；dispatch有conditional owner descriptor。2.6现在声明32个精确wait selector及经`work-inputs` schema限制的event字段。候选尚未证明生产Service选择了该SQLitePersistedMethodWorkSource、同authority BlobStore以及与选中bundle匹配的owner sources。`await_implementation_permission`的`dispatch_input`由方法输入提供，但wait只确认数据和package引用；canonical dispatch仍必须验证完整实际action tuple和当前Grant。`await_intent_ref`声明以原授权仓库按`intent_id`读取真实Intent，并核对方法引用及`intent_digest`；文档输入自身不是Intent证明。`await_execution_capture`声明以`submission_record`定位原生报告入口，Work source必须从原Submission解析真实Execution记录/query producer，并核验对应Unit、operation、prompt、query、blob及完成状态；来源或捕获缺失、结果未知时保持等待/拒绝。以上声明仍待生产source选择与运行资格验证。detached descriptors不是production catalog注册；Submission正向Qualification和末端采纳职责仍未闭合，因此publication/execution保持false。

所有32个wait node现在有精确的`metadata.work_source.waits`声明，并显式选择静态`events`或loop专用`events_by_round`：审核wait以原ReviewPlan/phase gate核验，授权wait以原Intent/ApprovalRef/动作和grant control核验，普通/结果wait只解析声明的原始精确引用。loop事件按原MethodRun行的`rounds`值读取；缺少当轮记录拒绝，已有轮次字段不可改写。match值来自已选上下文槽；bind值来自经方法schema验证的`work-inputs`数据，raw reviewer response只用同一原BlobStore的BlobRef读取。Work inputs以新Artifact revision创建后，必须调用原`engineering.work.bind_inputs`，按expected row digest和ordinal CAS绑定具体revision；不隐式读取artifact head。`dispatch_input`在实施wait仅是参数数据，不代表获准；原dispatch owner仍验证完整动作tuple和当前Grant。通知只能唤醒，不能推进。以上是候选方法声明，不证明该版本已被生产Service选择或完成source/runtime qualification，publication/execution仍为false。

## 完整流程及权限

讨论决定/授权/未决→DID充分设计/变更与摘要→来源语义与工程质量/内容/摘要完整review请求、真实record与等待gate→notice/确切文档接受intent/challenge→真实会话确认及当前Grant→原DID CAS应用receipt→主Agent按templates/spec-kit和spec_converter生成完整spec/plan/tasks及contracts/design/分片/双向依据/依赖写权/验收，原Artifact留档→有效generate_package权限下原Package freeze→确切封存包完整review等待→有效实施权限下真实Pi dispatch/capture→Unit通过MethodContent报告和固定ArtifactRevisionRef outputs→原Submission submitted/pending_review/accepted=false→独立Unit检查输出并核实报告中asserted的test/effect事实→复用原reviews.request进行完整验收等待→有效采纳权限下原owner CAS采纳→反馈。

不新增固定用户审批轮次：有原owner验证仍有效且精确覆盖实际generate_package/implement/adopt action、target与scope的许可即可使用；没有覆盖则走既定真实确认入口，不能复用含糊“继续”。DID接受、审核意见、包封存均不补造实施/采纳权限。原freeze消耗generate_package且dispatchable:false，实施前另验真实execute权限；重要设计缺口回DID，普通实现自由沿已授权范围。派发生成若有需要须有独立原任务接缝，不借依赖已封存包的ImplementationDispatch制造循环。

不要求额外草稿approval：正式完整package review在封存后；在生成/封存前原intent本来要求的review仍按完整集合保留，不能因顺序方便删除。草稿审核不能覆盖不同exact封存目标。方法模板、Agent任务和Artifact/freeze组成生成策略，不新增packages.derive原子生成器。

## 真实缺口与验证

原freeze/dispatch/Submission、schema/source机械proof、nominal/human及图scope/binding已有原机制，但具名完整adapter/descriptor未全部冻结。尚待冻结/qualification的是通用Unit pending-review入口、原Work/review Unit桥接、完整检查和采纳合同；当前已看到CurrentMethodWork/CurrentRunWait/AcceptanceUseCases源码，不能将合同未取得称为类不存在；exact API以原owner为准，不能把这些全称为注册工作。Candidate policy qualification及当前真实Decision/reviewer/source assembly仍未完成。Decision结论按本revision声明的有限Choice选项与criterion disposition处理；unknown、缺失、tie、不完整、截断或未映射仍manual/拒绝，不发明阈值或自动质量旗标。独立来源、证据、当前权限、原Gate及接受条件仍生效。真实Pi/JEV最终验收目标保留，没有offline/fake替代。

`validation.json`仍是旧的候选校验记录；当前loader/validation/compiler通过结果由主协调者串行验证并报告，不能把它解释为注册或发布。前一轮compiler拒绝证据保存在docs/validation.before-unit-policy.json，属于历史验证。boundary-vectors.json仍是待执行的运行边界，等待owner合同后由原SQLite/installed及真实来源验证。没有模型/数据库发布调用。未创建fixture catalog或使用fixture发布。

2026-10-12边界修正：正常提交不要求宿主前置采集全部文件/test/effect事实；独立review按固定版本核实，未核实测试事实保持asserted。审核者独立性按本方法声明的来源策略确定，宿主只提供原始来源关联及角色分配机制。详见docs/unit-submission-host-contract.md。

### 审核作者来源策略

`source_review`、`quality_review`、`package_review` 使用
`ordessa.review.authorship-policy/1` 条件策略：真实 `native_unit` 作者来源要求
审核者是不同的原始 Unit；`authenticated_material_submitter` 来源要求另行分配的
审核角色。该来源只由原 journal/key 证明认证 Principal 与已完成命令绑定的精确
固定 ArtifactRevision；它不证明该 Principal 是人类，也不构造或声明 native UnitRef。
来源缺失或未知时拒绝继续。三处均发生在执行派发之前，不能假造原生执行作者。

执行后的 `record_submission` 及 `acceptance_review` 继续要求原生作者 Unit 与审核
Unit 不同，并以原 UnitRecords 查询验证双方身份；不能用 material submitter 来源替代。
此策略不会降低 Submission、完整审核集合、固定材料版本、当前授权、证据或采纳条件。
候选中的声明仍须由公开策略解析器、实际来源装配和独立原生审核路径分别验证；它不构成
production 注册、角色授予或发布依据。

## 76：明确采纳输入与有界普通修正

候选工作流现在按 `engineering.acceptance.adopt` 的真实输入字段分别绑定
`submission_ref`、当前授权引用、控制版本和目标 CAS 预期；采纳回执由原操作结果
关联到 `acceptance_receipt_ref`，并通过 `MethodRun` 输出投影公开提交与回执引用。
该声明不创建授权、来源或生产 WorkConditionSource。

验收请求完成仍只表示请求已保存。候选新增等待并通过原
`engineering.reviews.record` 记录实际验收响应：`pass` 进入既有 gate，`fail`
进入候选自有的普通修正资格审核，`indeterminate` 停止为 `unknown`。资格审核以
新的 `standard.rework-scope` / `decision.rework-scope` 使用通用
`ordessa.decision.evaluate`，只允许精确已批准 DID、冻结 package、原提交和验收
记录下、且没有重要设计变更的普通修正；超范围/重要变更停止为
`revision_required`，证据不足保持 `unknown`。这不是接受、授权或自动执行。

普通修正资格审核的 subject 是新声明的 `correction-plan` 文档对应的不可变
`ArtifactRevisionRef`，使用现有 `quality` purpose。该文档只固定批准 DID/package、
失败 Submission、失败 ReviewRef，以及每项修正的 criterion、target、change、
validation steps 和 scope-basis refs；不含 Grant、approval 或 verified 标志。原来源
必须把失败 ReviewRef 与已完成的原审核命令、plan digest、request version 和 fence
核对。该 `correction-plan` schema/template 是方法资源，不是 Engineering domain 类型，
也不替代原 ReviewRecord/source guards。

资格审核通过后回到新的当前实施授权 wait，每轮都需要原权限与新交付/提交和独立
审核。方法选择 `max_rounds: 2`（首轮加至多一次经资格审核批准的修正），耗尽停止
`revision_required`。这是本首发方法的有界策略选择，不是历史快照授权或核心默认值。
该 wait 仍匹配原 exact frozen package；原来源必须重新核验当前Grant、作用域和剩余
budget，不可重用已消耗额度或替换 package 的 authorization refs。若原包不能再执行，
本 loop 必须拒绝推进；需要另行授权并冻结的新包，不会由此 loop 自动生成。不确定的
外部执行效果仍必须先由原来源协调；本 loop 不允许重放或重试未知副作用。

`work-inputs` schema v2 以不可变 ArtifactRevision 与显式 CAS 绑定。每个 wait 在固定方法元数据中明确选择 `events` 或 `events_by_round`；loop wait 只读取原 Work 行 `inputs.rounds` 指定的规范十进制轮次，缺少当轮记录时拒绝，不回退旧的静态事件。所有先前轮次已写入的事件字段保持不可变，round counter 仍只由原 MethodRun 步骤事务推进。既有冻结方法若没有 `event_map` 与 v2 修订声明，仍按其 schema v1/static `events` 契约读取，不升级旧快照。此声明定义了第二轮输入的传输方式，不单独证明外部来源、审核或执行绑定已通过资格验证。

以上流程图和待接线描述从 2.5.0 继承，是历史基线，不代表 2.6.0 已经接线或验证；
本修订的可信当前来源、完整原审核响应、来源关联和 production capability 注册仍须
单独接线与资格验证。此前某一组 2.6.0 候选字节的 loader、validator、compiler 与政策测试曾在受控 fixture 来源下运行；90阶段更新后的当前字节尚未重新运行这些检查。候选仍未发布或创建 production snapshot，完整五阶段与真实 Pi/JEV 没有闭环证据。


## 2.6.0 策略边界

2.6.0是显式新方法版本，不改写2.5.0、2.4.0或更早历史。它删除此候选之前复制的 `matching_validated_evaluation_required` 子策略；方法结果由本方法定义的 Decision questions、complete CheckKey answers、有限nominal转换和criterion disposition驱动。`semantic_consistency` 与 `semantic_drift` 使用显式有限 Choice v1 选项：coverage 的 `conflicting/partial/complete` 分别映射为 `violated/insufficient/satisfied`；drift 的 `drift_detected/no_drift_detected` 分别映射为 `violated/satisfied`。不将分数或原生布尔答案伪装成离散等级，也不使用阈值。缺失、tie、不完整、截断或未映射一律unknown/manual。正向结果仍须由原owner基于精确请求、方法/问题/材料版本、完整证据、独立review来源及当前Grant/guard决定是否推进；Decision本身不是Grant或verified事实。

## 90：声明审核阶段，不推断来源

未发布候选的 `proposal_reviews` 以 `source_review` 为锚点，按单标准、单 ReviewPlan 的顺序执行 source、quality、engineering-content、summary 四个 request/response/record 成员。source 成员记录后先经过原 source-only gate，再等待 quality ReviewPlan；其余成员通过显式 `advance_waits` 指定后续计划等待，summary record 才进入组最终 gate。每次响应使用精确 request/version/fence 与同库 BlobRef，记录操作只接受原 review owner 可解析的响应。`package_reviews` 同样声明 quality 与 engineering-content 两个单计划成员；候选的 package draft 目标引用不等于 original Package proof，生产来源仍缺时必须拒绝。

Proposal targets 声明原 proposal 的 did/did-change proposed revisions，并把 `summary_ref` 声明为独立 `session-summary`/`support` target。当前原 Proposal/TemplateTarget 来源没有独立 summary ArtifactRevision selector；不能拿 claim-owner 或 Proposal 正文替代，故这组声明尚未由生产来源证明。Acceptance targets 只从原 Submission.output_refs 投影真实 submission ArtifactRevision；缺少报告输出时拒绝。独立审核观察由本次 acceptance Unit 在其审核输入中形成，不要求预先存在 ReviewRef 或 ReviewRecord；实际角色与原始证据来源仍由原 reviewer authority/source 校验。

`rework_review` 是 correction-plan 单成员组。等待新计划时，match 只关联已绑定的 Submission、acceptance request、applied DID、package 与 method；新 acceptance ReviewRef、plan digest/version/fence 及 correction-plan refs 是该事件的输入，由原来源重新校验，不再把同一事件输入同时作为旧上下文 match。材料映射只引用声明的原槽或同类型记录；它不创建 Artifact 或记录。上述方法声明不替代原 ReviewPlan 完整 CheckKey 集合、当前权限、来源/角色真实性及原库事务 guard。候选 `publication_allowed` 与 `execution_allowed` 仍为 false，尚未运行候选校验或产品发布。
