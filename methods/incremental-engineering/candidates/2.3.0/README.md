# 渐进工程方法 2.3.0 候选：名义转换与质量准入

身份：`ordessa.incremental-engineering@2.3.0`，manifest schema1、compiled program schema2。这是独立冻结候选：**名义映射获父任务批准，精确声明合同已由 Engineering 原规则 owner 冻结；生产 resolver 消费与真实语义质量仍待验证。** 本候选不是生产选用/启用、自动通过或 Grant 的凭据。

## 精确变更

与2.2.0相比，仅 method release、source-review standard revision及该resource rawSHA更新；在claim_support.checks[0].bindings新增nominal_answer_conversion和quality_admission。原question_set/iteration/all_declared_claims/empty_claim_set=error、全部原policy、reduction和三选项问题字节保持。精确差异见source-delta.diff；其余声明资源逐字节复制原2.2。

- source-review raw SHA256：`23843c89dfc8d7e3f178ecc5e9b4f0d25befc184bdb184638ca524710b4c9423`
- MethodRef snapshot SHA256：`5e1f1312e06446d83cd7813547fc99db498d40969002729b7a99249e66cd60f9`
- 完整manifest rawSHA、resource closure、compiler/program digest见bundle-lock.json；编译程序见contracts/compiled-program.json。

```yaml
nominal_answer_conversion:
  contract_version: ordessa.nominal-choice-status/1
  answer_kind: choice
  option_statuses:
    supported: satisfied
    contradicted: violated
    insufficient: insufficient
  tie: unknown
  missing_answer: unknown
  incomplete_answer: unknown
  truncated_input: unknown
  unmapped_option: unknown
quality_admission:
  contract_version: ordessa.review-quality-admission/1
  activation: matching_validated_evaluation_required
  missing_evaluation: manual
  unresolved_model: manual
```

## 两层规则与原 owner

**名义语义转换**只是将原有限答案标签投影为CriterionAnswer的四语义之一；supported→satisfied不证明真实支持、模型质量或权限。合法tie/缺答/partial/截断/未映射项保持unknown，不挑赢家，不把原问题改成四status。非法binding/ref/shape由原resolver拒绝；原raw答案及失败事实不能丢失。

**质量准入**仍遵循DESIGN的匹配已验证evaluation要求，必须匹配criterion/question/input mapping/provider/actualmodel-checkpoint/truncation等原事实。没有可信evaluation owner时，Engineering当前拟实现会将名义satisfied的质量状态保持manual、原因MODEL_EVALUATION_UNAVAILABLE，并由review_observations独立强制；product自报evaluated不能提升信任。本声明没有阈值、calibration profile或evaluation通过证明，不能与decision_policy并用，也不构成免除评测的新路径。

当前criterion的原policy仍是satisfied→manual、violated/insufficient→block、unknown→manual；即使名义答案为supported，也不产生pass或Grant。映射冻结与置信阈值准入是两层原工程规则，不把三选项词义转换当作质量校准。原方法按all_declared_claims展开：不按kind（包括design_choice）、link存在或缺证据筛除；required空集合仍error。

声明由方法资产持有，通用解析/语义投影及独立质量门由Engineering原规则owner负责；source raw response、question/input/evidence来源与reviewer原capability仍归原provider/ReviewerSource owner。当前拟公开合同是nominal_criterion_answer(plan, exact_standard, check_key, *, selected_option, selection_status, answer_complete, input_truncated, evidence_refs=(), rationale='') → NominalCriterionResolution（包含原CriterionAnswer及classification/quality状态/原因）。此签名来自owner冻结交接，**本资产产出时尚未核验函数实现**；manifest声明不能证明resolver已可执行。

## 静态验证与剩余事项

tests/validate_candidate.py实际使用原loader/compiler，验证两个嵌套声明与冻结合同逐项一致、typed FrozenObject无损、stored program canonical往返一致、原问题及policy不变；篡改resource和stale release lock被真实loader拒绝。2.1/2.2的154项历史文件哈希保持，根fixture-lock与2.2索引不重封。结果见tests/validation-result.json。

tests/nominal-cases.json的14项是待Engineering消费的机制规格，未执行；不是14次模型判定。publication仍未跑，catalog仍fixture-only，不能冒称生产host。旧2.1/2.2 snapshot和synthetic结果不追认新语义或formal review。

下一步：Engineering完成并验证原公开resolver、独立质量门和反例；产品接真实JEV来源/原Graph/evidence准入；取得匹配真实evaluation、验证正文→正式Claim完整coverage；按既定用户确认/DID应用/spec-package/Pi/验收反馈链完成最终验收。本候选未运行模型、未改启停权威或确认policy。
