# Research — Ordessa Desktop 产品化

日期：2026-09-28。状态：设计输入（Phase 0 输出）。**只做只读核查与技术裁定，不含实施。**

对应 [spec.md](spec.md)。Constitution 门见 [plan.md](plan.md)。

---

## R1. 核心设计判断：什么要向 plugin 暴露接口

**判断准则**（源自 constitution 1/3 + `docs/design/plugin-layout-and-preparation-decisions.md` §1）：

1. 该能力是否**跨业务域共享机制**？→ 是则暴露（机制共享，业务内聚）。
2. 该能力是否涉及**品牌/业务语义**？→ 是则**不**在宿主实现，由插件提供、宿主只消费。
3. 该能力是否只与**进程/安装/生命周期**有关？→ 是则**不**暴露，宿主内聚。
4. 该能力是否已有既有契约？→ 复用，**不**新造（禁止自造跨树 API）。

### 判定表

| # | 能力 | 判定 | 理由 | 契约 |
| --- | --- | --- | --- | --- |
| 1 | **日志** | ✅ **必须暴露** | 所有插件都要写；不统一就会各自 `console.log`，脱敏与轮转无法保证（FR-011 是安全要求） | C-04 |
| 2 | **wire 传输口** | ✅ **必须暴露** | model-provider / profile 等要调 Server `modelProvider.*` 等方法；不暴露则插件自持令牌（违反 FR-031） | C-03 |
| 3 | **设置分区** | ✅ **必须暴露** | 已有 workbench「设置贡献点」；Z1/Z3 已按此实现，须冻结而非新造 | C-06 |
| 4 | **主题** | ✅ **必须暴露** | `packages/workbench/src/styles.ts` 与 `plugins/chat/frontend/src/theme.ts` **已各写一套**——这就是不统一的代价，必须收敛 | C-05 |
| 5 | **命令与快捷键** | ✅ **必须暴露** | 已有 `packages/desktop-platform/contracts` 的 commands source 契约；快捷键只是命令的绑定层 | C-07 |
| 6 | **Harness 可用性** | ✅ **必须暴露（插件提供）** | 品牌差异属 Harness 适配层（`plugin-layout` §4），宿主**不**得内置品牌逻辑；但 UI 要显示，故须有契约 | C-08 |
| 7 | **诊断片段** | ⭕ **可选暴露** | 插件可能有私有状态需诊断；但不阻塞主线，做成可选贡献点 | C-06 |
| 8 | **关于面板版本行** | ⭕ **可选暴露** | 插件版本需展示；但可由宿主读扩展清单获得，不必强加接口 | C-06 |
| 9 | 产品身份（图标/名称/元数据） | ❌ **不暴露** | 纯产品级，与插件无关 | — |
| 10 | Server 生命周期 / 数据根 / 随机端口 | ❌ **不暴露** | 进程与安装职责；`constitution` 2「一个进程一个终止责任方」 | C-01/C-02（**对内**契约，非插件 API） |
| 11 | 单实例锁 / before-quit / 窗口状态 / 崩溃恢复 | ❌ **不暴露** | 宿主生命周期内聚 | — |
| 12 | 一键更新 | ❌ **不暴露** | 应用级；插件随发行物一起走，无独立更新语义 | C-09（对内） |
| 13 | deb 打包 / 运行时捆绑 / 卸载 | ❌ **不暴露** | 构建期与系统集成 | C-09（对内） |
| 14 | 许可证聚合 | ⭕ **构建期声明**，非运行时 API | 插件在 `package.json`/`pyproject.toml` 声明第三方来源，构建期聚合 | C-09 |

**结论**：**6 项必须暴露**（日志、wire、设置、主题、命令、Harness 可用性）+ **2 项可选**（诊断、关于版本行）。其余宿主内聚。这 6+2 项全部收敛到 `packages/desktop-platform/` 的公开契约，插件**只** import 契约，**不** import 宿主实现。

> ⚠️ 易错点：**Harness 可用性**容易被做成"宿主检查 `which pi`"。那会把品牌逻辑塞进宿主，违反 `plugin-layout` §4 与 constitution 1。正确形态：Harness 插件实现 `HarnessAvailability`，宿主渲染。

---

## R2. deb 打包与"一键更新"的技术选型

### 问题

Electron 生态的一键更新（`electron-updater`）**原生只支持 AppImage / NSIS / dmg，不支持 deb**。用户已裁定用 deb。

### 选项

| 方案 | 机制 | 优点 | 缺点 |
| --- | --- | --- | --- |
| A. 自建 apt 源 | `apt upgrade` 完成更新 | 系统级、成熟、带签名链 | 需要自建/托管仓库 + GPG key 分发；用户未具备 |
| B. **下载 deb + polkit 提权安装** | 应用内检查→下载→校验→`pkexec dpkg -i`→重启 | 无需仓库；校验/备份/回退可控；后续可无缝换 A | 需 polkit 授权（一次 UAC 式弹窗） |
| C. snap/flatpak | 自带沙箱与自动更新 | 更新最省事 | 用户已裁定 deb，且沙箱会与现有 Electron 安全模型冲突 |
| D. 只提示去官网下载 | 半自动 | 实现最简 | 不满足"一键更新"（FR-074） |

### 裁定：**B**

