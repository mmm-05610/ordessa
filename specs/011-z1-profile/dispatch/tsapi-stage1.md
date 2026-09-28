# Z1 TS 轻量 API 包派单简报（单包：plugins/profile/api）

执行者：单包实施子代理。**只允许创建/修改 `plugins/profile/api/**`。**
不碰 `plugins/profile/src|tests|pyproject.toml`（另一代理在写），不碰任何其他目录。
不运行 git 命令（主代理负责）。

## 背景

Ordessa Profile v2 需要一个前端轻量 API 包（profile-api 检查点的 TS 部分）：
其他业务线（model-provider、skills 等）通过它向 Profile 贡献“预设字段编辑器”与
“Profile 设置区”，并消费 Profile 服务操作。语义来源（必读）：
- `docs/design/profile-v2/contracts.md` §1/§2/§3（facet descriptor、前端贡献、服务操作表）
- `docs/design/profile-v2/ux.md`（编辑器/设置页/Chat 选择器语义）
- `docs/design/profile-v2/data-model.md`（值状态四分、SessionRef、intent/receipt）
- 平台契约风格参照：`packages/desktop-platform/contracts/workbench/src/workbench.ts`、
  `packages/desktop-platform/contracts/agent/src/agent.ts`（Token/IDisposable/Availability 风格、
  注释里写清 absent ≠ supported 的习惯）

## 包约定

- 位置 `plugins/profile/api/`；`package.json` name=`@ordessa/plugin-profile-api`，
  private=true，`ordessa.id`=`ordessa.profile-api`（对齐 `@ordessa/contracts-agent-ui` 与
  `plugins/commands` 的写法）。
- 依赖只允许 `@ordessa/extension-api`（workspace 内，Token/ResourceScope/IDisposable）与
  react 类型（`react` 用 dependency 或 devDependency 都行，参照 workbench contract 的 import 方式——
  它只 `import type { ComponentType } from 'react'`）。**不得依赖 @ordessa/ui /
  ui-components / Chat / model-provider**（它们尚未发布或不在本线所有权内）。
- 必须 提供 scripts：`"typecheck"` 与 `"test"`（quickstart 要求）。typecheck 用本包
  tsconfig（`noEmit`，strict）；test 用 vitest（若根 lock 无法安装 vitest，见下“验证”）。
- 入口：`src/index.ts` 全量导出；另加 `src/entry.ts` 仿
  `packages/desktop-platform/contracts/agent-ui/src/entry.ts` 的空 plugin entry
  （id 用 `ordessa.profile-api`），交付形态为共享模块契约。

## 必须冻结的类型（语义按 contracts.md，命名可用 TS 惯用驼峰）

1. **值状态四分（PF04）**：`_unset` 哨兵（`ProfileUnset` 唯一实例/类型）、显式值
   （null/[]/false 合法）、`disabled`、`providerAbsent`。提供 `ItemValueState` 判别联合或
   等效表达，禁止把四者归一为 `undefined`。
2. **facet/item 描述**（对端与 Python `ordessa_profile.contracts` 对齐，字段名转 camelCase）：
   `FacetDescriptor{facetId, apiMajor, schemaVersion, label, description, category, order,
   itemDescriptors[]}`；`ItemDescriptor{itemId, valueSchema, optional, overrideSupported,
   sensitivity:'non-secret'|'opaque-reference', effect:'configuration'|'capability-selection'|'permission'|'instruction'}`；
   `Applicability='supported'|'unsupported'|'unknown'`。
3. **前端贡献注册面（contracts.md §2）**：
   ```ts
   ProfileContributions.forScope(scope: ResourceScope): {
     addEditor(c: ProfileEditorContribution): IDisposable
     addSettingsSection(c: ProfileSettingsContribution): IDisposable
   }
   ProfileEditorContribution{facetId, supportedSchemaRange, componentKey, category:
     'model'|'capabilities'|'behavior'|'instructions'|'advanced', order}
   FacetEditorProps{target:{serverRef, profileId, harnessId}, revision, draftGeneration,
     items, validation, applicability, readOnlyReason, onPatch(patch: ItemPatch[]): void}
   ProfileSettingsContribution{id, facetId, title, order, componentKey}
   ProfileSettingsProps{target:{serverRef}, settingsRevision, providerGeneration, values,
     validation, readOnlyReason, onPatch(patch: SettingsPatch, expectedRevision: number): void}
   ```
   `componentKey` 类型对齐平台 C7 的组件键表达——读
   `packages/desktop-platform/contracts/` 与 `plugins/workbench/src` 里已有的
   ComponentOutlet/ui binding 用法（若有），没有就定义本域 `ComponentKey<P>` 字符串键类型，
   并在注释中写明“发布对齐 C7 时只改类型别名，不改语义”。
   `ItemPatch`：`{facetId, itemId, op:'set'|'unset', value?}`（typed set/unset，
   未修改项不出 patch）；`SettingsPatch` 同构但带命名空间。
   重复 id 拒绝、scope 释放即卸载：这些行为语义写进接口 doc comment，
   并由 consumver 侧实现（本包只冻结契约+内存版参考实现）。
   提供 `createProfileContributions()` 内存参考实现（Map 存储、重复注册抛错、
   IDisposable 注销），供 glue 与测试用。
