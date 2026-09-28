# Workbench 统一侧栏改造 — 执行报告

2026-09-27 · 分支 `codex/workbench-sidebar` · 起点 `3c848bbba4`（开发基线 `1ea2084dfb`）
实现检查点：`40f700a6b6`（WS03–WS07）+ 本报告提交（夹具、证据与样式修正）。
**未 push、未合并 main、未删除分支。**

## 0. 起点与边界

- 基线复跑记录见 [baseline.md](baseline.md)：包内 34+7 全绿；根聚合 21/22（唯一红为登记预期红
  `rig:tests/acp-connector` U1–U6 / TARGET_MISSING，与本批无关）。
- 生产修改仅 `packages/workbench/**`；`api/workbench.ts`、`api/workbench.typecheck.ts`、
  `src/entry.tsx`、`src/model.ts` 零改动（`git show --stat` 可证）；无新公开 API。
- 未触碰主树/邻树；未复制 C8 未提交改动；测试生成的 `docs/ui-preview/*.png` 与
  `products/desktop/extensions.lock.json` 差异按登记不提交。

## 1. WS 逐项验收映射

| 任务 | 证据 | 状态 |
| --- | --- | --- |
| WS01 | baseline.md（本树） | ✅ |
| WS02 | `packages/workbench/PROVENANCE.md`（SHA 29628c9、Apache-2.0、三类裁决、上游键盘引擎未移植的诚实修正） | ✅ |
| WS03 | `src/sidebar.tsx` 四段；shell 中 `hasLeftContent`/`hasSidebarChrome` 分离；`tests/sidebar.test.tsx` 前 3 项反例 + `sidebar-width.test.ts` | ✅ |
| WS04 | 既有 6 个测试文件 0 改动全绿（composition/single-view/empty/contributor-unload/host-integration/popover）；`grep` 无 `.agent-*`/插件 ID/品牌条件；无插件 DOM 访问 | ✅ |
| WS05 | footer 单挂载 `FooterSurface`（mount=1、订阅平衡、设置唯一）；长导航/长 footer/零贡献/自滚动/非自滚动 fixture；浏览器复核发现 surface 盒模型致二次滚动 → 本批修复（见 §3 修正条目） | ✅（含修复） |
| WS06 | `src/sidebar-width.ts` 纯函数（264 初始/220 下限/min(360,40%)/冲突降限+constrained/无测量回退）；resize 与键盘仍归 react-resizable-panels；浏览器实测 264/256px | ✅ |
| WS07 | 单视图无标签、多视图标签+移动+关闭（浏览器 12 号证据：3 标签、select 与关闭存在）、reset、四辅助区域、overlay 焦点/锚点/error 反例原样保留 | ✅ |
| WS08 | 壳层类审阅 + `prefers-color-scheme:dark` 仅覆写既有 13 变量 + 真实浏览器 14 张截图（§3） | ✅ |
| WS09 | §2 门禁表 | ✅ |
| WS10 | 本报告 + diff 审阅记录（§5） | ✅ |

## 2. 测试门禁记录（主代理亲自复跑）

| 门禁 | 命令 | 结果 |
| --- | --- | --- |
| Workbench 定向 | `npx vitest run --maxWorkers=1` | 8 文件 / 50 测试全绿（基线 34 + 新增 16：sidebar.test.tsx 11、sidebar-width.test.ts 5） |
| 包内 node 门禁 | `node --test tests/` | 7/7 全绿 |
| typecheck | `npm run typecheck` | PASS（覆盖 workbench src+api） |
| 根聚合（第 1 次） | `npm test` | 20/22；红：acp-connector（登记预期红）+ `electron:test:agent-shell`(1.3s) |
| agent-shell 复跑 | `npm run test:agent-shell` ×2 | 均 exit=0 → 聚合中为启动抖动，非本批回归 |
| 根聚合（复跑） | `npm test` | 21/22，与基线一致；唯一红仍为登记的 acp-connector U1–U6（基线同 ID 同原因） |
| Electron 套件 | test:electron / test:extensions / test:agent-ui / test:agent-shell / test:ui-preview | 全绿（真实构建 + 真实产品 UI，Electron harness DOM 契约未破坏） |

WS04 证据：既有测试与 `apps/desktop/renderer/foundation.test.tsx`（范围外、不可改）全部原样通过。

## 3. 真实浏览器矩阵（Playwright + 系统 Chrome headless，受控预览夹具）

夹具：`packages/workbench/tests/preview/`（3 模块、12 导航命令、2 statusbar 组件 + 1 utility、
2 设置分区、popover/dialog 浮层、自滚动/非自滚动切换、超长标题；`window.__workbenchPreview` 驱动）。
构建 `node build.mjs`（esbuild 0.28.1，别名对齐 `tooling/vitest-extensions.mjs`），
服务 `node serve.mjs`（仅 127.0.0.1）。截图在 `screenshots/`。

