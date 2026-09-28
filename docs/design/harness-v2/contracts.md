# Domain contracts v1（目标契约）

这些接口尚未实现。下列名称在本包审定后冻结；实施时 DTO 必须提供可导入类型、判别联合、结构校验与类型反例，不能退化为任意字典。通用 carrier 使用平台已有 `Contribution(point_id, api_version, payload, required)`，owner 由宿主传入，不由业务声明。

## C1 Runtime adapter 注册

点：`harness.runtime-adapters`，版本 `v1`，多贡献者。每项：

组合期由 products/server 通过平台公开组合接缝声明这两个点，并绑定 Harness 提供的 handler；再激活贡献者。不是 Harness 插件 import 宿主私有类后自行改注册表。参考平台树已有 `register_contribution_point(..., handler=..., exclusive=False)`，但其正式公开组合入口及卸载/busy 对接仍须在 B1 冻结验证。点已声明而 handler 缺席必须拒绝，不能丢弃贡献。

| 字段/方法 | 约束 |
| --- | --- |
| adapter_id / api_version | 稳定唯一；不允许冒领其他贡献者 |
| harness_id / aliases | canonical 品牌唯一；别名冲突拒绝，不修改持久化标识 |
| supported_versions | 可确定匹配的版本范围；未识别版本返回 unknown，不猜测 |
| describe_installation() | 受控只读检测结果，包含 native/adapter 版本与证据引用 |
| describe_targets() | 文件/目录/环境目标句柄、codec、作用域、允许字段范围、reset 基线规则 |
| describe_actions() | 原生控制动作 ID、输入/结果 schema、作用域、确认机制、是否可补偿 |
| prepare_launch(request) | 只生成校验后的 launch plan；不 spawn、不解析实际 secret |
| start/connect/close/reconcile | 沿现有生命周期结果成功/拒绝/未知；关闭必须验证实例归属 |
| prepare_reconfiguration(plan) | 判断 session-local/reload/restart-resume/unsupported，并给影响集合 |
| resume(request) | 必须核验 native session identity 与预期 generation，不能退化 session/new |

同一 harness 的多个版本实现由一个 runtime adapter 内确定路由；本版不允许多个插件对同一 canonical harness 竞价或 last-wins。替换需明确卸载旧所有者，忙时拒绝。新实现必须跑统一 conformance suite。

## C2 Configuration adapter 注册

点：`harness.configuration-adapters`，版本 `v1`，多贡献者。配置 adapter 归业务插件，例如 `assets.model-provider.codex`、`assets.skills.claude`。

每项包含 adapter_id、facet_id、facet_schema_version、harness_id、受支持 native/adapter 版本范围、入口集合、业务 payload schema、claims、方法：

```text
assess(context, request) -> supported | unsupported | unknown
compile(context, before, desired) -> IntentSet | Refusal
verify(context, observed) -> Match | Mismatch | Unknown
```

context 仅包含授权的目标句柄、非秘密能力事实和版本；compile/verify 不得读用户 HOME、网络、spawn、调用模型或写文件。观察动作由 Harness 执行，verify 只解释采样结果。

注册时检查同一 `(facet_id, harness_id, entry, version-range)` 不重叠；不同 facet 对相同 native 字段的声明冲突也拒绝。范围无法证明不相交时拒绝，不靠优先级决定。多配置属于同一原生数组的，必须由一个业务所有者给出最终数组，不让两个 adapter 分别重排。

**同一业务 schema 在多个 Harness 复用；品牌差异在业务域内部模块，不为每个设置项开一个插件。** 通用格式/打包函数可以放业务域内共享，不能把共同名称当共同语义。

## C3 有类型的 IntentSet

业务 payload 可以由注册 schema 定义，但 intent 的外壳与操作必须封闭、可验证：

- `SetField(target_handle, field_path, typed_value)`。
- `ResetField(target_handle, field_path, baseline_rule)`：remove-key/native-default/restore-owned-baseline；规则必须由 runtime target 授权。
- `MountContent(target_handle, relative_name, immutable_content_ref, mode)`：内容引用与摘要，不是任意绝对路径。
- `RemoveOwnedContent(target_handle, relative_name)`：只能移除该贡献者此前产生的内容。
- `BindSecret(target_handle, slot, secret_ref)`：密钥仅在后端应用时解析，不能混进普通 typed_value。
- `InvokeAction(action_id, schema_version, typed_payload, expected_observation)`：仅 C1 已公布且本贡献者获准的动作，不接受 shell/任意代码。

每项携带 facet/item 来源和贡献版本，owner 由注册上下文补齐。target 不暴露任意写路径；field_path 使用结构化 segment，不用字符串拼接路径。祖先/后代路径写入、set/reset、文件/目录重叠都是冲突。相同值也不默许两个所有者争用同字段。

多项 intent 先合成完整快照，校验引用/容量/编码/未知字段，再写候选 generation。不能每个 adapter 单独写同一个 settings.json。JSON/TOML/YAML codec 只负责结构，不负责品牌含义；现有手写品牌 renderer 的语义测试迁到对应业务插件。

