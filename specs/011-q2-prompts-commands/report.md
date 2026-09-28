# Q2 — Prompts 与命令模板：本线报告

执行者：Qoder 主代理（派单包子代理实现）＋ 两个单包域实现代理（Prompts / Command-templates）。
分支：`codex/011-q2-prompts-commands`。合并 main 与 push：**未执行，未获授权**。

状态：**IN_PROGRESS**（R0/R1 基线已完成；域实现进行中；依赖检查点全部未发布）。

---

## R0 — 冻结基线（实测，非引用）

### 起点身份

| 项 | 值 | 取证方式 |
| --- | --- | --- |
| 本线 HEAD（起点） | `96fef2db47` (`git rev-parse HEAD`)，工作树起点 `git status --short` 为空 | 实测 |
| 设计快照父提交（main） | `cd7d31f3cfba6a0e1ec65f9a13014c6b9751540b` | `git log` |
| 检查点分支 | `codex/011-{foundation,harness-api,profile-api,chat-api,permissions-api}-ready` **全部不存在**；`specs/011-plugin-rollout/checkpoints/` 目录不存在 | `git for-each-ref 'refs/heads/codex/011-*ready*'`、`ls` |
| 本树业务包现状 | `plugins/` 仅有 `agent commands connections connectors harness server-compat workbench workspace`；`plugins/assets/**`、`plugins/profile`、`plugins/chat` 均不存在 | `ls plugins/` |

结论：Profile facet、Chat scoped `addInputSource`、Harness v2 应用端口在本树**没有可导入的真实实现**；依赖它们的条目只能作精确接缝缺口登记，不得假绿。

### 工具链与环境（本树实测）

| 工具 | 本线实测版本 |
| --- | --- |
| Node / npm | v22.22.1（`docs/baseline.md` 一致）；`npm ci` → added 277 packages，exit 0 |
| Python（基线钉） | `.venv/bin/python --version` = **3.12.14**（`/home/maoqh/.local/bin/python3.12`） |
| 系统默认 `python3` | 3.14.4 —— **不是**基线钉版本，域包验证一律用本树 `.venv` |

**登记：`docs/baseline.md` 后端安装命令不完整。** 文档给出的
`pip install -e packages/pacthold -e apps/server -e 'plugins/harness[dev]' …`
在本树失败：

```text
ERROR: Could not find a version that satisfies the requirement ordessa-server-plugin-api<1,>=0.1.0
SETUP_EXIT=1 → ModuleNotFoundError: No module named 'pacthold'
```

