# Unit提交与审核：宿主最小待冻结合同

本轮依据父转述2026-10-12用户决定及随后明确纠正。以下是策略需要的通用机制，不是已注册API；本方法不定义第二份身份/审批/提交状态。

1. **结构化提交**：原Unit来源与work/step/attempt关联、方法绑定的MethodContent与fixed ArtifactRevisionRef outputs；此2.5.0 report-mode Submission的`file_changes`、baseline/resulting snapshots、`commit_refs`、`test_evidence`、`effect_observations`和`source_refs`为空。原owner保存不可变SubmissionRef并置pending-review、accepted=false。普通提交无宿主先采集所有文件/test/effect事实的要求；无需宿主先生产verified测试观察。保留原来源/报告与asserted语义。不能把旧重型implementation SubmissionSourcePort当通用入口前置。
2. **固定版本读取**：解析同一SubmissionRef、ArtifactRevisionRef outputs和原报告；不读latest，不用新版本覆盖旧材料。Artifact原存储可复用；report-mode不附加commit/snapshot/tree字段。
3. **方法要求**：按exact method/phase/target展开完整ReviewRequirement/Plan/CheckKey(target,criterion_id,claim_id)；原CriterionSetRef和full required集合固定。作者/审核者不能挑subset，空适用集合沿error，无kind/evidence豁免。方法报告requirement_results只是作者追溯，不冒充CheckKey结果。
4. **审核Unit身份与结果**：通用原Unit身份匹配/约束检查，按本方法author!=reviewer策略选择独立Unit；不在所有方法硬编码。审核同一固定交付，真实性检查由review Unit执行。保存每key判断/证据/理由、原审核Unit/attempt/source及实际检查范围；未独立检查的事实为asserted，实际核实才可标verified。字段或独立角色标签不认证自己。原ReviewUseCases/来源admission/nominal质量规则保持，always-pass fixture不是生产审核。
5. **结果推进/返工**：原Work/current gate/CAS保存结果和推进，等待通知不是结果。返工新固定refs及SubmissionRef，旧review不覆盖新target，未知外部效果先reconcile。只有符合原方法完整验收条件与动作权限才采纳；审核不是Grant，不增加固定用户确认轮次。

可复用：原SubmissionRef、ArtifactRevisionRef/RepositorySnapshotRef与Blob来源；ReviewRequirement/TargetSet/CheckKey/Plan/Record、MethodBridge.submission_review_requirements；原CurrentMethodWork/CurrentRunWait及AcceptanceUseCases当前源码。它们的通用提交适配、实际结果/身份合同和资格证据仍待owner确认。本方法的提交schema2/模板、executor/reviewer skills、acceptance四criteria及原request→wait流程均复用，不另造流程。系统留来源并准确区分asserted/verified；不把“普通待审提交”误当“所有真实性已经宿主证实”。

本宿主合同是2.5.0继承的来源/ReviewUseCases边界说明，不是2.6.0的状态映射。2.6.0按标准中method-bound finite Choice选项归约完整Decision答案；缺失/未知保持manual或拒绝。回答正文不证明事实或授权，current source、独立review与原Grant/Gate仍生效。本候选不产生host catalog，不编译/封存/发布或触真实数据库；真实Pi与JEV目标保留，原人工admission范围不扩大。

该策略用于原Work中需要方法审核的Unit交付，包括DID/实施包/末端结果；每阶段用原declared standards，不给所有文档附加全部验收criteria。原人类确认/Q&A和人工admission范围不扩张，独立Unit身份约束待原机制按方法消费，不替代或新增用户授权。