路径必须位于实例所有的配置根内；拒绝穿越、symlink 逃逸及根替换竞争；权限按最小需求。内容大小/数量有硬上限，配置与日志不保存秘密明文。临时产物也有清理所有权。多文件发布不得声称操作系统提供跨文件事务：未运行实例可从完整 generation 启动；热读多文件须有原生原子切换机制，否则升级为受控重启。

## C4 Application service

后端领域端口 `harness.configuration`：

```text
inspect(target) -> ConfigurationCapabilities
plan(target, desired_fragments, expected_revision) -> Plan | Refusal
apply(plan_id, operation_key, submission_permit) -> Confirmed | Refused | Unknown
query(operation_key) -> OperationRecord | NotFound
reconcile(operation_key) -> Confirmed | Refused | Unknown
```

target 必须是服务端可验证的 server/session/channel identity + runtime_generation，不仅是 harnessId。调用主体从鉴权上下文确定，不能由参数冒领。plan 绑定配置内容摘要、版本、目标 generation、提供者 generation、授权修订、秘密引用修订、expiry；应用前重验证，任一变动拒绝 stale-plan。

`desired_fragments` 包含稳定 facet/item ID、schema、期望值/显式 reset、业务引用及修订。不接收 Profile CRUD 或完整 UI 状态。未知字段、缺失适配、未经支持的 operation 在副作用前拒绝。

Confirmed 含 operation_id、applied_revision、实际 native session identity、runtime_generation、验证证据引用和资源变更事实；不含 secret。Refused 含稳定 code、item 诊断、是否保持原状态。Unknown 含 operation_id、已知阶段、哪些效果已观察/待核验及允许的下一动作；不得扮成原样未发生。

幂等键 scope = principal + target identity + operation_key；内容摘要不同拒绝 conflict。同键进行中可查询/等待，不并发再执行。不同键同会话必须串行，安全性不能只靠前端按钮禁用。

## C5 与 ACP/发送的接线（禁止第二客户端）

一次提交使用唯一 submission_id，输入文本/附件摘要与配置意图一起冻结。会话服务持有跨配置/发送的串行闸门，并给 Harness 一个一次性的 submission permit。只有该闸门能消费 permit；外部裸 apply 无 permit 拒绝，防止输出期间绕过时机约束。

闸门的互斥、permit 校验与消费权威必须在后端，前端仅持有不透明引用，不可凭前端内存锁或自报 idle 授权。permit 绑定 principal、session/channel、runtime_generation、submission_id、输入摘要、配置摘要、expiry，重放或换目标拒绝；连接丢失后闸门保持待对账而非立即允许第二发送。生产绑定必须证明配置接口及同通道的 prompt 路径均受它约束，不能保留一条可绕过的裸发送入口。如何映射到当前唯一 ACP owner 是 B2 的必需接线验收，不由 renderer 生成“可信令牌”。

顺序固定：

1. 获得会话提交闸门，确认没有正在输出的 turn；重读 Profile 最新修订并叠加 item 覆盖。
2. 校验完整配置与项目/资源绑定；生成并持久化 plan/operation。
3. Harness 经**现有通道的协议控制所有者**应用；涉及原生协议动作时挂起业务 prompt，使用该所有者的请求 ID/响应关联机制。
4. 验证有效配置；Profile 持久化绑定/清除旧覆盖；会话服务记录可发送状态。
5. 原 ACP 客户端发送原消息一次，记录发送结果。配置确认不等于消息已送达。

不允许 Harness 对透明 relay 偷塞未登记的 JSON-RPC 请求，也不另建一个 ACP client 与 connectors/acp 抢 session。**本包要求给既有 channel/controller 增加受限控制端口，并在 connectors/acp 的既有 owner 中消费它**；具体 DTO 在 T00 对实际平台交付绑定，不能靠 mock 端口替代生产接线。

后端秘密环境/认证配置由 Harness runtime 的启动或 session-scoped adapter 入口注入，绝不让密钥经过桌面 ACP 帧。Claude 不调用全局 `providers/set`。若现有透明链无法提供“同一 owner、秘密留后端”的操作路径，该品牌切换门是阻塞，不把控制权转交前端绕过。

输出期间新选择只更新 desired choice；一次提交已经冻结后又作的新选择属于下次提交。传输中断或提交超时不自动重发 prompt，也不重做未知配置事务。取消必须到达同一闸门与操作；已发生副作用先对账，不当作普通无效计划删除。

## C6 生命周期、服务缺席与错误

注册 stage 纯校验、commit 才可见；启动失败逆序清理已发布贡献，原异常主导，cleanup_errors 累加。域内注册不能绕过宿主 requires/所有者限制。

计划尚未应用时提供者卸载使计划失效；正在应用时阻止卸载。活跃实例仍依赖 adapter 的 close/reconcile，runtime provider 也保持 busy。配置 provider 在仍持有秘密/资源或需要其验证恢复时同样 busy；成功转为不依赖 provider 的不可变快照后才可解除占用。不能卸载完再找不到恢复代码。

错误至少区分：adapter-missing、version-unverified、capability-unsupported、invalid-fragment、target-conflict、stale-plan、authorization-refused、isolation-unproven、busy、resume-unavailable、verification-mismatch、operation-unknown。领域 code 注册到已有 wire error-family 机制，不修改核心错误分支。不支持与未知不是一个状态。
