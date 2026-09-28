# Data model：内容、分配、运行快照

```text
AgentDefinition: serverScope, definitionId, slug, displayName, description,
                 originScope, originOwner, latestRevision, archived, rowVersion
DefinitionRevision: definitionId, revision, contentDigest, roleBody,
                    declaredModelRef?, toolRefs[], mcpRefs[], skillRefs[],
                    requestedPermission?, isolation?, limits?, source,
                    retainedNativeFields, approvalRecord
DefinitionAssignment: serverScope, principal, scopeKind, scopeId,
                      harnessId | any, definitionId,
                      decision: enable | disable, revision?, rowVersion
ResolvedDefinition: definitionId, revision, nativeName, selectedBy,
                    effectiveReferences, capabilityEvidence, diagnostics
DefinitionSnapshot: principal, projectId, profileId?, sessionId,
                    runtimeGeneration, profileRevision, assignmentRevisions,
                    definitionDigests[], adapterGeneration, snapshotDigest
NativeDefinitionObservation: nativeName, scope, sourceCategory,
                             targetGeneration, evidence, suppressible?
```

`definitionId` 不从名称派生。正文与声明存不可变修订，元数据用 CAS；源文件/远端位置只是出处，运行内容必须为本地已批准摘要。未引用版本保留至少至运行租约结束；不自动 GC 当前或可恢复会话需要的修订。修订新增不移动绑定，升级每个分配单独批准。归档隐藏新选择但不毁已有快照。删除仅是未来单独的数据保留政策，不由此包暗中实现。

资源引用是带属主/版本的 `ModelRef`、`ToolRef`、`McpRef`、`SkillRef`，不是可执行路径或 credentials。尚不存在相应服务时，数据可保存但运行期 `REFERENCE_UNRESOLVED`。引用解析要校验用户/服务/项目/目标 Harness 权限；配置快照只存引用或脱敏事实。工具名称在目标原生表里重新匹配，不把用户填的字符串信作权限。

## 范围解释

对每个 definitionId，低至高：当前用户全局通用 → 用户全局 Harness → 当前授权项目通用 → 项目 Harness → 同 Harness Profile → 本会话暂时覆盖。未出现即 inherit；`enable(revision)` 指向批准固定版；`disable` 排除受管项。后层可改变前层**普通选择**，但管理员/服务强制限制和实际运行权限始终另验。Profile 专用定义仅可由该 Profile 及其合法同 Harness 会话使用；项目专用不越项目。无 Profile 时公共/项目默认仍可独立工作。

同一原生名称不同 ID 或原生发现项撞名，一律按目标品牌名称规则拒绝，不能按版本或优先级随机选。已启用定义的 `description` 可能进入 Harness 的代理目录/模型上下文；应用前给总长度/数量限制，正文仅在实际调用时装载的品牌须单独验证，不默认宣传节省上下文。

## 状态和迁移

`stored`（已保存）、`selected`（解析有效）、`projected`（受管原生目标已生成）、`loaded`（目标原生加载器确认）、`invokable`（调用入口确认）、`used`（独立调用事件）是不同事实；不能由文件摘要或模型叙述直接升级。没有观测机制记 `unknown`，不能报 `false` 或 `true`。

旧 `ordessa_server_compat.profiles.subagents` 的 grant edges、roster、tool definitions、limits 是派工机制，不迁作 DefinitionRevision。T01 需逐表/字段盘点旧数据；只有确为纯定义内容且来源/权限/ID 可证明时才迁；授权边维持旧归属或另行治理，不默认为新定义的访问许可。迁移 dry-run 保留字节/ID 清单和回滚，必要的真实用户数据变更另经授权。
