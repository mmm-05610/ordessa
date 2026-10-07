# M04 · 任务边界与颗粒度审查

## 定位
只判断任务是否足够明确，可以进入单元选择。内部状态 gate_pass 不等于对外 ready；
完整提案尚未产生时不得提前返回ready。主Agent负责与用户沟通和修改任务。
默认策略是可版本化业务资源，位于flows之外的运行器不内建它。

## 输入
TaskBrief、授权事实安全引用、TaskGatePolicy、可选可信旧审查证据。
Policy含policyId/version/digest、适用任务类别、rubric维度、hard checks、合法缺陷代码、
解释模板、聚合规则、轮数限制。缺策略/无效阈值属于技术policy_invalid，不能怪用户任务。
策略使用可信代码或有限数据配置，不引入任意表达式eval/流程DSL。

## 默认六个维度
1. 目标：明确要得到或改变的结果。
2. 边界：对象、范围、禁止项及冲突。
3. 验收：有可观察完成条件且与目标对应。
4. 可分解性：是否多个独立交付/独立授权，而不是仅多个必要步骤。
5. 单元适配：任务是否形成有限工作约定，仍可由主Agent回答、不强制委派。
6. 风险：哪些成本、破坏性、外部写入和秘密边界尚未裁定；模型不授予权限。

一个主要交付、有结束点、不需单元替用户做重大取舍可以通过。
“分析→修改→测试”不必拆；“审查100文件交风险报告”也未必过大；
“修登录+迁DB+生产发布”需要核清独立交付与授权。
规模阈值由外部策略按任务类型明确，本模块无普适文件数/分钟阈值。

## 处理流程
结构校验 → 策略检查 → 纯规则缺字段/冲突检查 → 编译有限问题 →
Jev选择cohesive/independent/unknown等答案 → 确定性归并 → gate_pass或业务缺口。
已可确定缺口时零模型调用。Jev只选代码/证据槽，模板组装解释，不生成新任务。
unknown必需维度不能pass；模型“低风险”不能覆盖未知权限。

## 输出与聚合
缺陷：code、dimensionId、affectedRequirementIds、remedyActor(main_agent/user/owner)、
templateId、允许的templateParams、evidenceRefs。
- 事实已明确但提交表达有误：revise，由主Agent修正。
- 需新信息/用户选择/权利确认：clarify，问题有具体阻塞关系。
- 已知业务要求和能力冲突：blocked，说明可解除条件。
- policy/provider/protocol故障：failed；预算耗尽：budget_exhausted；取消不映射业务缺口。
全部缺陷保留；基础设施故障优先技术终态，其次可信policy声明且不依赖未知事实的fatalBusinessBlock→blocked，其次clarify，其次revise；无缺口继续流程。未知事实上的冲突不能当确定fatal block。policy缺聚合规则为policy_invalid。

## 多轮约束
仅run内或调用方显式提供可信旧证据时比较 taskRevision、policyDigest、相关facts/questions摘要。
同判定签名、无新的相关事实，不再调用模型；返回相同证据关联或clarify/revise，不能随机刷到pass。
不建立跨run全局缓存，不保证同requestId再次提交免费或幂等。
补无关上下文不构成新依据；主Agent补充任务后使用新taskRevision、新run，不自动继续旧run。

## 验收
T43–T48及T03/T11/T16/T41。模板不得引用任意敏感正文；策略缺失、任务缺失、模型故障明确区分。
