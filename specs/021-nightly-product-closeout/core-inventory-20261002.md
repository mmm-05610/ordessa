# 核心职责盘点 — core inventory (N4-R1, 2026-10-02)

范围：`packages/desktop-platform/*`、`packages/workbench`、`apps/server`、
`packages/pacthold`（含 `packages/server-plugin-api`）。
只读盘点，未改运行行为、未迁移契约、未重命名包。

命令与环境：全部在 `/home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout`
（分支 `nightly/021-harness-rollout-opencode-hermes-dsh-kilo`，基线检查点 865f3ab45f）。
Python 走 `.venv/bin/python`。本文件所有结论都带 `文件:行号`，不据名字断言。

## 0. 方法与证据口径

- 公开入口 = 包 `package.json` 的 `exports` / `ordessa.id`、`manifest.json` 的
  `id`、Python 包的公开门面（`pacthold.public` / `pacthold.extensions` /
  `server_plugin_api`）。
- 消费者 = 在 `apps/`、`plugins/`、`products/`、`packages/`、`tooling/` 里对该
  specifier 的实际 import（`grep` 全量统计，排除 `node_modules` 与 `dist`）。
- 注册 owner = 谁构造并持有该实例（不是谁 import 了类型）。
- 两张图分开画：**职责图**只说"谁拥有什么"；**依赖/装载图**区分 `import` 与
  `注册/装载` 两类边。`Server → Pacthold` 在依赖图上是合法使用边，不是归属违规。

---

## 1. 公开入口、消费者与注册 owner

### 1.1 `packages/desktop-platform/*`（9 个独立 npm 包，非"单一平台类"）

| 包 | npm 名 | extension id | 公开入口 | 提供的端口 / Token | 实际消费者（grep） | 注册 owner |
| --- | --- | --- | --- | --- | --- | --- |
| `extension-api` | `@ordessa/extension-api` | 无（非扩展） | `src/index.ts` | `Token`、`Contributions`、`OwnedResources`、`Host`、`PluginContext`、`HOST_API_VERSION='2'` | 167 处引用（plugins 94 / apps 11 / products 6 / packages 54 / tooling 2）；典型入口 `packages/desktop-platform/connections/api/connections.ts:11`、`apps/desktop/renderer/shared/api.ts` | 无（纯契约层） |
| `extension-loader` | `@ordessa/extension-loader` | 无 | `src/index.ts`、`./manifest` | `loadExtensions`、`Catalog`、`ExtensionDescriptor` | `apps/desktop/renderer/extensions.ts`、`extension-host/src/main/extensions.ts` | `apps/desktop/renderer/extensions.ts`（渲染进程启动时发现） |
| `extension-host` | `@ordessa/extension-host` | 无 | `src/index.ts`（`runtime`）、`./main`、`./platform`、`./services` | 宿主侧平台服务实现 + `runtime(plugins, services)` | 仅 `apps/desktop/{electron/main.ts, renderer/*}`；**插件零引用** | `apps/desktop/renderer/main.tsx:118` `runtime(loaded.plugins, services)` |
| `contracts/foundation` | `@ordessa/contracts-foundation` | `ordessa.contracts` | `src/entry.ts` → `src/contract.ts` | 8 个平台服务 Token + C-0x 类型载体 | 全部插件经浏览器 import map 的 `@extensions/ordessa.contracts/contract.js` | `products/desktop/extensions.json`（载体，非 provider） |
| `contracts/commands` | 无独立 package.json（foundation 的兄弟目录） | — | `src/commands.ts` | 命令/快捷键类型 | 经 `contract.ts:1` 再导出 | 同上 |
| `connections` | `@ordessa/connections` | `ordessa.connections` | `./api` | `ConnectionsToken`（`ordessa.connections.v1`）、`createConnectionKind` | `plugins/agent/contracts/src/connections.ts`、`plugins/agent/connections`、`plugins/agent/sessions`、`plugins/connectors/*`、`contract.ts:7` 再导出 | 内建扩展 `ordessa.connections`（`ConnectionsToken` 的实现方） |
| `ui-components` | `@ordessa/ui-components` | `ordessa.ui-components` | `./api`、`./react`、`./assembly` | `UiComponentsToken`、key/registration 工厂 | 42 处 `@ordessa/ui-components/api`；`contract.ts:10` 以外部 specifier 再导出 | 内建扩展 `ordessa.ui-components` |
| `ui` | `@ordessa/ui` | 无 | `.`、`./styles.css` | 基础控件 Card/Panel/表单（**非业务组件**） | `apps/desktop/renderer/main.tsx:14`、`contracts/foundation/src/contract.ts`（样式侧）、`ui-components/react/index.ts` | 样式由装配显式引入（`main.tsx:12-14` 注释：引入包本身不注入） |
| `native-bridge` | `@ordessa/native-bridge` | 无 | `.` → `src/index.ts` | 受限原生 IPC（Electron 主进程） | **仅** `apps/desktop/electron/main.ts`；另有两处插件 **type-only** 引用（见 §4.2） | `apps/desktop/electron/main.ts` |
| `server-bridge` | `@ordessa/server-bridge` | 无 | `.`、`./data-root`、`./errors`、`./wire-port`、`./lifecycle` | 宿主 onto Server 的接缝（数据根、wire port、生命周期） | **仅** `apps/desktop/electron/main.ts` | `apps/desktop/electron/main.ts` |