理由：满足 FR-074「一键」语义且不需要用户自建仓库；polkit 提权是 Ubuntu 桌面的标准授权模式，用户预期之内；校验/备份/回退三段都能自己控制，正好覆盖 FR-075/076/077。方案 A 的仓库端不在本期，但客户端的清单格式按可复用设计（`UpdateManifest`，见 C-09），日后切 A 不改客户端语义。

### 更新源形态

静态 HTTPS 上的 `update-manifest.json` + `.deb` 文件。清单带 SHA-256 与签名（Ed25519，公钥随包）。**服务端托管不在本期**，客户端按此格式实现并可用本地静态源测试。

### 回退语义

**不假定** `dpkg -i` 覆盖安装在任意中断下都是原子的。因此"回退"= **可检测 + 可修复 + 数据不丢**：用更新状态机（`$DATA_ROOT/backups/update-state.json`，见 C-09 §C4）记录阶段，下次启动识别未完成更新并恢复到可启动状态；同时保留旧 deb 副本 + 数据根备份供用户显式重装。**不做**双版本并存切换（成本高、易出错）。

---

## R3. Python 运行时捆绑

F5 要求"无 Node/Go/仓库 `.venv` 依赖"。选项：

| 方案 | 说明 | 裁定 |
| --- | --- | --- |
| 依赖系统 `python3` | deb `Depends: python3` | ❌ Ubuntu 各版本 Python 不一，Server 依赖闭包（starlette 1.7.0 等）无法保证 |
| **捆绑 python-build-standalone** | 固定 3.12.x 到 `/opt/ordessa/python` | ✅ 版本可控、可复现、离线 |
| 自编译 CPython | 最可控 | ❌ 维护成本过高，收益有限 |

Server 依赖用 `apps/server/lockfiles/server-linux-py312.txt` 预装进 `/opt/ordessa/python/site-packages`，**不**在用户机器上 pip。

---

## R4. ACP 桥与品牌制品随包

- ACP 桥：`plugins/harness/packaging/acp-adapter/build-acp-adapter-round-h.sh` 产出的二进制（**不进 git**），构建期生成并放入 `/opt/ordessa/bin/acp`。
- 品牌制品：`plugins/harness/packaging/{pi,codex,claude,claude-legacy,qwen,kilo,dsh}` 的既有准备，随包放入 `/opt/ordessa/harnesses/`，供 Harness 插件按 C-08 发现。
- **本期只保证"随包 + 可发现 + 缺失时类型化拒绝"**，不负责品牌真实可用性验收（那是后续品牌线）。

---

## R5. 日志与脱敏

**风险**：令牌/凭据落盘是 F4 硬门（`SC-004`）。不能依赖调用方自觉。

**裁定**：脱敏在 **sink 层强制**，不在调用方。规则：
1. 任何字段名匹配 `token|secret|password|credential|authorization|bearer` → 值替换为 `[redacted]`。
2. 任何值与 `secrets/http-token` 内容逐字节匹配 → `[redacted]`（哨兵比对，防止换名泄漏）。
3. `secrets/` 路径下的文件**永不**被诊断收集。
4. 反例测试：注入已知令牌字节，断言日志与诊断包内**零命中**（沿用 Z3 `test_no_credential_leak` 金丝雀方法）。

**格式**（TS/Python 同构，见 C-04）：JSON Lines，字段 `ts/level/scope/msg/…`；落在 `$DATA_ROOT/logs/{desktop,server}.log`，按大小轮转，保留 N 份。

---

## R6. 既有实现的复用与收敛

| 现状 | 处置 |
| --- | --- |
| `plugins/connectors/ordessa/src/target.ts` 的 env 契约 | **保留，冻结为 C-02**（拒绝语义已写明"desktop host must pass…"） |
| `apps/server/transport/http/app.py` 的 `/live` + `/wire/v1/{method}` + Bearer | **保留，冻结为 C-02/C-03** |
| `bootstrap/runtime.py::_ensure_token` | **保留**，C-01 复用其 `secrets/http-token` 语义 |
| `packages/workbench` 设置贡献点 | **保留，冻结为 C-06** |
| `packages/desktop-platform/contracts` commands source | **保留，冻结为 C-07** |
| `products/desktop/extensions.lock.json` 逐文件哈希 | **保留**，C-09 的产物哈希清单在其上层再加一层 |
| `workbench/src/styles.ts` 与 `chat/frontend/src/theme.ts` 两套主题 | **收敛到 C-05**，二者改为消费方 |
| `apps/desktop/electron/main.ts` 内嵌 smoke 驱动代码 | **拆出**到 `apps/desktop/scripts/`（H1） |
| `run-dev.mjs` 的 `--no-sandbox` | **仅限开发脚本保留**，发行启动路径禁止（FR-072） |

---

## R7. 明确不做（避免范围蔓延）

- 首次启动引导 onboarding（用户裁定后置）。
- i18n 翻译交付（只留语言设置项与字符串抽取纪律）。
- 自动崩溃上报上传（本地记录即可，上传涉及隐私与遥测授权）。
- SBOM、深链、协议关联、系统托盘、自动启动。
- Windows/macOS 发行物。
- 三品牌真实可用性验收与真实模型调用（需另行授权）。
- apt 源托管（客户端可复用清单格式）。
