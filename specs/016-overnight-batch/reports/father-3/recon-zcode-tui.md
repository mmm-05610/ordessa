# ZCode（TUI/CLI）配置面侦察

查询日期：2026-09-29。信任阶梯依 `docs/design/information-recon-priority.md`：
**L1**＝本机钉定事实（安装树、CLI `--help`/`--version` 原文、随装官方 zcode-guide@0.3.0
文档，路径可复现）；**L2**＝官方仓库 `github.com/zai-org/ZCode` README（release
`aeaed5ddce1348e8337374e217afcf08c54c83af`，页面标注 v3.14.3、更新 2026-9-23，抓取
2026-09-29）；L4/L6＝搜索线索，仅作待核指向。"有"表示所引证据有明确入口，不表示
Ordessa 已适配；未写热更新的项目一律视为**生效方式未核定**；`待核`表示证据不足，
不表示不支持。遵守 harness-configuration/README.md 精度边界：**不把 CLI/TUI 功能
推定成协议（ACP/stdio server）能力**。

## 0. 对象与版本口径

- 本机安装（L1）：`/usr/bin/zcode` → `/etc/alternatives/zcode` → `/opt/ZCode/zcode`
  （ELF 64-bit）；`/opt/ZCode/` 为 Electron 桌面壳（chrome-sandbox、app.asar、
  LICENSE.electron.txt）。内嵌 Agent CLI：`/opt/ZCode/resources/glm/zcode.cjs`，
  `--version` → **zcode 0.16.9**。
- 官方仓库（L2）：Z.ai 官方 monorepo，含 desktop（Electron 桌面）、web、server
  （HTTP/WS）、zcode-server-cli、ui、services、shared/rpc/client、provider(-node)、
  **apps/zcode-cli（Agent CLI、TUI、运行时与工具）**。统一 `zcode` 启动器：无参→
  TUI；`--web`→Web；其余参数→Agent CLI；三形态同一分发、无需 Electron。
- **版本映射缺口（待核）**：本机 CLI 版本线 0.16.9 与仓库应用发行线 v3.14.x 是两条
  版本线，对应关系本轮未核实。涉及版本敏感结论时两条线分别登记，不互相推定。
- 侦察定位：ZCode 属品牌优先级裁决中的"新品牌仅侦察"档，本轮只盘点，不设计实施。

## 1. 入口（证据级 L1）

CLI 命令面（`node /opt/ZCode/resources/glm/zcode.cjs --help` 原文，2026-09-29）：
无命令→全屏 TUI（默认面）；`app-server`（**Run the ZCode Protocol stdio app
server**）；`commands list`（自定义斜杠命令）；`doctor`；`login`/`logout`（Z.AI
OAuth）；`plugins list|install|uninstall|enable|disable|update|validate|marketplace`；
`skills list`；`tui`；`version`。选项面：`-p/--prompt`（headless 单 prompt）、
`--json`、`--mode build|edit|plan|yolo`（**--prompt 默认 yolo**）、`--resume
<sess_…>`、`-c/--continue`、`--target/--target-replace`（会话目标）、`--attach`、
`--cwd`、`--locale en-US|zh-CN|auto`、`--surface terminal|desktop`、
`--disallowed-tools`、`--browser-use headless`、`--browser-executable`、
`--memory-bench`、`--force-mcs`。

桌面侧（L1，仅结构未读用户数据）：`~/.zcode/v2/setting.json`（40 键桌面偏好：
enabledBuiltinAgentCliProviders、computerUseComposerEntryHidden、webRemoteControl*、
embeddedBrowser*、memoryEnabled、locale 等）与 `v2/` 下 agents-state、bot-config.v3、
credentials、provider_config、onboarding-record、runtime、certs、crash。桌面壳配置
`/opt/ZCode/resources/config/default.json`（feedback zhipu-ai.feishu.cn、Discord
社区）——Zhipu/Z.ai 身份（L1）。**setting.json 是桌面偏好面，不是 CLI 配置本体**，
不得整体当 Profile 模板。