4. **服务操作客户端接口（contracts.md §3 表，方法名转 camelCase）**：
   `ProfileServiceClient`：listProfiles/getProfile/createProfile/cloneProfile/renameProfile/
   saveProfile/archiveProfile/restoreProfile/describeFacets/getMechanismPolicy/
   updateMechanismPolicy/resolvePreview/selectForSession/setSessionOverride/
   clearSessionOverride/inspectSessionConfig/reconcile。
   每个方法的入参/返回类型按表冻结（expectedVersion/revision、operationKey、
   bindingVersion、pending intent 不返回“已应用”等），并附 doc comment 引用语义来源文件。
   `ProfileServiceToken = new Token<ProfileServiceClient>('ordessa.profile.service.v1')`。
   附带错误码联合类型 `ProfileServiceErrorCode`（与 Python 侧稳定错误码对齐：
   PROFILE_VERSION_CONFLICT、POLICY_REVISION_CONFLICT、OVERRIDE_WRITES_FORBIDDEN、
   APPLICATION_PORT_ABSENT、OPERATION_KEY_REUSED、NAME_CONFLICT、SESSION_REF_AMBIGUOUS、
   LEGACY_RECEIPT_UNVERIFIED、FACET_UNKNOWN、FACET_GENERATION_STALE 等）。
   **不实现网络传输**：定义接口 + 一个 `DelegatingProfileServiceClient`（把方法映射到
   注入的 transport 函数），wire 绑定由后续阶段/宿主完成。
5. **SessionRef/evidence DTO**：`SessionRef{realm, harnessId, nativeSessionKey, sessionUid}`、
   `AppliedReceiptDto`（不含秘密值字段）、`ApplicationJournalState=
   'planned'|'applying'|'confirmed'|'rejected'|'unknown'`、`ValueSource=
   'profile'|'session-overlay'|'target-default'`。
6. **Chat glue 需要的只读类型**（PV-10 用，Z2 消费 chat-api 后才接线）：
   `ProfileSelection{harnessId, profileId, displayName}`、两级目录 DTO
   `ProfileCatalogGroup{harnessId, harnessTitle, profiles[]}`。不定义 Chat 侧注册表
   （那是 chat-api 的所有权），只定义 Profile 侧提供的数据形状。

## 行为测试（vitest 或 node:test 均可，以能在本树跑通为准）

- 内存参考实现：注册/重复拒绝/注销/forScope 隔离（不同 scope 不互见）。
- 契约类型编译期正反例：用 `@ts-expect-error` 写负例测试（未知字段、错误判别、
  Applicability 'unknown' 被禁止当 supported 的类型表达）。
- ItemPatch 只含修改项、unset 无 value 的运行时校验函数（导出 `assertItemPatch`）。

## 验证（在本树根执行；根 node_modules 尚未安装）

```sh
npm install --no-audit --no-fund          # 只在本树；会更新根 package-lock.json —— 允许，主代理处理
npm run typecheck --workspace @ordessa/plugin-profile-api
npm test --workspace @ordessa/plugin-profile-api
```
若 workspace 命令形式不可用，用 `npx tsc -p plugins/profile/api`、
`npx vitest run plugins/profile/api` 等效命令，把真实命令与退出码记录进证据。

## 证据

写 `specs/011-z1-profile/evidence-tsapi-stage1.md`：实际执行的命令、退出码、
导出符号清单、与 Python 契约的字段对照表（camelCase 映射）、已知未决点
（如 componentKey 待 C7 对齐）。不要夸大：未跑的命令不能写通过。

## 完成定义

- 包内 `npm run typecheck`、`npm test` 真实通过（退出码 0）。
- 上述 1–6 全部类型冻结并有测试；无 any 逃逸（strict 下显式 any 需在证据中说明理由）。
- 输出变更文件清单 + 证据文件路径 + 遗留缺口。
