# P-A 报告 — Desktop 宿主与平台 UI

**worktree**：`worktrees/013-a-desktop-host`　**分支**：`codex/013-a-desktop-host`
**基线 HEAD**：`7adf5aeaca8a877e9f2c9caba7b594c51e18cdbb`（未提交；本包不操作 git，检查点归主会话）
**日期**：2026-09-28　**口径**：**core 发行能力就绪**（不是"完整产品首版已发行"）

---

## 0. 一句话结论

PA-01…PA-24 全部完成，PA-25（013 追加的 C-08 类型与缺席语义）完成；根聚合 `npm test`
**30/30 套件全绿、退出码 0**（基线同为全绿 → **新增红 = 0**）；**插件改动 = 无**（`plugins/**` 零改动，
`git status --short -- plugins` 为空）。

---

## 1. 验收命令与真实退出码

| 命令 | 退出码 | 说明 |
| --- | --- | --- |
| `npm ci` | 0 | 仅装依赖（未改 `package.json` / `package-lock.json`） |
| `npm run typecheck` | **0** | 覆盖全部 TS 源 + 契约类型反例 |
| `npm run build` | **0** | 真实构建：扩展 + 渲染 + 主进程 + 预载 + build-info + 图标 + **发行卫生闸门** |
| `npm test`（根聚合 30 套件） | **0** | 30/30 绿 |
| `npm run --workspace apps/desktop test` | 0 | 7 文件 / 125 测试 |
| `npm run --workspace packages/desktop-platform/extension-host test` | 0 | 6 文件 / 96 测试 |
| `npm run --workspace packages/workbench test` | 0 | vitest 60 + `node --test` 7 |
| `npm run --workspace plugins/chat/frontend test` | 0 | 未改插件，仅回归 |

