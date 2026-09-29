# Feature Specification: Ordessa Desktop 产品化（core 作为独立 Desktop 产品）

**Feature Branch**: `013-desktop-product`

**Created**: 2026-09-28

**Status**: Draft（待用户审）

**Input**: 用户描述："core 作为独立 Desktop 产品缺哪些必要的东西，全部都要（deb 打包、一键更新等）；首次体验不着急弄。用 Spec Kit 规格设计，设计时逐项判断是否需向 plugin 暴露接口，最后切成 2–3 个可并行的实施包。"

**上游依据**: `docs/release/first-release-handoff.md`（发行门 F1–F5）、`.specify/memory/constitution.md`、`docs/design/plugin-layout-and-preparation-decisions.md`、`docs/design/platform-core-convergence.md`。

---

## 范围裁定（用户已定）

| 项 | 裁定 |
| --- | --- |
| 安装格式 | **deb**（Ubuntu/Linux x64），不用 AppImage/snap/flatpak |
| 首次启动引导 onboarding | **本期不做**，列入 deferred |
| 其余产品化必需品 | **全部要做**（产品身份、日志、更新、可靠性、设置、诊断、Harness 检测、主题、快捷键、合规） |
| 三品牌发行门 | 不在本期；本期只交付"core 产品底座"，品牌能力由后续线接 |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 装完就能用，零手填 (Priority: P1)

用户在 Ubuntu 上安装 `ordessa_*_amd64.deb`，双击应用图标，窗口打开后 Server 已就绪、界面可继续操作。全程不需要填写数据根、端口、令牌、Python/Go/Node 路径或 ACP 桥路径。

**Why this priority**: 这是"开箱即用"的定义本身（发行门 F1）。没有它其余一切无意义。

**Independent Test**: 干净 HOME 的 Ubuntu 机器上 `sudo apt install ./ordessa_*.deb` → 点图标 → 观察 `~/.ordessa` 被自动创建（0700）、Server 就绪、界面可用。全程不打开终端。

**Acceptance Scenarios**:

1. **Given** 干净 HOME 且无 `~/.ordessa`，**When** 双击图标启动，**Then** 自动创建 `~/.ordessa`（目录 0700、`secrets/http-token` 0600），Server 就绪，界面可继续。
2. **Given** 已存在 `~/.ordessa` 且有历史数据，**When** 再次启动，**Then** 复用该根，不重建、不改写既有数据、不自动从任何旧根导入。
3. **Given** `~/.ordessa` 是符号链接 / 不可写 / 被另一实例锁住，**When** 启动，**Then** 显示可操作错误（说明原因 + 修复办法 + 日志入口），**绝不**空白窗口或假装成功。
4. **Given** 用户显式设置 `ORDESSA_DATA_ROOT`，**When** 启动，**Then** 使用该位置覆盖默认值（开发/高级入口），其余语义不变。
5. **Given** 应用已在运行，**When** 用户再次双击图标，**Then** 聚焦既有窗口，**不**开第二个实例、**不**争抢数据根锁。

---

### User Story 2 - 出问题能自助排查 (Priority: P1)

用户遇到异常时，能看到人话错误 + 一键导出诊断包（日志、版本、环境、产品清单哈希），发给支持者即可定位。

**Why this priority**: 发行门 F1/F4 明确要求"可操作错误，绝不空白或假绿"。没有日志就没有可操作错误，等于把所有故障变成黑箱。

**Independent Test**: 人为制造端口冲突 / 数据根不可写 / 缺随包二进制，观察错误提示与诊断导出内容完整。

**Acceptance Scenarios**:

1. **Given** Server 启动失败，**When** 等待就绪超时，**Then** 显示含"原因 + 可执行的下一步 + 查看日志"的错误，且诊断导出里含该次失败的完整日志。
2. **Given** 任意插件写日志，**When** 查看日志，**Then** 插件日志与宿主日志在同一日志目录、同一格式、同一时间线，且经统一脱敏（令牌/凭据永不落盘）。
3. **Given** 用户点击"导出诊断"，**When** 生成，**Then** 产出单个压缩包，内含：应用版本与构建号、产品清单及其哈希、环境信息、全部日志、数据根状态（**不含**任何令牌字节）。
4. **Given** 日志达到轮转阈值，**When** 继续写，**Then** 按规范轮转并保留有限份数，磁盘不会无限增长。

---

### User Story 3 - 一键更新 (Priority: P1)

用户在应用内点"检查更新"，看到新版本后一键安装并重启，数据完好；失败可回退。

**Why this priority**: deb 没有 AppImage 那样的自更新能力，必须自己做；不做就是"发了版没人能升级"。

**Independent Test**: 用本地静态更新源发布 `v_new`，走完 检查 → 下载 → 校验 → 备份 → 安装 → 重启 → 历史仍在 全链。

**Acceptance Scenarios**:

1. **Given** 更新源有新版本，**When** 点"检查更新"，**Then** 展示版本号、体积、更新内容与来源，**不**自动下载。
2. **Given** 用户确认更新，**When** 下载，**Then** 校验 SHA-256 与签名；校验失败**拒绝安装**并说明。
3. **Given** 校验通过，**When** 安装，**Then** 先备份数据根与当前版本信息，再经 polkit 提权安装 deb，随后重启应用。
4. **Given** 安装过程中断电/失败，**When** 重启应用，**Then** 能启动（旧版本仍在或新版本完整），数据根未损坏，且给出明确状态。
5. **Given** 更新源不可达，**When** 检查更新，**Then** 明确报"无法连接更新源"，**不**静默当作"已是最新"。
6. **Given** 无新版本，**When** 检查更新，**Then** 如实显示当前已是最新。

---

### User Story 4 - 它看起来是个正经产品 (Priority: P2)

图标、应用名、关于面板、版本号、单实例、窗口状态记忆——这些"产品身份"让用户相信这是一个产品而不是一个 dev script。

**Why this priority**: 不影响功能，但决定第一印象与可支持性；且图标/产品名是 deb 打包的硬前置。

**Independent Test**: 查看桌面图标、关于面板内容、重启后窗口尺寸位置恢复、重复启动不重复开窗。

**Acceptance Scenarios**:

1. **Given** 安装完成，**When** 在应用菜单/桌面查找，**Then** 有正确图标与应用名 `Ordessa`，多尺寸图标清晰。
2. **Given** 打开关于面板，**When** 查看，**Then** 显示应用版本、构建号、各插件版本、第三方许可证入口、许可证全文入口。
3. **Given** 用户调整窗口大小位置后关闭，**When** 再次启动，**Then** 恢复到上次的尺寸与位置（显示器配置变化时退化为默认值，不崩溃）。
4. **Given** 主进程或渲染进程崩溃，**When** 恢复，**Then** 崩溃被记录进日志，渲染进程崩溃自动重载；主进程崩溃后重启能正常起来。

---

### User Story 5 - 可配置与可访问 (Priority: P2)

用户可在设置页调整主题（浅/深/跟随系统）、语言、日志级别、更新通道、数据根位置，并可用键盘完成主要操作。

**Why this priority**: 主题与快捷键是长期维护成本的分水岭——现在不统一，每个插件都会各写一套。

**Independent Test**: 切换主题后所有界面（含插件贡献的界面）一致变色；快捷键可达主要命令。

**Acceptance Scenarios**:

1. **Given** 选择"深色/浅色/跟随系统"，**When** 切换，**Then** 宿主与所有插件贡献界面同步更新，**无**局部仍是旧主题。
2. **Given** 插件注册了设置分区，**When** 打开设置页，**Then** 该分区出现；插件卸载后分区隐藏但**保留**其已存配置。
3. **Given** 插件注册了命令，**When** 打开命令面板/快捷键表，**Then** 可发现、可绑定、可执行。
4. **Given** 仅用键盘，**When** 操作，**Then** 主要路径（导航、发送、对话框、设置）全部可达。

