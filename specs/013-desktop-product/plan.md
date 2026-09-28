# Implementation Plan — Ordessa Desktop 产品化

**Branch**: `013-desktop-product` | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md) · [research.md](research.md) · [data-model.md](data-model.md) · [contracts/](contracts/README.md)

## Summary

把 core 从"能跑的开发树"补成**独立 Desktop 产品**：产品身份、统一日志（强制脱敏）、Server 生命周期归属、默认数据根、wire 传输口对插件发布、设置/诊断/主题/快捷键、Harness 可用性、deb 打包与一键更新、许可证聚合与产物哈希、卸载。**首次启动引导 onboarding 后置**（用户裁定）。

技术路线：**契约先行**（9 条已冻结）→ 三个实施包并行 → 各自独立验证 → 主会话集成复验。deb 的一键更新走"下载 deb + polkit 提权安装"（research R2 裁定 B）。

## Constitution Check

| 条 | 检查 | 结论 |
| --- | --- | --- |
| 1 领域独立、机制共享 | 6+2 项机制收敛到公开契约；宿主**不**出现品牌/Profile/模型字段（C-08 明确禁止宿主 `which pi`） | ✅ 通过 |
| 2 诚实生命周期 | Server 进程唯一终止责任方 = Desktop 宿主；清理异常不覆盖主因（C-02 §5、C-04 §6） | ✅ 通过 |
| 3 契约先行 | 9 条契约冻结在 `contracts/`；空宿主有效（`AbsentWirePort`/缺席语义）；禁止全局 service locator | ✅ 通过 |
| 4 证据不假绿 | 每条契约含正例+反例+金丝雀；`Unknown` 不冒充 `Accepted`；红账本逐 ID 比对（SC-010） | ✅ 通过 |
| 5 安全与回退 | 磁盘格式/持久 ID/协议标识不变；零迁移（data-model §4）；无真实模型调用；不碰用户服务 | ✅ 通过 |

**Complexity Tracking**：无违规，无需填写。

## Technical Context

| 项 | 值 |
| --- | --- |
| Language/Version | TypeScript 6.0.3 / Node 22.22.1 / Electron 40.10.2；Python 3.12.14（捆绑 python-build-standalone 3.12.x） |
| Primary Dependencies | FastAPI + uvicorn（Server，锁 `server-linux-py312.txt`）；esbuild；vitest/pytest |
| Storage | 文件系统数据根（C-01）+ 既有 SQLite（**不改**） |
| Testing | vitest / pytest / 既有根聚合 `tooling/test-all.mjs` |
| Target Platform | **Ubuntu/Linux x64**（deb） |
| Project Type | desktop-app（Electron）+ server + plugins |
| Constraints | 零手填启动；令牌不进渲染进程；renderer 沙箱开启；启动 p95 ≤ 15s（SC-002） |
| Scale/Scope | 9 契约 / 3 实施包 / 1 deb / 1 更新链 |

## Project Structure

### Documentation (this feature)

```text
specs/013-desktop-product/
├── spec.md                 用户旅程 / FR / SC
├── research.md             技术裁定 + 插件接口判定表
├── plan.md                 本文件
├── data-model.md           数据根布局与实体
├── contracts/              ★ 冻结接口（9 条）
│   ├── README.md           索引 + 全局语义
│   ├── C-01-data-root.md
│   ├── C-02-launch-handoff.md
│   ├── C-03-wire-port.md
│   ├── C-04-logging.md
│   ├── C-05-theme.md
│   ├── C-06-settings-diagnostics.md
│   ├── C-07-commands-keybindings.md
│   ├── C-08-harness-availability.md
│   └── C-09-packaging-update.md
├── tasks.md                三包任务账（PA-/PB-/PC-）
└── dispatch/               ★ 三个实施包派单简报
    ├── P-A-desktop-host.md
    ├── P-B-server-runtime.md
    └── P-C-packaging-update.md
```

### Source Code (repository root)