根聚合逐套件（`tooling/test-all.mjs`）全部 `PASS exit=0`：typecheck、build:examples、build:foundations、
build:app、`workspace:*`（apps/desktop、connections、extension-host、native-bridge、ui、ui-components、
workbench、plugins/agent/*、plugins/assets/sandbox/frontend、plugins/chat/*、plugins/connectors/*、
plugins/permissions/frontend、products/desktop）、`node-test:products/desktop`（16/16）、
`rig:tests/acp-connector`、`electron:*` 7 个门。

### 1.1 先红后绿（原始日志留档）

| 项 | 红 | 绿 |
| --- | --- | --- |
| 契约类型反例（PA-01） | 临时移除全部 `@ts-expect-error` → `tsc` 报 **18 条**真实类型错误（`TS2540/TS2322/TS2345/TS2322…`），`RED_EXIT=2` | 恢复后 `npx tsc --noEmit` → `EXIT=0` |
| 契约伞目录（PA-01） | 新建 `contracts/product/` 触发 `products/desktop` 守卫红：`the platform umbrella must hold exactly the platform carriers commands/ + foundation/` | 迁入既有 `contracts/foundation/src/product/` 后该套件 16/16 绿 |
| 发行卫生（PA-11） | 把 smoke 驱动留在 `electron/main.ts` 时，闸门在真实构建里报 `Release hygiene: test driver code reached the distribution: electron-main.cjs contains "MODULAR_LOADER_READY"…` | 驱动迁出后 `findTestDrivers(dist) = []` |
| Host 页面文本（PA-13/04 回归） | 关于面板常驻 DOM → `test:ui-service` 红（`rootText` 命中 `provider-a`） | 改为按需浮层后绿 |
| 首次启动数据根（PA-07） | 数据根不存在即报故障 → `electron:test:agent-ui` / `ui-service` 红（`errors` 含"数据目录不可用"） | 首次启动先建后探 → 绿 |
| Token 单例门（PA-01） | 8 个 Token 合并在一个文件 → `token-single-instance` 的越界直引反例失去判别力（`2 !== 1`） | 每 Token 一个模块 → 绿 |

---

## 2. 逐条任务事实

### 阶段 1 — 契约类型与产品身份

**PA-01 契约类型（完成）**
`packages/desktop-platform/contracts/foundation/src/product/{wire-port,logging,theme,settings-diagnostics,commands-keybindings,harness-availability,index,tokens}.ts`
+ `typecounterexamples.typecheck.ts`（18 处 `@ts-expect-error` 真实触发）；由
`contracts/foundation/src/contract.ts` 从公开载体导出。8 个 DI Token **每 Token 一个模块**
（`product/token/*.ts`）——见 §5 命名裁决。
证据：`apps/desktop` tsconfig `include` 覆盖 `contracts/某包/src`，故 `npm run typecheck` 即门。

**PA-02 产品元数据（完成）**　`apps/desktop/package.json` 补 `productName/description/author/license/homepage/repository`；
版本号**单一来源** = 该文件 `version`；构建号由 `ORDESSA_BUILD_NUMBER` 注入，缺省 `<version>-local`；
构建期写 `dist/build-info.json`（关于面板、诊断 `meta.json`、发行清单同源 → C-09 §A4 四处相等的前提）。
非法版本号被 `assertBuildInfo` 拒绝。证据：`apps/desktop/tests/host-main.test.ts` PA-02 组。

**PA-03 图标接线（完成，含诚实缺口）**　`apps/desktop/scripts/build-icons.mjs` + `png.mjs`（自带零依赖 PNG 编码器）：
从单一事实位置 `assets/brand/icon.svg` 导出 16/32/48/64/128/256 PNG、Linux hicolor 布局
（8 个尺寸槽 + scalable SVG）与 `generated.json`；主进程把 `dist/icons/flat/256.png` 接到窗口图标，**缺图不传字段**。
**当前 `assets/brand/icon.svg` 不存在**（设计稿由用户后续提供）：产出内置占位 PNG、构建与运行都不阻塞；
用户放入设计稿后**不改任何代码**即可生效（有测试覆盖"存在的 SVG 走矢量路径"）。
**未测**：本机无 `rsvg-convert/inkscape/convert`，PNG 栅格化路径未经真实栅格化器验证，
`generated.json` 会如实登记 `rasterized: false`（由 P-C 在打包机用自带工具补齐）。

**PA-04 关于面板（完成）**　`renderer/desktop-ui.tsx::AboutPanel` + 主进程 `desktop:about`：
应用版本、构建号、作者/许可证/主页/仓库、**各插件版本**（来自扩展 manifest）、**第三方许可证**列表、**许可证全文**入口。
证据：PA-04 组测试。

### 阶段 2 — 日志与可靠性

**PA-05/PA-06 日志与金丝雀（完成）**　`extension-host/src/services/logging.ts`：
级别/scope/child 嵌套、JSON Lines 字段序 `ts,level,scope,msg,…`、10 MiB 轮转保留 5、**sink 层强制脱敏四规则**
（字段名 / 哨兵含消息正文与 URL / `secrets/` 路径 / 定位符收缩到 basename）、写失败丢弃并计数、
连续失败达阈值回调（"日志不可写"不静默）、`setLevel` 即时生效。
**金丝雀**：`CANARY-0f3a91c7-…` 三路注入（字段名 `token`、换名 `myKey`+令牌值、消息正文）→ 落盘**零命中**，只剩 `[redacted]`。
证据：`extension-host/tests/logging.test.ts`（18 测试）。

**PA-07 单实例 + 数据根锁（部分）**　`electron/lifecycle.ts` + `electron/data-root.ts`：
解析顺序 env → `~/.ordessa`；锁文件 `{pid,host,since}`；活锁 → `DATA_ROOT_LOCKED` 且故障带 `reason/remedy/logRef`；
取锁/释放/残留锁三条路径有测试。首次启动**先建后探**（建不起来才升级为故障）。
**未测**：Electron 的 `requestSingleInstanceLock` / `second-instance` 聚焦既有窗口**只有接线没有自动化断言**
（需要真实双进程 Electron 场景）。**两侧**：数据根锁语义 ✅ 有测试；单实例聚焦 ⚠️ 仅接线。

**PA-08 统一清理（完成）**　`runCleanup()`：所有步骤跑完、失败被收集而不是短路；`before-quit` 统一走
「停子进程 → 释放锁 → flush 日志 → 落盘干净退出标记」，清理错误与主因**分别**记录，绝不覆盖。
证据：PA-08 组测试（顺序 `['a','b','c']` + errors 精确断言）。

**PA-09 窗口状态记忆（完成）**　`restoreWindowState()`：合法几何恢复；显示器变小 → 退化为默认值；
拔掉扩展屏 → 位置失效但**保留尺寸**；损坏/缺失状态文件不抛异常。

**PA-10 崩溃恢复（部分）**　会话标记 `state/session.json`：启动写 `clean:false`，正常退出写 `clean:true`；
上次不干净 → `recovered` 报告 + 日志 warn。渲染进程 `render-process-gone` → 记日志并**只重载一次**（防崩溃循环）；
`child-process-gone` 记日志。
**未测**：`render-process-gone` 事件本身无自动化断言（需真实崩溃注入）。**两侧**：落盘与判定 ✅；事件处置 ⚠️ 仅接线。

**PA-11 代码卫生（完成）**　`electron/main.ts` 从 257 行降到约 250 行且**零** `executeJavaScript`：
约 200 行 smoke 驱动迁到 `apps/desktop/scripts/smoke-driver.mjs`（+`smoke-agent.mjs`、`smoke-ui.mjs` 转 .mjs），
主进程只按 `ORDESSA_SMOKE_DRIVER` 路径**运行时**动态加载（esbuild 不打包）。
发布卫生闸门 `scripts/release-hygiene.mjs` 在**真实构建**里执行（`build.mjs` 调 `assertNoTestDrivers(dist)`），
另有单测直接测闸门本身。**额外修正**：测试专用预览驱动原本编译进 `dist/preview-electron.cjs`（发行目录里有测试驱动），
已迁到 `dist-preview/`（并加 `apps/desktop/.gitignore`），渲染与预载路径用 `ORDESSA_PREVIEW_RENDERER` /
`ORDESSA_PREVIEW_PRELOAD` 显式传入。

### 阶段 3 — 故障 UI / 设置 / 诊断

**PA-12 故障 UI（完成）**　`FaultScreen` 渲染 `reason + remedy + logRef + 导出诊断/查看日志/重试`；
**5 类故障各一条**（无目录 / 端口冲突 / 缺二进制 / 根被锁 / 更新源不可达）逐条断言，**零空白**；
字段不全的故障被 `isRenderableFault` 拦在 UI 之外；故障顺序稳定。
另外把渲染进程的"故障 ≠ 崩溃"写进了 `main.tsx`：宿主能力缺席按"无故障"处理。

**PA-13 设置页（部分）**　五区（通用/数据/日志/更新/关于）齐全；数据根**只读**展示 + 打开目录；
日志级别即时生效 + "日志不可写"显式告警；更新分区走检查/下载/安装三步 + 失败原因可见 + 进度条。
**部分原因**：更新引擎归 P-C，本包只做 UI 与主进程接线，当前是**受控 fixture 状态机**；
`apply → 统一清理 → relaunch` 的重启路径**无自动化断言**。**两侧**：UI + 状态机 ✅；真实引擎与重启 ❌（未交付）。

**PA-14 设置分区贡献点（完成）**　注册/注销/排序（`order` + 标题稳定序）；卸载（注销）后分区消失；
已存配置**保留**（重开 store 读回断言）；未知片段标 `unknown` 且**不下发值**；坏 JSON/非对象文档归一化不崩。

**PA-15 诊断导出（完成）**　`extension-host/src/services/diagnostics.ts` + 零依赖 `zip.ts`：
五段内容（`meta.json`/`environment.json`/`product-manifest.json`/`data-root-state.json`/`logs/`）+ 插件片段；
解析失败的日志行**先脱敏再保留**并标 `parse-failed`；provider 抛异常或超 3 s → `{state:'unknown', reason}`，
导出仍成功；整体 **≤ 5 秒**（含一个会挂 10 s 的 provider 的用例）。
**金丝雀**：注入令牌 → zip 字节**零命中**，且无任何 `secrets` 条目路径。

### 阶段 4 — 主题 / 命令

**PA-16 主题服务（完成）**　`extension-host/src/services/theme.ts`：light/dark/system + tokens + subscribe + CSS 变量
（`--ordessa-*` 共 21 个）；tokens **逐层深冻结**（`Object.isFrozen` 在顶层与 color/space/radius/font/z 各层断言），
每次变更产生**新对象**；抛异常的订阅者不影响他人；缺席时 `createNeutralThemeService()` 返回非空中性令牌且 `resolved='light'`；
缺字段用默认值补齐不抛异常。

**PA-17 workbench 收敛（完成）**　`packages/workbench/src/styles.ts` 改为 `createWorkbenchStyles(tokens)`：
13 个旧 `--ui-*` 属性全部映射到 `--ordessa-*`（中间色用 `color-mix`），**无原始颜色字面量、无 `prefers-color-scheme` 分支**；
默认导出仍是字符串，既有消费方零改动。对照测试 `packages/workbench/tests/theme-tokens.test.ts`（9 测试，含 jsdom 下
宿主写变量的亮/暗生效与"互不为对方取值"）。

**PA-18 主题缺口登记（完成，按 013 = core 修订）**　`plugins/**` **零改动**（用户已裁定并回退主树；本树 `git status -- plugins` 为空）。
`packages/workbench` 已收敛为 C-05 消费方；**已知缺口**：chat 界面仍用自己的本地主题，
**暂不随全局主题切换**，由后续插件线收敛。
→ 提请主会话登记进 `docs/known-issues.md`（该文件不在本包写入面，见 §6）。

**PA-19 命令与快捷键（完成）**　`services/keybindings.ts` + `services/commands.ts`：
`Mod/Ctrl/Shift/Alt` + `+` 组合 + `,` 序列；非法快捷键**拒绝注册**并给类型化错误；
冲突（同解析后组合）**后注册者被拒**、在位者保留、失败注册不污染注册表；
`when`（标识/取反/&&/||/括号）求值，非法表达式在注册时即拒且不留半条记录；
三态执行（`command-absent` / `command-unavailable` / `command-failed` / `host-not-ready`），**永不抛裸异常**；
命令面板 `listPalette`（含 `available` 与解析后的组合键显示）、`dispatchKey` 键盘分派。
卸载：命令消失、绑定保留但标 unbound（`getUnbound()`），重装后恢复。

**PA-20 键盘可达（部分）**　命令面板键盘全流程（打开 → 搜索 → ↑↓ → Enter 执行 → Esc 关闭）在 jsdom 里**真实派发键盘事件**走通，
`Mod+Shift+P` 全局绑定与 Esc 关闭已接线。
**未测**：导航/发送/对话框/设置/错误关闭的**全链路**键盘走查未在真实 Electron 会话中断言
（既有 `electron:test:*` 门覆盖了 Tab 焦点与部分流程，但不是本条要求的端到端走查）。**两侧**：命令面板 ✅；全流程 ⚠️ 未测。

### 阶段 5 — 接线与边界

**PA-21 消费 C-01/02/03（部分，切换点已登记）**　`@ordessa/server-bridge` **尚不存在**（P-B 未交付）：
`apps/desktop/electron/wire-fixture.ts` 是**明确标注的受控 fixture**——不 spawn 进程、不发网络请求、不读令牌，
按冻结契约实现三态与缺席。**切换点**：把主进程 `createFixtureWirePort()` 一处构造换成 server-bridge 实例即可，
渲染代理与缺席实现不变（见 §3）。

**PA-22 WirePort 注入（完成）**　宿主侧注入（`runtime(plugins, services)` 把平台服务注册为**宿主自带 provider**，
插件用公开 Token `requires` 拿到实例）；**令牌只在主进程**，渲染进程经 IPC 代理、只拿三态；
缺席 → `AbsentWirePort` 恒 `Unknown/port-absent`；不自动重发；`Unknown` 不折叠成 `Refused`。

**PA-23 安全回归（完成）**　`electron/security.ts` 集中基线并被单测直接断言：
`SECURE_WEB_PREFERENCES = {sandbox:true, contextIsolation:true, nodeIntegration:false}`；
`isTrustedIpcCaller()` 拒绝跨窗口/子 frame/其它协议/已销毁窗口；`WINDOW_OPEN_ACTION='deny'`；权限请求全拒；
导航与 webview 附着阻止。preload 暴露面**无任何令牌字段**。

**PA-24 边界反例（完成）**　受控第三方 fixture 插件 `apps/desktop/tests/fixtures/third-party-plugin.ts`
**只** import 两个公开面（`@extensions/ordessa.contracts/contract.js` + `@ordessa/extension-api`），
在真实宿主装配里完成 6 项接入：① 日志 ② 主题 ③ 设置分区 ④ 诊断片段 ⑤ 命令+快捷键 ⑥ wire 口；
断言：宿主内部 import 数 **= 0**、激活零失败、卸载后贡献全消失、
**插件可见 wire 键恒为 `['call','ready','scope']`（无 `token`/`tokenFile`/`origin`）**。

**PA-25 C-08 类型与缺席语义（完成）**　类型在 `contracts/foundation/src/product/harness-availability.ts`
（6 态 + `reason/remedy/version/observedAt` + `provided` 缺席标记）；宿主侧语义在
`extension-host/src/services/harness-availability.ts`：
不变量校验（`available` 不得带 `reason`、非 `available` 必须带 `reason`，违反者**降级**为 `unknown/invariant-violation`，不崩不假绿）、
缺席实现（`provided:false`，`inspectOne` → `unknown/host-not-ready`，永不抛异常）、
**受控 fixture 提供者**（有界探测：超上限 → `unknown/inspect-timeout`；未安装一律 `not-installed`；未知品牌 → `unknown`）、
渲染三态区分（缺席 = "未提供 Harness 可用性信息"；空列表 = "状态未知"，**不冒充"没有 Harness"**）。
**边界**：C-08 相关宿主与契约源码品牌名扫描 = 0 命中（PA-25 测试组）。

---

## 3. 切换点（外部依赖未就绪时的登记）

| 依赖 | 现状 | 切换点 |
| --- | --- | --- |
| **P-B** `@ordessa/server-bridge`（C-01/C-02/C-03 真实现） | 未交付 | `apps/desktop/electron/main.ts` 里 `createFixtureWirePort()` → server-bridge 实例；`wire-fixture.ts` 的 `ServerLifecycleFact` 换成 bridge 的就绪探针。渲染代理、`AbsentWirePort`、三态与金丝雀测试**不动** |
| **P-B** C-08 Harness 提供者 | 未交付（且 013 明确不改插件） | 宿主默认注入**缺席实现**；插件线交付后把 `buildHostServices({harness})` 换成提供者即可，UI 分支（缺席/空/报告）已写好 |
| **P-C** 更新客户端入口 + `backups/update-state.json` | 未交付 | `apps/desktop/electron/update-client.ts` 导出 `UpdateClient` 接口 + 受控 fixture；换成 P-C 实现即可，设置页与 `update:apply → 清理 → relaunch` 接线不动 |
| **用户** `assets/brand/icon.svg` 设计稿 | 不存在 | 放入即生效，**不改代码**；本机若需真实栅格化可用 `ORDESSA_ICON_RASTERIZER` 指定工具 |

三处 fixture 都在文件头**明确标注**"这是 fixture，不是真实现"，无一处冒充真实现。

---

## 4. 插件改动清单

**无。** 013 = core 阶段，`plugins/**` 一律只读。
- `git status --short -- plugins` → 空。
- 曾经做过的 `plugins/chat/frontend/src/theme.ts` 迁移已按主会话裁定**回退**，成果备份在
  `scratch/013-plugin-changes/P-A-chat-theme.patch`（**本包不重做**）。
- `plugins/chat/frontend` 套件作为回归跑通（exit 0），未修改其任何文件。

**申报改动（写入面内的构建产物与守卫调整，逐文件）**

| 文件 | 性质 | 原因 |
| --- | --- | --- |
| `products/desktop/extensions.lock.json` | 追踪文件，被真实构建重写 | workbench 样式变化导致产物哈希变化；由 `tooling/build-all.mjs` 在每次 `npm run build` 生成，内容仍是同一份哈希账 |
| `docs/ui-preview/*.png`（6 个） | 截图，被 `test:ui-preview` 重写 | 既有 Electron 预览门每次运行都重拍；非源码 |
| `packages/workbench/tests/token-scan.mjs` | 守卫清单扩展 | 新增 8 个平台 Token 必须进 watch list，否则"越界直引源文件"反例失去判别力（PA-01/PA-22 的单例保证） |
| `packages/workbench/tests/theme-tokens.test.ts` | 新增测试 | PA-17 对照测试 |
| `apps/desktop/tsconfig.json` / `vitest.config.ts` / `package.json` | include 与元数据 | 新增 `tests/`、`allowJs`（测试要 import `.mjs` 构建脚本）、PA-02 元数据与脚本 |
| `apps/desktop/.gitignore` | 新增 | 忽略 `dist-preview/`（测试驱动产物不进版本库） |

`specs/013-desktop-product/{plan,tasks,contracts/C-05,contracts/C-08,dispatch/*}` 的改动**不是我做的**——是主会话在本树里下发的更新，我按新版执行（plugins 只读 / PA-18 改登记缺口 / 新增 PA-25）。

---

## 5. 命名裁决（不改契约文本的导出适配）

1. **C-07 的 `Command` 与既有 commands source 同名冲突**：既有 `contracts/commands/src/commands.ts` 已在公开
   载体导出另一个 `Command`（`execute` 形状）。契约文本不动，C-07 的 `Command` 以命名空间 `C07` 导出，
   `CommandSource` / `Keybinding` / `CommandOutcome` 等无冲突名扁平再导出。
2. **每个 Token 一个模块**：`token-single-instance` 门按"一个构造点 ↔ 一个源文件"核对单例身份；
   8 个 Token 合并在一个文件会让"越界直引源文件"反例无法判别（实测 `2 !== 1`），故拆为
   `contracts/foundation/src/product/token/*.ts` + `tokens.ts` 聚合再导出。
3. **C-08 增加 `provided`**：契约要求 UI 能区分"没有提供者"与"有提供者但列表为空"（§3 禁止空列表冒充），
   故 `HarnessAvailability` 增加只读 `provided`，缺席实现 `provided:false`。

---

## 6. 未测范围与已知缺口（诚实登记，不冒充通过）

1. **PA-07** Electron 单实例二次启动聚焦：无自动化断言（需真实双进程）。
2. **PA-10** `render-process-gone` 自动重载：逻辑有测试，事件处置仅接线。
3. **PA-13** 更新后重启：状态机有测试，Electron `relaunch` 仅接线。
4. **PA-20** 键盘全流程：命令面板全流程已走通；导航/发送/对话框/设置/错误关闭的端到端键盘走查未测。
5. **PA-03** PNG 栅格化：本机无栅格化器，SVG→PNG 真实路径未验证（占位路径已验证）。
6. **PA-21** server-bridge 真实接线：依赖 P-B；当前为受控 fixture。
7. **PA-13** 更新引擎（清单/签名/下载/校验/备份/`pkexec`）：归 P-C，本包**未实现**，也不假绿。
8. **已知功能缺口（PA-18）**：chat 界面不随全局主题切换（013 不改插件）。
9. **建议主会话登记**：`docs/known-issues.md` 增加第 8 条（chat 主题缺口）与第 1/3/4 条的"未测"范围。
   该文件不在本包写入面，故只在本报告登记。

**诚实声明**：以上 1–4 项**不以局部测试冒充整线通过**；对应任务在 `tasks.md` 标为 `[~]` 并写清两侧。

---

## 7. 红账本

基线（`docs/baseline.md` / 本树 `npm test` 首次运行）：根聚合除本次新增外**全绿**。
本次交付后根聚合 **30/30 全绿、退出码 0**，**新增红 = 0**，红账本逐 ID 未变。
Harness 2 / Server 67 / acp_orchestration 18 属 P-B 与后续线，本包未触碰。

---

## 8. 声明

- **不操作 git**：无 add / commit / merge / push / checkout / stash；检查点归主会话。
- **契约零改动**：`specs/013-desktop-product/contracts/**` 本包**未修改**（git status 中的改动来自主会话下发）。
- **零插件改动**、零真实模型调用、无凭据/用户数据进入仓库、未 kill/restart 用户服务。
- **无假绿**：没有删断言、加 skip 或复活兼容链；新增红灯全部修复或如实登记。
- 本包完成后**停止**待审。
