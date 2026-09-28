# Tasks — Ordessa Desktop 产品化

日期：2026-09-28。状态：待实施。任务按**实施包**分组，ID 前缀 `PA-`/`PB-`/`PC-` 对应 [plan.md](plan.md) 的三个包。

**状态记法**：`[ ]` 未做　`[~]` 部分（写清两侧）　`[x]` 完成并留有证据（SHA + 文件 + 命令 + 真实退出码）　`[!]` 阻塞（指名 owner + 缺口）

**通用要求**（每条任务都适用）：契约见 [contracts/](contracts/README.md)；正例 + 反例**先红后绿**留档；涉密钥处留金丝雀；不改契约；不操作 git；红账本逐 ID 不得变。

---

## P-A — Desktop 宿主与平台 UI

> 写入面：`apps/desktop/**`、`packages/desktop-platform/{contracts,ui,ui-components,extension-api,extension-loader,extension-host,native-bridge}/**`、`packages/workbench/**`
> 插件改动：**无**（013 = core 阶段，`plugins/**` 一律只读；确需改须先经用户裁定）

### 阶段 1 — 契约类型与产品身份
- [ ] **PA-01** 在 `packages/desktop-platform/contracts` 落 C-03/04/05/06/07/08 的 TS 类型（不可变 + 类型反例 `@ts-expect-error` 全部真实触发）。FR-030/041/042/043/051
- [ ] **PA-02** 产品元数据：`apps/desktop/package.json` 补 `productName/description/author/license/homepage/repository`；版本号单一来源 + 构建号注入机制。FR-001
- [ ] **PA-03** 应用图标**接线**：从单一事实位置 `assets/brand/icon.svg` 消费，导出多尺寸（16/32/48/64/128/256）`png` + Linux hicolor 布局 + 窗口图标接入。FR-002　**注**：设计稿由**用户后续提供**；占位期间须可构建可运行（内置占位 + 缺图不阻塞），换图**不**改代码
- [ ] **PA-04** 关于面板：应用版本、构建号、各插件版本、第三方许可证入口、许可证全文入口。FR-003

### 阶段 2 — 日志与可靠性
- [ ] **PA-05** 日志 TS sink（C-04）：级别/scope/child、JSON Lines、10 MiB 轮转保留 5、**sink 层强制脱敏**（字段名 + 哨兵 + 路径 + basename 四规则）。FR-010/011/012/014
- [ ] **PA-06** 日志金丝雀：注入已知令牌字节（字段名、换名值、消息正文三路）→ 文件**零命中**。FR-011
- [ ] **PA-07** 单实例锁 + 二次启动聚焦既有窗口；数据根锁语义接入（C-01 `DATA_ROOT_LOCKED`）。FR-025
- [ ] **PA-08** `before-quit` 统一清理：停子进程、释放锁、flush 日志；**清理异常不覆盖主因**。FR-026
- [ ] **PA-09** 窗口状态记忆与恢复；显示器配置变化退化为默认值。FR-027
- [ ] **PA-10** 崩溃恢复：渲染进程崩溃记录 + 自动重载；主进程崩溃落盘；重启可正常启动。FR-028
- [ ] **PA-11** **代码卫生**：把 `apps/desktop/electron/main.ts` 内嵌的 smoke 驱动代码（约 200 行 `executeJavaScript`）拆到 `apps/desktop/scripts/`，发行物内**零**测试驱动代码。

### 阶段 3 — 故障 UI / 设置 / 诊断
- [ ] **PA-12** 故障 UI（C-06 §C）：`reason + remedy + logRef + 导出诊断`；5 类故障各一条反例，**零**空白窗口。FR-024
- [ ] **PA-13** 设置页（C-06 §A2）：通用/数据/日志/更新/关于五区；数据根只读展示 + 打开目录；**「更新」分区接线 P-C 的更新客户端入口**（检查更新 / 下载进度 / 失败原因 / 更新后重启；责任划分见 plan.md §跨包集成归属）。FR-040
- [ ] **PA-14** 设置分区贡献点（C-06 §A1）：注册/注销/排序/卸载隐藏但保留配置/未知片段不下发。FR-041
- [ ] **PA-15** 诊断导出（C-06 §B）：五段内容 + 插件可选片段 + 超时兜底；**≤ 5 秒**；令牌零命中。FR-060/061/062