平台 8 个 C-0x 服务 Token 与**真实产品消费者**（`grep` 全 plugins/）：

| Token（字面量） | 定义 | 产品插件消费者 |
| --- | --- | --- |
| `ordessa.settings.v1` | `token/SettingsContributionToken.ts:11` | **0**（仅 `apps/desktop/tests/fixtures/third-party-plugin.ts`） |
| `ordessa.diagnostics.v1` | `token/DiagnosticsContributionToken.ts` | **0** |
| `ordessa.logger.v1` | `token/LoggerToken.ts` | **0** |
| `ordessa.theme.v1` | `token/ThemeServiceToken.ts` | **0** |
| `ordessa.commandSource.v1` / `ordessa.keybindings.v1` | `token/CommandSourceToken.ts` / `KeybindingServiceToken.ts` | **0** |
| `ordessa.harnessAvailability.v1` | `token/HarnessAvailabilityToken.ts:11` | **0**（provider 也只有测试 fixture：`apps/desktop/tests/fixtures/third-party-plugin.ts:48`） |
| `ordessa.wirePort.v1` | `token/WirePortToken.ts` | **6** 个插件 src（mcp / sandbox / skills / model-provider desktop + chat-contribution / profile 前端），另有 3 个测试文件 |

对比之下领域 Token 全部有真实消费者：`ordessa.workbench.v1`（8 个插件 src + 4 个测试文件）、
`ordessa.commands.v1`（`plugins/commands`、`plugins/agent/sessions`）、
`ordessa.connections.v1`、`ordessa.agent.connections.v1`、`ordessa.agent.sessions.v1`
（Agent 三域）、`ordessa.ui-components.v1`（5 个插件 src + 3 个测试文件）。

**盘点结论（事实，不是建议）**：8 个平台服务端口里只有 `wirePort` 被产品插件消费；
其余 7 个的实例由宿主注入，唯一的读方是宿主自己的 UI（见 §3 Settings）或测试。

### 1.2 `packages/workbench`

| 项 | 值 | 证据 |
| --- | --- | --- |
| npm 名 / extension id | `@ordessa/workbench` / `ordessa.workbench` | `package.json`、`manifest.json:1` |
| 公开入口 | `./api` → `api/workbench.ts` | `package.json` |
| 公开 API | `Workbench`（`forScope().addView/addUI`、`open`、`close`）、`WorkbenchComposition`（`forScope().addModule/addOverlay/addSettingsSection`、`activateModule`、`openOverlay`、`openSettings`）、`WorkbenchModule`、`WorkbenchOverlay`、`WorkbenchSettingsSection`、`View`、`UIContribution` | `api/workbench.ts:3-58` |
| 提供的端口 | `WorkbenchToken = new Token('ordessa.workbench.v1')` | `api/workbench.ts:60`（仓内唯一构造点） |
| 注册 owner | 自身即 provider：`src/entry.tsx:6` `provides: WorkbenchToken`，`:9` `context.root.mount(...)` | `src/entry.tsx` |
| 消费者 | **8** 个插件 src（chat 前端、profile 前端、mcp、sandbox、skills、model-provider desktop、agent connections、agent sessions）+ 4 个测试文件 | grep `WorkbenchToken` |
| 额外依赖 | `CommandsToken`（`src/entry.tsx:6` `requires`） | 同上 |

内部模块（`packages/workbench/src/`）：`model.ts`(182) `shell.tsx` `sidebar.tsx`
`sidebar-width.ts` `popover.ts` `region-header.tsx` `styles.ts`(246) `entry.tsx`；
共享工具 `shared/registry.ts`、`shared/boundary.tsx`。
现状已经是"按责任分文件"，只是没有 layout/navigation/overlays/settings 的目录分组
（见 §7 的 R2 建议）。

### 1.3 `apps/server`

| 项 | 值 | 证据 |
| --- | --- | --- |
| 分发名 / 入口 | `ordessa-server`，`ordessa_server.__main__:main` | `pyproject.toml:36` |
| 组合入口 | `bootstrap/runtime.py:481 build_runtime(...)`，`:452 _resolve_product_composition()` | 同上 |
| 后端宿主 | `plugin_host/host.py:315 ServerPluginHost`（`methods` / `stream_routes` / `http_routes` / `contribution_points` / `wire_error_families`） | 同上 |
| 贡献点注册表 | `plugin_host/contribution_points.py:84 ContributionPointRegistry` | 同上 |
| Pacthold 唯一接缝 | `core_binding.py:49 from pacthold.public import (...)`；`bootstrap/runtime.py:31 from pacthold.storage import ObjectStore, SecretStore` | 同上 |
| 依赖（`pyproject.toml:23-30`） | `pacthold==2.0.0a1`、`ordessa-server-plugin-api`、`fastapi`、`uvicorn`、`wsproto`、`pydantic` | 同上 |
| 产品装配 owner | `products/server/src/ordessa_server_product/composition.py:369 create_composition()`，`products/server/src/ordessa_server_product/` | 同上 |