---

### User Story 6 - 插件能接入统一机制 (Priority: P2)

插件作者能通过**公开契约**写日志、取主题、调 Server wire 方法、注册设置分区、注册命令、查询 Harness 可用性——**不**需要 import 宿主内部、**不**需要自己造一套。

**Why this priority**: constitution 第 1/3 条"领域独立、机制共享""契约先行"。不提供统一机制，插件就会各造一套，边界必然被打破。

**Independent Test**: 用一个受控第三方 fixture 插件，仅通过公开 API 完成上述六件事，且边界测试证明它无法 import 宿主内部。

**Acceptance Scenarios**:

1. **Given** 受控第三方插件只依赖公开契约，**When** 写日志/取主题/调 wire/注册设置/注册命令/查可用性，**Then** 全部成功，且该插件源码零宿主内部 import。
2. **Given** 插件调用 wire 口，**When** 未授权/缺席/失败，**Then** 返回类型化结果（Accepted/Refused/Unknown），**不**静默回退、**不**抛裸异常。
3. **Given** 某机制的宿主未就绪，**When** 插件调用，**Then** 明确返回"缺席/未就绪"，**不**假装成功。

---

### User Story 7 - 卸载干净 (Priority: P3)

用户卸载后不留残渣，且**不会**误删用户数据。

**Why this priority**: deb 的基本契约；错误删除用户数据是不可接受的。

**Independent Test**: 装 → 产生数据 → 卸载 → 检查文件系统与数据根。

**Acceptance Scenarios**:

1. **Given** 已安装且有用户数据，**When** `sudo apt remove ordessa`，**Then** 程序文件移除，`~/.ordessa` **保留不动**。
2. **Given** 用户希望连数据一起删，**When** `sudo apt purge ordessa`，**Then** 移除系统级文件；用户级数据仍**不**自动删除（须用户手动或应用内显式选择），并在提示中说明。

---

### Edge Cases

- 端口被占用 / 随机端口分配失败：必须给出可操作错误，不得退化为"固定端口硬试"。
- 数据根被另一实例锁住：必须识别为"已有实例在运行"，而不是报磁盘错误。
- 更新源返回被篡改的 manifest（哈希不符）：必须拒绝安装并保留旧版本。
- 更新安装到一半断电：必须仍可启动（旧版本完整或新版本完整），不得出现半套文件。
- 磁盘满导致日志/备份写失败：不得影响主流程；主流程失败时不得因日志失败而丢原始错误原因（清理异常不覆盖主因，constitution 第 2 条）。
- 无任何 Harness 可用（Pi/Codex/Claude 均未安装）：必须诚实显示"不可用 + 原因"，不得显示空白或假装有连接。
- 显示器配置变化导致窗口位置越界：退化为默认尺寸位置，不得崩溃或开在屏幕外。
- 运行时捆绑缺失（Python/桥二进制被误删）：必须在启动早期类型化拒绝并指名缺失物，不得进入半可用状态。

---

## Requirements *(mandatory)*

### Functional Requirements

**产品身份（R-ID）**

- **FR-001**: 系统 MUST 具备完整产品元数据：`productName`、`description`、`author`、`license`、`homepage`、版本号，且版本号有**单一来源**并注入构建产物。
- **FR-002**: 系统 MUST 从**单一事实位置**取用应用图标并导出多尺寸（≥ 16/32/48/64/128/256 px，含 `.png` 与 Linux hicolor 安装布局），且 deb 安装后在桌面环境可见。图标**设计稿由用户后续提供**；占位期间应用 MUST 可构建、可运行（内置占位图 + 缺图不阻塞），换上真图后**不**改代码。
- **FR-003**: 系统 MUST 提供"关于"面板，显示应用版本、构建号、各插件版本、第三方许可证与许可证全文入口。
- **FR-004**: 系统 MUST 在安装后注册 Linux 桌面条目（`.desktop`）与图标，应用名与图标一致。