### 阶段 4 — 主题 / 命令
- [ ] **PA-16** 主题服务（C-05）：light/dark/system + tokens + subscribe + CSS 变量；tokens 深层冻结。FR-042
- [ ] **PA-17** 收敛 `packages/workbench/src/styles.ts` 为 C-05 消费方 + 对照测试。FR-042
- [ ] **PA-18** 主题收敛**登记缺口**：`packages/workbench` 收敛为 C-05 消费方；`plugins/chat/frontend/src/theme.ts` **本期不改**，登记为已知缺口（chat 界面暂不随全局主题切换）。FR-042
- [ ] **PA-19** 命令与快捷键（C-07）：注册/注销/冲突拒绝/非法拒绝/`when` 求值/命令面板/快捷键表。FR-043
- [ ] **PA-20** 键盘可达全流程（导航/发送/对话框/设置/命令面板/错误关闭）。FR-044

### 阶段 5 — 接线与边界
- [ ] **PA-21** 消费 C-01/C-02/C-03：接入 `@ordessa/server-bridge`（P-B 提供）；P-B 未就绪时用**受控 fixture** 开发与测试，登记切换点。FR-020/022/030
- [ ] **PA-22** WirePort 宿主侧注入：插件可调、令牌不进渲染进程、三态语义。FR-030/031/032
- [ ] **PA-23** 安全回归：`sandbox:true / contextIsolation:true / nodeIntegration:false / 权限全拒 / window-open deny / IPC 调用方校验` **不退化**。FR-033
- [ ] **PA-24** 边界反例：受控第三方 fixture 插件仅凭公开契约完成 6 项接入，宿主内部 import 数 **= 0**。SC-007
- [ ] **PA-25** C-08 缺席语义与渲染（core，**不改插件**）：无提供者时显示"未提供 Harness 可用性信息"；用**受控 fixture 提供者**验证 6 态渲染与 `state/reason` 不变量、有界探测；**宿主源码出现品牌名即判红**。FR-050/051

---

## P-B — Server 运行时与接缝

> 写入面：`apps/server/**`、`packages/server-plugin-api/**`、`packages/desktop-platform/server-bridge/**`（**不含任何 `plugins/**`**）

### 阶段 1 — 数据根（C-01）
- [ ] **PB-01** `apps/server/src/ordessa_server/bootstrap/data_root.py`：解析顺序（env → `~/.ordessa`）、创建/复用、0700/0600、拒符号链接、拒不可写、锁语义。FR-020
- [ ] **PB-02** 类型化错误五件（`DATA_ROOT_SYMLINK/NOT_WRITABLE/LOCKED/INVALID/MIGRATION_REFUSED`）+ `reason`/`remedy`。C-01 §6
- [ ] **PB-03** `__main__.py`：`--data-root` 改 optional（缺省走规范）、`--port` 支持随机（`0` = 系统分配）并**回读实际 origin**。FR-021/023
- [ ] **PB-04** 常量文件（布局路径）供 TS/Python 共用；**跨语言一致性测试**（两入口解析结果与布局常量逐字相同）。FR-021
- [ ] **PB-05** 旧根/升级 preflight 保持：无迁移提供者**拒绝并保留原字节**。C-01 §4
- [ ] **PB-06** headless CLI 核查：若支持缺省数据根 → 与 Server CLI 共用同一规范 + 一致性测试。FR-021

### 阶段 2 — 生命周期与接缝（C-02/C-03）
- [ ] **PB-07** `packages/desktop-platform/server-bridge`（新包）：spawn / 就绪探针（`GET /live`）/ 状态机 / 退出只杀自己 pid（进程组 + 孤儿防护）。FR-022/024
- [ ] **PB-08** env 交接：`ORDESSA_SERVER_ORIGIN` / `ORDESSA_SERVER_TOKEN_FILE` / `ORDESSA_DATA_ROOT`，命名**保持既有拼写**。C-02 §2
- [ ] **PB-09** 运行时捆绑解析（`ORDESSA_BUNDLED_ROOT` → `/opt/ordessa/{python,bin,harnesses}`）；缺失**早期**类型化拒绝 `BUNDLED_RUNTIME_MISSING`。C-02 §6
- [ ] **PB-10** C-02 五类错误 + 反例七条（端口/缺二进制/早退/超时/只杀自己/二次启动/金丝雀）。C-02 §7-8
- [ ] **PB-11** WirePort 实现（C-03）：`POST /wire/v1/{method}` + Bearer 注入、三态、`AbsentWirePort`、`ready/scope`。FR-030/032
- [ ] **PB-12** 凭据边界：令牌只在主进程/Server；插件可见对象、日志、诊断**金丝雀零命中**。FR-031