**`Server → Pacthold` 的全部 import 面**（`grep -rn pacthold apps/server/src`）：
3 处真实 import —— `core_binding.py:49`（`pacthold.public`）、`bootstrap/runtime.py:31`
（`pacthold.storage`）、`:609`（`pacthold.storage`）；其余 10 处是注释/字符串。
另有 `pacthold_runtime_compat`（`plugins/runtime-compat`）被 `runtime.py:102,149,154`
按需 import，方向仍是 compat → kernel，合法。**这一整段是合规使用，不是归属违规。**

### 1.4 `packages/pacthold`

| 项 | 值 | 证据 |
| --- | --- | --- |
| 分发名 | `pacthold` 2.0.0a1，`dependencies = []` | `pyproject.toml:7,26` |
| 公开门面 | `pacthold.public`（C1 稳定入口，`:169 __all__`）；`pacthold.extensions`（插件机制 + `agent_box.plugins` entry-point group，`extensions/loader.py:20`）；`pacthold.storage`；`pacthold.cli` | 同上 |
| 子域 | `core/`、`work_core/`、`execution/`、`storage/`、`extensions/`、`migrations/`、`cli/` | `src/pacthold/` |
| 消费者 | `apps/server`（3 处）、`plugins/harness/src`（35 处文件命中 `ordessa_*` 前缀扫描，反向证明 kernel 不引用它）、`plugins/runtime-compat`、各后端插件 | grep |
| 注册 owner | 无（内核不组装；组装在 `apps/server` 与 `products/server`） | — |
| **依赖实测** | 全树 AST 扫描：非 stdlib、非 `pacthold` 的 import 只有 `pytest` 与 `us1_doubles`（测试用） | 本次实测，见 §5 测试 1 |

### 1.5 `packages/server-plugin-api`（顺带核实）

`ordessa-server-plugin-api` 0.1.0，`dependencies = []`（`pyproject.toml`）。
`src/server_plugin_api/__init__.py:1-25` 的模块 docstring 就是它的边界声明：
"must never import `ordessa_server`, `pacthold` product code, or any plugin"。
宿主与插件都从这里取共享词表（`ServerError`、wire/1 家族表、`WireError`），
避免插件 import 宿主内部。

---

## 2. 两张图

### 2.1 职责图（谁拥有什么；不含 import）

```text
                    ┌──────────────────────────────────────────┐
                    │ products/  插件清单 / 版本 / 组合选择 / 薄装配 │
                    │ desktop: extensions.json(+lock)          │
                    │ server : create_composition()            │
                    └──────────────────────────────────────────┘
                       启用(id)                     提供产品组合()
                         │                              │
   ┌─────────────────────┴──────────────┐               │
   │ apps/desktop（Electron 壳）          │               │
   │ 窗口/进程/安全 IPC/启动             │               │
   │ owner: renderer/host-services.ts    │               │
   │ owner: renderer/extensions.ts(装载) │               │
   └──────────────┬──────────────────────┘               │
                  │ 装载(extension id)                     │
   ┌──────────────▼───────────────────────────────────────▼──┐
   │ 扩展进程（plugins/* 领域能力）                            │
   │ 领域数据/操作/存储 + 自己的 UI + Harness 品牌适配           │
   └──────────────────────────────────────────────────────────┘

   ┌────────────────────────┐   ┌────────────────────────────┐
   │ desktop-platform        │   │ workbench（可装载 UI 框架） │
   │ 扩展 API / 装载 / 宿主  │   │ 导航 / 区域视图页 / 浮层    │
   │ 通用服务 / 基础控件      │   │ 设置页容器 / UI 贡献注册    │
   │ 组件注册装载             │   │ 不拥有：模型·Profile 状态   │
   │ 不拥有：工作台布局、     │   └────────────────────────────┘
   │        Agent/Harness 业务│
   └────────────────────────┘

   ┌────────────────────────┐   ┌────────────────────────────┐
   │ apps/server（网络运行壳）│   │ pacthold（后端治理内核）    │
   │ HTTP/WS/wire           │   │ execution/resource 生命周期 │
   │ 后端插件宿主（方法/路由）│   │ 治理/引用/组合              │
   │ 不拥有：执行状态机、     │   │ 内核贡献与存储契约          │
   │        品牌实现、配置业务│   │ 不拥有：网络路由、桌面 UI、  │
   └────────────────────────┘   │        Agent 对话、产品品牌  │
                                └────────────────────────────┘
```

### 2.2 依赖/装载图（`--import-->` 是 import/继承；`==装载==>` 是注册/启用）

