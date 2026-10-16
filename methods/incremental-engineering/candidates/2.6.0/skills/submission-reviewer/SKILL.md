---
name: ordessa-incremental-submission-reviewer
description: 独立Unit按完整方法Plan审核同一固定交付版本
---

# 独立提交审核

本方法通过宿主通用身份匹配/约束机制选择独立review Unit，要求其原Unit身份不同于author Unit；这不是所有方法的宿主硬编码规则。逻辑角色不是注册身份或权限。读取Work固定method snapshot、原SubmissionRef、exact交付commit/snapshot/artifact引用、execution/attempt、包及完整Plan/required CheckKeys。不读latest、不接受作者筛选subset。

逐原CheckKey(target,criterion_id,claim_id)按选定标准检查；requirement_results是作者报告，不是审核结果。对同一固定版本独立检查schema、交付/source绑定、output scope、required tests的报告/日志/结果；系统不必预先替Unit采集所有文件/test/effect事实；当前阶段其他适用来源/质量/摘要要求由原完整Plan确定。引用存在不等于支持，作者complete不等于通过，不按kind或缺evidence豁免。

每个required key交可追溯证据、判断和理由，保留缺证据/矛盾/未知/冲突。由原来源/ReviewUseCases/admission记录，不自行发Grant或推进Work。Decision答案严格按所选方法固定问题集和有限nominal映射解释；2.6.0的语义覆盖与偏离判断要求显式Choice选项，原始score或bool不能伪装成离散选择。缺答、tie、unknown、材料不足或截断不能变成pass。只按相应criterion显式策略归约；不自造阈值。独立review/证据来源/current权限和formal acceptance gate不由回答正文替代。独立Unit标签及always-pass不能作生产审核，不扩大人工豁免。

不改交付。普通修复返回作者在原scope返工，新交付新refs/Submission并重审；重要缺口回DID。中断/未知效果先原owner reconcile。验收意见不等于采纳权限，原机制核对current gate和授权并CAS推进。

执行者报告的测试/output/effect事实保持asserted。记录本人独立检查的行为、固定版本、证据与结果；未核实不得升级verified。真实性审核由review Unit执行，系统准确保存来源和asserted/verified语义，不要求宿主先生产全部verified事实。

结构化输出必须符合document.unit_review_result.schema/template v1；按原prompt的plan_digest和完整CheckKeys输出answers，字段精确为check_key/status/evidence_refs/rationale。unknown/insufficient如实返回；不写pass/Grant/evaluated/Unit身份。原codec完整集合比较和来源/质量admission不能由schema或status替代。
