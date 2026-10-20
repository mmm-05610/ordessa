# 完整流程与有限投影覆盖表

本方法包的目标规格是 `PROCESS.md` 描述的完整 Nova feature-delivery 外部流程。整体 `full_flow_support` 为 **unsupported**。唯一可编译候选在 [`projection/method.yaml`](projection/method.yaml)，其 `method_id` 为 `ordessa.nova-feature-delivery.report-smoke`，仅以真实 `engineering.artifacts.create` 登记一份阶段报告。它不调度完整流程，也不替代上游工作。表中“保留”指规格描述；“投影覆盖”只指可以登记该阶段的报告，不表示阶段行为被执行。

| 完整流程阶段 | PROCESS 规格 | report-capture 投影 | 不覆盖/执行边界 |
| --- | --- | --- | --- |
| Blueprint 创建、范围与影响说明 | 保留 | 可登记 blueprint 报告 | 不查询/创建/更新 Launchpad Blueprint，不核实属性 |
| spec 需求判定 | 保留“需要 spec”和“无需 spec”两支 | 可登记筛选报告；`spec_required:false` 时 `spec:null` | 无条件判断器；no-spec 不能绕过周期批准 |
| 设计评审与返工 | 保留评审、负评反馈、修改后重审与无需 spec 情形 | 可登记每轮 design-review 报告并以 predecessor 链接 | 不召集评审、不评判材料、不自动循环；`not_applicable` no-spec 报告须说明理由 |
| 本周期批准/接纳 | 保留，含 no-spec Blueprint 的周期批准 | 可登记 cycle-approval；无 spec 时 `spec_required:false`、`spec:null`；spec 已要求但尚未提交时允许 null | 不投票、不认证批准人/会议、不分配周期 |
| 补丁、测试、文档 | 保留实现交付要求 | 可登记 implementation 报告 | 不改代码、不运行测试、不写文档、不接受自验收 |
| Gerrit 提交与评审 | 保留 change、patchset、review、负评返工 | 可登记 Gerrit 报告 | 不提交 patch、不读取/写入 Gerrit、不代替 reviewer；每轮需新报告关联版本 |
| Zuul check 与 gate | 保留 check/gate 区别、报告记录和恢复路径 | 可登记相应阶段报告及 failure class | 不启动/重试 pipeline、不查询 buildset；代码/测试失败与设施失败分类由有权外部角色调查并报告 |
| 合并 | 保留通过 gate 后合并及 commit 绑定 | 可登记 merge 报告，已合并时需 commit 信息 | 不批准、不合并、不确认远端状态 |
| 发布准备与 freeze | 保留发布准备、冻结窗口及错过冻结后的延期重审 | 可登记准备、等待、延期与重审报告 | 不追踪日历、不判断 freeze、不安排下一周期；延期后需外部重审批准 |
| 正式 release | 保留正式版本发布与 inclusion 证据要求 | 可登记 release 报告；仅 `result:released` 要求 release 对象 | 不发布、不构建、不确认完整 CI 或客户部署；只有官方 release/inclusion 引用可支持版本绑定陈述 |
| 取消、拒绝、结束反馈 | 保留流程结束反馈、后续动作、取消/拒绝记录 | 可登记对应阶段报告；feedback 可登记摘要与 follow-ups | 不撤销 Blueprint/Gerrit 工作，不关闭外部流程，不把 artifact 命令的 `rejected` 当业务拒绝 |

因此 no-spec 分支、负评重工、CI 诊断与恢复、freeze 重审及任何发布动作全部属于规格，不属于可执行投影。成功、返工等待后恢复、拒绝/延期、no-spec 周期批准 JSON 都位于 `_support/design-traces/`，是合成报告形状说明，不是可运行 fixture 或运行证据。

## 对应的实现边界证据

- Manifest/workflow contract：`packages/engineering/src/ordessa_engineering/methods/definitions/schemas/v1.py` 定义 `ordessa.methods/v1` 的有限 operation/wait/stop 结构；`packages/engineering/src/ordessa_engineering/methods/validation/workflow.py` 对 workflow 引用、真实 descriptor/outcomes 与 acyclic graph 做静态检查。其 contract 不提供通用条件、循环或并行节点。
- Catalog：`docs/implementation/packages-convergence-20261012/engineering/CAPABILITIES.json` 的 `engineering.artifacts.create` 条目声明 interface version `2`、必填 `kind`（真实枚举含 `design`、`evidence`、`implementation_package`、`other`、`plan`、`review_body`、`specification`、`task_list`）、可选 `initial` 和 `method_refs`；`initial` 是受限 `ArtifactRevision`/MethodPayload envelope，不能把 schema resource 当成自动生成的 input。真实 descriptor digest `0bc02e9e5a17ada14fc47a3da92abd6c360247768ab0ab1debfc6ec444b213f4` 在投影 manifest 中明确固定。artifact 命令 outcomes `completed` / `rejected` 不是 Nova 业务决定。
- 静态方法内容绑定：`packages/engineering/src/ordessa_engineering/application/usecases/artifacts.py` 中 `ArtifactUseCases._mutate` 消费 `initial`；`packages/engineering/src/ordessa_engineering/application/usecases/material_closure.py` 的 method-content 校验要求精确 MethodPayload/schema ref 闭包。只有资源文件存在于 manifest 不足以强制验证；调用还须携带准确 `method_refs` 与完整 initial envelope。
- 方法运行桥接：`packages/engineering/src/ordessa_engineering/application/orchestration/method_bridge.py` 的 `MethodBridge` 只将声明的 slots 映射为 operation inputs。`CurrentMethodWorkBindings` 位于 `packages/engineering/src/ordessa_engineering/application/usecases/queries/method_work.py`；通用 Work wait/CAS 路由不等同于 Nova 事件源或 Nova 适配器。
- 当前能力清单的 18 个真实 commands 与 2 个 checks 里没有 Nova/Launchpad/Gerrit/Zuul/release descriptor。禁止用 fixture catalog 造出能力。`wait` 的语法支持也不代表有可用的生产 source。

统一编译和校验结果由协调者记录在 `_support/verification/`；本文件不声称投影已编译或运行。


协调者进一步核对了编译与运行差异：分支语法存在，但当前运行桥只消费有限命令的 journal completed/rejected；Work入口还须是通用current-condition wait并绑定resume contract。完整分类、精确接口和三个设计问题见 [_support/verification/design-findings.md](_support/verification/design-findings.md)，实际静态校验见 [_support/verification/README.md](_support/verification/README.md)。
