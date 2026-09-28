# Z1 TS 轻量 API 包证据（evidence-tsapi-stage1）

执行方式：单包实施子代理两次派发均因平台配额（exceed quota limit）失败，
按"普通阻塞自行解决"由主代理直接实施（偏差登记 report.md）。

## 包

`plugins/profile/api`（`@ordessa/plugin-profile-api`，`ordessa.id=ordessa.profile-api`）。
依赖：`@ordessa/extension-api`（workspace，Token）、`react`（仅 type import）、
`@lumino/disposable`（DisposableDelegate，平台既有锁定版本 2.1.6）。
**不依赖** `@ordessa/ui`/`ui-components`/Chat/model-provider（foundation/chat-api
未发布或不在本线所有权）。

## 实际执行命令与退出码（2026-09-28）

| 命令 | 结果 |
| --- | --- |
| `npm ci --no-audit --no-fund`（根，冻结锁） | 退出码 0 |
| `tsc -p plugins/profile/api/tsconfig.json`（strict，noEmit） | 退出码 0，0 错误 |
| `vitest run --maxWorkers=1`（在 plugins/profile/api 下） | **9 passed**（退出码 0） |
| 根 `package-lock.json` | **无 diff**（新增 workspace 包未写锁；所需增量登记 integration-request.md，最终根锁由 C0 生成） |

## 导出符号清单（src/index.ts 全量再导出）

- contract.ts：`UNSET`/`Unset`、`DisabledValue`、`ItemValue`、`valueState`/`ValueStateKind`、
  `Applicability`、`FacetCategory`、`ItemSensitivity`、`ItemEffect`、`ItemValueSchema`、
  `ItemDescriptor`、`FacetDescriptor`、`FacetCatalogEntry`、`Violation`、`ItemPatch`、
  `SettingsPatch`、`assertItemPatch`、`ValueSource`、`ResolvedItem`、`SessionRef`、
  `JournalState`、`AppliedReceiptDto`、`JournalEntryDto`、`SessionEvidence`、
  `MechanismPolicyDto`、`PolicyImpactPreview`、`MechanismPolicyPatch`、
  `ProfileTargetRef`、`FacetEditorProps`、`ComponentKey<P>`、`EditorCategory`、
  `ProfileEditorContribution`、`ProfileSettingsTargetRef`、`ProfileSettingsProps`、
  `ProfileSettingsContribution`、`ProfileContributions`/`ForScope`、
  `ProfileSummary`、`ProfileCatalogGroup`、`ProfileSelection`
- service.ts：`ProfileServiceErrorCode`（26 个稳定码）、`ProfileServiceError`、
  `ProfileServiceClient`（22 个操作）、`ProfileTransport`、`DelegatingProfileServiceClient`
- contributions.ts：`InMemoryProfileContributions`、`DuplicateContributionError`
- token.ts：`ProfileServiceToken`（'ordessa.profile.service.v1'）
- entry.ts：空 plugin entry（共享模块交付形态，无自动启用）

## 与 Python 契约的字段对照（snake_case → camelCase）

contracts.py ↔ contract.ts 一一对应：facet_id→facetId、schema_version→schemaVersion、
item_descriptors→itemDescriptors、override_supported→overrideSupported、
value_schema→valueSchema、session_uid→sessionUid、native_session_key→nativeSessionKey、
runtime_generation→runtimeGeneration、config_digest→configDigest、
policy_revision→policyRevision、evidence_kind→evidenceKind、allow_null→allowNull。
错误码集合与 Python 侧一致（PROFILE_VERSION_CONFLICT、…、LEGACY_RECEIPT_UNVERIFIED）。
UNSET 语义：TS 用 `Symbol`（运行时单例），Python 用 `_UnsetType` 单例；两侧都保证
unset ≠ null ≠ [] ≠ disabled。

## 行为测试（9 项）

四值状态判别、UNSET 非 undefined/null；patch set 必带值/unset 禁带值/未知 op 拒绝；
注册表重复拒绝、dispose 卸载、scope 隔离、排序；DelegatingClient 路由 +
`selectForSession` 恒返回 pending（不假报 applied）+ `APPLICATION_PORT_ABSENT` 传播；
编译期负例（@ts-expect-error：undefined 冒充 UNSET、前端禁用 'reset' op）。

## 已知未决点（诚实登记）

1. `ComponentKey<P>` 现为 branded string 别名：C7 组件注册表随 foundation 发布后
   对齐真实类型——语义不变，只改类型别名（contracts.md §2 预留）。
2. `DelegatingProfileServiceClient` 不含网络实现；wire 绑定（HTTP 路由、auth、
   realm 绑定）由宿主/C0 集成完成（integration-request.md）。
3. 本包未在真实浏览器装载验证（属 frontend 阶段 PV-08/09/10）。