```text
==装载==> products/desktop/extensions.json  --启用 18 个 extension id-->
   ordessa.contracts · ordessa.workbench · ordessa.ui-components ·
   ordessa.connections · ordessa.chat · ordessa.profile-* · ordessa.skills ·
   ordessa.asset-mcp · ordessa.model-provider* · ordessa.agent-* · ordessa.commands

==装载==> apps/desktop/renderer/extensions.ts --discover+load-->
   packages/desktop-platform/extension-loader   (extension discovery)
   packages/desktop-platform/extension-host     (runtime / 生命周期 / 平台服务)
==注入==> apps/desktop/renderer/host-services.ts --PlatformServiceMap-->
   8 个平台服务实例（含 settings、harness 缺席实现）
==装配==> apps/desktop/renderer/main.tsx:118  runtime(loaded.plugins, services)

--import-->
  plugins/*  --import-->  @ordessa/extension-api                (94 处)
  plugins/*  --import-->  @extensions/ordessa.contracts/contract.js (29 处)
  plugins/*  --import-->  @ordessa/ui-components/api             (42 处)
  plugins/*  --import-->  @extensions/ordessa.chat-api | ordessa.agent-contracts |
                          ordessa.profile-api | ordessa.model-provider
  apps/desktop/renderer/*  --import-->  @ordessa/extension-host (13 处，宿主内部)
  apps/desktop/electron/*  --import-->  @ordessa/native-bridge, @ordessa/server-bridge
  contracts/foundation/src/contract.ts  --import/re-export-->
        ../../commands/src/commands            (commands 载体)
        ../../../../workbench/api/workbench    (C4：把 Workbench 公开 API 聚合进平台载体)
        ../../../connections/api/connections  (C6：把 Connections 公开 API 聚合进平台载体)
        @ordessa/ui-components/api             (C7：外部 specifier，保持单份 Token)
        ./product/index                        (C-03..C-08 平台契约)

--import--> (后端，合法使用边，不是归属违规)
  apps/server/src/ordessa_server/core_binding.py:49   --import-->  pacthold.public
  apps/server/src/ordessa_server/bootstrap/runtime.py:31 --import--> pacthold.storage
  plugins/harness/src/ordessa_harness/**              --import-->  pacthold.work_core / pacthold_runtime_compat
  plugins/* (后端)                                    --import-->  server_plugin_api
  products/server/src/ordessa_server_product/composition.py  --装配--> apps/server + plugins

  pacthold  ==(不得 import)==>  ordessa_server / ordessa_harness /
                                 ordessa_* 插件 / products / apps
```

---

## 3. 两套 Settings 入口：三选一结论 = **两个实例（两个独立注册表）**

`core-boundaries-small-refactor.md` §判断要求"不能仅凭名称断言当前有两个活跃
注册表"。以下是完整证据链。

### 3.1 平台契约 `SettingsContribution`

| 环节 | 证据 |
| --- | --- |
| Token 定义 | `packages/desktop-platform/contracts/foundation/src/product/token/SettingsContributionToken.ts:11` — `new Token<SettingsContribution>('ordessa.settings.v1')` |
| 类型定义 | `packages/desktop-platform/contracts/foundation/src/product/settings-diagnostics.ts:21-33` — `SettingsSection`（`id/title/order/component/items`）+ `SettingsContribution.register(section) => () => void` |
| 聚合出口 | `.../product/tokens.ts:10` 再导出；`.../product/index.ts:8`；`.../src/contract.ts:14` |
| **实例创建** | `apps/desktop/renderer/host-services.ts:111` `const sections: SettingsSection[] = []`，`:120-126` `settings: { register(...), getSnapshot() }`。注意：这是一个**普通数组 + 闭包**，不是 lumino token 解析出来的服务 |
| 注册/注入 | `apps/desktop/renderer/main.tsx:113` `buildHostServices(...)` → `:118` `runtime(loaded.plugins, services)` → `extension-host/src/runtime.ts:38` 把 `services.settings` 注册为 `SettingsContributionToken` 的 provider |
| **消费者调用** | `apps/desktop/renderer/main.tsx:95` `contributed={services.settings.getSnapshot()}` → `apps/desktop/renderer/desktop-ui.tsx:73,87,98-100` 渲染成 `<li>` 的**纯文字标题**（`data-testid="contributed-section"`，无 component 渲染） |
| 产品插件消费者 | **0**。全仓 `SettingsContributionToken` 命中仅 4 处：定义、聚合、runtime 注册、以及 `apps/desktop/tests/fixtures/third-party-plugin.ts:11,51`（测试 fixture） |
| 可达性 | `main.tsx:80` `<nav … hidden={rootViews.length > 0}>`；而 `packages/workbench/src/entry.tsx:6,9` 是 `autoStart: true` 且 `context.root.mount(...)`。默认产品启动后必有 root view，宿主 chrome 的"设置"按钮被 `hidden` 隐藏 → 该浮层在默认产品里不可达 |

### 3.2 Workbench `WorkbenchComposition.addSettingsSection`

| 环节 | 证据 |
| --- | --- |
| 类型定义 | `packages/workbench/api/workbench.ts:25-30` `WorkbenchSettingsSection`（`id/title/order/component`），`:41` `addSettingsSection(section): IDisposable` |
| Token | **无**。`api/workbench.ts:60` 只构造 `WorkbenchToken`；全仓无 `SettingsContributionToken` 出现在 workbench |
| **实例创建** | `packages/workbench/src/model.ts:24` `const sections = registry<WorkbenchSettingsSection>(lifetime)` —— 在 `createWorkbench()` 内部新建，随 Workbench 实例生命周期 |
| 登记入口 | `packages/workbench/src/model.ts:124` `addSettingsSection: section => sections.add(scope, section)` |
| 作用域 | `forScope(scope)`（`api/workbench.ts:38`）；`shared/registry.ts:7-11` 按 `ResourceScope` 归属并随 scope 释放 |
| 消费者调用 | `packages/workbench/src/shell.tsx:185` `useSyncExternalStore(model.sections.subscribe, model.sections.getSnapshot)`；`:137-172` `SettingsOverlay` **真正渲染 section.component**；`:110`（`model.ts:110`）`openSettings` 校验 section 存在 |
| 产品插件消费者 | 6 个插件族：`plugins/permissions/frontend/src/settings-region.ts:235`、`plugins/assets/sandbox/frontend/src/settings-region.ts:278`、`plugins/assets/mcp/frontend/src/entry.tsx:52`、`plugins/assets/skills/desktop/src/entry.tsx:150`、`plugins/assets/model-provider/desktop/src/entry.tsx:42`、`plugins/profile/frontend/src/entry.tsx:17`（另有 `plugins/assets/subagents/settings/src/section.ts:75`） |