### 阶段 3 — 日志 Python 侧
- [ ] **PB-13** 日志 Python sink（C-04）：与 TS **同构**（字段顺序、脱敏四规则、轮转 10 MiB/5 份）；`server.log` 落点。FR-013
- [ ] **PB-14** 同构一致性测试：同一条记录 TS/Py 写出，字段集与顺序**一致**。C-04 §8.6

---

## P-C — 发行物：deb + 一键更新 + 捆绑

> 写入面：`packaging/**`、`scripts/**`、`tooling/**`、根 `package.json`、根 `package-lock.json`

### 阶段 1 — deb 与捆绑
- [x] **PC-01** `packaging/debian/`：control（`Depends` 只列 Electron 系统库，**不**含 nodejs/golang/python3）、postinst/prerm/postrm、copyright。FR-070/073
- [x] **PC-02** 安装布局落地（C-09 §A2）：`/opt/ordessa/{python,bin,harnesses,app,licenses}` + `.desktop` + hicolor 图标（**构建期从 `assets/brand/icon.svg` 导出**，产出 `packaging/icons/generated/`）+ `/usr/share/doc`。FR-070/071
- [x] **PC-03** 运行时捆绑：python-build-standalone 3.12.x（固定 SHA）+ `server-linux-py312.txt` 预装 + ACP 桥 + **仅 core 与默认装配实际需要的 Harness 组件**（品牌制品**不**作为打包前置，Claude 再分发条件未确认）；产出 `packaging/bundle-manifest.json`。FR-071
- [x] **PC-04** 发行启动器 `/opt/ordessa/bin/ordessa`：**禁用 `--no-sandbox`**；单条命令启动。FR-072
- [x] **PC-05** 版本/构建号注入一致性：`package.json` / 关于面板 / 诊断 `meta.json` / 更新清单四处相等。FR-001（C-09 §A4）
- [x] **PC-06** 许可证聚合：`THIRD-PARTY-NOTICES` 从各包声明构建期聚合到 `/opt/ordessa/licenses/`。FR-078
- [x] **PC-07** 产物哈希：`SHA256SUMS`（deb、bundle-manifest、app 目录树）；扩展层沿用 `extensions.lock.json`。FR-079

### 阶段 2 — 一键更新
- [x] **PC-08** `packaging/update/`：`update-manifest.json` 生成 + **Ed25519 签名**工具 + 公钥随包。C-09 §C1
- [x] **PC-09** 更新客户端流程七步（检查→下载→校验→备份→兼容→polkit 安装→重启→自检），任一步失败中止并保留旧版本。FR-074
- [x] **PC-10** 失败语义（源不可达**不**静默当最新 / **签名覆盖清单关键元数据**且任一项被改即拒绝 / 哈希不符拒绝 / 取消 polkit / **中断可检测、可修复、数据不丢**（C-09 §C4 故障门）/ 自检失败回退指引 / 数据不兼容保留备份）。FR-075/076/077
- [x] **PC-11** 更新前备份（数据根关键内容 + 版本信息 → `backups/<ts>/`）、`minDataSchema` 检查，以及 **`backups/update-state.json` 状态机**（阶段推进 / 未完成更新识别 / 恢复入口 / 数据不丢硬门）。FR-077（C-09 §C4）

### 阶段 3 — 验收
- [x] **PC-12** 卸载语义：`remove` 移除程序文件**保留** `~/.ordessa`；`purge` 亦**不**删除。FR-080
- [x] **PC-13** **干净机器验收**：无 Node/Go/仓库 `.venv`/开发 PATH 的 Ubuntu 环境安装并启动；重装/升级后仍可启动。SC-006
- [x] **PC-14** 更新全链验收：**受控更新源**发 `v_new`，走完检查→下载→校验→备份→安装→重启→历史仍在；篡改清单或包 **100%** 被拒；**中断后可检测、可修复、数据不丢**。SC-005
- [x] **PC-15** `tests/integration/` 归位：`tests/{acp-connector,acp_orchestration}` 移入并修引用；**逐 ID 与迁移前一致**。plan.md §结构

---

## 跨包集成（主会话负责，三包交付后）

- [ ] **INT-01** 三包写入面冲突核查 + 契约一致性复验
- [ ] **INT-02** 根 `package-lock.json` 统一生成（仅 P-C 提交）
- [ ] **INT-03** 全量红账本逐 ID 复验（Harness 2 / Server 67 / acp_orchestration 18），新增红 **= 0**
- [ ] **INT-04** 从**安装产物**的最小纵切实测（F1：干净 HOME → 双击 → Server 就绪 → 界面可继续）
- [ ] **INT-05** 三包报告汇总 → 更新 [plan.md](plan.md) / 本账 → 报用户审