## 2. 配置面（随装官方 zcode-guide@0.3.0 文档，L1；目录实测 L1）

| 面 | 已核到的配置入口/能力 | 应如何解释 |
| --- | --- | --- |
| 配置根 | 用户 `~/.zcode/cli/config.json`；工作区 `<repo>/.zcode/config.json`（或 `zcode.json`） | 两级作用域；工作区文件可入库共享。是否热读取**未核定** |
| 指令 | `~/.zcode/AGENTS.md` ＋ `<repo>/AGENTS.md`（自 cwd 向上找到项目根） | 用户先注入、工作区后注入可收窄/覆盖宽泛默认；`/init` 只写工作区文件；onboarding 可从 `~/.claude/CLAUDE.md` 迁移 |
| Skill | 目录+`SKILL.md`：`~/.zcode/skills/`、`~/.agents/skills/`、`<repo>/.zcode/skills/`（cwd 逐级）、`<repo>/.agents/skills/`、插件 roots；另有显式配置 roots | 发现序：显式 > 用户 .zcode > 用户 .agents > 工作区（逐级，深层优先）> 插件（最低）；身份是文件路径，同名只载第一个，其余被遮蔽 |
| 命令 | `.md` 文件，作用域与发现序同 Skill | 按规范化命令名去重、首者胜；嵌套目录冒号命名（`review/code.md` → `/review:code`） |
| MCP | `.zcode/config.json` → `mcp.servers`（fallback `.agents/mcp.json` → `mcpServers`） | 同名覆盖序 **CLI → env → user → workspace → system defaults**；插件自带 server 构成基底层 |
| Hooks | config 内 `hooks` 对象；事件恰七个：SessionStart、UserPromptSubmit、PreToolUse、PermissionRequest、PostToolUse、PostToolUseFailure、Stop | 配置文件 hooks 须 `hooks.enabled: true` 才运行（默认禁用）；任一插件贡献 hook 则 runner 自动启用——双轨启用语义 |
| 原生插件 | `.zcode-plugin/plugin.json`（兼容名 `.claude-plugin/`、`.codex-plugin/` 也认）；组件字段 `commands/skills/hooks/mcpServers/agents`；市场来源 GitHub repo/Git URL/本地目录/文件 | 最小 manifest 仅 `name`（`^[a-z0-9][a-z0-9._-]{0,127}$`）；**`channels/lspServers/outputStyles/settings` 记录但不执行**；内置插件可禁用不可卸载；启用态存 `~/.zcode/cli/config.json` 的 `plugins` |
| 模型/供应商 | CLI 侧配置键本轮**未核到**（`provider_config.json` 在桌面 v2/ 侧）；会话选择经 OAuth login | 模型目录与选择分离判定不成立前不得写适配；`待核` |
| 会话 | `--resume <sess_…>`、`-c` 续最近会话、`--target` 会话目标；会话持久化内建 | 会话身份（sess_ id）稳定可引用；存储位置本轮未核 |
| 工具裁剪 | `--disallowed-tools`：仅本次 prompt/TUI 运行生效，"saved settings are unchanged"；帮助明言 `"Bash(git *)"` 等价移除整个 Bash、**不做命令级模式匹配** | 与 Ordessa"会话临时覆盖不反写全局"语义同构；但**无命令粒度**，适配时不得假称有 |
| 权限 | `--mode build|edit|plan|yolo`；**headless `--prompt` 默认 yolo** | 包装器红旗位：headless 调用必须显式降 mode，否则默认无监督执行 |
| 运营/显示 | `--locale`、`--surface terminal|desktop`、`doctor` 自检、`--memory-bench`（Memory 功能）、`--force-mcs`（Anthropic 系投影开关） | 多为运行期开关；`--surface` 说明同一 CLI 可被桌面宿主嵌入 |

## 3. 通道（研究判定）

