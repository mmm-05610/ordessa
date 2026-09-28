# ZCode Desktop 可复用/借鉴优化点清单

调研方式：浅克隆 `zai-org/ZCode`（Apache-2.0）至本地，三路并行通读一手源码（窗口外壳 / app-shell 布局 / 设计系统与组件）。每条附证据路径。分级沿用本项目口径：**①=低成本、现有边界内即可做；②=需产品/架构决策；③=平台特定或超出当前范围，仅记录**。

## A. 外层窗口框架（最底层框）

| # | 借鉴点 | ZCode 证据 | 说明与价值 | 级 |
|---|---|---|---|---|
| A1 | 窗口尺寸持久化只存 `{width,height,maximized}`，用 `getNormalBounds()` 防最大化覆盖用户尺寸，恢复时按主屏 workArea 钳制；resize 防抖 250ms，close 只取消防抖（避免退出时写锁） | `desktop/src/main/desktopWindowSize.ts` L17-82 | 小而正确的窗口记忆方案，无 x/y 漂移问题 | ① |
| A2 | 启动防白闪：`index.html` 里 `#root{opacity:0}` + CSS splash，`zcode-startup-ready` 类淡入；次级窗口 `show:false` + `ready-to-show` + 主题匹配的 `backgroundColor` | `desktop/src/renderer/index.html`；`desktop/src/main/index.ts` L1563+ | 与"show 时机"解耦的纯 CSS 方案，成本低、观感提升明显 | ① |
| A3 | 缩放（zoom）管理：zoomFactor 持久化、创建时应用、并在 `did-finish-load` 重放（Chromium 会按 origin 重放覆盖持久值）；macOS 红绿灯随页面缩放用 `setWindowButtonPosition` 重定位（1.5 纵向增益） | `desktopWindowChrome.ts` L617-624；`desktopWindowButtonPosition.ts` L70-112 | 若 Ordessa 未来支持界面缩放，这是踩坑清单 | ② |
| A4 | 平台分档窗口视觉：mac `titleBarStyle:'hidden'`+trafficLightPosition+vibrancy；Win `frame:false`+`backgroundMaterial:'acrylic'`；Linux `transparent+frame:false+hasShadow:false`（WM 黑边问题） | `desktopWindowChrome.ts` L136-168 | 记录各平台 frameless 的坑；Ordessa 当前保留原生框，暂不引入 | ③ |
| A5 | 渲染层窗口按钮 + `env(titlebar-area-*)` 安全区：`DesktopWindowControls.tsx` 经命令总线派发 min/max/close，主进程推送 chrome 状态同步图标 | `packages/ui/src/DesktopWindowControls.tsx`；`DesktopTopOverlay.tsx` | 自绘标题栏的完整参考实现（含 maximize 状态回传） | ② |
| A6 | Windows 失焦/托盘隐藏后 acrylic 残影：有界两次 `webContents.invalidate()` 重绘 | `desktopWindowChrome.ts` L227-263 | 平台 bug 的规避样本 | ③ |

## B. App-shell 与布局

| # | 借鉴点 | ZCode 证据 | 说明与价值 | 级 |
|---|---|---|---|---|
| B1 | 外层侧栏用 **CSS 变量自绘分隔**（不走 react-resizable-panels），拖拽期间命令式写 var、pointerup 才 commit 一次；px 持久化 + 键盘步进 16px + `role=separator aria-valuemin/now` | `app-shell/WorkspaceShellLayout.tsx` L99-176, 1520-1611 | 避免窗口 resize 时布局 store churn；与 Ordessa 全用 RRP 的现状互补，可只借鉴"拖拽期命令式、松手才 setState" | ① |
| B2 | `useAnimatedResizablePanel`：collapse/expand 延迟一帧执行（防崩溃守卫）、记住最后展开百分比、仅在显式 toggle 时临时开 flex-grow transition | `app-shell/useAnimatedResizablePanel.ts` L96-124 | 面板开合动画不抖动的实用配方 | ① |
| B3 | 设置页 = **inert 覆盖层**而非路由替换：shell 常驻挂载，`opacity-0 pointer-events-none inert` 后覆盖 `absolute inset-0 z-10` | `renderer/root/RootWorkspaceContent.tsx` L99-204 | 消除整树重挂载闪烁；Ordessa 未来加设置/详情面时适用 | ② |
| B4 | 响应式自动收起阈值：会话区宽 `<480px` 收右栏、`<360px` 收侧栏，用 resize 监听 + 300ms idle 去抖（故意不用 ResizeObserver，避免与手动重开打架） | `WorkspaceShellLayout.tsx` L447-521 | 与 Ordessa 窄窗验收目标直接相关 | ① |
| B5 | 每个区域独立 `ScopedErrorBoundary` + 作用域 resetKey | `app-shell/` 多处 | 一 pane 崩溃不白屏整个 shell | ② |
| B6 | 快捷键纯函数内核：`matchesShortcutBinding`（修饰键精确匹配、CmdOrCtrl 平台归一、`event.code` 物理键兜底非美键盘）、IME/重复噪声过滤、用户覆盖解析 | `shortcuts/bindings.ts` | 框架无关、可直接移植的 keybinding 设计 | ② |
| B7 | 长列表虚拟化：`@tanstack/react-virtual` + 动态 `measureElement` | `workspace-grouped-tasks/virtualized-top-level-list.tsx` | 会话列表变长后的方案储备（新依赖，需报方案） | ② |
| B8 | 命令面板：cmdk `shouldFilter={false}` 自评分 + `loop` 循环导航 + 分 scope 段 | `command-center/CommandCenterDialog.tsx` | Ordessa 暂无命令面板需求，仅记录 | ③ |

