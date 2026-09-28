# 目标契约：服务、贡献、调用分界

本页只冻结领域语义；必须在 T00 对当前平台真实公开 API 绑定，禁止仅靠同名 mock 端口宣称已生产接入。注册 owner 由宿主授予，不接受定义/贡献者自行声明所有者。

## C1 后端定义服务

```text
create / importPreview / approveImport / get / list / saveRevision
archive / restore / clone / approveAssignmentUpdate
resolvePreview(target, expectedRevisions) -> EffectiveSet | Refusal
inspectNative(target) -> NativeObservation[] | Unknown
```

所有 mutation 带 principal、serverScope、expectedRowVersion、operationKey；服务鉴权上下文给 principal，客户端不可自报。CAS 与幂等键 scope 包括 principal/target/payload digest；同键不同 payload 拒绝。读操作按公共、项目、Profile 专用归属过滤，不泄露他人存在性。Preview 不读取任意宿主路径、不 spawn、不调用模型、不写 native 目录。导入从明确选择的本地文件或固定 Git revision 做预览和批准，远端漂移拒绝；未经授权的客户端路径不进入服务端文件读 API。

解析结果含每个定义修订、来源、排除原因、版本/能力事实和冲突，供 Profile 与 Chat 使用同一个服务；不能让前端重写覆盖算法。未知 provider/旧 schema 的已存片段保留，不能编译入运行。

## C2 Profile 与 UI 贡献

- 后端本域按 [Profile v2 FacetDescriptor](../profile-v2/contracts.md) 注册 `assets.native-subagents` 配置 facet：候选定义引用、三态决策、固定修订与只读能力诊断；Profile 保存引用/选择，本域保存正文与来源。provider 卸载时 Profile 隐藏编辑项并保留数据，发送时未知片段 fail closed。
- 本域通过 Profile 公共 `.addEditor` 注册定义选择/版本/描述编辑组件；Settings 注册内容库、导入、全局/项目默认及本业务自己的设置区。所有 UI 仅通过平台 C7 `UiComponentKey` 与 outlet 安装，不将 React 实现直接 import 到 Profile/Chat。
- Chat 可用 [Chat Contributions](../profile-v2/contracts.md) 的公开扩展点提供受控列表/调用入口；没有已证可调用接口就仅显示详情，不向用户消息附加“请使用 X”作为伪调用。Chat 仍拥有输入、发送、草稿；本域没有第二 ACP 客户端。

前端响应携带 server/session/project/profile/revision/providerGeneration，晚到结果不能回填另一目标。provider 卸载摘其 UI，数据留存；运行中目标若仍依赖 adapter 的 reset/reconcile，宿主 busy 拒绝卸载而不是先卸再失联。没有 Profile/Chat，内容库服务和 Settings 仍独立。

## C3 Harness 配置贡献

每品牌按 [Harness v2 C2](../harness-v2/contracts.md) 注册 `harness.configuration-adapters/v1`，facet 为 `assets.native-subagents`，包含 adapterId、harnessId、目标版本范围、native/extension-backed 证据、claims、payload schema，以及纯函数 `assess/compile/verify`。只产出有类型 `IntentSet`；不直接改 HOME、cwd、进程、ACP 帧或凭据。Pi 额外需要经 Harness runtime 注册且明确 owner 的 executable extension；定义插件不能自带一个隐藏执行宿主。

目标字段必须由 Harness C1 `describe_targets/actions` 授权；同一原生字段、目录或文件与 Skill/Prompts/其他 adapter 重叠时配置计划类型化冲突，不能 last-wins。多定义共享同一原生目录由本 facet 一次性编译**完整目标集合**，不逐项拼补丁。未知前置字段若目标会静默忽略，则拒绝把它记作受保护的能力。

## C4 应用/提交/调用

选择变化只保存 desired choice；用户下一次显式输入由既有会话提交闸门冻结 Profile、分配、定义 revision 与目标 generation，先让 Harness `plan/apply/verify`，Confirmed 后才原消息发送一次。输出中不应用；失败/Unknown 不发消息、不清覆盖、不自动重试，仍可按 operationKey reconcile。恢复必须核验同一 native session identity；新 session 不等价。

真正“运行一个子代理”只可调用目标 Harness 经授权的**既有受限调用动作**或通用派工设施。该动作另核当前 caller、目标定义、工具/权限/项目、额度及父会话状态；不能靠业务定义审批自己，也不能从 UI 直接发裸协议帧。只有原生调用事件能记录 used；定义已投放不是一次运行。

## C5 错误与卸载

至少区分：`DEFINITION_INVALID`、`REVISION_STALE`、`ASSIGNMENT_CONFLICT`、`REFERENCE_UNRESOLVED`、`PERMISSION_EXCEEDS_CEILING`、`NATIVE_VERSION_UNKNOWN`、`NATIVE_ENTRY_UNAVAILABLE`、`NATIVE_NAME_CONFLICT`、`NATIVE_DISCOVERY_UNCONTROLLED`、`ADAPTER_MISSING`、`TARGET_CONFLICT`、`LOAD_UNVERIFIED`、`OPERATION_UNKNOWN`、`PROVIDER_BUSY`。拒绝在任何 native 副作用前给出 item-level 原因。未知结果必须可查询，不回退为静默成功。

staging 先校验再发布；注册冲突/激活失败按宿主生命周期逆序清理，仅当前贡献回滚，主错误不被清理错误覆盖。卸载让尚未应用的计划 stale；活跃目标依赖 reset/reconcile 时 busy。移除定义分配后 Harness 只删除本插件持有的 generation 内容，绝不清理用户已有原生项。
