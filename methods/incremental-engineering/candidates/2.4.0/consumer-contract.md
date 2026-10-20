# Engineering 原owner冻结的人工审核消费合同

来源：Engineering会话01a1292f-d25b-7765-b7bb-1537beda50b7的版本化声明交接，父批准来源01a118bc-dd26-7553-b5b6-cf5137c070d6。字段形状已冻结，实际consumer实现未由本任务验证。

仅source-review.claim_coverage/claim_support checks[0].bindings新增：

```yaml
human_review_admission:
  contract_version: ordessa.human-review-admission/1
  activation: selected_product_policy_required
  policy_id: ordessa.product.v1.chat-attested-human-review
  policy_revision: 1
  policy_digest: sha256:833be965ff8e43b0fec817e205a4d2f7817f45b7b36777a405a905fff44ec008
  status_dispositions:
    satisfied: pass
    violated: block
    insufficient: block
    unknown: manual
```

独立原UTF8 policy的required字段是：schema_version1、contract_version ordessa.human-review-policy/1、同policy id/revision、selection_authority product_composition_and_configured_engineering_admission、authorized_attestor_role registered_main_agent、accepted_source_trust_level agent-attested、review_path human_semantic_review、whole_plan_answer explicit_complete_checklist、missing_answer/ambiguous_answer pending、mechanical_integrity required、review_is_implementation_grant false及同status_dispositions。provenance只说明批准/合同来源，不替人类答复或authenticity。

Product原policy/source/current-role authority须返回实际选中policy原字节并持guard到COMMIT；Engineering比较exact raw SHA/id/revision及map与actual snapshot的human声明。method不能自选产品policy，机制不得硬编码pass map。真实问答/必要上下文/来源locator及限制、exact plan/request/object版本/完整CheckKeys均须原owner验真；任何漏项/重复/替换/版本错误不能使用本声明盖过。

拟入口EngineeringHumanReviewAdmission复用原ReviewUseCases.record_response/schema2/CAS。原ManualReviewCapture当前实际只是pending evidence；不得将已存在的pending捕获当作新正式Record链已实现。没有真实答复不写ReviewRecord。主Agent忠实转交不豁免原reviewer-role/current-source guard和完整mechanical proof，也不产生implementation Grant。

自动JEV路径及2.3历史路径保持原map和质量准入；本声明不能把自动supported/satisfied提升pass。quality标准不在此次冻结范围，若另需人工声明须先列criterion交原owner/父审，不自动扩大。