### 3.3 结论与影响

1. **两个实例，不是同一实例**：两处 `const sections` 是各自新建的（host 是
   `host-services.ts:111` 的数组，workbench 是 `model.ts:24` 的 `registry()`），
   类型不同（`SettingsSection.items?` vs 无 `items`）、释放语义不同
   （host 无 scope 归属，workbench 按 `ResourceScope` 释放）。
2. **没有第三个协调器，也没有桥接**：全仓无任何代码把
   `services.settings.getSnapshot()` 送进 `model.sections`，反向也没有。
   `packages/workbench/src/**` 对 `SettingsContribution` / `SettingsContributionToken`
   的引用数为 0（已作为回归断言钉在
   `packages/workbench/tests/layering.test.ts` 的
   "no Workbench source names the platform Settings contract or its token"）。
3. **平台那一套在默认产品里事实上是死的**：无插件 provider/consumer，且宿主浮层
   因 `main.tsx:80` 的 `hidden` 不可达。它不是"一个已死的注册表"这么干净——
   代码路径与测试（`apps/desktop/tests/host-ui.test.tsx:114,133-145,252-263`）
   仍然活着，只是产品里没有插件会往里登记、用户点不到。
4. **R3 的决策输入**（不在本轮执行）：
   - 若选 Workbench 为唯一登记事实 → 平台 `SettingsContributionToken` 的
     消费者清单为空、宿主浮层消费者为 0，**没有需要转发的活跃消费者**；
     迁移成本主要是删/冻结 `apps/desktop/renderer/desktop-ui.tsx:73,98-100` 与
     `host-services.ts:87,120-126`，以及 `apps/desktop/tests/host-ui.test.tsx`
     的 4 处断言（这些是产品 UI 回归测试，不是边界测试，不能删断言来变绿）。
   - 若选平台为 owner → 要把 workbench 的 `forScope` 作用域语义搬进一个没有
     scope 概念的数组，属于新增协调能力，违反 §R3 "禁止双写/新增第三个协调器"。
   - 建议 R3 明确写成：**UI 分区 owner = Workbench**，平台入口冻结为
     "只读、无消费者"并单独走一次迁移评审。

---

## 4. 现有边界问题清单（含 `文件:行号`）

标注约定：**[违规]** = 应修；**[已知/已登记]** = 代码注释或现有 guard 已显式接受；
**[合规]** = 正常依赖，不是问题。

### 4.1 跨层错误引用

