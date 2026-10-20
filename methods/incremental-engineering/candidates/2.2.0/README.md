# 渐进工程方法 2.2.0 候选：逐 claim 审核声明

身份：`ordessa.incremental-engineering@2.2.0`，manifest schema1 / compiled program schema2。状态为 **冻结候选，待父任务核对及 Engineering 消费验证**，未发布、未激活、未通过最终验收。

本候选按 Engineering 会话 `01a1292f-d25b-7765-b7bb-1537beda50b7` 转交的父任务决定新增两个版本化 check bindings；来源及限制见 `provenance.json`。上一版根目录 2.1.0 的 manifest、资源、snapshot lock、94项 fixture-lock 条目及 fixture-lock 自身均保留，没有给旧 MethodRef 追加新语义。

## 精确差异与身份

`source-delta.diff` 给出与根2.1.0的精确文本差异：method release 从2.1.0变为2.2.0；source-review resource rawSHA 更新；候选 source-review revision从2.0.0变为2.2.0；其 claim_support.checks[0].bindings 增加：

```yaml
claim_selection: all_declared_claims
empty_claim_set: error
```

原 `iteration: each_evidence_required_claim`、question_set、其他检查、policy、answer vocabulary、reduction以及全部其他声明资源字节保持。标准 revision升为2.2.0是候选身份选择，用于区分新语义资源，不能推导旧revision自动升级。

- standard raw SHA256：`499cb9abe2b5f4d83c0c6bb700b72f2c5fd7bdb7f63e53b7ed13459f2af4697f`
- MethodRef snapshot SHA256：`fef3b88ea4db0336ab9a081960c092ada7b0550d1978e0be85fbf8680f0a39d4`
- 完整 source snapshot payload、manifest rawSHA及compiled plan digest见 `bundle-lock.json`。
- 精确编译程序见 `contracts/compiled-program.json`。catalog仍为fixture-only，不能据此发布/运行；新增bindings是现有JSON数据合同中的声明，未新增顶层DSL或结果类型。

## 冻结的语义

当前方法声明待审的事实、约束及设计决策 claim 均进入逐claim检查；不按 kind（包括 design_choice）、source_ids、link存在与否筛除。实施消费须对原exact ArtifactRevision.claims全量精确集合展开既有 `CheckKey(target, criterion_id, claim_id)`，不能只用客户端选择的 ClaimRef 子集。设计依据可来自真实用户Q&A或已确认决定上下文；不虚构外部出处。缺依据仍展开检查，可以得到 insufficient并按现policy阻门。

适用且required的claim_support若原claim集合为空，本候选声明error；当前没有可据以放行的NA规则，空集合不能自动pass。该语义不取消source_integrity/claim_coverage或其他标准检查。原 satisfied→manual、violated/insufficient→block、unknown→manual保持；逐claim全部supported也不能变成自动授权。

## 验证及仍待交付

实跑：`PYTHONDONTWRITEBYTECODE=1 <configured-python> tests/validate_candidate.py --build-lock`（首次生成），后续仅运行不带build-lock的验证。脚本拒绝静默覆盖已有候选锁。真实loader/compiler通过；typed FrozenObject保留两个键；stored program canonical round-trip无损；纯projection修改不能改变frozen binding。哈希篡改claim_selection被真实loader拒绝；旧release替换与stale lock被拒绝；上一版95项哈希不变。结果见 `tests/validation-result.json`。

`tests/per-claim-cases.json` 的11项是未执行的消费者反例规格：设计选择、缺依据、无语义支持的link、遗漏claim、空集合、跨target同名claim、排序、statement/ref替换、漏答、旧版不重解释、manual不放行。不能把这些规格当作运行通过。Engineering消费实现计划原owner保留于 `docs/implementation/nightly/evidence/engineering-convergence-20261011/v1-authorization/per-claim-implementation-plan.md`；本目录不改机制文件或该owner证据。

尚待：原MethodBridge按版本化声明消费及精确requirement/plan集合、原review gate反例、可信业务输入与原authority guard、父任务候选核对、真实JEV语义判断质量和真实Pi全流程。未运行模型或改当前method启停权威。
