# M01 · 公共契约
目的：使流程、模型、事实来源和产品消费者可独立实现而共享精确语义。
详细结构见 [数据模型](../data-model.md) 和 [公开接口](../contracts/public-api.md)。

## 内部组成
identity/task/observations/questions/proposals/outcomes/limits/ports/codec。
只有标准库，所有 DTO 可深度冻结、规范编码、有边界验证；端口为 Protocol，不实例化外部服务。
public.py 精选导出，不 re-export 上游图或核心内部类。

## 不变量
1. 稳定引用保留 source namespace 和完整 identity；显示名称不能成为 key。
2. 不完整任务结构有效，交给任务审查；无效 JSON/身份/版本在运行前拒绝。
3. 公共终态排他；completed 才能持有业务结果。
4. 提案必须绑定依据与 checker；valid receipt 精确绑定 proposalDigest。
5. 不向模型传 principal、Token、lease、callback 或任意执行对象。
6. 观察副本不写回 owner；版本未知不拿时间或 hash 伪造 CAS。

## 实施要求
先发布 JSON schema、规范编码向量、Python DTO 和 fake ports；
明确 proposalDigest/resultDigest 的覆盖域，避免 receipt 自引用。
顶层未知字段拒绝，扩展只进命名空间；未知 configurationKind 可通过外部描述正常传递。
上游类型仅在本包内部装配层出现，产品 wire 不传播图执行器对象。

## 单模块验收
T01/T02/T07/T08/T09/T10/T17/T18/T21/T22/T26/T27/T31/T32，编号定义见 [验收矩阵](../acceptance.md)。
重点反例：frozen 外壳中的 dict 仍能修改；跨 namespace 同 id 被合并；
旧 receipt 配新 payload；正文自授权限；task 缺 acceptance 被 codec 拒绝。
模块结构通过不替代真实提供者兼容验证。