**日志（R-LOG）**

- **FR-010**: 系统 MUST 提供统一日志机制：级别（debug/info/warn/error）、命名 scope、文件落盘、按大小轮转、有限保留份数。
- **FR-011**: 日志 MUST 统一脱敏：令牌、凭据、`secrets/` 内容**永不**进入日志；脱敏在 sink 层强制，不依赖调用方自觉。
- **FR-012**: 插件 MUST 能通过**公开契约**写日志，并与宿主日志同目录、同格式、同时间线。**（→ 向 plugin 暴露）**
- **FR-013**: Server（Python）与 Desktop（TS）两侧日志 MUST 采用同一格式与同一数据根位置规范。**（契约对齐，实现各自）**
- **FR-014**: 日志文件位置 MUST 位于数据根下且可被诊断导出收集。

**运行时与生命周期（R-LIFE）**

- **FR-020**: 系统 MUST 解析默认数据根 `~/.ordessa`，安全创建（0700）、复用、拒绝符号链接与不可写路径，并保留显式覆盖入口。
- **FR-021**: 默认数据根规范 MUST 有**唯一明文定义**，Server CLI 与 Desktop 宿主共同遵守，并有一致性测试。（交接文档要求"两入口须有同一个明文规范"）
- **FR-022**: Desktop 宿主 MUST 拥有它启动的 Server 进程的完整生命周期：启动、就绪探测、失败诊断、退出时**只**终止自己启动的进程。
- **FR-023**: Server MUST 绑定随机 loopback 端口，宿主取得**实际** origin；不得要求用户填写端口，也不得假定固定端口。
- **FR-024**: 就绪 MUST 由明确探针判定；超时/失败 MUST 进入故障 UI，**不**空白、**不**假绿。
- **FR-025**: 系统 MUST 保证单实例（第二次启动聚焦既有窗口），并持有数据根锁以识别并发。
- **FR-026**: 退出 MUST 有统一清理点（`before-quit`）：停止子进程、释放锁、flush 日志；清理异常**不**覆盖主因。
- **FR-027**: 窗口尺寸与位置 MUST 被记忆并在下次启动恢复；显示器配置变化时 MUST 退化为默认值。
- **FR-028**: 渲染进程崩溃 MUST 被记录并自动重载；主进程崩溃 MUST 落盘记录，且下次启动可正常进行。

**wire 与插件接缝（R-SEAM）**

- **FR-030**: 宿主 MUST 向插件暴露 wire 传输口（`POST /wire/v1/{method}` + Bearer），使插件无需自持令牌、无需自建传输。**（→ 向 plugin 暴露）**
- **FR-031**: 令牌 MUST 只在主进程/Server 侧持有；渲染进程与插件**不**得接触令牌字节。
- **FR-032**: wire 调用 MUST 返回类型化结果（Accepted/Refused/Unknown），失败**不**静默回退。
- **FR-033**: 只接受 loopback；渲染进程沙箱 MUST 保持开启（已达标，须回归不退化）。

**设置、命令、主题（R-UX）**

- **FR-040**: 系统 MUST 提供应用级设置页，至少含：数据根位置（只读展示 + 打开目录）、日志级别、更新通道、主题、语言、关于。
- **FR-041**: 插件 MUST 能注册设置分区；卸载后分区隐藏但**保留**已存配置，未知片段**不**下发。**（→ 向 plugin 暴露）**
- **FR-042**: 系统 MUST 提供统一主题机制（浅/深/跟随系统），宿主与全部插件贡献界面一致生效。**（→ 向 plugin 暴露）**
- **FR-043**: 系统 MUST 提供命令注册与快捷键绑定机制，命令可被发现、绑定、执行。**（→ 向 plugin 暴露）**
- **FR-044**: 主要操作路径 MUST 键盘可达。

