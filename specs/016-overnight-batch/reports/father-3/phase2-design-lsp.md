# phase2-design-lsp · LSP 域四家（hermes/opencode/dsh/kilo）扩展设计草案

016 夜批 overnight-3 · 阶段二产物（只文档不改代码）。依据：spec.md 品牌优先级
节（四家不实施转阶段二）、son-lsp 包 report（F6 两处失真已修正）、
docs/design/harness-configuration/harnesses.md（八家盘点，官方源 pin/SHA 见
source-index.json）、information-recon-priority.md 信任阶梯（L2＝官方源码/
Schema 钉 commit；L3＝官方文档带抓取日期；L5＝一手受控观测/E2 级）。
**本文件是可派单方案包草案，不是实施授权；各格"实施（待授权派单）"均以
品牌优先级裁决的显式授权为前提。**

## 1. 目标

把 `plugins/assets/lsp`（016 已建：facet `assets.lsp`、定义模型、可用性探测、
投影决策流水线）从"pi/codex/claude-code 三格诚实 unsupported"扩展到四家：
凡有原生 LSP 配置面者投影，无者诚实 unsupported，全部带探测与字节稳定决策
记录。复用红线：不重造定义模型/探测/守护形制，只增品牌 adapter 与证据账行。

## 2. 四家证据格（现状→目标）

| 品牌 | pin（harnesses.toml） | 原生 LSP 面证据（可回指） | 目标格 |
| --- | --- | --- | --- |
| hermes | 2.0 | harnesses.md :110 "扩展服务/显示：LSP、搜索、媒体后端"（官网 configuration 页，L3）；source-index hermes 条目 54 键 0 命中——**配置键级证据不足，待核** | 先侦察（L2/L3 补证 hermes LSP 配置页/配置文件形制），证得→adapter+claims；证不得→unsupported+证据（同 pi 格） |
| opencode | 2.0 | 官方 config schema `lsp`/`formatter`/`permission.lsp`（source-index opencode 条目，SHA 在案）；harnesses.md :130 | **实施（待授权派单）**：adapter 编译 server 定义/语言映射/formatter 进 opencode.json（JSONC 注意注释保留策略），claims 钉 `opencode-config` 文件目标 |
| dsh | 0.1.5-rc.1 | source-index dsh 条目 17 键 `@deepseek-ai/dsh-lsp-stdio`（command/args/env/servers/extensionToLanguage/initializationOptions/killGraceMs/maxDocumentBytes/maxMessageBytes/maxStderrBytes）；harnesses.md :152；官方 config-catalog 按包给出 source/inject | **实施（待授权派单）**：adapter 对 Cordis 装配链（bundle→profile→home→CLI patches）的 lsp-stdio 包键投影；配置整体替换语义（harnesses.md :142）→ claims 走包级 patch 而非字段级；生效方式（HMR vs 启动读取）按装配待核 |
| kilo | 7.7.2 | 官方 config schema `lsp`/`formatter`/`permission.lsp`（source-index kilo 条目）；harnesses.md :199；官方 CLI 文档要求改配置后重启 | **实施（待授权派单）**：adapter 编译进 `~/.config/kilo/kilo.jsonc`/项目 kilo.jsonc；重启生效→applyMode=restart + 会话身份恢复语义必须先证（沿用 model-provider 重启事务口径） |

## 3. 适配形制（只仿不 import）

每家 `assets.lsp.<brand>`：C2 descriptor（claims 按上表或零 claims）、
`assess/compile/verify` 纯函数（不读 HOME/spawn/网络）、探测复用
`probe.resolve_executable`（注入式 PATH）、决策记录经 `canonical_json_bytes`
golden。payload schema 只开各家原生键（闭合对象，禁 shell/path 任意写——
沿 sandbox/LSP 形制）。三家 unsupported 旧格（pi/codex/claude-code）不动。

## 4. 测试门（每家）

1. golden 转录字节稳定（定义→探测→决策，注入 PATH 正反例）；
2. 值域/形状墙：payload schema 拒未知键（平台 ContractError）；
3. 双会话隔离（Store 语义沿用）；
4. 探测缺席→unsupported 不产假配置（LSP-4 口径）；
5. 与 contracts 交叉核对：LSP 各家语义以官方文档/Schema 为准（引用逐条
   URL+日期+commit，L6 记忆不入账）。

## 5. 派工边界与待核

写入面：`plugins/assets/lsp/**` + 报告。前置取证：hermes 官方文档 LSP 页
（URL/日期/pin）；dsh 生效方式（HMR vs 启动读取）按装配取证；kilo 重启后
原生会话身份恢复取证——opencode 证据已足（schema SHA 在案）。风险：dsh 配置
"整体替换"与字段级 claims 的冲突（C2 语义需按包级 target 变通，先在
api-requests 登记与 harness 域的接缝）。产品装配（products/server 挂
`ordessa.lsp-adapters`）登记归 INT/AR（son-lsp report §5.1）；**注意** chat
域 z2 登记产品装配归 C0（CMP-chat report V08）——两域装配 owner 登记不一致，
待裁统一，派单前不得互推。
