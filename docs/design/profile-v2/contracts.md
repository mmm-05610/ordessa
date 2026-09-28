# Contracts：配置面、编辑器、会话接入

此处定义 v2 语义边界，尚不是发布的 Python/TypeScript API；落地须复用平台实际 ResourceScope/UiComponentKey、Server contribution carrier、会话身份与运行期接口，禁止创造第二套相同 Token 或 ServiceLocator。

## 1. 配置面后端贡献

每个提供者声明：

```text
FacetDescriptor
  facetId / apiMajor / schemaVersion
  label / description / category / order
  itemDescriptors[]
    itemId / valueSchema / optional / overrideSupported
    sensitivity: non-secret | opaque-reference
    effect: configuration | capability-selection | permission | instruction
  applicability(harness capability facts) → supported | unsupported | unknown
  validate(items, referenceFacts) → violations[]
  migrate(oldSchemaVersion, storedItems) → migrated | unsupported
  compile(resolvedItems, targetFacts) → typed config intents | violations[]
```

owner 由宿主 scope 注入，不信 provider 自报 owner；重复 facetId 拒绝、generation 防晚回调。后端注册是否在用通过既有 lifecycle 规则处理，不重建加载器。

- applicability 只消费真实 Harness 能力，不从品牌名猜所有版本一致。UI 可据此隐藏不适用项，unknown 必须如实阻止应用。
- validate/migrate/compile 不 spawn、不改配置文件、不写全局默认、不发送模型请求。资源引用解析走声明依赖的公开服务，有授权且可取消的只读查询；不能把跨插件服务实例塞进通用 context。
- compile 产物仅声明本配置面拥有的 native configuration intent，包括 set/reset 及来源，不直接执行；两个提供者写同一 native 目标键时类型化冲突，不 last-wins。
- 只要新增配置面和对应已有 Harness 配置能力，就不应修改 Profile；如果新原生能力确实不存在，需要更新该 Harness adapter，不污染 Profile/Server/Pacthold。
- 普通权限字段允许作为声明式 facet 保存；**不能保留旧“没有 permission 字段所以安全”的假保证**。真正权限校验在应用接缝，不能经任意 schema 绕过。

首版不要求新增独立 permission 插件：Harness 自有审批/工具暴露配置可由 Harness 域的 Profile glue 提供；只有出现跨 Harness 的独立策略管理需求时再设计业务插件，不把可选插件当本批前置依赖。

## 2. 前端贡献

Profile 暴露轻量 API key，提供两个独立的注册面：`ProfileContributions.forScope(scope).addEditor(...)`（单个预设的字段）与 `.addSettingsSection(...)`（Profile 自身设置页）。

```text
ProfileEditorContribution
  facetId / supportedSchemaRange
  componentKey<FacetEditorProps>
  category: model | capabilities | behavior | instructions | advanced
  order

FacetEditorProps
  target: serverRef + profileId + harnessId
  revision / draftGeneration
  items + validation + applicability + readOnlyReason
  onPatch(typed item set/unset operations)

ProfileSettingsContribution
  id / facetId / title / order
  componentKey<ProfileSettingsProps>

ProfileSettingsProps
  target: serverRef（不是 profileId）
  settingsRevision / providerGeneration
  values + validation + readOnlyReason
  onPatch(typed settings patch, expectedRevision)
```

设置贡献绑定到本 scope 所拥有的真实配置提供者；重复 ID 拒绝，scope 释放即卸载区域。提供者声明设置 schema，并通过自身公开服务读取、验证和 CAS 保存其命名空间内的设置；Profile 只绑定受限 props/actions，不提供全库写入或任意服务查找。Profile 自己仍拥有启用/覆盖规则等机制策略，贡献设置不能绕过这些规则和运行授权。不存在设置贡献时不留空卡。

这类设置不写入某个 ProfileRevision 或 SessionOverlay，不复制供应商密钥/资源仓库。配置面禁用不等于提供者卸载，已加载提供者仍可呈现其机制设置；卸载隐藏，数据保留。服务域/提供者代次/修订变化后晚到响应或保存必须拒绝，切换服务不能串写。若设置参与配置编译，其修订进入应用快照校验。

