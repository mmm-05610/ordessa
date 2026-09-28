# Contracts：两个域经公开点接入

以下名称是目标语义，尚非已发布可导入 API。T00 以平台最终 SHA 对照已交付的 `Contribution`、Profile `FacetDescriptor`、Harness C1/C2 和 Server handler contract，冻结真实类型；不得建立第二套宿主或由插件 import 私有 host。严格区分配置时 adapter 与运行时 authorization gate。

## C1 Permissions 贡献

`permissions.policy-adapters@1` 由 Permissions 域向 Harness 公开点贡献，owner/generation 由宿主赋值。按 `(harnessId, nativeVersionRange)` 唯一，重叠拒绝，不 last-wins。形状：`adapterId`, `supports(evidence)->supported|unsupported|unknown`, `compilePolicy(snapshot)->IntentSet|Refusal`, `verifyPolicy(observation)->Confirmed|Unknown|Mismatch`。纯编译不得网络、spawn、访问 HOME、读取密钥。原生操作由 Harness C1/C4 在隔离配置根执行。

`permissions.authorizer@1` 为后端唯一决策服务端口：

```text
evaluate(principal, sessionRef, executionRef, nativeGeneration,
         toolIdentity, targetFacts, argumentDigest, ceilingRevision,
         policyRevision, nativeRequestId)
  -> Denied(code, evidenceRef) | AllowedOnce(boundGrant) | PendingApproval(approvalId)

decide(approvalId, expectedVersion, decision, scope, operationKey)
  -> Recorded | AlreadyRecorded | Invalid | Unknown
query/reconcile(approvalId, nativeRequestId) -> ApprovalState + nativeReceipt | Unknown
```

该服务不能仅暴露普通 wire 方法供桌面自行调用：必须被 Harness **真正的副作用前钩子**使用。ACP `session/request_permission` 请求须经现有通道 owner 关联，不新增第二 client；对无法由当前通路拦截的工具类别返回 unsupported，不以 `permissions` capability 标签替代门证。工具执行器在使用一次性 grant 前重验目标、policy/ceiling generation、过期和操作摘要；原生绕过路径要么封闭，要么该强制策略不可宣告受支持。管理员策略保存在可信服务侧，不能由 `settings` 普通表单直接覆写。

## C2 Sandbox 贡献

`sandbox.native-configuration@1` 是 `harness.configuration-adapters` 的业务 facet，逻辑 owner 为 Sandbox asset。输入仅含版本、平台、配置目标句柄与受权事实；输出 `assess/compile/verify`，意图为 Harness C3 的封闭 `SetField/ResetField/InvokeAction`，禁止任意 shell/路径写入。`requiredCoverage` 明列需覆盖 Bash/Read/Edit/MCP/网络等哪些类别；不能核验其中一类就返回 blocked/unknown，而不是“基本受保护”。

`sandbox.describe@1` 后端查询返回当前 pin 可用的选项、来源、平台与覆盖范围、是否被管理员锁定；UI 不能从 Harness 品牌名猜菜单。原生 sandbox facet 的 item 可注册到 Profile Editor 与 Settings；各作用域保存配置引用，实际生效仍是 Harness 应用收据。若原生配置与 Permissions 的原生权限投影触及同一字段，Harness C2 冲突门拒绝；两个业务所有者应预先分配字段，不能调一个优先级避开冲突。

## C3 与 Profile/Chat/Server

- 两域各自可选 `ProfileContributions.forScope(scope).addEditor` 和 `addSettingsSection`；卸载后 UI 区域消失、值保留，下一轮缺编译提供者时拒绝该 facet，不把未知片段透传到 Harness。
- Permissions 可向 Chat 的审批区贡献受限审批视图/动作。Chat 不 import 其内部服务或按按钮色推断授权；没有 UI 的 headless/失联路径必须遵循后端 fail-closed。Sandbox 不需要常驻 Chat 大按钮，若有选择器只显示该 Harness 实际支持的能力。
- 对外方法由业务插件向 Server 公开 method registry 注册；`apps/server` 不添 permissions/sandbox 条件分支。Pacthold 只消费中性资源/执行事实，审批数据与规则不进入它的核心模型。
- 必须保留旧 `approvals.decide` 路由与 `server_approvals` 数据标识的兼容计划（迁移/适配谁实现先在 T00 验证）；禁止两个独立 `decide` 权威同时接同一 native request。

## C4 生命周期与错误

stage 时验证 schema、命名/版本/字段 claim；commit 才可见。卸载时活跃审批、尚未核对的 native grant、仍使用该 adapter 的实例必须 busy/deferred，不能先卸再找不到拒绝/对账代码。请求中 provider generation 改变则重验；旧 UI 响应不能落到新服务域。

错误码至少分 `POLICY_CEILING_VIOLATION`, `POLICY_ADAPTER_MISSING`, `POLICY_SCOPE_UNVERIFIED`, `PERMISSION_UNKNOWN_TOOL`, `APPROVAL_STALE`, `APPROVAL_NOT_ACTIONABLE`, `APPROVAL_RESULT_UNKNOWN`, `SANDBOX_NATIVE_UNSUPPORTED`, `SANDBOX_COVERAGE_UNPROVEN`, `SANDBOX_PLATFORM_UNSUPPORTED`, `SANDBOX_CONFIG_CONFLICT`, `SANDBOX_EFFECT_UNKNOWN`, `PROVIDER_BUSY`。`unsupported` 与 `unknown` 不合并；所有拒绝应带源、目标与修复建议但不泄漏工具参数/凭据。错误须映射至既有 wire family，不修改核心错误分支。
