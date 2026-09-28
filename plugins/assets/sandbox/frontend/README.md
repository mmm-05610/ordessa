# `plugins/assets/sandbox/frontend` — Sandbox Settings 区（T06 / FR-05·06·08·09）

Sandbox 域通过平台**真实**的 Settings 贡献接缝注册自己那一块
"Harness 原生隔离" 区域，只渲染后端 `sandbox.describe@1` 说出来的事实。
本包不 import Permissions 域的任何东西，也不 import host 内部；只依赖 Workbench 一个服务。

## 注册用的真实接缝

* 契约：`packages/workbench/api/workbench.ts:41` —
  `WorkbenchComposition.forScope(scope).addSettingsSection(section)`
  （由 `packages/desktop-platform/contracts/foundation/src/contract.ts` 再导出，
  消费者按 `@extensions/ordessa.contracts/contract.js` 导入；
  `SandboxSettingsHost` 用 `ReturnType<WorkbenchComposition['forScope']>['addSettingsSection']`
  取型，因此不可能经第二个"宿主"注册）。
* 实现：`packages/workbench/src/model.ts:124` —
  `addSettingsSection: section => sections.add(scope, section)`，作用域持有、退出即回收。
* 页面归属：Settings 页由 Workbench 拥有（`model.ts:9` 的 `SETTINGS_OVERLAY_ID`、
  `shell.tsx:114` 渲染 `<h2>{section.title}</h2><Content/>`）。本包只提供 section 内容，
  不复制对话容器、不自建浮层；控件全部来自 `@ordessa/ui`（C8 基础件）。
* 入口：`src/entry.ts` 的插件 `requires: [WorkbenchToken]`，仅此一项。

`tests/settings-region.test.ts` 与 `tests/settings-view.test.tsx` 把 section 注册进
**真实的** `createWorkbench(...).composition`，并断言真实 registry 快照里出现/消失的
`sectionId`，所以"注册形状"不是照抄文档猜出来的。

## 消费的后端

`plugins/assets/sandbox/backend` 唯一的只读方法 `sandbox.describe`
（required `{harnessId}`，optional `{nativeVersion,osName,osVersion,platformVersion}`，
见 `plugin.py:34-36`），返回 `composition.py:FacetDescription.to_wire`。
`src/contract.ts` 是它的 TypeScript 镜像；词汇来自
`ordessa_sandbox_api/{describe,matrix,platform,errors}.py`，本包不自造选项名。

一个刻意的差异记录：describe 单元格的状态词汇是 `matrix.py:CellStatus`
（`supported|unsupported|unknown`），`verified` 属于 `verifier.py:VerdictKind`
（校验裁决）而不是描述结果。TS 镜像照抄两侧各自的词汇，没有把 "verified"
塞进 describe 选项、也没有合并两个枚举。

## 六条行为规则与各自的断言

| 规则 | 断言位置 |
| --- | --- |
| 只有 describe 成功才有区域；无提供者 ⇒ 区域不存在（不是坏占位） | `settings-region.test.ts` "no sandbox provider installed => the Settings section is never registered"、"an uninstalled facet (backend visible=false) leaves no broken placeholder"（断言真实 registry 为空） |
| 服务在场但出错 ⇒ 局部错误文案，绝不谎称未安装 | 同上 "a present-but-failing provider registers a local error state, not an absence"；文案规则在 `settings-view.test.tsx` "an unproven provider error reads as unavailable, never as uninstalled"（`role=alert` 含 `不可用` 与稳定码，且 `/未安装\|not installed\|uninstalled/` 不得出现） |
| 选项只来自 describe；无证据项按 unsupported/unknown 呈现且不可选；未知 pin 不猜菜单 | `contract.test.ts` "offers only supported options"、"an unknown-pin describe yields an empty menu: no default list is ever invented"；`settings-region.test.ts` "describe for an unknown pin contributes no menu at all"、"an unsupported option cannot be selected"、"an unproven (unknown) option refuses with the unknown code, never merged with unsupported"、"an option absent from describe is refused instead of being invented"；`settings-view.test.tsx` "an unknown pin shows no invented menu: zero options"、"unsupported and unknown options are offered as read-only with their evidence status" |
| `lockedByAdministrator` 只读带原因，任何放宽被拒绝（不静默降级） | `settings-region.test.ts` "an administrator-locked option is read-only and widening it is refused with a stable code"（`SANDBOX_CONFIG_CONFLICT`，且草稿**未被写入**、未被降级）；`settings-view.test.tsx` "a locked option is aria-disabled, still focusable, and announces the organisational reason"（`aria-describedby` 指向含"组织/宿主限制"的节点；用 `aria-disabled` 而非 `disabled`，被禁项仍在焦点序里） |
| 覆盖范围按实测呈现；绝不把某品牌说成"完全隔离"；无跨品牌同义标签 | `settings-view.test.tsx` "Bash-only coverage is shown as measured scope and never claims all tools are isolated"（禁词 `/全部工具\|所有工具\|完全隔离\|fully isolated/`）、"never labels one brand with another brand vocabulary or a generic bypass word"（渲染 claude 时不得出现 `sandbox_mode=`，也不得出现 `YOLO\|bypass\|完全访问\|自动模式`）、"an option with no coverage evidence is stated as unproven rather than silent" |
| 卸载后配置项隐藏、值保留；重新显示以后端新事实为准 | `settings-lifecycle.test.ts` 三条：hide 后真实 registry 空而草稿仍在；re-show **再次调用** transport（`calls` 计数 1→2→3）并采用新答案；`visible:false` 的卸载答案隐藏区域但保留已存值。`settings-region.test.ts` "a late click against a superseded describe generation does not land"（FR-08 晚到点击 → `PROVIDER_BUSY`，不写入） |