- **headless 机器面（L1）**：`-p/--prompt` ＋ `--json`；stdout 机器可读。同型
  headless 通道已有夜批实操（`specs/016-overnight-batch/bin/run-qoder.sh`、
  `run-review.sh`，分别封装 qoder 与 pi 的 `-p` 调用）。
- **stdio 协议面（L1）**：`app-server`——官方名"**ZCode Protocol** stdio app
  server"。协议名非 ACP；报文语义、能力协商、会话/配置变更通道**全部待核**。按
  精度边界：TUI/CLI 现有功能（如 `/model`、Settings 面板）不得推定为该协议能力。
- **RPC/Web（L2）**：仓库 server（HTTP/WS）＋ `--web` 模式、`ZCODE_SERVER_AUTH_TOKEN`
  鉴权、`ZCODE_DATA_BASE_DIR` 数据根重定向（L2，README）。与 Ordessa server 的
  对接形态待核。
- **ACP**：两轮证据（CLI help、README 可见部分）均**未见 ACP 字样**→"ACP 通道
  存在"不成立，登记为未证实，不是否定。

## 4. License 与安装（L2/L4）

仓库元数据口径 Apache-2.0；README 指向 NOTICE.md，原文本轮未直读（raw 抓取被限流）
——**待核**。安装：官方 `install.sh`（`ZCODE_DIST_BASE_URL`）→ `~/.zcode/runtime`，
bin 入 `~/.local/bin`；工具链 Node 24.14.0 / pnpm 10.33.2（mise.toml）（L2）。复用
前必须完成许可证原文核验与 pin（信息路径硬规则）。

## 5. 安全面（L1 证据 → 风险注记）

1. **MCP 全作用域自动连接**：user/workspace/plugin/env/CLI 全部"trusted and
   connected automatically at session start"（官方文档自述；工作区作用域曾需手动
   授权、现默认自动）。打开项目即连接其声明的 server——Ordessa 侧若适配，信任
   边界前移必须在 adapter 层显式收口。
2. **headless 默认 yolo**：`--prompt` 无显式 `--mode` 即无监督执行。
3. 工作区 `AGENTS.md` 自动向上发现＋自动注入：项目指令注入面。
4. 插件 manifest 兼容 `.claude-plugin/`/`.codex-plugin/`：跨生态装载面宽，加载即
   执行贡献组件（hooks/mcpServers/agents）。
5. 对冲证据：配置文件 hooks 默认禁用（须 `hooks.enabled:true`）；`--disallowed-tools`
   提供运行期工具裁剪。

## 6. 缺口清单（全部待核）

1. CLI 版本线 0.16.9 ↔ 仓库 v3.14.x 映射；本机安装对应的仓库 commit。
2. `app-server` 的 ZCode Protocol 报文面（能力协商/会话/配置变更/工具事件）。
3. CLI 侧模型/provider 配置键（用户级如何配自选 endpoint；`ZCODE_BUILTIN_PROVIDER_CONFIG_FILE` 的作用域）。
4. `~/.zcode/cli/config.json` 的完整 schema 与热/冷读取语义（生效方式未核定）。
5. LICENSE/NOTICE.md 原文；L1 安装发行条款是否与仓库一致。
6. 会话存储格式/位置；`--resume` 跨版本兼容性。
7. Skills/Commands/MCP 变更后的生效时点（重启 or 热载）——TUI 内有 `/reload` 类
   机制与否未核。

## 7. 方法自检

- 证据面：L1（安装树＋CLI help＋随装官方文档）、L2（官方仓库 README @release）、
  L4/L6（版本动向、AICoder/GLM Coding Plan 线索，仅指向待核，未写入事实）。
- 双源交叉：配置面结论以随装官方文档（L1）为主、目录实测（L1）与 CLI help（L1）
  交叉；仓库结构为 L2 单源、已标注。
- 覆盖度：按"配置入口 → 扩展面 → 通道 → license → 安全面"顺序；§6 缺口如实列
  7 项，不冒充穷尽。
