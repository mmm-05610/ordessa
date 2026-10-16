# ordessa.incremental-engineering@2.5.0 — unsupported owner-binding candidate

父任务认可request→等待→真实结果、组合生成实施包与原子采纳的方向后形成独立数据/流程候选。方向认可不等于发布、产品Grant或真实验收。旧2.4保持字节冻结。

## 明确身份与来源

release_version 2.5.0；manifest schema1；完整原47个资源沿2.4，另增独立审核Unit skill，包含DID/决定/提案/摘要/apply receipt/完整Spec Kit包/反馈/标准profile/confirmation的schemas/templates/skills和全部标准。本轮还在未发布2.5内更新submission方法正文schema2、模板/skills与acceptance标准revision2.5.0的Unit审核输入来源；其他标准、问题、词表、nominal/human与原产品policy字节及质量边界不变。旧source-review标准独立revision2.4.0沿用，不伪称改了审核规则。提案来源 docs/proposals/request-wait-composition-v1 与原软件工程Harness设计；父最新指示明确不得额外增加不必要审批。

主协调者对当前候选字节串行实测：public loader、validation与compiler均通过，19项requires与当前实际descriptor精确匹配，保留1条fixture-trust warning。该compiler使用临时原型descriptor集合；descriptor不是production source registration，也没有创建production catalog或MethodRef snapshot。此前50资源/16 requires与14个`UNKNOWN_CAPABILITY`是历史诊断，见validation.before-unit-policy.json。当前manifest含57项资源；19项requires由13个Service operation descriptor、1个conditional dispatch descriptor、2个Mechanical descriptor和3个当前check descriptor组成。新增checks来自真实 `invariant_review_check_capabilities()` 与 `generic_decision_check_capability()`；mechanism/descriptor存在不等于production source registration。`pending-bindings.yaml`区分descriptor可用、生产注册待接线和正向Submission资格待验证。候选 **未封存、未发布、不可执行**，没有MethodRef snapshot。candidate-index只证明候选字节完整性，不能代替SnapshotStore或production catalog。

## 实际与待绑定的数据边界

method.yaml现在绑定13个由EngineeringService.operation_capabilities()实际导出的operation descriptor（原11项加`engineering.packages.freeze`和`engineering.submissions.record_report`）、1个conditional `engineering.executions.dispatch` owner descriptor，以及2个MechanicalReviewCheckSource descriptor。`contracts/implemented-owner-contracts.json`记录实际detached descriptor的schema/version/digest/outcomes；dispatch descriptor要求execution-dispatch composition，且不属于19个core查询/操作自描述中的core command集。以上均不是production catalog注册或认证声明。freeze和record_report使用core命令的completed/rejected outcomes；report的completed语义仅为`submitted`、`pending_review`、`accepted: false`。Dispatch描述提供completed/failed/unknown；真正推进原MethodRun step log的是独立`engineering.work.record_dispatch_step`，它核验原terminal dispatch row并在同一UoW/CAS内把completed/failed路由到方法结果。unknown在该入口以`WORK_OPERATION_OUTCOME_UNKNOWN`拒绝推进，不能靠workflow的stop: unknown伪装成已处理结果。该 operation 尚无production native catalog descriptor，且`dispatch_input`仍无权威来源绑定。

reviews.request输入仅plan；completed进入专属审核wait，不进入passed分支。approvals.prepare_intent输入intent；approvals.request输入intent_id/intent_digest；completed进入pending challenge等待，不出现granted分支。changes.apply输入approval_ref。主Agent通过原artifacts.create/append_revision记录完整材料；真实reviews.record及record_conversation由各原来源入口在等待期间调用，业务原owner重新查记录和gate。

pending-bindings.yaml记录generic Decision与deterministic schema/submission check descriptors已可由真实owner函数提供，但生产source注册、Submission正向qualification及wait/source边界仍待接线；三个语义专用ID已改为方法question sets调用generic Decision，未新增具名业务checker。freeze与record_report已有精确core descriptors；dispatch有conditional owner descriptor，但需真实composition。现有`await_frozen_package`已声明`package_ref: event.package_ref`槽绑定，dispatch node的`package_slot`指向此确切槽；冻结后这个wait仍需可信来源交付原package ref。`await_implementation_permission`目前只产生opaque `event.dispatch_input`，尚未证实其来源实际给出dispatch schema要求的run/step/attempt/unit_ref/params/actions/timeout。`await_execution_capture`仍需actual Unit response source产生method-bound MethodContent和固定ArtifactRevisionRef报告输入。所有精确descriptor仅是detached descriptions，不代表production catalog注册。wait/source接线、conditional composition qualification和Submission正向Qualification仍未解决；完整标准/check引用和末端采纳职责保留，因此仍不可发布或执行。

