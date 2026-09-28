# Contracts：MCP 领域 API 与宿主边界

这些是目标语义契约，**不是 main 已有的可导入符号**。T00 先对平台/Profile/Harness/Chat/Permission 实际公开 API 作绑定表；名称不吻合用薄适配，不另建 registry、ServiceLocator 或 host。

## 1. 后端服务与贡献

`plugins/assets/mcp/` 的服务通过现有 Server 插件公开贡献机制注册 typed method descriptor，提供：

| 操作 | 输入与输出 | 无副作用/拒绝点 |
| --- | --- | --- |
| list/get/saveRevision/archive | scope、principal、definitionId、expectedVersion、operationKey → 版本摘要 | save 不探测/启动；字段与 secretRef 校验 |
| probe | revision、受控 probe policy → probe facts/typed refusal | 明确 probe 权限；无凭据 probe 不能宣称凭据可用；临时进程必关 |
| assign/unassign | 项目/Profile/用户 scope、决策、批准 revision、toolSelection、CAS → assignment | 目标权限、修订和名字冲突先验 |
| resolvePreview | target + scope revisions → effective snapshot preview | 只读，不触发连接或模型 |
| inspectConnection/listTools | sessionRef + generation → lease/catalog facts | 不能把定义条目伪装为活连接 |
| planForSubmission/apply/reconcile | 受授权 target、唯一 submission permit、expectedRevision → confirmed/refused/unknown | 与 Harness C4/C5 同一提交闸门；没有 permit 不应重配置或启动 |

每项 shape/auth/availability 随原子描述符注册；业务插件不修改 `apps/server/wire/handlers.py`。所有跨插件依赖用公开端口显式声明，provider 缺席类型化拒绝。数据 owner 属 MCP 业务插件，不属于 Profile/Server。

## 2. Profile、Settings、Chat

- `McpFacetDescriptor` 注册 Profile facet `mcp.servers`：值仅为定义版本引用、启用/禁用、toolSelection；validate 用 MCP 只读服务核对修订/项目/能力。compile 只产 C2 的业务片段，不连接服务器。移除提供者隐藏该配置面，原值保留但 apply fail-closed。
- Profile Settings section 归 MCP：定义库、凭据引用选择、默认 probe 策略、状态与导入；保存用 MCP 自身服务/CAS，不将设置复制到 ProfileRevision。
- Chat contribution 在输入区提供当前有效服务器和工具状态的按需小面板/选择器；能区分 pending、connected、catalog changed、refused。Chat 只消费公开贡献与状态，不 import MCP 内部模块，不接触秘密/进程。
- UI provider 缺席不影响已安装的业务服务；后端 provider 缺席时设置区域不显示，已存 Profile 字段不可执行。渲染错误须局部可见，不能当成未安装静默吞掉。

## 3. Harness C2 适配与唯一所有者

每品牌 adapter 归 MCP 域，注册 `harness.configuration-adapters`，facet `mcp.servers`；`assess` 返回 supported/unsupported/unknown；`compile` 对**完整有效集合**产唯一目标快照，`verify` 解读 Harness 给的原生观察结果。纯函数不得读取 HOME、spawn、网络或 secret。Harness C1/runtime 拥有 native target、配置 generation、launch/restart/resume 和 native 进程关闭。若目标原生文件已有其他 facet 字段，Harness C3 合并冲突、不能 MCP adapter 覆写整个文件。

Ordessa-managed lane 不经 native 文件。MCP 插件持有 client 与租约，向目标 Harness 只提供**受限、可审计的工具桥接入口**；该入口不能绕过后端 caller identity 与 Permission 决策。Pi 扩展只是受管入口的一部分，不能直接另起同一 MCP server。没有受控桥接能力时不能把 Pi 标为 ready。

## 4. 权限接口与双重校验

MCP 插件只负责候选工具、catalog/schema、来源、工具子集选择；最终 `authorizeToolCall(principal, sessionRef, leaseId, toolName, argsDigest, policyRevision)` 由 Permission 域服务裁定。拒绝发生在任何 MCP `tools/call`、敏感代理转发或本地 subprocess 副作用前。审核事件引用决策 ID 而非秘密/完整参数。**MCP 工具的 annotations 由服务端自报，未获信任时不构成自动批准依据**（[规范](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)）。

在独立 Permission 插件尚未合入时，只能沿当前 Harness 原生权限机制运行并显示其实际策略；不允许宣传 Ordessa 的跨 Harness 统一授权已实现。若首版验收要求统一权限，则该前置条件阻塞所有实际工具调用；可独立完成定义/目录管理，但不能放行未授权测试调用。native lane 若无法拦截每次调用，须证明等价的原生逐工具/规则强制和 policy revision；否则 `permission-enforcement-unproven` 拒绝运行，而不是用 UI 隐藏代替。

**无人值守不等于默认批准。** 仅当事前的授权精确绑定 principal、服务器版本、工具名/参数约束、项目、会话/时间窗口、允许的副作用等级与审计策略，且调用时重验未过期，才可无需即时 UI 继续。未覆盖、外部写入或副作用不明的工具调用拒绝或停在审批待办；审批不可用时 fail closed。即便 MCP 规范描述工具交互可要求人类确认，Ordessa 也不能把无人操作解释为隐式同意。

## 5. 失败与生命周期

Plan 绑定 principal、session/generation、definition+assignment+catalog digest、credential revision、lane/owner、许可策略 revision、expiry；应用前重验。断开不代表请求取消或进程已死；先 reconcile。卸载在活租约中拒绝或 drain，停机调用其 lane owner 一次且可重试；cleanup 抛错不遮蔽主错误，并留下 unknown/cleanup_errors 供追踪。所有事件写入现有事件/审计接口，不另建第二条宿主生命周期。