跨语言一致性：`tests/cross-language-codes.test.ts` 读
`../api/src/ordessa_sandbox_api/errors.py` 的 `SandboxErrorCode` 成员，断言本包
六个稳定码与之**双向**完全相等（`SANDBOX_INTENT_INVALID` 按 `errors.py` 自己的注释
留在稳定集之外，并被单独断言存在于 Python 侧）；同一文件读
`../../backend/src/ordessa_sandbox_backend/plugin.py` 的 `_DESCRIBE_REQUIRED` /
`_DESCRIBE_OPTIONAL`，断言 TS 参数名与 wire 完全一致。

反"假绿"检查：这些守卫做过变异审计（见
`specs/011-q5-safety/evidence/t06-green-sandbox-settings.txt`）——去掉放宽拒绝、
让 re-show 走缓存、菜单不再过滤 supported、让区域恒可见、把覆盖文案改成
"全部工具/完全隔离"，各自精确地把对应断言变红，然后回退。

独立性门：`tests/dependency-boundary.test.ts` 扫 `src/**` 的全部 import，
禁 `*permission*` / `ordessa_permissions` / host 内部 / `workbench/src`，
白名单只有 `react`、`react-dom`、`@ordessa/extension-api`、
`@extensions/ordessa.contracts/contract.js`、`@ordessa/ui`。
也就是说本包**可以在没有 Permissions 的安装里工作**。

## 已证明 / 尚未证明

已证明（L1，本包 `npx vitest run` 34 例退出 0、`npx tsc -p tsconfig.json --noEmit` 退出 0）：
上面六条规则的**正例 + 反例**，以及对真实 Workbench 贡献点的实际注册/回收形状。

尚未证明（不要当成已完成）：

1. **Profile 侧 Facet 粘合**（contracts.md §C3 的
   `ProfileContributions.forScope(scope).addEditor`）——**blocked**，不是本包漏做：
   本线的 `profile-api` 检查点已被回退，`plugins/profile/**` 与
   `FacetDescriptor`/`addEditor` 在这棵树里不存在
   （登记于 `specs/011-q5-safety/api-requests.md` G4）。所以本包只交付 Settings 区，
   不交付 Profile Editor facet，也不为了看起来完整而造第二套宿主或占位 facet。
2. **真实传输接线**：`SandboxDescribeTransport` 是注入的，本包不发任何请求。
   把 `sandbox.describe` 经产品装配的 Server 通道接上来的那一段尚未接线；
   注入点的形状有测试，通道本身没有。因此"桌面真的显示后端事实"这一条属 L2，未验。
3. **原生配置真的生效**：本区域只读 describe 事实。写配置/回读/行为探针属于
   `sandbox.native-configuration@1` 与 Harness C3（G3，`harness-api` 检查点未发布），
   所以 `supported` 只代表"配置面已实测"，效果证据仍待 T05 取证——
   这正是 `source`/`coverage` 原文照录、不改写、不加"已隔离"结论的原因。
4. **产品装配与跨域共存**：本包未加入 `products/desktop/extensions.json`
   （不允许改产品配置），因此 `npm run build` 不含它；与 Permissions 的
   Settings 区**同页共存**（两块独立区域各自出现）也尚未在同一装配里跑通过。