```text
apps/
├── desktop/                       ← P-A
│   ├── electron/  renderer/  scripts/
│   └── package.json               产品元数据（P-A 拥有，P-C 只读）
└── server/                        ← P-B
    └── src/ordessa_server/
        ├── bootstrap/data_root.py ★ 新增（C-01）
        ├── __main__.py            ✎ --data-root/--port 缺省（C-01/C-02）
        └── transport/http/        /live + /wire/v1（既有，冻结）

packages/
├── desktop-platform/
│   ├── contracts/                 ← P-A  契约类型（C-03/04/05/06/07/08）
│   ├── ui/  ui-components/        ← P-A  基础件 / 组件注册（C-05 载体）
│   ├── extension-api/-loader/-host/ ← P-A
│   ├── native-bridge/             ← P-A  受限 IPC（wire 口通道载体）
│   ├── server-bridge/             ★ 新包 ← P-B  C-01/02/03 的 TS 实现
│   └── connections/               （既有）
├── server-plugin-api/             ← P-B
└── workbench/                     ← P-A  设置贡献点（C-06）

plugins/
├── connectors/{ordessa,acp}/      🔒 只读（既有 env 契约已冻结，core 侧适配即可）
└── harness/…                      🔒 只读（C-08 实现留待后续插件线）

assets/brand/                      ★ 图标单一事实位置（用户设计后放入；P-A/P-C 只读消费）
└── icon.svg                       矢量源；换图不改代码，占位期间不阻塞

packaging/                         ★ 新目录 ← P-C
├── debian/{control,postinst,prerm,postrm,copyright}
├── electron-builder.yml           （独立配置，不写 apps/desktop/package.json）
├── bundle-manifest.json           捆绑清单（C-09 §B）
├── update/                        更新清单生成 + Ed25519 签名工具
├── licenses/                      THIRD-PARTY-NOTICES 聚合
└── icons/                         构建期从 `assets/brand/icon.svg` 导出的多尺寸产物（P-C 生成器）

scripts/  tooling/                 ← P-C  打包/构建入口
tests/integration/                 ← 归位（acp-connector / acp_orchestration）
```

**Structure Decision**：按**进程/层**切分而非按功能横切——Desktop 宿主（TS 前端侧）、Server 运行时（Python + 接缝）、发行物（构建期）三者写入面**天然不重叠**，且契约已冻结故可并行。`packages/desktop-platform/server-bridge` 单列为新包，是 P-A 与 P-B 之间唯一的代码耦合点，且方向单向（P-A → P-B）。

---

## 分包方案：3 个可并行实施包

### 依赖与解耦判断

```text
                    ┌──────────────┐
                    │  contracts/  │  ★ 冻结输入（只读）
                    │   C-01..C-09 │
                    └──┬───┬───┬───┘
          消费         │   │   │        消费
        ┌──────────────┘   │   └──────────────┐
        ▼                  ▼                  ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  P-A          │  │  P-B          │  │  P-C          │
│  Desktop 宿主  │─▶│  Server 运行时 │  │  发行物        │
│  与平台 UI    │  │  与接缝       │  │  deb + 更新    │
└───────┬───────┘  └───────┬───────┘  └───────┬───────┘
        │  只读 package.json│                  │ 只读
        └──────────────────┴──────────────────▶│
                            只读捆绑内容清单     │
```

**唯一耦合点**：P-A 消费 P-B 的 `@ordessa/server-bridge`（C-01/02/03 实现）。解法：**契约已冻结**，P-A 先用受控 fixture 实现开发与测试，P-B 提供真实现后切换；P-C 只读两者的产物与元数据。

---

### P-A — Desktop 宿主与平台 UI