补齐**三个**可编辑包后成功（`IMPORT_OK`，exit 0）：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r apps/server/lockfiles/server-linux-py312.txt
.venv/bin/python -m pip install -e packages/pacthold -e packages/server-plugin-api      # 文档缺
.venv/bin/python -m pip install -e apps/server -e 'plugins/harness[dev]' 'apps/server[dev]' 'packages/pacthold[dev]'
.venv/bin/python -m pip install -e plugins/server-compat -e plugins/workspace            # 文档缺
.venv/bin/python -m pip install -e products/server                                       # 文档缺
.venv/bin/python -c "import pacthold, ordessa_server, ordessa_harness, server_plugin_api"  # exit 0
```

两处可观测后果（都实测过）：

- 不装 `ordessa-server-compat` → `python -m pytest apps/server` **采集中断**：78 errors，
  `ModuleNotFoundError: No module named 'ordessa_server_compat'`。
- 不装 `ordessa-server-product`（提供 `ordessa.server_product` 装配）→ 多出 180 条红，
  主因 `SERVER_PRODUCT_MISSING: no installed product provides the 'ordessa.server_product' composition`
  与未构建的 `plugins/harness/runtime/worker-entry.mjs`。

### 权威基线（装齐产品装配后，同环境复跑）

`npm` 侧不变（typecheck/test/build 均 exit 0）。Python 侧：

| 套件 | exit | collected | passed | failed | errors | skipped |
| --- | --- | --- | --- | --- | --- | --- |
| `packages/pacthold` | 0 | 238 | 238 | 0 | 0 | 0 |
| `plugins/harness` | 1 | 313 | 308 | 2 | 0 | 3 |
| `apps/server` | 1 | 928 | 850 | 43 | 25 | 10 |

`apps/server` 现为 **43 failed / 25 errors / 10 skipped**（`qe2-evidence/q2-baseline/server-with-product.{log,xml}`，
用时 119.77s），与 `docs/baseline.md` 记载的继承红账 `…/43F/10S/25E` 同类计数一致；
首轮 90F/158E 的差值全部由上述两个未安装包造成，已按原因归类而非当作回归。

**跨道对账（同轮、同树、两个独立环境）**：prompts 域代理自行采集的 `apps/server` 红账
（`qe2-evidence/prompts/server-junit.xml`）与上面的权威红账做**逐 ID 集合差**：
`only-main = 0`、`only-prompts = 0`（各 78 条红含 skip）。两条道对“既有红”的定义一致，
后续任何差分都以这份逐 ID 清单为唯一基准。

### 受影响套件改动前红账（同环境、同轮采集）

原始全文/JUnit 与逐 ID 清单：`/home/maoqh/.local/share/qe2-evidence/q2-baseline/`
（`<suite>.log`、`<suite>.xml`、`<suite>-reds.tsv`、`exits.txt`、`baseline-summary.json`）。
命令一律为 `.venv/bin/python -m pytest <path> -q --junitxml=…`（在仓库根执行），退出码取自命令本身。

| 套件 | exit | collected | passed | failed | errors | skipped | 逐 ID 红 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `packages/pacthold` | 0 | 238 | 238 | 0 | 0 | 0 | 0 |
| `plugins/harness` | 1 | 313 | 308 | 2 | 0 | 3 | 5（2 F + 3 S） |
| `apps/server` | 非 0 | 928 | 670 | 90 | 158 | 10 | 258（环境未装齐，见下节修正） |
| `plugins/workspace` | 5 | 0 | 0 | 0 | 0 | 0 | 0（no tests collected） |
| `npm run typecheck` | 0 | — | — | — | — | — | 0 |
| `npm test` | 0 | 146 | 146 | 0 | 0 | 0 | 0 |
| `npm run build` | 0 | — | — | — | — | — | 0（9 extensions → `products/desktop/dist`） |

与 `docs/baseline.md` 记载的差异**如实登记，不做掩盖也不套用历史数字**：

1. `plugins/harness` 的 2 个失败是文档已登记的继承红（`tests/install/test_acp_schema_drift_target.py`
   两例，`@agentclientprotocol/sdk` 1.3.0 与闭包声明 1.4.0 的 schema 漂移），ID 与原因一致。
2. `apps/server` 本环境为 **90 failed / 158 errors**，与文档的 `783P/43F/10S/25E` 不同。按原因聚类，本环境红账主因是**工件/装配缺失而非业务回归**：
   - 与另一道逐 ID 集合差精确为 **180 条**，且这 180 条的红消息**全部**含
     `SERVER_PRODUCT_MISSING`（脚本核对：`diff size 180 {'PRODUCT': 180}`）；
   - `FileNotFoundError: plugins/harness/runtime/worker-entry.mjs` — 31 例（sidecar 入口未构建，harness 日志同记 `ARTIFACT_sidecar-entry=ABSENT`、`ARTIFACT_acp-npm-closure=ABSENT`）；
   - `FileNotFoundError: tests/server/fixtures/…home_probe_acp_peer…` — 16 例（夹具文件不在本树）；
   - 其余为 claude CLI/node 缺失、sidecar 提前退出等。后三类在安装产品装配后**仍为红**，属继承账，不在上面 180 条差集内。
   这些属 C0 的 foundation 装配与构建链范围；本线不修改 `products/**`、根装配或 harness runtime。
   **本线的回归判据**是：同一环境、同一命令下，改动后不得出现新的红 ID，也不得让既有红 ID 换因。
3. `plugins/workspace` 无测试可收集（exit 5）——登记为环境事实，非本线引入。

### `npm run build` 会脏化 C0 所属的生成锁（实测两次，可复现）

基线采集执行 `npm run build`（exit 0，`Built 9 enabled extensions into products/desktop/dist`）后，
受版本控制的 `products/desktop/extensions.lock.json` 变为 modified：

```text
- "extensions/ordessa.workbench/entry.js": "324d734792dfea52850074afe868ee5a10543b4bed5dc4058270566b9db9e861"
+ "extensions/ordessa.workbench/entry.js": "5eab6515fa889030966c8da50e2aa126fc47cca99477695b8fe1af9e641b03cd"
```

再跑一次构建，锁内容与第一次**逐字节相同**（`diff -q` → `LOCK_DETERMINISTIC_ACROSS_REBUILDS`），
且期间无任何源码改动。因此不是构建不稳定，而是 **main 提交的 lock 与已提交的
`plugins/workbench` 源码不同步**。处理：本线不提交 `products/**`（C0 独占），该改动已用
`git checkout -- products/desktop/extensions.lock.json` 还原（`git status` 复验仅剩未跟踪的
`plugins/assets/`）；缺口与由谁重算锁记入 `integration-request.md` 交 C0。
后续本线任何 UI/构建门都会在运行后还原该文件，不把它计入本线交付。

### 品牌 pin（本树实测，供两域 T01 裁定复核）

| 品牌 | 适配器包 pin（`plugins/harness/packaging/*/package.json`） |
| --- | --- |
| Claude | `@agentclientprotocol/claude-agent-acp` **0.81.2** |
| Codex | `@agentclientprotocol/codex-acp` **1.1.14** + `@agentclientprotocol/sdk` **1.3.0** |
| Pi | `@automatalabs/pi-acp` **0.5.0** + `@agentclientprotocol/sdk` **1.3.0** |
| dsh | 需 `@agentclientprotocol/sdk` 1.4.x，与共享根 1.3.0 分离（即上文 schema 漂移红的来源） |

官方机制文档 ≠ 这些 pin 在 Ordessa 运行链上已支持；逐格 supported/unsupported/unknown 判定以各域
`implementation-baseline.md` 的受控证据为准。

---

## 所有权裁定（共同 plan 覆盖原包条款）

- 本线可写：`plugins/assets/prompts/**`、`plugins/assets/command-templates/**`、本 feature 目录。
- `products/**`、根 `package.json`/`package-lock.json`、`tooling/**`、`server-compat` 公共清理 = **C0 独占**。
  因此原表 prompts **T13**（产品 manifest/锁与真实构建）与 templates **T14**（产品启用/构建锁）的“装配与锁”部分
  登记为 C0 集成请求（`integration-request.md`），本线交付插件本体、装配前置条件与可执行验证脚本；
  不以手改 lock 或越界写 `products/**` 代替。
- Profile facet 接线依赖 Z1 `profile-api`，Chat 输入来源依赖 Z2 `chat-api`，原生投影/提交闸门依赖 C0 `harness-api`；
  发布后按固定 publication SHA 正常 merge 复跑，不读他树脏文件。

## R2 — 域实现进度（截至最后一次主代理实测；两域代理仍在写码中）

门命令：`bash /tmp/q2-gates.sh <label>`（在仓库根用钉版 `.venv/bin/python` 3.12.14 跑
`python -m pytest <pkg> -q --junitxml=…`，退出码取自身，逐 ID 红账 + `summary.json` 存
`/home/maoqh/.local/share/qe2-evidence/<label>/`）。

| 采集 | 时刻 | command-templates | prompts | 受影响套件 |
| --- | --- | --- | --- | --- |
| `interim-2` | 18:12:08 | 24 passed / exit 0 | 无测试可收集 / exit 5 | — |
| `snapshot-1` | 18:12:28 | 24 passed / exit 0 | exit 5 | — |
| `wave1-gate` | 18:13:34 | 3 failed, 52 passed / exit 1 | exit 5 | pacthold 238P exit 0；harness 2F+3S exit 1（同基线 ID） |
| `final-17` | 18:15:02 | 2 failed, 63 passed / exit 1（`final-17/plugins_assets_command-templates-reds.tsv`） | 0 collected / exit 5 | apps/server 复跑见 `wave1-affected/exits.txt` |

判定：**这些数字是进行中快照，不是验收结果。** 采集瞬间两域仍在写文件（最近 2 分钟内有 20 个文件被改动），
失败 ID 随写作过程移动；主代理在每个采集点都保留了逐 ID 清单，交回后按同一脚本重跑并以最终一份为准。

已具备真实证据的部分（符号级审阅见 `review-notes.md`，非仅"文件存在"）：
- command-templates：包骨架 + `api/{dto,errors,schema}`、`expansion/{parser,renderer,digest}`、`library/store`、
  `assignments/`、TS `contracts/index.ts`；封闭语法与单次替换语义经符号核对；无 skip/xfail/恒真断言。
- prompts：包骨架 + `api/{dto,errors,ports}`、`backend/{storage,records,textio}`；
  修订不可变与禁硬删由 DB 触发器强制、幂等回执与业务同事务、latest 单事务解析（核对结论见 `review-notes.md`）。

## R3 — 阻塞与未测（诚实边界，不计通过）

**结构性阻塞（依赖检查点未发布，本树可证）**：
`codex/011-foundation-ready`、`-harness-api-ready`、`-profile-api-ready`、`-chat-api-ready`、
`-permissions-api-ready` 全部不存在（`git for-each-ref 'refs/heads/codex/011-*ready*'` 为空），
`specs/011-plugin-rollout/checkpoints/` 亦不存在。因此以下原表条目**不能在本线本轮完成**，
已按符号缺口交 owner（`api-requests.md`）：

- prompts T08（Profile facet 接线）、T10（Profile 编辑器）、T11（下一次提交闸门）、T12（三品牌受控 L3 装载）、T13 装配部分；
- command-templates T08（facet 三态接线）、T09 依赖平台 UI 原语部分、T10（Chat `/`+`+` 输入源）、
  T11（受控对端字节/角色）、T12/T13（原生投影与双投影负面门）、T14 装配部分。

**未测（授权与环境边界）**：真实模型 L4 全部未测（未获授权）；Windows/远程未测；
`plugins/harness` 的 2 例与 `apps/server` 的 43F/25E 为继承红，逐 ID 见基线账。

**本线不发布 `codex/011-q2-ready` 分支**：ready 检查点意味着本线全部必需门已过，当前不成立；
提前发布会把进行中状态冒充为完成。改为本线交付 **clean 提交检查点**（工作树无未提交改动）＋ 本报告与缺口清单；
待两域交回、门复跑通过且回工项（CT-R1、PR-R1..R3）关闭后，再按协议发布 ready 分支。

## 待补章节（域代理交回后由主代理按真实证据填写）

- R2 逐条任务账：prompts T00–T15 / command-templates T00–T15，每 ID 的文件、命令、退出码、G 门
- R4 Spec Kit analyze/converge 查漏结论

### R2 补充实测（派发接续切片时点，18:16）

前一位 Prompts 代理在“重写竞态测试”中途被截断，但已落下可收集的工作：
`.venv/bin/python -m pytest plugins/assets/prompts plugins/assets/command-templates -q`（label `ct-check`）：

- prompts：**23 collected，3 failed**，exit 1（红 ID：`qe2-evidence/ct-check/plugins_assets_prompts-reds.tsv`）；
  包内已有 `backend/service.py`、`plugin.py`、`contracts/{index,dto,keys}.ts`、`tests/{conftest,test_g01_api_purity,test_g02_revisions_cas}.py`。
  此前 `final-17` 报 0 collected 是采集时点早于这些文件出现，说明逐次重跑的必要性。
- command-templates：**74 collected，1 failed**，exit 1（红 ID 见同目录 `plugins_assets_command-templates-reds.tsv`）。
- 受影响套件在 18:13–18:14 复跑无本线引入的回归：pacthold 238 passed（exit 0）、harness 2 failed+3 skipped（exit 1，同基线 ID）、
  apps/server 43 failed+25 errors+10 skipped（exit 1，与 R0 权威账逐 ID 相同集合）。

处置：已派 Prompts 域**接续切片**（只写 `plugins/assets/prompts/**` 与本 feature 的 `prompts/` 子目录），
任务是补齐 G01–G08 反例、完成真实 `server_plugin_api` 注册的 T06 与 PR-R1..R3 回工；
两域在红 ID 清零之前不作为验收证据。

---

## 阶段收束（本会话停止点，供接续者接手）

**本线未达到“完成”**，不发布 `codex/011-q2-ready`（协议要求 ready 表示本线必需门全过，当前不成立）。
本会话交付的是 **clean 提交检查点** + 本报告 + 缺口清单。

### 已完成并有真实证据
- R0 线级冻结：SHA、工具链（钉版 `.venv` Python 3.12.14）、逐 ID 红账、`docs/baseline.md` 安装缺口、
  产品锁漂移证明（重建两次同值）→ 提交 `354a576b06`、`46846b2c25`、`2c0c8bd209`。
- R1 接缝请求：`api-requests.md` AR-Q2-01..05，逐符号判定可用/不可用（含 `contract.py:164-215`、
  `workbench.ts:25/41/45/59` 等定位）。
- 审阅账 `review-notes.md`（提交 `d1267c034c`、`9375d20631`）：两域核心存储/语法的符号级结论 + 回工项 CT-R1、PR-R1..R3。
- 两域包骨架与领域核心已在树内并可在钉版环境收集执行（计数见 `qe2-evidence/park-1/summary.json`）。

### 仍在进行（已派代理，本会话不再等待）
- command-templates：`park-1` 时点的 collected/failed 以 `qe2-evidence/park-1/` 为准；原代理仍在写 T06/T07 与反例。
- prompts：接续切片仍在补 G01–G08 反例与 T06 真实注册（`park-1` 前一份计数为 23 collected / 3 failed，红因见 `check-2/`）。

### 剩余工作（按顺序，下一步即可执行）
1. 两域代理交回后：`bash /tmp/q2-gates.sh accept-1` 复跑，**红 ID 必须为 0**；关闭 CT-R1 与 PR-R1..R3；
   再跑 `bash /tmp/q2-gates.sh affected packages/pacthold plugins/harness apps/server`，与 `q2-baseline` 逐 ID 同因对照。
2. UI/贡献层：以本树真实可用的 `WorkbenchSettingsSection`/`addSettingsSection` 先落贡献层与键盘/窄窗/失败态反例；
   平台 UI 原语（AR-Q2-04）待 foundation 发布后替换为公共件。
3. 接线类条目（Profile facet、Chat 输入源、Harness adapter、三品牌受控 L3、产品装配）：
   等对应检查点分支出现后按 `contracts/checkpoints.md` 固定 publication SHA 正常 merge 复跑，再回填本报告 R3 消费表；
   owner 与缺口已在 `api-requests.md`、`integration-request.md` 写清。
4. Spec Kit `analyze` / `converge` 查漏（R4）后，若必需门全过，才发布 `codex/011-q2-ready` 指向含本报告与检查点记录的提交。

### CT 道交回（主代理复验，非代理自述）

- 钉版 3.12 复跑：`bash /tmp/q2-gates.sh ct-final plugins/assets/command-templates`（见
  `qe2-evidence/ct-final/`，计数与退出码以该目录为准）。域代理自报 83 passed 是在其 **Python 3.14.4** 临时 venv，
  本线验收口径为 `.venv` 3.12.14。
- 域代理交回清单：T00–T07 完成并有反例；明确未过 G09、G10、G11、G13–G19、G22、G23；
  原生逐格记 unknown/unsupported（不由官网推 L3）；新增外部依赖为零；不宣称整包完成。
- **新事实（改变下一步）**：交回时报告 `codex/011-chat-api-ready` 已在本会话中途发布（`54ad26c1`），
  与本节上方 `git for-each-ref` 输出同源。R1「消费必需 checkpoint」自此对 Chat 一条**可执行**：
  下一步是把该固定 publication SHA 正常 merge 进本分支、核对 `addInputSource` 与字面 `/` 开头正文的
  提交语义，再落 CT T10/T11；profile/harness/foundation 仍无分支。

### Prompts 道交回（切片被自身轮次上限截断，但实测状态良好）

- 主代理在**截断之后**独立复跑：`bash /tmp/q2-gates.sh prompts-cap plugins/assets/prompts`
  → **149 collected / 0 failed / 0 errors / 0 skipped**（`.venv` Python 3.12.14，
  证据 `qe2-evidence/prompts-cap/`）。此前 23/3 的三份红已消失，且测试面扩展到
  `tests/test_g01_api_purity` … `test_g08_plugin_surface` + `test_g03_clone_archive_lifecycle`、
  `test_g04_text_import_export`、`test_g05_body_privacy_logs`、`test_g06_scope_authorization`、
  `test_g07_snapshot_consistency`、`test_g08_plugin_surface`、`test_review_regressions`。
- 审阅回工项**按符号核实已关闭**（不看代理自述）：
  PR-R1 → `tests/test_review_regressions.py:40-71`（在写事务内调用走 `read()` 的读者必须
  得到 `cannot start a transaction within a transaction` 且断言 `metadata_version` 仍为 1、
  无半成品行），并在 `:89` 对**每个**写入口重复同一不变量、`:133` 断言生产路径不触发；
  PR-R2 → `:174` `test_an_update_without_a_body_patch_echoes_the_live_digest` 与
  `:223` clone/get 恒带摘要，实现见 `backend/records.py:216`（无正文补丁时回传既有 `sha256`）；
  PR-R3 → `:250`、`:271` 断言生产装配从不武装 `fault_after`，装配后的 store 仍以 `None` 起步并可写入。
- 停点说明：该切片最后一句是「现在做实现修复」，但**其实现与反例已在树内并绿**，
  结论以上述复跑与行号为准，不以其最后一行为准。
- 仍未过/未做（不记通过）：prompts T07（三品牌 adapter 的 assess/compile/verify 与版本矩阵）、
  T08/T10（Profile facet 与编辑器）、T09 依赖平台 UI 原语的部分、T11/T12（下一次提交闸门与三品牌受控 L3）、
  T13/T14 装配与安装/泄漏扫描、T15 汇总审阅；profile/harness/foundation 检查点分支仍不存在。
