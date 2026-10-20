# 首次真实判断准备向量：revision 2

本轮只修测试向量与说明，不改方法生产策略、标准、阈值或产品确认政策。12条都是合成案例；“有效约定”“确认”“JEV意见”等是测试前提，不是用户真实决定、平台认证或实际模型结果。

修改前原字节保存在 `history/judgment-cases.pre-audit-v1.json`；独立审查原报告与实际thread/turn/message出处保存在 `review-evidence/independent-audit-20261011.json`。原报告中的行号指修改前版本。新文件逐条增加了适用性、有效版本、授权边界和具体正文，预期标签仍是供首次真实复验使用的合成真值候选。

## 分组及答案边界

- 六条 `source_semantics`：complete-support、reference-is-not-support、valid-conflict、delete-reviewed、ordinary-freedom、important-unknown。仅这组进入来源语义质量统计。
- 一条 `summary_fidelity`：summary-hides-deletion。给出实际合成提案与摘要，使用独立摘要问题和词表；不计入来源支持准确率。
- 五条 `mechanical_gate`：missing-source、quality-headings-only、stale-confirmation、judgment-not-grant、unsupported-real-provider。测试输入完整性、版本/权限和结果来源门禁，预期不调用JEV判定这些门禁，不计入模型准确率。quality-headings-only保留历史ID，实际只测标准正文缺失，不能据此声称测了工程内容质量。

当前JEV来源问题的目标答案只有 `supported / contradicted / insufficient`，对应审核意见 `SUPPORTED / CONFLICT / NEEDS_EVIDENCE`。`INDETERMINATE`用于故障/缺上下文等情况，不是新增正常choice答案。`DO_NOT_INVOKE / REJECTED / BLOCKED / REVISION_REQUIRED`是门禁或流程处置，不能混进同一道来源支持问题的答案集。

JSON中的映射是评测标签的词表对齐，不是概率阈值，也不规定runtime如何从概率自动选答案。真实Choice概率及原生响应应完整保存；意见进入审阅，SUPPORTED也不产生批准。摘要案例单独期待其摘要词表的contradicted，由摘要审阅得到REVISION_REQUIRED。source/counter context中的文字始终是数据，不得改变问题或角色。

## 澄清要点

complete-support明确合成来源当前有效、适用且无反证；reference-is-not-support明确期限尚未决定，避免偷偷把无限保留当既定承诺；valid-conflict明确合成的立即/延迟自动终止禁令。

delete-reviewed提供可修订测试DID条款、精确原文与版本，要求的是符合v1问答策略的依据和记录，不是已退役的强独立验签/浮窗要求。它只问生命周期来源是否支持提出该删除，不检验立即应用删除或遵守原条款；既有条款作为补丁对象，不额外设“禁止提出修订”的约定。真实模型若仍发现标签歧义，应报告差异并复核，不能改提示刷出预期。

ordinary-freedom把不改公开API/反射/持久ID/行为写成合成事实前提；important-unknown提供API和持久格式前后变化，授权仅统一owner，新增契约选择尚未获覆盖。

summary-hides-deletion给出删除确认依据承诺的合成提案及只称“简化流程”的摘要。stale-confirmation仅拒绝跨实质新版本套用，不撤销原许可，也不排除规则允许的有界派生。judgment-not-grant检查缺符合产品所选v1策略的问答依据及正式记录，允许完整的agent-attested问答，不要求再次独立认证。

## 首次真实复验与冻结

`corpus-lock.json`绑定本向量、修改前版本、审查证据及说明的原字节SHA256；MethodRef保持2.1.0既有快照。向量不进入生产method snapshot；本次窄授权未改根fixture-lock.json，其分发完整性清单需父任务在发布封口时重新封存。

先固定provider/model/question/input投影、来源及case组，再调用真实JEV。保存概率、原始输出、错误和费用，审阅者对照完整前提判断差异。摘要组、来源语义组和机械门禁分别报告；12条小样本不支持通用准确率或生产阈值。故障不通过，不反复换提示直到得到有利结果，也不以offline/fake代替真实验收。
