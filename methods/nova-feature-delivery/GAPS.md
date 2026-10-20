# 当前契约缺口与边界

| 状态 | 具体能力 | 本方法中的含义 |
| --- | --- | --- |
| 当前实现 | `packages/engineering/src/ordessa_engineering/methods/definitions/schemas/v1.py` 的 `ordessa.methods/v1` manifest/workflow contract；有限 acyclic graph；operation outcomes 必须覆盖注册 descriptor。 | `projection/method.yaml` 仅声明一份报告的 report-capture smoke；完整流程 `full_flow_support: unsupported`。 |
| 当前实现 | `engineering.artifacts.create` 的实际 interface-2 schema（见 `docs/implementation/packages-convergence-20261012/engineering/CAPABILITIES.json`、`packages/engineering/src/ordessa_engineering/application/usecases/artifacts.py`）、`MethodBridge.operation_inputs` 精确槽绑定；`ArtifactUseCases._mutate` 与 `material_closure._verify_method_content` 的 MethodPayload/静态 schema 闭包校验。 | phase report 需提交完整、精确的 MethodPayload，并绑定当前 method resource；仅有文档 resource 不代表任意输入都已验证。 |
| 当前实现 | `validation/workflow.py` 校验 slot 引用、descriptor/outcomes 与 DAG；operation 可按真实已注册 outcomes 转移。 | 校验图和 contract，不会读取报告中的业务决定去驱动流程；此处 `completed` / `rejected` 仅为 artifact create 结果。 |
| 在实现/未完成装配 | `packages/engineering/src/ordessa_engineering/application/usecases/queries/method_work.py` 中 `CurrentMethodWorkBindings`、`application/orchestration/method_bridge.py` 的 `MethodBridge`，以及一般 `engineering.work.*` / `engineering.runs.resume` 的 wait/CAS/conditional implementation routes。 | 一般 Work 路由仍依赖宿主 binding；这不是 Nova 适配器。本方法不声明 `wait` event，也不绑定 Nova/Gerrit/Zuul source。 |
| 缺失 | Nova-specific Launchpad、Nova meeting/role、Gerrit、Zuul、release descriptor/catalog、authenticated status provider，以及生产 Nova wait source。 | 上游状态只能由外部权威核验并以引用报告；无自动查询/写入或身份认证。 |
| 缺失 | Nova wait event/生产 source，以及通用条件执行、循环和并行能力。 | `spec_required`、review、冻结、CI 分类和返工均不能在图中执行；PROCESS 是外部程序契约。 |
| 缺失 | 完整外部身份/角色绑定、source trust、变更/发布的外部执行权与对账。 | `reporter`、`decision_record.role_claim` 都是报告者提供的可追溯声明，不认证角色/权威。 |

1. **没有 Nova 状态 owner/adapter。** Current Engineering catalog 的命令不包含 Launchpad Blueprint 查询/更新、Nova meeting decisions、Gerrit、Zuul、OpenStack release discovery。方法文字和来源 URL不会注册这些外部能力。
2. **没有可用的阶段事件来源。** `ordessa.methods/v1` 可编译 `wait` 节点和事件名，但当前没有已发布的 Nova/Gerrit/Zuul event descriptor，也没有生产事件 source。此方法 workflow 因而不含 `wait`。等待、通知、恢复由上游人员处理，并提交新的阶段报告。
3. **无条件执行分支/循环/并行。** 图不自动判断 `spec_required`、review 意见、冻结日期或 CI failure class；完整决策和反复返工只在 `PROCESS.md` 定义为外部程序。没有伪造 outcome、fixture descriptor 或执行循环。
4. **artifact.create 只登记单个报告。** 已声明的真实 descriptor 是 `engineering.artifacts.create`，interface 2、digest `0bc02e9e5a17ada14fc47a3da92abd6c360247768ab0ab1debfc6ec444b213f4`，输入 schema 必填 `kind`（本契约用 `evidence`）；`initial` 和 `method_refs` 按真实接口传入。唯一 workflow outcomes 是命令 `completed`/`rejected`，不是业务批准。每次阶段报告独立调用；它不推进 Nova 生命周期。
5. **方法内容验证有精确条件。** 当前 artifact v2 `MethodPayload` material closure 会读取当前绑定的方法快照和 `document_schema`，校验 resource id/path/digest、schema `$id` 与报告 value。调用者须传完整 `initial` envelope 和匹配 `method_refs`，并具备 host access 和方法绑定。只有 resource 在 manifest 中但没有准确 MethodPayload 绑定，不足以触发此校验。
6. **上游身份、权限和证据真实性仍由上游保证。** schema 检查报告结构，不验证身份、Launchpad 状态、Gerrit vote 来源、Zuul buildset、freeze 适用性或 release 官方性。没有 authenticated Nova role catalog / external-provider trust contract。
7. **无自动版本/周期一致性校验。** schema要求报告携带周期、Blueprint、前序报告和相关链接；PROCESS要求人工比对，但没有外部 API 的最新值或冻结日历。特定行为须由 Nova 本周期规则和有权角色确认。
8. **正式发布与客户采用是不同事实。** 结束状态必须引用 Nova 官方版本/发行说明和关联 commit。无发布时不得声称 release complete；官方发布记录也不证明某一客户部署或完整 CI 历史。
9. **拒绝/取消/延期不等于撤销外部对象。** 本方法无 cancel、abandon、撤回或改周期命令。由具备上游权限者执行，并在后续报告中保留旧链接与新决定。
10. **本包执行证据尚待协调者补录。** `_support/verification/` 由协调者在实际统一编译校验之后记录；此目录不预置“通过”或虚构执行结果。


协调者进一步核对了编译与运行差异：分支语法存在，但当前运行桥只消费有限命令的 journal completed/rejected；Work入口还须是通用current-condition wait并绑定resume contract。完整分类、精确接口和三个设计问题见 [_support/verification/design-findings.md](_support/verification/design-findings.md)，实际静态校验见 [_support/verification/README.md](_support/verification/README.md)。
