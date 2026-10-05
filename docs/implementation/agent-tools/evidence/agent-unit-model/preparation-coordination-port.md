# 固定 Profile → Unit → Node 协调接缝

`AgentServices.assembly` 与 ProfileCatalog/NodePublication 使用同一个 Environment、CoreRegistry、OperationStore/DomainStore 和 InvocationIssuer。显式 v2 `agents.nodes.prepare` 薄绑定现有参数；默认 v1 不扩展。`nodePreparation` 只说明所需部署端口已组成，仍须逐请求核实 Provider、安装与授权，不证明某家二进制或某配置声明可用。缺端口时返回 CAPABILITY_UNSUPPORTED，未取得 claim。

## 固定与派发

协调器先核对可信 principal，读取准确 ProfileRef 的不可变 manifest，经唯一 Registry 获取当前 admitted RuntimeProvider。请求摘要含完整 ProfileRef/context/options，沿用环境＋调用者＋request-id：同键异内容/异操作拒绝；同键同内容保留原操作。原 Node/operation 身份只在第一次预留分配。

准备 context 的部署 owner 使用 `PreparationContextPort.resolve` 核实 Workspace DirectoryBinding、安装版本来源、运行时关联、选项及启动作用许可。它必须是观察接口，不能创建根、进程或调用模型；不能把 caller 路径、Bearer 或 OS 可访问当执行授权。未批准的模型/启动 hook、未满足的安装版本/保证或可选省略必须拒绝。结果包含已核 DirectoryBinding、installationRef 等安全来源引用、private_context 及 management epoch；private_context 的 nodeRef 必须是核心固定目标。

Provider.plan_preparation 保持纯函数。核心保存受保护的 planDigest、准确 ProfileRef、DirectoryBinding/来源引用及命名 prepare/start 步骤，原生计划和私有根不进入操作日志。每个尚未派发步骤前以及 Node 发布前，重新生成计划并比较来源、摘要、epoch 和当前 provider generation。更改来源不授权重建 Unit。

预留 Node/operation/provider Usage 同事务完成；每步由原 Issuer 获取一次 durable claim，Provider 在 Environment admission 锁外执行，并必须消费原 InvocationContext。同一步已有 claim 就返回原状态，不重发。核心无法证明结果时记录 unknown 并保留占用。

## Owner 确认与发布

`PreparationObservationPort.observe(operation, step, reply)` 必须读取原 owner journal/native 回执，核对 stepId/provider/inputDigest/recoveryCorrelation；不能仅把 reply ACK 转成已完成。它返回安全证据引用、唯一 prepared UnitRef 和本原操作已取得的 Usage。prepare 结论与实际 Unit use 占用同事务记录；start 只能沿用这一 Unit，不能换目标。

preparedUnit 只持久 `{unitRef: ...}`。这里的 UnitRef 必须携带既有 Node 契约所需 environmentNamespace/ownerProviderRef/sourceRevision 和真实叶身份。sourceRevision 是固定 Unit 引用的来源，不是核心推算的当前原生配置版本。当前三家 prepare 返回的两字段 raw UnitRef 与后续 Node 的 owner-bound 引用尚未统一，需要 AU003 由所属 owner 保持身份并接通；不能在 CLI 里剥离或补造身份。

所有结论齐备后，NodePublication 再核实实际 owner binding、完整步骤来源、access surface 及 provider 当前接纳身份。原 provider 和 Unit Usage 全部转交固定 Node，同事务发布；缺实际 Unit use、遗漏保留 Usage 或 unknown 均不得发布。配置与 native session 实际知识仍属插件；允许已证实 Unit 没有 session，核心不填假 session。

## 查询与崩溃窗

`assembly.query(request)` 只查询已经 claim 的原步骤，由原 query InvocationContext 验证。没有原 native owner 证据就保持原状态；不调用 prepare/start 或派发缺失步骤。原查询确认后，显式 prepare 可继续尚未派发的原步骤，或仅进行数据发布；不会重建已 claim 的 Unit。迟到/旧观察不能覆盖较新 step revision，失败观察不能降级已有结论。

首次提交前、claim 后断连、owner 回执后未记录、已结论未发布分别留在原持久链中；没有额外 recovery ledger。冷启动不能凭句柄缺席推断未派发。部署 owner 的冷查询证据和三家进程恢复仍待接线，此阶段测试没有证明真实进程崩溃恢复。

## 当前边界与验收

C1 acquire/material/SecretRef 生产端口尚未接入，manifest 含 resourceRefs 或 SecretRef 即在取得 claim 前拒绝；不直接把引用当材料。该拒绝是未完成范围，不能用无材料 fixture 替代材料门。完整安装版本核验、目录/作用授权来源、持续 writer fence、三家真实 receipt 投影及生命周期仍待完成。

`test_assembly.py` 使用真实 Profile/Registry/SQLite/Issuer 和受控 Provider/owner，不使用真实品牌二进制或模型。覆盖原步骤贯通、全部 Usage 转交、请求冲突、缺端口/材料、ACK/失去验证/错关联/换 Unit、两步间来源/授权/退役变更、unknown 不重发、原查询继续、并发重放与迟到失败不降级。公开 v2 handler 直接调用实际协调器；默认未装配时不在 supportedMethods 宣称 prepare。不能把这些 C 证据升级为三家 P/M 或 AU002_DONE。
