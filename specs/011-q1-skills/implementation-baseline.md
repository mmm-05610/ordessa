# Q1 Skills v2 实施基线（T00 / T01 / T02 冻结）

冻结时间：2026-09-28（本文件所有 SHA、数字、退出码均为本树实测，非引用他树或旧文档）。
证据细则：[research/legacy-inventory.md](research/legacy-inventory.md)、
[research/brand-matrix.md](research/brand-matrix.md)、[research/seam-gaps.md](research/seam-gaps.md)。

## 1. 本线起点与输入

| 项 | 值 |
| --- | --- |
| 工作目录 | `/home/maoqh/projects/ordessa/worktrees/011-q1-skills` |
| 分支 | `codex/011-q1-skills`，起点 `96fef2db47`（= `refs/heads/codex/011-plugin-plan`） |
| 计划锚 | `specs/011-plugin-rollout/plan.md`、`contracts/checkpoints.md` |
| 旧实现来源 | commit `752f148b1b01f58c0d090e79728948127173f9fb`，`plugins/assets/`（`ordessa_assets 2.0.0a1`：`src/` 下 23 个 `.py` 源模块 + 13 测试文件 69 测试函数，0 skip） |
| 兼容面漂移核验 | `git diff 752f148b1b HEAD -- plugins/server-compat/.../assets/ core_wire.py plugin.py profiles/clone.py packages/.../agent_skill_v1.py apps/server/tests/test_asset_hubs.py` = **空**，兼容面与旧树同字节 |
| 检查点消费（2026-09-28 晚，本树实测） | foundation publication `8844c475bc`（impl `8229e20824`）→ merge `84e5c668f0`；profile-api publication `4943628f47`（impl `f5435be938`）→ merge `9048f7b79f`；chat-api-r3 publication `3d8c3fa410`（impl `a3ec20c046`）→ merge `71f926683e`；**harness-api publication `d3f026904e`（impl `61966e3118`，`dependsOn` foundation + permissions-api `bcd4387bec`）→ merge `aab8c6c4a2`**。每条均核对 `status=READY`、impl 为 publication 祖先、`planAnchorRef` 可达 `96fef2db47` 后**正常 merge**（无 rebase/强推、未读他树脏文件）。消费 harness-api 后本线接线用真实 `ConfigurationAdapter/IntentSet/Verification` 与 `harness.configuration-adapters` 贡献点（提交 `4c7d749a69`）。 |

## 2. 本树环境（含一处基线文档缺口）

- Python：`python3.12 -m venv .venv` + `pip install -r apps/server/lockfiles/server-linux-py312.txt`
  + editable 安装 `packages/pacthold`、`apps/server`、`plugins/harness[dev]`、`apps/server[dev]`、`packages/pacthold[dev]`。
  **`docs/baseline.md` 的安装行缺 `packages/server-plugin-api`**：`apps/server` 依赖
  `ordessa-server-plugin-api>=0.1.0,<1`（`apps/server/pyproject.toml:25`），该包只在仓内存在，
  按文档原样安装会 `No matching distribution found`。已在本树补装并验证 `IMPORTS OK`。
  本线不改公共 `docs/baseline.md`，已列入 [integration-request.md](integration-request.md) 请 C0 收口。
- Node：`npm ci`（root，exit 0）；`.venv/bin/python` 为唯一跑测解释符。
- 本树只用本树 venv/node_modules，未读他树未提交文件。

## 3. 冻结的基线套件数字（本树实测，逐命令真实退出码）