**Harness 可用性（R-AVAIL）**

- **FR-050**: 系统 MUST 显示每个 Harness 的真实可用性：已安装 / 未安装 / 未登录 / 适配失败，并给**原因**，不得空白或假绿。
- **FR-051**: 可用性判定与品牌差异 MUST 由 Harness 插件提供，宿主只消费结果，不内置品牌逻辑。**（→ 向 plugin 暴露）**

**诊断（R-DIAG）**

- **FR-060**: 系统 MUST 提供一键诊断导出：应用版本与构建号、产品清单及其哈希、环境信息、全部日志、数据根状态。
- **FR-061**: 诊断包 MUST **不含**任何令牌/凭据字节。
- **FR-062**: 插件 MUST 能**可选**贡献诊断片段。**（→ 向 plugin 暴露，可选）**

**发行物（R-PKG）**

- **FR-070**: 系统 MUST 产出 Ubuntu/Linux x64 的 `.deb`，安装后可直接启动，**不**依赖 Node/Go/仓库 `.venv`/开发机器 PATH。
- **FR-071**: deb MUST 捆绑固定版本的 Desktop、Python 运行时、Server 依赖、ACP 桥与许可证资料；Harness 运行时**仅捆绑 core 与默认装配实际需要的组件**，品牌制品（尤其再分发条件未确认的 Claude）**不**作为 core 打包前置，留给后续插件发行线。
- **FR-072**: 正式发行 **MUST NOT** 使用 `--no-sandbox`（开发脚本遗留）。
- **FR-073**: deb MUST 声明正确的包依赖与安装路径，提供 `postinst`/`prerm`/`postrm`。
- **FR-074**: 系统 MUST 提供应用内一键更新：检查（需用户确认）→ 下载 → 校验（SHA-256 + 签名）→ 备份 → polkit 提权安装 → 重启。
- **FR-075**: 更新源不可达 MUST 报错，**不**静默当作"已是最新"。
- **FR-076**: 更新安装失败/中断 MUST **可检测、可修复、数据不丢**：下次启动能识别未完成更新、恢复到可启动状态、数据根未损坏、备份保留。（**不**假定安装原子）
- **FR-077**: 更新前 MUST 备份数据根与版本信息，更新后 MUST 做数据兼容检查；不兼容 MUST 明确失败并保留备份。
- **FR-078**: 系统 MUST 聚合第三方许可证（全局 `THIRD-PARTY-NOTICES`），并在关于面板可达。
- **FR-079**: 发行产物 MUST 有可校验的哈希清单；扩展层沿用 `extensions.lock.json` 逐文件哈希。
- **FR-080**: 卸载 MUST 移除程序文件并**保留**用户数据；`purge` 亦**不**自动删除 `~/.ordessa`。

**明确不在本期（deferred）**

- 首次启动引导 onboarding（用户裁定"不着急"）。
- 三品牌（Pi/Codex/Claude Code）真实可用性验收与真实模型调用。
- i18n 完整本地化（本期仅留语言设置项与字符串抽取纪律，不交付翻译）。
- Windows/macOS 发行物、SBOM、深链、遥测、自动崩溃上报上传。

### Key Entities

| 实体 | 含义 | 关键属性 | 归属 |
| --- | --- | --- | --- |
| **DataRoot** | 用户级数据根 | 路径、权限、锁、`secrets/http-token`、`logs/`、`backups/` | 宿主定义规范（C-01），Server 使用 |
| **ServerInstance** | 一次 Server 进程 | origin(loopback)、token locator、pid、就绪状态 | Desktop 宿主所有（C-02） |
| **LogRecord** | 一条日志 | ts、level、scope、msg、redacted 字段 | 宿主所有（C-04） |
| **ProductManifest** | 产品装配清单 | enabled 扩展 id、逐文件哈希 | `products/desktop`（既有） |
| **UpdateManifest** | 更新源清单 | 版本、通道、deb URL、SHA-256、签名、变更说明 | 发行侧（C-09） |
| **DiagnosticBundle** | 诊断导出 | 版本、构建号、清单哈希、环境、日志、数据根状态 | 宿主（C-06） |
| **HarnessAvailability** | Harness 可用性 | brand、state(installed/loggedIn/unavailable/failed)、reason | Harness 插件（C-08） |

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