所有21个wait node现在声明现有通用事件`engineering.work.current_condition`与`ordessa.engineering.current-work/1` resume contract；其独特`step.id`及method-owned `bind`/`match`仍是外部WorkConditionSource识别具体当前业务条件的输入。旧`pending.owner.*`仅作为历史占位文本，不再作为候选事件名。原WorkConditionSource/MethodRunBindings必须实际提供并保持原业务source/current review/Grant predicates、exact refs/versions/full requirements与同authority CAS/COMMIT；该composition仍未接线或qualification。通知只能唤醒，不能推进。候选静态声明不证明owner来源已注册或wait可执行，因此仍不能seal/publish。

## 完整流程及权限

讨论决定/授权/未决→DID充分设计/变更与摘要→来源语义与工程质量/内容/摘要完整review请求、真实record与等待gate→notice/确切文档接受intent/challenge→真实会话确认及当前Grant→原DID CAS应用receipt→主Agent按templates/spec-kit和spec_converter生成完整spec/plan/tasks及contracts/design/分片/双向依据/依赖写权/验收，原Artifact留档→有效generate_package权限下原Package freeze→确切封存包完整review等待→有效实施权限下真实Pi dispatch/capture→Unit通过MethodContent报告和固定ArtifactRevisionRef outputs→原Submission submitted/pending_review/accepted=false→独立Unit检查输出并核实报告中asserted的test/effect事实→复用原reviews.request进行完整验收等待→有效采纳权限下原owner CAS采纳→反馈。

不新增固定用户审批轮次：有原owner验证仍有效且精确覆盖实际generate_package/implement/adopt action、target与scope的许可即可使用；没有覆盖则走既定真实确认入口，不能复用含糊“继续”。DID接受、审核意见、包封存均不补造实施/采纳权限。原freeze消耗generate_package且dispatchable:false，实施前另验真实execute权限；重要设计缺口回DID，普通实现自由沿已授权范围。派发生成若有需要须有独立原任务接缝，不借依赖已封存包的ImplementationDispatch制造循环。

不要求额外草稿approval：正式完整package review在封存后；在生成/封存前原intent本来要求的review仍按完整集合保留，不能因顺序方便删除。草稿审核不能覆盖不同exact封存目标。方法模板、Agent任务和Artifact/freeze组成生成策略，不新增packages.derive原子生成器。

## 真实缺口与验证

原freeze/dispatch/Submission、schema/source机械proof、nominal/human及图scope/binding已有原机制，但具名完整adapter/descriptor未全部冻结。尚待冻结/qualification的是通用Unit pending-review入口、原Work/review Unit桥接、完整检查和采纳合同；当前已看到CurrentMethodWork/CurrentRunWait/AcceptanceUseCases源码，不能将合同未取得称为类不存在；exact API以原owner为准，不能把这些全称为注册工作。自动JEV仍需匹配validated evaluation，当前质量manual；人工仅原已批准coverage/support范围，不扩大quality/summary/验收豁免。真实Pi/JEV最终验收目标保留，没有offline/fake替代。

`validation.json`仍是旧的候选校验记录；当前loader/validation/compiler通过结果由主协调者串行验证并报告，不能把它解释为注册或发布。前一轮compiler拒绝证据保存在docs/validation.before-unit-policy.json，属于历史验证。boundary-vectors.json仍是待执行的运行边界，等待owner合同后由原SQLite/installed及真实来源验证。没有模型/数据库发布调用。未创建fixture catalog或使用fixture发布。

2026-10-12边界修正：正常提交不要求宿主前置采集全部文件/test/effect事实；独立Unit按固定版本核实，未核实测试事实保持asserted。author!=reviewer是本方法策略，宿主只提供通用身份匹配/约束机制。详见docs/unit-submission-host-contract.md。

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

以上仅为 2.5.0 的候选声明；新 wait 的可信当前来源、完整原审核响应、来源关联和
生产 capability 注册仍须单独接线与资格验证。未运行本修订的 loader、validator、
compiler 或 tests，也未发布或创建 production snapshot。
