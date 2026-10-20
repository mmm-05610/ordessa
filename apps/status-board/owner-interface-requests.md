# 后续产品集成：精确 owner 接口请求

本文件是交回后端 owner 的需求，不是已发布契约或已接通声明。Python system-access/bindings/Server 均未由本轮修改；不要求新增业务判定到前端或 apps。

初始检查点只有服务发现；后续父任务已交接 `engineering.capabilities` 和六项 Engineering 精确查询，并按 `engineering-wire/1` 接入侧窗原记录详情。它们不提供 Work 投影、目标结构或可信 consent。`system_access/contracts/schemas/operation-catalog.json` 标记 `runtime_contract_candidates`，且 `trusted_confirmation_callback: false`，不能依据候选名字猜测写操作；本轮只按实际 engineering_wire.py 发布的读取方法消费。

## 读取投影

请由实际 Engineering / Execution owner 经 system-access 发布只读查询并提供 operation id、输入/输出 schema/version、availability 和权限范围。TS 对接位置：`apps/status-board/src/composition.ts`；显示接缝：`BoardSource.read()`。

一次读取必须携带一致快照 revision 和权威 scope，并覆盖：

1. 工作记录：稳定 id、内容 version、scope、标题、待处理/进行中/最近结果分类、原始状态、变化说明。包含跨目录及无目录工作，不以 filesystem path 限定唯一归属。分类由 owner 提供，前端不从 Agent 进程存活推断验收。
2. 每条工作的实际方法绑定：名称、方法版本（可在投影名称/依据说明中呈现）、有序 step id/label/status；未绑定明确缺席。不能将 DID 或 spec-kit 固定成通用步骤。
3. 已记录目标结构：稳定 node id、可选 parent id、工作关联 id，以及分别来自设计、实施、验收 owner 的状态。不是文件系统扫描。请提供结构来源与版本；可映射为节点名称/工作依据，后续如有权威结构版本元数据可扩展显示投影。
4. 详情：依据、审核、批准、执行与证据的可显示引用与状态；没有记录明确缺席。初始显示投影为字符串列表，不复制内部业务对象；适配层从已发布 wire schema 投影并验证，禁止查询 SQLite 或读取 owner 私有模块。
5. 查询失效、权限拒绝、暂不可用应保留明确结果；没有记录的成功空态必须与未接通区分。分页/增量协议需保证快照一致性，不允许拼合不同版本的批准与变化。

## 可信确认

请提供可信人类入口、确认准备查询及提交操作，明确谁验证身份、权限、版本/范围和最终写入。当前机器 bearer 无默认 Engineering grants，不能充当人类授权。

显示接缝 `BoardSource.confirm({id, version, scope, snapshotRevision})` 仅在正式可信实现接入后绑定。后端必须在同一权威提交中原子比较精确内容版本、授权范围、确认意图/有效期和撤销状态；变化后拒绝，不能仅靠前端刷新比对。请提供防重复 operation/intent id 和提交结果查询，处理 Unknown 而非自动重发。前端提示不构成 Grant，UI 测试通过也不构成批准。

## 订阅与恢复

请提供权威订阅 capability、事件 schema、游标/断点及重新读取协议。当前只有每 30 秒显式只读刷新与本地状态订阅，不声称已接入 Server 事件流。断线保留最后成功快照与时间，恢复重新读取。

## 当前禁止补位

不由本轮改 Engineering、Execution/Environments、Harness 或 Infrastructure 核心；不新增本地任务登记簿，不扫描夜间文档冒充实时状态，不复制业务对象，不实现假的批准操作。