| # | 位置 | 性质 | 影响 |
| --- | --- | --- | --- |
| B-01 | `packages/desktop-platform/contracts/foundation/src/contract.ts:4` `export * from '../../../../workbench/api/workbench'` | **[已知/已登记]**：C4 的既定通道，产品级 guard 已在 `products/desktop/tests/contract-ownership.test.mjs` 的 `WORKBENCH_API_ROOT` 白名单里显式接受 | 平台载体再导出另一个包的公开 API，导致图上"平台依赖 Workbench"。运行时是**单份 Token**（`token-single-instance.test.mjs` 断言 `ordessa.workbench.v1` 只在 `ordessa.contracts` 载体构造一次），所以不是重复身份问题；但它让"平台不拥有工作台布局"这条职责在 import 图上读不出来。R4 的迁移对象，本轮不动。 |
| B-02 | `packages/desktop-platform/contracts/foundation/src/contract.ts:7` `export * from '../../../connections/api/connections'` | **[已知/已登记]**：C6 同构通道，`contract.ts:5-6` 有注释说明 | 同 B-01 的读图问题；`ConnectionsToken` 单份身份已被产品 guard 覆盖。 |
| B-03 | `packages/desktop-platform/contracts/foundation/src/product/harness-availability.ts:1-41`（`HarnessState/HarnessReport/HarnessAvailability/AbsentHarnessAvailability`）+ `product/token/HarnessAvailabilityToken.ts:11` | **[违规（域契约落在平台）]**：`core-boundaries-small-refactor.md:18-20` 点名的 `product/harness-availability.ts` 与宿主 runtime 的 harness 注入混入领域契约。**当前准确位置已核实**：不是 `products/harness-availability`，而是 `contracts/foundation/src/product/` 下；`extension-host/src/runtime.ts:40` 是注入点 | 影响：① `packages/desktop-platform/**` 内出现 Agent/Harness 域类型名，而 `products/desktop/tests/contract-ownership.test.mjs:64-78` 的 `FROZEN_DOMAIN_NAMES` **只冻结了 Agent/Chat 名字**，Harness 域名未被任何 guard 覆盖；② 域契约与宿主缺席实现（`extension-host/src/services/harness-availability.ts:18`）被同一个包承载，将来无法单独搬走而不动平台。**实际产品消费者为 0**（`grep HarnessAvailability plugins/` = 0 命中），迁移成本目前最低，是 R4 里最容易先动的一块。 |
| B-04 | `packages/desktop-platform/server-bridge/src/data-root.ts:24` `import sharedLayout from '../../../../apps/server/src/ordessa_server/bootstrap/data_root_layout.json'` | **[已知/已登记]**：平台 → app 的**数据**（不是 API）引用；`contract-ownership.test.mjs:84-88` 的 `SERVER_LAYOUT_JSON` 白名单显式接受，并注明"B-001" | 影响：跨语言子系统之间存在一条平台 → app 的硬边。已被跨语言比较测试兜住，不是正确性风险；但它让"平台不依赖 app"在 import 图上不成立。与 B-01 同类，属 R4 的"内部服务注入分类"对象。 |
| B-05 | `plugins/connectors/acp/src/host.ts:3`、`plugins/connectors/ordessa/src/client.ts:5` `import type { AgentNativeBridge } from '../../../../apps/desktop/renderer/agent-native'` | **[违规（插件指名宿主内部）]**：`docs/architecture.md:53` "plugins never import host internals" | **type-only，运行时无耦合**（构建时被擦除，`tooling/build-extension.mjs:22-23` 的 externals 也不含该路径）。影响是编译期耦合：插件的类型检查依赖 `apps/desktop/renderer/` 的文件布局，且这两个插件包并未在 `package.json` 声明对该路径的依赖。已登记进 `extension-host/tests/plugin-host-boundary.test.ts` 的 `KNOWN_TYPE_ONLY_LEAKS`，新增第 5 条会让套件变红。 |
| B-06 | `plugins/connectors/acp/src/native.ts:4`、`plugins/connectors/ordessa/src/native.ts:1` `import type { NativeConnection, NativeTransport } from '../../../../packages/desktop-platform/native-bridge/src/index'` | **[违规（插件指名宿主原生模块）]**：同上，type-only | 同 B-05。注意 `native-bridge` 的公开入口本来就是 `.` → `src/index.ts`，所以路径可达同一模块**内容**，但走相对路径会绕过包名与 external 列表——一旦从 `import type` 变成值 import，esbuild 会把宿主原生模块**内联进插件产物**。这是 B-05/B-06 必须在 R2 之前处理的现实理由。 |
| B-07 | `packages/desktop-platform/contracts/foundation/src/product/settings-diagnostics.ts:21-33` 与 `packages/workbench/api/workbench.ts:25-30` 两套结构相近但不同的 Settings 类型 | **[R3 待决]**：见 §3 | 影响：领域插件只能走 Workbench 那套（B-03 同类问题，但因产品 100% 走 Workbench 而暂未暴露）。**本轮不动**，交 R3。 |
| B-08 | `plugins/assets/model-provider/chat-contribution/src/stub-chat-contract.ts:27` 再次构造 `new Token<ChatContributions>('ordessa.chat.contributions.v1')`（真实构造点在 `plugins/chat/api/src/contract.ts:424`） | **[非违规，已被既有测试守住]**：该文件是迁移史的本地转录（`:1-8` 的 docstring 自述"main does not carry that contract yet"），生产入口 `src/chat-api-entry.tsx:14-20` 走的是 `@extensions/ordessa.chat-api/contract.js` 真实载体，`tests/production-entry.test.tsx:153` 断言生产源码不含 `stub-chat-contract`。该字面量也**不在** `tests/token-scan.mjs` 的 `TOKEN_WATCHLIST` 里，所以构建级单份身份检查没覆盖它 | 记录以免 R3 误把它当成"第三个设置入口"（它的 `slot: 'chat.settings'` 是 **Chat 域内部**槽位，见 `stub-chat-contract.ts:22`），也提醒：这是全仓唯一一处在插件包里构造领域 Token 的地方，虽然当前无害，但产品 token guard 看不见它 |

### 4.2 明确合规、不要"修成平级"的依赖

| 依赖 | 证据 | 判定 |
| --- | --- | --- |
| `apps/server` → `pacthold` | `core_binding.py:49`、`bootstrap/runtime.py:31,609` | **[合规]** 合法使用。`core-binding.py:1-30` 的 docstring 明确 "imports come ONLY from `pacthold.public`"。新增 guard `packages/pacthold/tests/platform/test_n4r1_kernel_direction.py` 只禁止**反向**（kernel → server/harness/plugin），不禁止这一向。 |
| `plugins/harness` → `pacthold` / `pacthold_runtime_compat` | `plugins/harness/src/ordessa_harness/claude/profile.py:4-5`、`codex/continuation.py:3-4` 等 | **[合规]** compat → kernel 方向，由 `test_t009_direction_guard.py:118-132` 的正向测试钉住。 |
| `products/server` → `apps/server` + 插件 | `composition.py:369` | **[合规]** 组合根的职责（`core-boundaries-small-refactor.md:31`）。 |
| 插件 → `packages/workbench/api` 的 C4 公开 API（经载体） | `api/workbench.ts` + `contract.ts:4` | **[合规]** 插件用的是 Workbench 自己的公开入口，不是宿主内部。 |
| `apps/desktop/renderer/*` → `@ordessa/extension-host` | 13 处 | **[合规]** 宿主本来就是装配方（`core-boundaries-small-refactor.md:32`）。 |

---

## 5. 新增的正例/反例边界测试

三条都遵循同一纪律：**现状全绿**，每条断言配一个"当前违规会红"的反例，
没有任何 skip、没有删除既有断言。所有新文件都加进既有边界测试目录，未改包源码。

