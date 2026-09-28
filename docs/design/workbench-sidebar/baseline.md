# WS01 基线复跑记录

2026-09-27，本树 `codex/workbench-sidebar @ 3c848bbba4`（开发基线 `1ea2084dfb`，两者只差本设计文档提交）。
依赖安装：根 `npm ci`（lockfile 未变动）。

## Workbench 包定向（实现前）

- `npx vitest run --maxWorkers=1`：6 文件 / 34 测试全绿
  - composition.test.tsx (20)、single-view-fallback.test.tsx (3)、empty-workbench.test.tsx (3)、
    contributor-unload.test.tsx (1)、host-integration.test.tsx (2)、popover.test.ts (5)
- `node --test tests/`：7/7 全绿（token-single-instance 等 mjs 门禁）

## 根聚合 `npm test`（实现前）

21/22 绿，退出码 0。唯一红：`rig:tests/acp-connector`，
`ui/acp-conversation.test.tsx` U1–U6 共 7 项（U1,U2,U3,U4,U5,U5b,U6），
原因 `TARGET_MISSING: plugins/connectors/acp/src/entry.ts does not resolve`——
登记的预期红（tests/acp-connector/docs/acp-connector-test-review.md），与 Workbench 无关。
其余：typecheck、build:examples、build:foundations、build:app、全部 workspace 套件、
products/desktop、electron 四项 smoke 全过。

## 公共 API 快照（本批不得变动）

`api/workbench.ts`：`Region`、`View`、`WorkbenchModule`、`WorkbenchOverlay(ContentProps)`、
`WorkbenchOverlayOpenOptions`、`WorkbenchSettingsSection`、`WorkbenchComposition`、
`UIContribution`、`Workbench`、`WorkbenchToken('ordessa.workbench.v1')`。
`src/entry.tsx` 插件 id `ordessa.workbench`、`provides: WorkbenchToken` 不变。

## 范围外硬契约（只读盘点，实现必须继续满足）

- `apps/desktop/renderer/foundation.test.tsx`：直接 import `src/model`+`src/shell`；
  断言 `[data-region]`×5、`[data-testid=workspace]` inert、`[data-testid=full-page]`、
  `.wb-actions` toolbar 槽、`[role=alert]`、跨区移动后组件实例状态保留（"move count 1"）。
- `apps/desktop/electron/main.ts` / `preview-main.ts`（test:electron、test:agent-shell、test:ui-preview 驱动）：
  `[data-region="left|right|…"]`、`#wb-left` 宽度键盘探测、
  `[data-region] header [role="group"] button` 标签条、`[data-region][data-active-view]`。
- `products/desktop/dist/extensions/ordessa.workbench/entry.js` 为构建产物（每次 build 重写）。

## 基线运行副作用（不提交）

根 `npm test` 会重写 `docs/ui-preview/02-history.png、05-running.png、06-narrow.png` 与
`products/desktop/extensions.lock.json`（本会话开始时树为 clean，属于测试生成差异）。
交付提交时逐文件 add，禁止包含这些路径。
