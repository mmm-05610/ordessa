# Data Model

| 实体 | 必需信息 | 约束 |
| --- | --- | --- |
| CoreRuntime | instance_id/store/registry | 无全局当前数据库 |
| ExecutionPlan | provider/version/resources/request_key/digest/Work 关联 | 提交后不可变，同键不同摘要拒绝 |
| ResourceRequirement | slot/contract/provider/dependencies/ownership | 无环，缺 provider 不隐式选择 |
| ResourceBinding | slot/ref/contract_version/适用 revision 或 digest | 契约校验，不含明文凭据 |
| Lease | id/execution/provider/version/operation_key/ownership/state/safe_handle | 借用只释放引用；句柄可序列化脱敏 |
| Operation | key/kind/input_digest/state/result或error/时间 | 并发同键一个派发者，先意图后副作用 |
| Execution | 既有 ID/Work/plan/provider_handle/状态/原因 | 持久枚举兼容、终态不可逆 |
| ContributionBatch | owner/generation/services/routes/core | staging 不可见，整批发布撤销 |
| ServiceRef | ID/version/interface/scope | required 缺失拒绝、optional 显式缺席 |

## Transitions

Operation: planned → in_flight → succeeded/refused/unknown。unknown 仅凭证据转 succeeded/refused，不超时猜测、不自动重做。
Lease: acquiring → acquired/acquire_unknown/acquire_refused；acquired → releasing → released/release_unknown/release_failed。unknown 固定相关依赖；release_failed 仅显式重试复用身份。
Execution: 保持原持久状态，投影区分启动未知、请求停止、真实终态；transport dead/cancel ack 不造 cancelled。清理状态独立。
Plugin: staged → active → draining → inactive；draining 拒新操作、允许观察/收尾；busy 拒卸载保持依赖，清理未知持久记录。

## Recovery / Historical Storage

凭安全句柄核实未确认运行，不默认 spawn，无 reconciliation 则明确人工处置。Session resume 新 Execution，可关联 previous_execution_ref，不复用终态 ID。
旧 SQL 摘要/编号/表名保持，临时新旧库+二次启动验证。新迁移独立命名空间，不能被旧 schema_versions 最大值跳过。缺旧迁移/解析提供者明确拒绝所需操作，不把旧库当空库重建。