| 项 | 内容 |
| --- | --- |
| **worktree** | `worktrees/013-a-desktop-host`（分支 `codex/013-a-desktop-host`） |
| **写入面** | `apps/desktop/**`、`packages/desktop-platform/{contracts,ui,ui-components,extension-api,extension-loader,extension-host,native-bridge}/**`、`packages/workbench/**`、本包报告 |
| **插件改动** | **无**（013 零插件改动；`plugins/chat` 的主题收敛留待插件线） |
| **负责契约** | C-04（TS 实现）、C-05、C-06、C-07 的定义与实现；C-03/08 的类型与消费 |
| **交付** | 产品身份/图标/关于/版本注入、日志 TS sink、单实例 + before-quit + 窗口状态 + 崩溃恢复、故障 UI、设置页、诊断导出、主题收敛、命令面板 + 快捷键 + 键盘可达、smoke 代码拆出 |

### P-B — Server 运行时与接缝

| 项 | 内容 |
| --- | --- |
| **worktree** | `worktrees/013-b-server-runtime`（分支 `codex/013-b-server-runtime`） |
| **写入面** | `apps/server/**`、`packages/server-plugin-api/**`、`packages/desktop-platform/server-bridge/**`、本包报告 |
| **负责契约** | C-01、C-02、C-03 的定义与实现；C-04（Python 实现） |
| **交付** | 默认数据根 + CLI 缺省 + 跨语言一致性测试、随机 loopback origin、Server 生命周期模块（spawn/就绪/退出只杀自己）、wire 传输口对插件发布、日志 Python sink、Harness 可用性契约 |

### P-C — 发行物：deb + 一键更新 + 捆绑

| 项 | 内容 |
| --- | --- |
| **worktree** | `worktrees/013-c-packaging`（分支 `codex/013-c-packaging`） |
| **写入面** | `packaging/**`、`scripts/**`、`tooling/**`、根 `package.json`、根 `package-lock.json`、本包报告 |
| **负责契约** | C-09 的定义与实现 |
| **交付** | deb 打包（control/脚本/图标/.desktop）、运行时捆绑（Python/Server 依赖/ACP 桥/品牌制品）、一键更新（清单+Ed25519+polkit 安装+备份+回退）、许可证聚合、产物哈希、卸载语义、干净机器验收 |

---

## 跨包集成归属（谁把 core 拼起来）

> 三包各自完成 ≠ core 能跑。下表明确**每个能力由谁实现哪一段、由谁接线、由谁端到端复验**，避免"各自绿、拼不起"。

| 能力 | 实现（模块） | 接线 / 装配 | 端到端复验 |
| --- | --- | --- | --- |
| 数据根 C-01 | **P-B**（`bootstrap/data_root.py` + 布局常量） | P-A（宿主调用）/ P-C（deb 权限与提示） | P-B 出跨语言一致性测试；主会话 INT-04 |
| Server 生命周期 C-02 | **P-B**（`server-bridge`） | **P-A**（主进程 spawn / 就绪 / 退出只杀自己 / 故障 UI） | P-A 端到端；主会话 INT-04 |
| wire 口 C-03 | **P-B**（`server-bridge` + Server 侧） | **P-A**（注入扩展宿主，令牌不进渲染） | P-A 边界测试；主会话复验 |
| 日志 C-04 | **P-A**（TS sink）+ **P-B**（Py sink） | P-A（插件 API 发布）/ P-C（诊断收集源） | 同构测试 + 金丝雀 |
| 主题 C-05 | P-A | P-A（收敛 workbench / chat） | P-A 对照测试 |
| 设置与诊断 C-06 | P-A | P-A | P-A |
| 命令与快捷键 C-07 | P-A | P-A | P-A |
| Harness 可用性 C-08 | **P-B**（契约载体）+ Harness 插件（实现） | **P-A**（渲染） | P-A 渲染反例；主会话复验 |
| **一键更新 C-09** | **P-C**（更新引擎：清单 / 签名 / 下载 / 校验 / 备份 / 故障门 / 安装） | **P-A**（设置页"更新"分区 UI + 主进程调用更新引擎 + 重启） | P-C 全链；主会话 INT-04 |
| deb / 捆绑 / 卸载 | P-C | P-C | P-C 干净机器验收 |
| 产品身份 / 图标 / 关于 | P-A | P-C（hicolor / `.desktop` 安装） | P-C 装包验收 |