| ID | 可度量结果 | 对应发行门 |
| --- | --- | --- |
| **SC-001** | 干净 Ubuntu 机器上，从 `apt install` 到界面可用**不超过 3 步**（安装 → 点图标 → 可用），全程零终端命令、零手填。 | F1 |
| **SC-002** | 启动全链（安装包启动 → Server 就绪 → 界面可继续）**≤ 15 秒**（干净机器、冷启动、p95）。 | F1 |
| **SC-003** | 5 类故障（无目录、端口冲突、缺随包二进制、数据根被锁/不可写、更新源不可达）**100%** 显示可操作错误，**0 次**空白窗口或假绿。 | F1/F4 |
| **SC-004** | 插件日志与宿主日志 **100%** 落在同一日志目录、格式一致；令牌/凭据落盘次数 **= 0**。 | F4 |
| **SC-005** | 一键更新全链（检查→下载→校验→备份→安装→重启→历史仍在）**100%** 通过；篡改包 **100%** 被拒；中断后 **100%** 仍可启动。 | F5 |
| **SC-006** | deb 在**无 Node/Go/仓库 .venv/开发 PATH** 的干净机器上 **100%** 可启动；重装/升级后仍 **100%** 可启动。 | F5 |
| **SC-007** | 受控第三方 fixture 插件仅凭公开契约完成 6 项接入（日志/主题/wire/设置/命令/可用性），宿主内部 import 数 **= 0**。 | 契约边界 |
| **SC-008** | 正式发行启动命令中 `--no-sandbox` 出现次数 **= 0**；renderer 沙箱、contextIsolation、nodeIntegration 保持 `true/true/false`。 | F4 |
| **SC-009** | 诊断包生成 **≤ 5 秒**，令牌字节命中数 **= 0**，含全部必需段。 | F1 |
| **SC-010** | 既有测试红账本逐 ID **不变**（Harness 2 条、Server 67 条、acp_orchestration 18 条继承红），新增红数 **= 0**。 | 证据不假绿 |

---

## Assumptions

1. 目标平台限定 **Ubuntu/Linux x64**；其他系统不在本期（与 handoff 首版边界一致）。
2. deb 的"一键更新"通过**下载新版 deb + polkit 提权安装**实现，不依赖 apt 源（用户无自建仓库的前提）。若后续建 apt 源，本期逻辑可复用（校验/备份/重启不变）。
3. 更新源为**静态 HTTPS 清单 + deb 文件**，本期只实现客户端；服务端托管不在本期。
4. Python 运行时采用固定版本的独立发行物随包捆绑（不用系统 Python），以满足 F5"无开发机器依赖"。
5. Harness 运行时**仅捆绑 core 与默认装配实际需要的组件**；品牌制品（Pi/Codex/Claude）留给后续插件发行线，**不**作为本期打包前置，也不负责品牌可用性验收。
6. 图标的**单一事实位置**定为 `assets/brand/icon.svg`（矢量源）。**设计稿由用户后续提供并替换**；P-A/P-C 只做消费与导出接线，占位期间不阻塞，换图不改代码。
7. 现有安全基线（`sandbox: true` / `contextIsolation: true` / `nodeIntegration: false` / 权限全拒 / window-open deny / IPC 调用方校验）**已达标**，本期只做回归不退化。
8. `apps/desktop/electron/main.ts` 内嵌约 200 行 smoke 驱动代码，须在本期拆出到 `scripts/`，否则会进入发行物。
9. 子代理实施**不操作 git**（constitution：主会话管 git 检查点）；各实施包在独立 worktree 中工作，不共写文件。
