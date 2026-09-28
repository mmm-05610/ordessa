# C8 — 通用 UI 基础件与开放组件装载

Date: 2026-09-27 | Owner: C frontend | Status: APPROVED_FOR_IMPLEMENTATION
追加起点：`33b5c19606`（C7 T032/T033 已入库）；完成检查点见 reports/C7.md 的 UIB007/UIB008 节，分支 `codex/010-platform-frontend`。
用户已裁决本增补加入当前前端线；本文是 C8 的实施权威，[amendments/ui-foundations](../amendments/ui-foundations/README.md) 是其设计快照。

## 快照来源（逐字复制，未在本线改写）

`specs/010-platform-core/amendments/ui-foundations/` 复制自主树
`docs/design/platform-ui-foundations/`，sha256 前缀：
`af9d7ac9` README · `ed2431d4` spec · `72d550e6` plan · `da493421` tasks · `f213a8aa` qoder-addendum。
主树原件只读，本线不回写；快照内容与本文件冲突时以本文件为准（快照保留其设计阶段的“待审/未分派”措辞）。

## 本次裁决（对 C7 权威链的增补与替换）

1. **保留** C7 全部通用语义与门禁：`packages/desktop-platform/ui-components` 的注册、绑定、装载、
   产品冻结选择、作用域回收、代次、错误隔离与动作 guard；U01–U16 与 T030–T036 不重做、不缩小。
2. **新增** `packages/desktop-platform/ui`（`@ordessa/ui`）：可直接 import 的 React 基础件（容器/布局/
   控件/Field/反馈 + 显式 scoped `styles.css`），按快照 plan 的有限清单为上限，不扩展成设计系统。
3. **撤销** 统一 `plugins/agent-ui`、12 项领域组件总包与统一默认提供者的实施要求。
   `amendments/ui-components/component-catalog.md` 与 `contracts/agent-ui.md` 只保留历史与取材价值，
   不是本线约束；不得把其中的领域字段、组件名或默认 provider 搬进平台或基础件。
4. 领域组件的契约与 key 由各业务插件自己定义并按需注册；平台不枚举业务组件种类，也不新增公共
   key 清单。基础件不认识 Git/Chat/Profile/审批/运行状态（快照 spec F01/F03）。
5. 组件注册（`ui-components`）与 Workbench 的页面/面板/浮层贡献位是两回事：本轮不重写 Workbench，
   不建立第二套 Dialog/Portal/焦点/overlay 管理器，不扩大 host/loader 行为（C7 已批准的通用接线除外）。
6. 依赖方向：`ui` 不依赖 `ui-components`；`ui-components` 不强制依赖 `ui`。React/Context 单例沿用既有
   共享构建映射（carrier/真实构建证明），不得用开发 alias 冒充生产构建证据（快照 V07）。

## 权威链

- 通用组件机制契约：[ui-components-platform.md](ui-components-platform.md)（C7，仍有效）。
- C7 通用契约正文：[amendments/ui-components/contracts/component-platform.md](../amendments/ui-components/contracts/component-platform.md)（不变）。
- C8 基础件契约与验收：本文件 + [amendments/ui-foundations/plan.md](../amendments/ui-foundations/plan.md)
  （最小公开基础件表、样式/主题/构建约束）+ [amendments/ui-foundations/tasks.md](../amendments/ui-foundations/tasks.md)
  （V01–V08 反例矩阵）。实施勾选表是 `specs/010-platform-core/tasks.md` 的 UIB001–UIB008。
- C7/C8 报告：`reports/C7.md`（含 C8 增补章节），原 C 线交付记录在 `reports/C.md`。

## 允许修改

`packages/desktop-platform/ui`（新包及其测试/样式）、`packages/desktop-platform/ui-components` 的通用
接线（不含已冻结的 api 语义）、必要的公共 exports/build 映射与 `tooling` 共享 API 映射、产品显式样式
接线、根 workspace/lock/typecheck/测试聚合、受控 examples 与测试夹具、本线 specs/reports/tasks。
禁止：业务插件实现、Workbench 重写、host/loader 行为扩大、Python/Go、其他工作树、根 main、用户服务、
真实模型、push/自动合并。锁由 npm 更新。

## 完成标准

T030–T036 与 U01–U16 保持全部有证据；UIB001–UIB008 全部完成且 V01–V08 每条同时具备正向证据与规定的
反例；类型正反例进既有 typecheck，真实构建与临时 Electron 门禁实际执行并记录退出码；原测试 ID 无未
解释退化（用 `tooling/id-diff.mjs` 比对）。报告逐项记录 source→reuse（React/原生/既有平台）、
任务→测试→日志，并区分受控组合与真实业务接入。达到后停在 `C7_C8_IMPLEMENTATION_REVIEW_READY`。