| # | 文件 | 测试 id（describe/it） | 命令 | 退出码 | 结果 |
| --- | --- | --- | --- | --- | --- |
| T-1 | `packages/pacthold/tests/platform/test_n4r1_kernel_direction.py`（新建，6 个 test） | `test_kernel_tree_has_no_import_of_server_harness_or_product` / `test_scanner_covers_src_and_tests_and_reads_real_imports` / `test_tripwire_planted_server_import_turns_the_guard_red` / `test_tripwire_from_import_form_is_detected_too` / `test_tripwire_on_a_real_kernel_file_would_be_reported` / `test_allowed_direction_is_actually_present_server_and_harness_import_pacthold` | `.venv/bin/python -m pytest packages/pacthold/tests/platform/test_n4r1_kernel_direction.py -q` | **0** | 6 passed |
| T-2 | `packages/desktop-platform/extension-host/tests/plugin-host-boundary.test.ts`（新建，7 个 test） | `scans a non-empty plugin source set…` / `has no VALUE import of a host-internal module` / `records exactly the known type-only host references and no more` / `still lets a plugin reach the public API packages and its own subdirectories` / `counterexample: a value import of a host internal IS a violation` / `counterexample: a type-only import of the same host internal is NOT a violation` / `counterexample: a plugin importing its own subdirectory is NOT a violation` | `npx vitest run --maxWorkers=1 --root packages/desktop-platform/extension-host tests/plugin-host-boundary.test.ts` | **0** | 7 passed |
| T-3 | `packages/workbench/tests/layering.test.ts`（新建，8 个 test） | `N4-R1: the Workbench reaches nothing above or beside its own package` → 6 个 it；`N4-R1: the two Settings entry points are still two independent registries` → 2 个 it | `npx vitest run --maxWorkers=1 --root packages/workbench tests/layering.test.ts` | **0** | 8 passed |

### 5.1 全套件回归（确认没把任何现有套件变红）

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `.venv/bin/python -m pytest packages/pacthold/tests -q` | **0** | 218 passed（含新增 6） |
| `npx vitest run --maxWorkers=1 --root packages/desktop-platform/extension-host` | **0** | 7 files / 103 passed（基线 6 files / 96，新增 1 file / 7） |
| `npx vitest run --maxWorkers=1 --root packages/workbench` | **0** | 10 files / 70 passed（基线 9 files / 62，新增 1 file / 8） |
| `node --test tests/`（packages/workbench） | 0（`--test-only` 探测） | 确认 node 的 test runner 不会拾取新增的 `.ts` 文件（Node 22.22 只收 `.js/.mjs/.cjs`），因此 `npm test` 的第二步不受影响 |

未运行（本轮无相关改动、且会触发真实全量构建/锁）：
`packages/workbench/tests/token-single-instance.test.mjs`、
`products/desktop/tests/contract-ownership.test.mjs`（两者都会
`acquireRealBuildLock` 并重建 `apps/desktop` 与 `products/desktop/dist`，
夜间并行会话可能冲突）。

### 5.2 反例有效性说明

- **T-1 的反例是真变异**：两个 tripwire 测试在
  `packages/pacthold/src/pacthold/` 与 `tests/platform/` 里**真实写入**一个
  `import ordessa_server` / `from ordessa_harness.launch import …` 文件，
  断言扫描器变红，再 `finally` 删除并要求回到绿。第三个测试把真实内核文件
  `work_core/db.py` 的内容追加一行产品 import 后暂存扫描，证明"真实文件被污染"
  也会被抓到。
  另用同一扫描器跑 `plugins/harness/src`（35 命中）、`products/server/src`（42 命中）、
  `plugins/profile/src`（1 命中），证明扫描器不是对当前树"恰好全绿"。
- **T-2/T-3 的反例是同函数级的合成输入**：把违例源码字符串喂给导出的
  `hostTargetOf` / `violationReason` / `specifiersOf`，断言它们被拒、而合法形式
  （公开 API 包、自身子目录、`import type`）被接受。这证明了判定逻辑的鉴别力，
  **但没有做"改动真实文件→套件变红"的端到端变异**（那需要写包源码，超出本任务写权）。
  如需端到端变异证据，建议在 R2 开始前由 Lead 授权一次性跑。

---

## 6. 与既有边界 guard 的关系（避免重复）

| 已有 guard | 覆盖的墙 | 本轮是否重复 |
| --- | --- | --- |
| `products/desktop/tests/contract-ownership.test.mjs` | 平台不得反向再导出 Agent 域载体；域载体位置与 id | 否（它管平台↔Agent 域，不管插件↔宿主、不管 workbench、不管 pacthold） |
| `packages/desktop-platform/connections/tests/platform-isolation.test.ts` | Connections 平台零业务耦合 | 否 |
| `packages/workbench/tests/token-single-instance.test.mjs` + `token-scan.mjs` | 真实构建里 Token/ConnectionKind 只构造一次 | 否（T-3 的域名 token 断言是**源码级、构建前**的补充，不替代它） |
| `packages/pacthold/tests/platform/test_t009_direction_guard.py` | kernel ↛ `pacthold_runtime_compat` | 否（只禁 compat 一个包；T-1 禁 `ordessa_*` 全前缀 + `plugins`） |
| `packages/pacthold/tests/platform/test_t009_bare_core_imports.py` | 阻断 compat 的裸内核导入扫描 | 否（导入阻断器只挡 compat） |