组件提供者通过 C7 注册，Profile 用 Outlet 装载；Profile 不 import 字段实现。通用 schema editor 可覆盖基本 text/boolean/enum/list/ref，复杂模型/Skill 选择器由提供者自供。schema decoder 必须后端再次执行，前端校验不是授权。

编辑器只更新页面 draft，不直接保存整个 Profile、不取得会话/凭据/registry。可用自己的服务查询候选；目标/revision/provider generation 变化后旧查询/动作不得落到新项。未修改项不出 patch，隐藏项保留。

缺后端 provider：隐藏编辑项，已存数据留存。后端 provider 在但 UI provider 缺：仅当声明了通用 schema editor 才使用安全通用表单，否则隐藏，不冒充能编辑；实际 apply 验证独立于 UI。渲染抛错不同于未安装，错误隔离本区并可见，不能静默吞掉。

## 3. 服务操作（名字为语义名，不是现有 wire 事实）

| 操作 | 关键输入 / 输出 |
| --- | --- |
| list/get/create/clone/rename/save/archive/restore | 服务域、profileId、expectedVersion/revision、operationKey；不可变 harnessId |
| describeFacets | Harness capability facts + policy revision → 脱敏可编辑配置目录 |
| get/updateMechanismPolicy | expectedRevision、授权调用者、patch、impact preview；不返回业务秘密 |
| resolvePreview | profileId + revision/当前快照 + 可选目标覆盖 → 各项来源/冲突/待运行验证；零副作用 |
| selectForSession | canonical target、目标 profileId、bindingVersion、operationKey → pending intent，不返回“已经应用” |
| set/clearSessionOverride | target、facet/item、expectedOverlayRevision、operationKey；清除可在禁止新增规则下使用 |
| inspectSessionConfig | desired/lastConfirmed/applied generation、来源、pending/recovery，必须分开 |
| reconcile | 指定 application operation → read-only evidence 或 needsRecovery；不得重放消息 |

这些方法由 Profile 后端插件向 Server 既有 registry 注册（typed shape/auth/availability），不修改 wire/handlers 或 bootstrap 业务分支。所有 mutation CAS 与幂等键绑定调用者/域/目标/request hash；同 key 不同 payload 必须拒绝，不能复用旧成功。

上述 inspect 状态用于正确性、恢复和按需诊断，不要求 Chat 展示状态标签。selectForSession 成功后选择器显示所选名称；下一次用户提交输入才触发应用，不能把选择动作实现为立即中断当前运行。

## 4. 可选接入而非循环依赖

```text
配置业务核心（model-provider / Skill / MCP / ...）
  ├── 自己的独立服务与设置
  └── 可选 Profile glue → Profile 轻量契约

Profile backend → facet descriptors + Harness 配置端口（公开 API）
Profile frontend → Profile service + Workbench + ui/ui-components
Profile Chat glue → Profile service + ChatContributions
Chat → ChatContributions registry（不反向 import Profile）
```

无 Profile 时能力插件照常独立使用；无 Chat 时 Profile 管理正常。若 optional service 生命周期会卸载整个业务插件，拆同业务域下的小 glue entry，而不是给核心插件加 required Profile/Chat。Profile 未启用时会话执行仍按既有原生配置工作，不造必需空 Profile。

## 5. 宿主与内核

Pacthold 不存 Profile 字段/模式/品牌，Server 不解释 facet。既有治理内核管执行/资源依赖/租约/收尾，Profile 的只读解析快照可由本插件提供为 execution 资源，具体入口用已审 C1 类型；不要为了每轮解析新建 execution。配置 apply 是 Harness 会话接缝，详见 application.md。

现存插件依赖旧 pacthold.extensions 的空注册须适配真正的公开宿主接入；不自动将旧 docs 里的 apps/server/core_wire 修改指令带入新架构。