| 目标 | 命令 | 真实退出码 | 结果行（原文） |
| --- | --- | --- | --- |
| pacthold | `.venv/bin/python -m pytest packages/pacthold -q` | 0 | `212 passed in 2.68s` |
| plugins/harness | `.venv/bin/python -m pytest plugins/harness -q` | 1 | `2 failed, 347 passed, 3 skipped, 28 subtests passed in 5.71s` |
| apps/server | `.venv/bin/python -m pytest apps/server -q --tb=no` | 1 | `42 failed, 1092 passed, 10 skipped, 1 warning, 25 errors in 126.18s (0:02:06)` |
| Q1 本线套件 | `.venv/bin/python -m pytest plugins/assets/skills/tests -q` | 1 | `373 passed, 6 errors in 1.94s`（6 条全为 profile-api 导入缺口的集成钉，未 skip、未删断言；较上轮 +44 为 harness-api 接线与 apply-chain 新测） |
| Q1 桌面套件 | `cd plugins/assets/skills/desktop && npx vitest run` | 0 | `Test Files 9 passed (9)` / `Tests 103 passed (103)` |
| `apps/desktop` typecheck | `cd apps/desktop && npx tsc --noEmit` | 2 | 9 个 `error TS`，全部落在 `plugins/chat/frontend/**`（缺 `streamdown`/`@streamdown/cjk` 依赖），Q1 自身 TS 零诊断 |
| 根聚合套件 | `npm test`（先 `npm ci`） | 非 0 | `18/29 suites green`；红项：`typecheck`、`build:examples`、`build:app`、`workspace:plugins/chat/frontend`、`node-test:products/desktop`、6 个 `electron:*`。归因：合并进来的 `plugins/chat/frontend` 缺 `streamdown`/`@streamdown/cjk` 依赖（离线不可装）与 electron 需要显示/产物，**非 Q1 代码**（Q1 自身 vitest 9 files/103 passed 绿，`apps/desktop` tsc 的 9 个 error 全在 `plugins/chat/**`） |

对照检查点记录：foundation 自报 `apps/server 42 failed / 1092 passed / 10 skipped / 25 errors`、
`pacthold 212 passed`、Harness 两项 Pi ACP SDK lock 失败——本树把全部本地包重装齐后**逐条复现同数**，
说明 Q1 的合并与本线代码未引入新红。
踩坑记录（重要，避免他线重复）：首轮 `pip install` 未把 `plugins/harness/api`（`ordessa-harness-api`）、
`plugins/runtime-compat`、`products/server` 等本地包放进同一条命令，pip 把它们当 PyPI 依赖而整体失败，
导致 `apps/server` 假报 `78/87/95 errors`（`ModuleNotFoundError: ordessa_server_compat` 等）。
把全部本地 editable 包一条命令装齐后才是真正的合并后基线；红必须先归因到环境再记账。
合并前的旧树首次实测（时间线对照，勿与他树混用）：pacthold `238 passed`、
harness `2 failed / 308 passed / 3 skipped`、apps/server `78 errors`（未装齐所致，已作废）。
旧历史账（`specs/003-assets-skills/evidence/shared-suites-ledger.md`，环境不同不可套用）：
`HEAD: 90 failed / 670 passed / 10 skipped / 158 errors`。

**profile-api 的真实缺口（本树实测，非本线可修）**：
`plugins/profile/src/ordessa_profile/plugin.py:17` `from pacthold.resource_contracts import AgentBoxProfileV1`
在 foundation 之后 ImportError（`pacthold.resource_contracts` 模块树已搬空，符号现居
`pacthold_runtime_compat.resource_contracts.agent_box_profile_v1`）；`python -m pytest plugins/profile` 同因红。

## 4. 冻结的外部兼容标识（迁移不得改名，AGENTS.md 规则 5）

完整清单见 research/legacy-inventory.md §B.2，要点：
11 个 `assets.*` wire 方法及其参数/响应 camelCase 字段；`server_assets` /
`server_profile_assets`（迁移 12→13 建表，当前 `PRODUCT_SCHEMA_VERSION = 21`）；
`data_root/assets/` 下 `skill/<assetId>/<revision>/`、`mcp/…/server.json`、`plugin/…`、
`catalogs/<sourceId>/index.json` 布局；`sha256:` 摘要拼写与
`runtime_artifact_tree_digest`；契约 id `agent-box.skill@1` 与 `skill_target`/`skill-tree` 槽名；
错误码字符串集合。非 Skill kind（mcp/plugin/command）不归本线：`command` 在两树均无发布者
（休眠枚举），`mcp`/`plugin` 由 server-compat 持有，本线只保证不写不删其行（已由
`test_library_kind_isolation.py` 断言字节一致）。