---

## 7. R2 建议（只建议，不执行）

判据：**已有稳定责任 + 有回归覆盖 + 能证明行为等价**。不满足"证据不足"的直接列出。

### 7.1 具备"已有稳定责任"、可以整理的 Workbench 内部模块

| 模块 | 已有责任（证据） | 行为等价的可证明性 | 建议 |
| --- | --- | --- | --- |
| `src/model.ts` | 唯一的状态与登记源：5 个 registry（`views/ui/modules/overlays/sections`，`:21-24`）+ 选择/布局/浮层栈 + 公开 service | 高。它不含 React，`tests/host-integration.test.ts`、`composition.test.tsx`（22 例）直接驱动它 | **按责任拆**：登记（registries）/ 布局（layout+selection）/ 浮层栈（overlay stack）三块，`model.ts` 保留一个组合入口。公共导出 `WorkbenchModel`、`createWorkbench` 形状不变 |
| `src/shell.tsx` | 渲染：region 网格、导航、overlay 宿主、`SettingsOverlay`（`:137-172`） | 中。有 DOM 断言（`data-overlay-id`、`aria-current`）可锁 | 按 layout / overlays / settings 三块切文件；`WorkbenchShell` 签名不变 |
| `src/sidebar.tsx` / `sidebar-width.ts` | 侧栏与宽度（拖拽持久化） | 高。`sidebar.test.tsx`(13) + `sidebar-width.test.ts`(5) 专测 | 保持独立；可归入 `navigation/` 分组 |
| `src/popover.ts` / `region-header.tsx` / `styles.ts` | 浮层定位 / 区域标题 / 样式常量 | `popover.test.ts`(5)、`theme-tokens.test.ts`(8) | 归入 `overlays/` 与 `styles/`，不合并 |

具体建议目录（**保持所有文件名与公共导出**，只加分组）：
`src/layout/`（model 布局部分、region-header）、`src/navigation/`（sidebar*）、
`src/overlays/`（popover、overlay 栈部分）、`src/settings/`（SettingsOverlay 部分）、
`src/registry/`（registries 部分）。**不搬** `shared/registry.ts`（它是内部 helper，
不是宿主服务，注释已声明）。

### 7.2 证据不足，**不建议**在本轮整理

| 对象 | 为什么证据不足 |
| --- | --- |
| `src/entry.tsx` | 13 行，只做 provides/requires + mount。除非 R2 需要新增入口文件，否则动它没有收益 |
| `src/model.ts` 中 `openSettings` 与 `SETTINGS_OVERLAY_ID`（`:9,108-115`） | 与 §3 的 R3 决策耦合。**在 R3 选定 owner 之前碰这里，等于替 R3 做了决定** |
| `api/workbench.ts` | 公开契约，R1/R2 都明确禁止迁移。最多补注释，不改形状 |
| 把 `contracts/foundation/src/contract.ts` 的 C4/C6 再导出搬走 | 属 R4，需要单独迁移批准 |
| `product/harness-availability.ts` 迁往领域 owner（B-03） | 属 R4。当前产品消费者为 0，迁移成本最低，但**不是 R2 的 Workbench 内部整理** |
| 两套 Settings 合并（B-07） | 属 R3，用户未批准 |
| `plugins/**` 的 B-05/B-06 type-only 泄漏 | 不在 R2 范围（只整理 Workbench 内部）。建议 R2 之前或并行单独处理，因为一旦 B-06 从 `import type` 变成值 import 就会内联宿主原生模块 |

### 7.3 R2 开工前的建议前置条件

1. 跑一次 `packages/workbench/tests/token-single-instance.test.mjs` 与
   `products/desktop/tests/contract-ownership.test.mjs` 取得**改动前**的真实构建基线
   （本轮未跑，见 §5.1）。
2. 取得 Lead 对"改动真实文件→套件变红"端到端变异证据的授权（§5.2）。
3. R3 的 Settings owner 决定至少先有结论再动 `model.ts` 的 settings 部分。

---

## 8. 事实地图更新（docs/architecture.md）

`docs/architecture.md` 有三处过时事实，已在同批更新中修正（见该文件的 diff）：

1. `:89` "Profile / Provider / Workboard: independent repos outside the monorepo"
   —— 与 `docs/reference-index.md:32-34` 核对后：**仓外**的是
   `harness-profile` / `harness-provider` / `harness-workboard` 三个**归档仓**；
   当前产品的 Profile / model-provider 插件族在树内（`plugins/profile`、
   `plugins/assets/model-provider`），且已在 `products/desktop/extensions.json`
   启用。已改写为区分两者，并显式提示 `AGENTS.md` 仍用旧简称（需 Lead/用户确认）。
2. `:38` 插件清单列了不存在的 `agent/conversation/`，并漏掉 `chat/`、`assets/*`、
   `profile/`、`permissions/`、`workspace/`、`runtime-compat/`、`server-compat/`。
3. `:18-29` `desktop-platform` 清单漏了 `ui/`、`ui-components/`、`server-bridge/`；
   `products/` 清单漏了 `server/`。

**未改** `AGENTS.md`（不在写权内）、`takeover-progress.md`（主执行者统一写）。