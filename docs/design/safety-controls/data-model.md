# Data model：分层意图、运行证明和失联事实

所有 ID 都由权威服务生成/绑定真实鉴权主体。以下是目标模型，不代表当前 DB schema。现有 `server_approvals` 标识与事件名需保持兼容；如用户数据迁移会改结构，先设计可回退迁移并征得批准。

## 分离的实体

| 实体/所有者 | 关键字段 | 生命周期 |
| --- | --- | --- |
| `PolicyCeiling`（Permissions，管理员/宿主） | policyId、scope、revision、signed/source provenance、deny/requireApproval/maximumExposure、effectiveFrom | 只能经管理权修改；普通 Profile 不可写/撤销；缺可信来源不推断为“无上限” |
| `PermissionIntent`（Permissions 配置、Profile 可引用） | intentId、revision、harnessId、tools/targets 的 typed rules、期望原生模式、scope | 可单独使用；Profile 只存 ID/revision 或 facet 片段，不能变成上限 |
| `EffectivePolicySnapshot`（Permissions） | target server+session+execution+native generation、principal、ceiling revision、intent revision、hash、validity | 每次实际工具决策重验；输出中旧快照仅代表当时事实 |
| `AuthorizationDecision`（Permissions） | nativeRequestId、operationDigest、target/subject、tool、decision allow/ask/deny、reason、policy hash、expiry | 只针对一次已绑定操作；不能由 UI 构造 |
| `ApprovalFact`（Permissions） | 旧 approvalId、sessionId、executionId、version、state、decision、scope、requestId、native correlation、outcome receipt | 现有 `server_approvals` 表渐进迁移；保留 open/settled/invalid 与 CAS；终止即不可再行动 |
| `NativeSandboxIntent`（Sandbox asset） | sandboxId、revision、harnessId、品牌 schema、文件/网络/命令覆盖、requiredCoverage、platform gate | Profile 可引用；不存通用 SandboxV1、密钥和绝对路径执行实例 |
| `SandboxEvidence`（Sandbox asset/Harness） | target+runtime generation、原生版本、配置摘要、内核/平台事实、覆盖工具集、verified/unknown、reason | 探测与实际实例绑定；版本/配置/平台变动后失效 |

## 规则合成

1. 先鉴别请求主体、项目/会话/执行、真实工具和参数摘要；任何字段不可靠 = deny/unknown，不进入“默认继承”。
2. `PolicyCeiling` 是不可提升上限：硬 deny 恒 deny；需审批恒不小于 ask；原生管理员禁止 bypass/限制隔离的规则恒保持。多个权威上限取交集，不能 last-wins 放宽。
3. 在上限内选择 Profile/会话意图。无意图不等于 allow：沿既有原生路径，且若有强制上限则必须证明原生路径执行前被约束；证明不了就拒绝该强制配置目标。
4. 业务意图中相互冲突的等优先级规则不靠顺序暗自获胜。`deny` 优先；`ask` 优于普通 `allow`；例外规则必须显式带可验证管理授权，不接受通用 wildcard 覆盖安全上限。
5. 当规则要求 ask 时，审批 token 仅匹配同一 operationDigest/target/policy revision/native generation；用户允许一次不是扩大 Profile 或管理员策略。审批结果未确认 native owner 已收到之前不称“工具已获执行”。

旧 `permissions.py` 的列表最后匹配胜出可能允许低优先级规则反转 deny。迁移器必须把旧规则限定为 **同一 Profile 内用户意图**，先对比运行语义；不能无损证明时保存原值、标 `needsReview`、禁止冒称新强制策略生效，不删除数据。管理员策略从独立可信来源导入，不从旧 Profile 推导。

## Sandbox 与权限合成

沙盒 intent 描述“原生 OS/进程隔离想达到什么”，不是审批规则。`allow` 仍受已证 sandbox 限制；管理员强制原生 sandbox 时，Profile/用户的 disabled/例外不能关掉它。`ask` 批准可能只允许工具调用，不能越过沙盒；原生 Harness 可有独立 escalation，必须另走明确的管理授权与审计。原生沙盒只覆盖 Bash 时，对 Edit/MCP 等其他工具的风险由 Permissions/原生权限控制，不能填写 `coverage=all`。

## 多会话/变更

记录绑定 `serverInstanceId + sessionId + channel/nativeSessionId + runtimeGeneration`，不能仅凭 harnessId 或原生会话名隔离。一个进程若承载多个会话而原生 sandbox/审批策略为进程级，plan 必须给影响集合；若无法只改变目标且不同意影响其他会话，拒绝。提交边界冻结配置与权限修订；执行前若管理员修订收紧，重判并拒绝/升为 ask；不可因缓存旧快照继续 allow。断连、超时、回执未知时保持 pending/unknown，查询既有 operation；不得重试副作用或本来待授权工具。
