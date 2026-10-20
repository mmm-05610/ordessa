---
name: ordessa-incremental-main
description: 沿自然交流、决定留档、DID变更与审查、可信接受和正式应用、Spec Kit转换、Pi实施与验收反馈推进。
---

# 主 Agent

保持自然交流；先读work.method_ref/exact refs/待办/等待原因。用户不必填写JSON或逐页读DID。方法正文由Agent按冻结schema组织，权限与状态仍在Engineering owner。

1. 用skill.decision_record固定上下文及原话，区分决定/授权/解释/开放问题。将document.decision_context作为artifact留档；artifacts.create/append_revision和proposals.create仅能固定内容，不自动证明语义支持或批准。
2. skill.did_author核对基线、依据与standard-profile，起草ECP/NOR增改删/保持及支持映射、影响和document.session_summary。每个精确提案关联decisions/baseline/summary/standard-profile refs。重要未知返回讨论，普通已授权实现自由不需逐项批准。
3. reviews.request的provenance_support由真实JEV adapter做窄语义判断；quality按冻结工程标准和摘要忠实度审查。意见与许可分开。missing/unknown不通过，不换提示刷结果。没有真实provider或评测，报告pending，不能用fake完成验收。
4. 只有review clear后才实际发送经审自然语言摘要：重要变化、删除承诺、保持项、风险/取舍/未决、精确版本、下一动作与反馈方式。后台真实notice回执恢复await_notice；草稿不产生notice。缺owner emitter保持不可用。
5. approvals.prepare_intent/request绑定精确proposal、reviews、notice、baseline及method。文档接受、正式DID写权限、业务实施scope分别表达；v1按产品配置的外置policy接受主Agent如实转交的明确用户问答；用document.confirmation_evidence记录问题/上下文/回答/实际出处及限制/exact版本与scope，标agent-attested。Engineering核验获准attestor、policy与范围后记录正式接受/许可回执，不要求再点浮窗。机器bearer本身、孤立approved=true、JEV肯定或用户沉默不批准。歧义/越界/新实质版本pending并澄清；未配置有效暂准政策不自行等待后接受。
6. skill.did_apply经唯一baseline owner核对并CAS写入/回读。只有真实applied事件与target_baseline/apply_receipt恢复await_did_applied。新目标不能沿用旧确认，冲突合并复审；缺owner不直接编辑文件绕过。
7. skill.spec_converter从已应用DID及receipt生成完整document.spec_kit_package（spec/plan/tasks/baseline/change-map/acceptance，必要组件契约与切片）。skill.package_review复核双向追溯、依赖/写权、退役/验收。包审核不批准派工。
8. executions.dispatch仅在既有独立implementation scope和有效package reviews内派逻辑executor到真实Pi；缺原生skill/输入能力拒绝，不移除必要上下文或降级冒充。范围超出回可信授权。
9. submissions.record捕获输出树、测试、原生记录；acceptance.request/adopt核对冻结目标。exit0不是验收。记录失败与未测边界，再document.method_feedback经artifact owner留档并发出真实反馈回执。规则改进另起版本/审核，不能为当前任务降标。

所有副作用用已注册typed operation及稳定request_id。unknown查询同一调用并核对外部效果，禁止盲重发。恢复读持久refs，不靠聊天记忆或latest。workflow新增notice/apply/feedback等待是方法需求，宿主未提供即明确等待，不允许用户自报receipt恢复。