| # | 场景 | 实测 | 结论 |
| --- | --- | --- | --- |
| 01 | 1280×800 默认+长导航 | 侧栏 264px；导航 15 项、footer 5 贡献在侧栏内；无横向溢出 | ✅ |
| 02 | 模块激活 | header 顶 0、footer 底 800（不随内容滚走）；内容区自身可滚；身份"工作区"；选中态 aria-pressed=true | ✅ |
| 03/03b | 自滚动/非自滚动 | 内部滚动生效；**发现 `.wb-surface` content-box 致外层第二滚动条**（基线同源问题，plan 明令不无条件套第二滚动条）→ 本批以 `box-sizing:border-box` 修复并复跑门禁+浏览器复核 | ✅（含修复） |
| 04/04b | 900×600 | 侧栏 264px（220–min(360,40%) 内）；footer 可达、主区 >300px；无溢出 | ✅ |
| 05 | 200% 等效（640×400 CSS, dsf2） | 侧栏收至 256px（=40% 上限）；折叠按钮与"打开设置"均可见可操作；无溢出 | ✅ |
| 06 | 折叠 | footer 移到紧凑底部带（`.wb-status` 全页计数=1，无第二挂载）；设置带内可达；恢复按钮 « 在主区 header | ✅ |
| 07 | 键盘恢复 | Tab 聚焦恢复钮 + Enter → 侧栏回归、带清空、footer 单实例回到侧栏 | ✅ |
| 08 | footer 锚定 popover | 打开成功且完整在视口内（w=245） | ✅ |
| 09 | 设置浮层 | 打开→Escape 关闭 | ✅ |
| 10 | 深色 | `prefers-color-scheme:dark` 生效（--ui-surface=#1b1c1e），四段与对比正常 | ✅ |
| 11 | 超长标题 | 主区多视图标签条内截断规则、无横向溢出 | ✅ |
| 12 | 多 left 视图 | 3 标签（对话/会话/工作流侧栏）、移动 select、关闭钮均在 | ✅ |

诚实边界：04b 中 15 项导航在 600px 高窗口未触发导航自身滚动（内容高度仍 < 可用高度），
"长导航限高自滚"由结构断言 + 400px 高场景截图支持，未单独量化 scrollHeight>clientHeight 的
触发样本；矩阵用 `?selfcheck` 之外的真实交互（click/键盘），非 mock 空数据。

## 4. 复用来源→目标→验收映射

见 `packages/workbench/PROVENANCE.md`。摘要：
- 移植纯函数：ZCode `clampWorkspaceSidebarWidth` → `src/sidebar-width.ts`（边界改 Ordessa 值；
  上游键盘/Home/End 引擎**未**移植，键盘 resize 由 react-resizable-panels 承担——已如实修正登记）。
- 结构提取：`WorkspaceSidebar.tsx` aside 骨架 → `.wb-sidebar*` 四段 CSS 结构。
- 仅参考：`WorkspaceSidebarCollapsedRail.tsx`（恢复入口原则）、footer 组织方式；无 logo/品牌/业务。
- 无新增依赖；无 ZCode 业务 import（grep 证据：仅来源注释）。

## 5. 明确未改范围与审阅记录

- Chat 插件项目树/置顶/最近会话/更多加载/草稿项目选择：未改、不越界（中部内容仍由 Chat 渲染，
  与目标截图存在过渡期差异，plan §5 已预告）。
- 主区旧 toolbar 的 Refresh 等按钮原样保留；overlay/settings/statusbar 注册方式与 ID 不变。
- 主代理 diff 审阅结论：shell 重构为移动+提取，ViewSurface/overlay 栈/焦点陷阱/锚点观察器
  逻辑未变；`hasSidebarChrome` 不含固定"设置"入口，保持空 Workbench 契约；一处
  aria-label 语义重复（侧栏内收起钮与 layout-actions 同义）登记为可评审项。
- 范围外契约自查：`tooling/id-diff.mjs` 冻结 265 ID MISSING:0（实现代理跑，主代理以根聚合复证）。

## 6. 未验证项（诚实清单）

- 真实产品装配（含 Chat/connections 全部扩展）下的 Electron 手工走查未做；已用 test:ui-preview
  （真实产品 UI + 匿名 fixture）与 Electron smoke 全绿替代，但矩阵截图来自包内受控预览夹具。
- 原生窗口最小尺寸、系统级缩放（OS 200% 而非 CSS 等效）未测。
- 长导航滚动触发阈值未单独量化（见 §3 诚实边界）。
- `expand()` 恢复"用户最后宽度"的精确性依赖库内部行为，矩阵未覆盖"拖宽→折叠→恢复仍为该宽度"
  的像素级断言（jsdom 无几何，浏览器矩阵未加此交互）。

## 7. 与平台后续改动的潜在冲突（只读盘点，2026-09-27 采集）

固定基线 `1ea2084dfb` 之后，`codex/010-platform-frontend` 新增两个已提交检查点（C7-T034 `77e911c454`、
C7-T035 `3411401795`）。对 `packages/workbench/**` 的触碰仅一处：`tests/token-scan.mjs`（+2 行）。
本批不修改该文件 ⇒ 零文本冲突。
平台树另有**未提交** C8 工作触及本批契约面：`apps/desktop/electron/main.ts`（Electron harness 选择器所在）、
`apps/desktop/renderer/main.tsx`、`apps/desktop/tsconfig.json`、`tooling/build-examples.mjs`、
新包 `packages/desktop-platform/ui/`、`examples/ui-foundations-probe/`。本批均只读、未修改；
集成时冲突点集中在 Electron harness 与 desktop tsconfig，需人工裁决，不可自动覆盖。
根 main `cd7d31f3cf` 仍含旧 `plugins/workbench` 路径，集成需走 review。