## 5. T02 品牌矩阵冻结状态

`research/brand-matrix.md` 已按仓内证据冻结三家 pin：Codex CLI **0.147.0** +
`@agentclientprotocol/codex-acp` **1.1.14**；Claude `@agentclientprotocol/claude-agent-acp` **0.81.2**
（SDK 0.3.280；CLI 2.1.274 仅注释级观察，无机器 pin）；Pi `@automatalabs/pi-acp` **0.5.0** 内包
`pi-coding-agent` **0.84.2**（运行链 PATH 解析，无 native pin）。
可证格：pin、同 native id 的 resume、技能挂载语法、Codex skills/* 协议面为 vendored schema 声明。
**未知格**：三家原生技能发现是否真的扫描、`/reload` 类能力、显式调用路由、独立 loaded 观测、
原生命名空间优先级。运行时侧唯一现存消费者 `generic_cli.py:20-38` 的 `agent-box.skill@1` 生产者已断链，
`skill_observation.py` 零调用零测试。
本轮受控补测（T02 的「实测」半边）已执行，结果见
[research/probe-results.md](research/probe-results.md)：**14 个运行时格 + 3 个静态格**从「无证据」转为实测。
- Claude 在精确 pin（adapter 0.81.2 + SDK 0.3.280，loopback 假对端）实测：项目 `.claude/skills` 自动扫描、
  `/name` 展开可达 provider wire；`CLAUDE_CONFIG_DIR` 用户级 skills 根**默认为关**（需 `settingSources` + `skills:"all"`）。
- Codex 只能在 **0.155.0-alpha（版本错位）** 实测发现根、缺 description 静默丢弃、`forceReload`、
  `skills/config/write` 启用往返、`extraRoots/set` 触发 `skills/changed`、`perCwdExtraUserRoots` 负例；
  codex-acp 1.1.14 dist 静态实测：每 session/prompt 重同步并把 skills 作为 `available_commands_update` 发布，忽略 `skills/changed`。
- Pi 只能在 **0.86.1（版本错位）** 实测四个发现根、prompt 注入、`/skill:name` 展开、无会话内 reload；
  并且实测本仓 Pi 运行链 argv `--skill-dir/--agent-dir` 被该版本以 `Error: Unknown option` 拒绝（exit 1）。
- **仍未知**：Codex 0.147.0 与 Pi 0.84.2 的 pin 版本运行时行为（原生二进制不在本机，未联网取包）；
  三品牌在生产通路的 `loaded` 独立观测（`skill_observation.py` 零调用者、投放腿无生产者）；
  Claude 的模型自主 Skill 调用、reload 语义、插件与项目优先级。真实模型调用未授权、一次未发。
  因此 `harness_adapters/capabilities.py` 中对应格保持 `unknown`，未因错位实测而上调为 `supported`。

## 6. 本线未测/受阻面（与 report.md 同步）

1. 生产装配（G1）：`products/server` 的 `default_plugins()` 硬编码，`products/desktop` 扩展清单归 C0。
2. 真实装载链（G2）：harness-api 未发布，本线只交付 Skills 侧纯意图词汇与保守拒绝。
3. Profile 真实 facet 与会话覆盖（G3）、Profile 编辑器插槽（G6）：Z1 未发布；
   旧 `server_profile_assets` 行仅作为只读历史，迁移账未执行。
4. Chat `/`、`+` 贡献与显式调用路由（G4）：Z2 未发布；`invokeDescriptor` 三品牌均 unknown。
5. apps/server 套件与桌面 build/electron smoke、干净 wheel 装配（G21/G22）：受 §3 产物缺失阻塞。
6. 真实模型链路（L4）：本批未授权，不做。
7. T02 的 pin 版本格（Codex 0.147.0 / Pi 0.84.2）与三品牌生产通路 loaded 证据：见 §5 与 report.md §6。