**关键接线责任（评审指出的缺口，明确如下）**：

- **更新引擎归 P-C**，但**设置页「检查更新」UI 与主进程接线归 P-A**。两者以 C-09 的流程语义 + `update-state.json` 格式对接：P-C 交付**可调用的更新客户端入口**，P-A 负责 UI 与生命周期接线（含更新后重启）。
- **跨包集成由主会话负责**（INT-01..05）：写入面冲突核查、契约一致性复验、根 lock 统一生成、红账本逐 ID 复验、从安装产物的最小纵切实测。

## 完成口径（评审裁定）

013 完成后应报告 **「core 发行能力就绪」**，**不是**「完整产品首版已发行」。理由：F2/F3（三品牌真实对话、配置与输入经真实接缝）不在本轮范围；三品牌可用性验收与真实模型调用属后续线。

## 插件改动清单（013 = **空**）

**本阶段是 core 阶段，不改任何插件。** 下表列明原方案 3 处插件触点如何由 core 侧替代，以及各自留下的已知缺口（登记，不隐瞒）。

| 原计划的插件改动 | 现处置 | 留下的已知缺口 |
| --- | --- | --- |
| `plugins/chat/frontend/src/theme.ts` 迁移到 C-05 | **不改**。core 提供 C-05，`packages/workbench`（core）收敛为消费方 | chat 界面暂不随全局主题切换，保留本地主题；由后续插件线收敛 |
| `plugins/connectors/{ordessa,acp}/**` env 交接 / wire 对齐 | **不改**。其 env 契约（`ORDESSA_SERVER_ORIGIN` / `ORDESSA_SERVER_TOKEN_FILE`）已冻结且正确，core 侧正确设置即可 | 若实测与新宿主不兼容，**core 侧适配优先**；确需改插件须先经用户裁定 |
| `plugins/harness/api` 承载 C-08 | **不改**。C-08 **类型**移入 core 的 `packages/desktop-platform/contracts`；实现留待插件线 | UI 显示"未提供 Harness 可用性信息"（诚实缺席，**不**假绿）；真实可用性由后续插件线提供 |

**例外协议**：实施中若发现**确需**改插件才能完成某项 core 能力 → **停止该项**，上报主会话并取得用户裁定；批准后逐文件登记再动。**禁止**静默改插件、禁止以"顺手"为由扩大写入面。


## 写入面纪律（三包共同遵守）

1. **只写自己的写入面**；其他树只读。
2. **契约冻结**：`contracts/**` 不得修改；确需变更 → 上报主会话并**停受影响任务**。
3. **根 `package.json` / `package-lock.json` 归 P-C**；P-A/P-B 如需根脚本，在报告中登记由主会话统一合入；**lock 只由 P-C 最后生成**。
4. **零插件改动**：`plugins/**` 一律只读。确需改插件 → **必须先上报主会话并取得用户裁定**，经批准后逐文件登记方可进行；**不得静默改**。
5. **不操作 git**（constitution）：不提交、不合并、不 push、不动其他 worktree；git 检查点由主会话负责。
6. **不 kill/restart 用户服务**（`docs/known-issues.md` §services）。
7. **零真实模型调用**；受控 fixture 明确标注。

## 验证与证据（每包必交）

| 项 | 要求 |
| --- | --- |
| 正例 + 反例 | 每条契约按其反例清单，**先红后绿**留档（含原始日志哈希） |
| 金丝雀 | 涉密钥处：注入已知令牌字节，断言**零命中** |
| 红账本 | 逐 ID 比对既有红账本（Harness 2 / Server 67 / acp_orchestration 18），新增红数 **= 0** |
| 边界 | 插件 import 宿主内部 → 判别为违规（反例） |
| 未测范围 | 诚实登记，**不**以局部测试冒充整线通过 |

## 明确不在本期

首次启动引导 onboarding · 三品牌真实可用性验收 · 真实模型调用 · i18n 翻译 · SBOM · 深链 · 崩溃上报上传 · Windows/macOS · apt 源托管。