## C. 设计系统（多数与本轮已实现方向一致，可继续收敛）

| # | 借鉴点 | ZCode 证据 | 说明与价值 | 级 |
|---|---|---|---|---|
| C1 | **单一字号变量驱动字阶**：只改 `--ui-font-size`，`text-ui-*` 按 ±N 派生（xl+4…2xs−5），禁止改 html font-size | `DESIGN.md` 类型节 | Ordessa 已有 `--ui-*` 命名，可把散落的 px 字号收敛成 calc 派生 | ① |
| C2 | 语义分层阶梯 background<surface<card<popover/menu + "无分层理由不得混用"；结构色（header/panel/sidebar）不得当通用卡色 | `DESIGN.md` 色彩节 | 本轮已按此实施，可写入 token 文档作为约束条文 | ① |
| C3 | **圆角=嵌套深度**：外层 xl→内层 lg→md→sm；仅 4 个 2xl 白名单（聊天输入壳、浮动状态面板、toast、品牌底）；`rounded-full` 只留给胶囊 | `DESIGN.md` 圆角表 | 直接解释并规范了"底部大圆角 composer + 内部小圆角"的做法 | ① |
| C4 | 边框用 `color-mix(in oklab, ink 10%, transparent)` 派生 alpha 线，而非硬编码灰 | `packages/ui/src/styles.css` L308+ | 主题切换时边框自动跟随，Ordessa 灰阶可迁移 | ① |
| C5 | `useTheme` 模式：偏好持久化 + `matchMedia` 监听 + 同步 `color-scheme` 和 `<meta name=theme-color>` | `packages/ui/src/useTheme.ts` | 未来暗色主题（B 类待确认项）的现成参考 | ② |
| C6 | 细则："先文字层级后边框"、"交互浮层必须在被动 tooltip 之上"、"菜单首帧就要带投影"、按钮只 transition-colors（transition-all 在大列表卡帧） | `DESIGN.md`；`components/ui/button.tsx` | 可直接抄进 ui-tokens 文档的硬规则 | ① |

## D. 对话区组件视觉（对照本轮实现）

| # | 借鉴点 | ZCode 证据 | 说明与价值 | 级 |
|---|---|---|---|---|
| D1 | 消息不对称：user=右气泡 `bg-secondary rounded-lg`，assistant=全宽无底色正文 | `components/ai-elements/message.tsx` | 与本轮实现一致，确认方向正确 | ✅已做 |
| D2 | 工具卡分状态图标（clock/pulse→绿勾→红/橙叉）+ params/result 双栏 `max-h-60 overflow-auto bg-muted/50` | `ai-elements/tool.tsx` | Ordessa 工具卡可补"运行/成功/失败"三态图标 | ① |
| D3 | 思考区：流式时触发行用 animated-gradient 文字，展开体 `border-l pl-3.5 text-subtlest`（左竖线代替卡片） | `ai-elements/reasoning.tsx` | 左竖线样式比整卡更轻，值得对照截图后择优 | ① |
| D4 | 审批卡：pending/approved/denied 状态机 + 专用 `--color-interaction-confirmation-*` 绿对（**不用** success 色） | `ai-elements/confirmation.tsx` | 把"审批等待"与"操作成功"色域分开，避免语义混淆 | ① |
| D5 | Composer 三态边框：`border-input-border → hover → focus-within 变背景`（focus 时输入区微微提亮） | `prompt-editor/ChatPromptEditor.tsx` | 低成本交互质感 | ① |
| D6 | tooltip/menu 全走 Radix Portal + `z-[60]` + Radix 自带 available-height CSS 变量限高 | `components/ui/tooltip.tsx`, `dropdown-menu.tsx` | Ordessa 现用原生/受控浮层；如浮层被裁剪问题出现再评估（新依赖需报方案） | ② |

## E. 许可与复用边界

- Apache-2.0 + `NOTICE.md`：任何代码移植需保留许可与 NOTICE 声明；`THIRD-PARTY-NOTICES.md` 由 `scripts/licenses.mjs` 生成，可借鉴其"锁文件→许可清单"自动化思路。
- 许可更正（2026-09-27）：本次核对的 ZCode `29628c9acdb81b703bbd4080c207a0e7ce5e276e` 中，`ai-elements/*` 文件头与 THIRD-PARTY-NOTICES 均标注派生自 Vercel AI Elements、Apache-2.0，并非先前记录的 MIT。移植须保留相关版权、许可与修改说明；具体取材范围见 `docs/design/agent-ui-implementation/research.md`。
- 本轮结论维持：**只借设计约定与配方，不整文件搬运**；①级项全部可在现有展示层边界内落地。
