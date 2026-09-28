# LSP-report · 016 夜批（son-lsp，支 codex/plugin-lsp）

日期：2026-09-28 深夜。执行者：**zcode 代打**（qoder 不可用，见下）。

## 写入面自查（按分支提交逐一披露，订正版）

本分支相对 main 恰有两个提交，归属如下：

1. `892a74a47e` **夜批基线补同步**（编排者准备动作，先于派工）：把本树
   `specs/016-overnight-batch/` 对齐 main 现行版（品牌优先级 pi/codex/
   claude、qwen 除名、CMP 三档口径、无人值守附加），**仅文档、零代码**。
   动机：本树切基点早于品牌优先级裁定，树内旧 tasks.md 的 LSP-3 仍是
   "五品牌实施（含 qwen）"——不先同步，派工就会执行已被用户裁定推翻的
   任务清单。该提交内容 = `git archive main specs/016-overnight-batch`
   的逐字节快照，非本包改写任何口径。此提交在 LSP 包派工之前完成，
   属编排文档基线，不在 LSP 写入面内，特此披露。
2. `d6ef928a9e`（+ 本次订正提交）**LSP 包本体**：只写
   `plugins/assets/lsp/**` 与 `specs/016-overnight-batch/reports/LSP-report.md`。

除上述两笔外 `git status` 无任何域外文件。

**git 取证（回应"编排文档改动归属"质疑，可复核）**：
- `git diff main 892a74a47e -- specs/016-overnight-batch` **输出为空**——
  sync 提交的 016 目录与 main **逐字节一致**（"逐字节快照"由此可证，非本
  分支改写）；
- `git show main:specs/016-overnight-batch/tasks.md` 的 LSP-3 即"只实施 pi"
  新文本——该文本由 **main 侧提交 `dcc4b53c3c`**（用户品牌优先级裁定）写入，
  本分支零改写；本分支在 sync 前处于合并基 `5a22ffc587` 的旧文本；
- `git cat-file -e main:specs/016-overnight-batch/bin/run-qoder.sh` 通过——
  bin 脚本、CMP dispatch、fathers 均为 main 既有文件。
- 审阅所见"新增/改写"来自 `git diff main...HEAD` 的**三点语义**：比较对象
  是合并基（5a22ffc）而非 main，main 侧自身演进因此呈现为分支侧改动。
  直接对照 main 的两点 diff：`git diff main HEAD -- specs/016-overnight-batch`
  **只含一个文件**——本 report 自身（151 行新增，位于派工允许的
  `reports/` 内）；编排文档（spec/tasks/dispatch/bin/fathers）相对 main
  **零差异**。写入面合规不依赖自述，上述命令可直接复核。

## 0. 执行方式记录（qoder 与代打）

1. **run-qoder.sh 第 1 次**（23:29:33，log
   `specs/016-overnight-batch/reports/logs/son-lsp-qoder-20260928-232933.log`）：
   被会话恢复（基础设施）中断，树内零改动。
2. **run-qoder.sh 第 2 次**（23:41:31，log
   `specs/016-overnight-batch/reports/logs/son-lsp-qoder-20260928-234131.log`）：
   qoder 进程正常跑完并退出 0，但**零产出**——其在 `-p` 无人值守 +
   `--permission-mode default` 下一切写/执行被拒，自行声明
   "Goal blocked and registered… all require write/exec permission that this
   session is denying" 后停止。同墙同样挡住了父会话 1/2 的
   son-pe1 / son-ext 派工（同夜日志可查）。
3. **处置**：按 spec.md 红线 5（qoder 不可用 → 父会话代打并标注）与
   father.md（再失败你自己顶上做完）转 **「qoder 失败、zcode 代打」**。
   降级条款的裸调用同一 `--permission-mode default`，确定性撞同一堵墙，
   故未执行无意义的第三次同参调用；此判断如实登记于此。
4. 模型白名单：qoder 未产出任何执行，未涉及模型调用问题。

## 1. 任务勾选对照（main 版 tasks.md LSP 节）

| 任务 | 状态 | 证据 |
| --- | --- | --- |
| LSP-1 域骨架 + facet `assets.lsp` 注册进 C2 | ◐ 库级完成 | `adapters/src/ordessa_lsp_adapters/points.py`：真点 `harness.configuration-adapters`(v1) 上贡献批构造+自测；`registry.py` 的 `LspAdaptersServerPlugin`；形制仿 sandbox/model-provider（只仿不 import，`test_dependency_direction.py` 钉死）。**未含**：products/server 装配与 C2 真机 stage 通路（越本包写入面，登记 §5.1/§5.3 待办） |
| LSP-2 定义模型 | ✅ | `api/src/ordessa_lsp_api/definitions.py`（server/formatter 定义、语言映射、选择与 session/profile 作用域、引用制）；`transcription.py` 字节稳定转录 |
| LSP-3 品牌收窄 | ✅*（任务前提被证据证伪，按红线 3 落诚实格；**卡点 C-LSP3** 见 §5） | 三家 descriptor（pi/codex/claude-code，全部带证据 unsupported）；hermes/opencode/kilo 投影入口 `PHASE2_DEFERRED`；qwen `BRAND_REMOVED`（`.lsp.json` 行跳过并登记）。**修正 1**：pi 无原生 LSP 面（见 §3）；**修正 2**：dsh 有原生 lsp-stdio（17 键），非 unsupported，归阶段二。口径注："只实施 pi" = 不给任何品牌做原生投影实现（本批无原生面可投）；codex/claude-code 的 descriptor 正是 dispatch 要求的 "unsupported+证据" 格载体，不是对它们的实施。任务-代码不一致是**事实**：任务原文"实施 pi 原生面"的前提被官方证据证伪，本包不改任务文本（main 侧 `dcc4b53c3c` 为任务文本唯一权威），以卡点登记交用户晨裁 |
| LSP-4 可用性诚实检查 | ✅ | `probe.py` 注入式 PATH 探测（默认 `shutil.which`，不 spawn）；缺席=`absent-executable`+原因，不产假配置（`test_probe.py`、`test_projection_golden.py` 反例）。口径注：`absent-executable` 就是任务文本 "缺席=该格 unsupported 并带原因" 的落地状态名——它是 unsupported 在缺席成因下的精确分类，语义同一 |
| LSP-5 受控测试 | ✅ | golden 转录字节稳定（`tests/golden/lsp-projection-golden-v1.json` 按字节比较）+ 两会话隔离（`test_sessions.py`）+ 缺席可执行反例；42 passed |
| LSP-6 report.md | ✅ | 本文件 |

## 2. 测试与命令（真实执行）

```
$ cd <son-lsp 工作树>
$ PYTHONPATH=plugins/assets/lsp/api/src:plugins/assets/lsp/adapters/src:plugins/assets/lsp/adapters/tests \
  /home/maoqh/projects/ordessa/.venv/bin/python -m pytest plugins/assets/lsp -q
42 passed in 0.12s
```

构成（逐文件计数，`pytest --collect-only` 可复核）：api 13（定义模型正反例/
转录字节稳定）+ adapters 29（探测 4、C2 形制+callable+品牌门 16、golden/
反例 5、两会话 2、依赖方向 2）。测试环境说明：
合同 dist（ordessa_harness_api/server_plugin_api）来自主仓 .venv 的 editable
安装，与 son 分支携带的同源同内容；harnesses.toml 的 pin 以**本树 file-relative
路径实测**（`_lsp_helpers.HARNESSES_TOML`），不跨树。

## 3. 五家逐格表（LSP-3/LSP-6 核心；证据均可回指）

| 品牌 | pin（harnesses.toml 实测） | 本批格 | 原生 LSP 面证据 | 处置 |
| --- | --- | --- | --- | --- |
| **pi** | 2.0 | unsupported | 研究钉定提交 `2b0a123de983`：settings.md 全量参考 0 个 lsp/formatter 键；docs 目录无 lsp/formatter 文档；configuration.md agent 目录无 LSP 文件；extensions.md 无 LSP API；monorepo workspaces 无 LSP 包；source-index.json pi 68 键 0 命中 | adapter=零 claims+unsupported 终态；若 pi 未来出现原生面/已证扩展 LSP API，单点扩 |
| **codex** | 2.0 | unsupported | config-reference 437 键 0 命中；harnesses.md §1 无 LSP 行 | descriptor+CAPABILITY_UNSUPPORTED |
| **claude-code** | 0.81.2 | unsupported | settings-reference 234 键 + env-vars 371 键 0 命中；harnesses.md §2 无 LSP 行 | 同上 |
| hermes | 2.0 | 阶段二（不实施） | harnesses.md :110 列入扩展服务行；source-index hermes 54 键 0 命中（证据不足待核） | 投影入口 `PHASE2_DEFERRED` |
| opencode | 2.0 | 阶段二（不实施） | **有原生面**：config schema `lsp`/`formatter`/`permission.lsp`；harnesses.md :130 | `PHASE2_DEFERRED`；设计包见 phase2-design-lsp.md |
| dsh | 0.1.5-rc.1 | 阶段二（不实施） | **有原生面**：source-index dsh 17 键 `@deepseek-ai/dsh-lsp-stdio`（command/args/env/servers/extensionToLanguage/…）；harnesses.md :152 | `PHASE2_DEFERRED`；**F6 "dsh 无原生" 失真已登记** |
| kilo | 7.7.2 | 阶段二（不实施） | **有原生面**：config schema `lsp`/`formatter`/`permission.lsp`；harnesses.md :199 | `PHASE2_DEFERRED` |
| qwen | 0.23.4（toml 事实仍在） | **已除名**（用户裁定 2026-09-28） | 原生 `.lsp.json`（harnesses.md :178）——按裁定跳过不做 | 投影入口 `BRAND_REMOVED`；toml 摘除归 PE2-8，非本包写入面 |

**plan F6 两处失真的修正登记**（证据见 `evidence.py` 模块 docstring）：
1. "pi :130" 为行号漂移——现行 :130 是 OpenCode 的 LSP 行；harnesses.md 全部
   历史版本的 pi 节均无 LSP 行（`git log --reverse` 取证）。LSP-3 "只实施 pi
   （LSP/formatter 原生面）" 的前提不成立，按红线 3 如实落为带证据的
   unsupported，而不是编造 pi 配置格式。
2. "dsh 无原生 → unsupported" 与 source-index/harnesses.md 矛盾，dsh 归阶段二。

## 4. 复用与自建清单（红线 7）

**复用**：C2 点与合同词汇（ordessa_harness_api，零改动）；server_plugin_api
贡献形态；sandbox adapters 的绑定形制（pins 实测法/闭合 schema/callable
三答——只仿不 import）；harnesses.toml 实测 pin；source-index.json 与
harnesses.md 的存量证据面。**自建**：定义模型与规范转录（域本无）、探测器
（~40 行，注入式）、投影决策流水线与会话存储、逐格证据账。自建均为本域
必需的新机制且薄；无任何"替代实现"性自建（没有品牌存在可投影的原生面，
投影流水线的诚实产出=决策记录而非配置，这正是结果而非妥协）。

## 5. 卡点与移交

1. **产品装配越界待办**（登记请求，未越界写）：`products/server/`
   composition 需 import `LspAdaptersServerPlugin` 并加
   `ordessa-lsp-api==0.1.0`/`ordessa-lsp-adapters==0.1.0` 依赖与 plugin id
   `ordessa.lsp-adapters`（同 sandbox-adapters 的装配位）——归 INT/AR。
2. **C-LSP3（晨裁卡点）**：LSP-3 "只实施 pi（LSP/formatter 原生面）" 的
   前提被官方钉定证据证伪（pi 无原生 LSP 面，§3 修正 1）。本包未改任务
   文本，按红线 3 落为带证据 unsupported；用户晨裁可选：(a) 接受诚实格，
   LSP 域转为"定义模型+探测+决策流水线"机制包，等任一品牌出现原生面再投；
   (b) 若裁"pi 扩展 LSP"路线，先补官方扩展 API 证据（L2）再扩 pi adapter；
   (c) 若裁"dsh/opencode/kilo 提前实施"，从阶段二设计包直接派工。
3. **C2 真机通路未做**：`stage_contributions` 产品级装配（§5.1）与真机
   staging 未验证——本包未动 host，与 EXT-5 同口径登记归 INT/AR。
4. golden 与 digest 为自产自证：防漂移不证语义；语义正确性由逐格证据账
   （§3）与审查承担。

## 6. 审阅

**第 1 轮（run-review.sh，pi + mimo-v2.6-pro）结论：不通过。** 三条问题与
处置：
1. "写入面越界 + 自查陈述失实"——审阅对象是 `main...HEAD` 全量 diff，
   其中编排文档改动来自 `892a74a47e` 基线补同步（派工前的编排者准备动作，
   非 LSP 包产出），原报告未披露造成失实。**已订正**：§写入面自查改为按
   提交逐一披露归属；任务/规格文本零改写（sync = main 快照）。
2. "LSP-3 三家 descriptor 与 '只实施 pi' 文本不一致；LSP-4 状态名新造"
   ——前者为口径误读（descriptor 即 dispatch 对 codex/claude 要求的
   "unsupported+证据" 载体），后者为命名更精（absent-executable ⊂
   unsupported）。**已在 §1 勾选对照表补口径注**。
3. `conftest.py` api 路径多一级 `.parent`（真 bug，测试绿靠 PYTHONPATH
   兜底）；`test_golden_digest_recorded` 空转断言。**已修复**：conftest
   改正解析并在无 PYTHONPATH 下自证（29 passed standalone）；digest 钉死
   期望哈希。

**第 2 轮（run-review.sh 复审）结论：不通过。** 三条问题与处置：
1. "bin/dispatch/fathers 为新增、spec/tasks 被改写，自查'逐字节快照'与
   diff 矛盾"——**git 取证反驳**（见 §写入面）：`git diff main 892a74a47e
   -- specs/016-overnight-batch` 为空、`git cat-file -e main:…/bin/run-qoder.sh`
   通过、tasks.md 新文本出自 main 侧 `dcc4b53c3c`。审阅的三点 diff 以合并
   基为比较对象，把 main 侧自身演进呈现为分支改动；报告已补记该语义与
   可复核命令。
2. "LSP-3 文本被本分支先改再答"——同上，改题者是 main 侧 `dcc4b53c3c`
   （用户裁定），本分支只是被 sync 追平；"pi 原生面实施"前提的证伪与
   诚实落格见 §3 修正登记 1。
3. `test_only_published_contract_dists_imported` 漏检无 "ordessa" 字样的
   import（真缺陷）——**已修复**：改为全量 AST 扫描，白名单=三合同
   dist+pytest+`sys.stdlib_module_names`。报告 §2 计数分解同步订正
   （12+4 → 16）。

**第 3 轮（run-review.sh 复审）结论：有保留。** 审阅认可证据账与测试诚实
（"未见删断言/空测试/谎报"、计数自洽、前两轮修复均真修）。三点残余处置：
1. "写入面合规靠不可验证自述"——已补**两点 diff 直接对照**（见 §写入面
   末条：016 目录相对 main 唯一差异=本 report，编排文档零差异）。
2. "LSP-3 任务-代码不一致是事实"——**采纳**：改为 ✅* + 卡点 C-LSP3 登记
   （§5.2），不改任务文本，交用户晨裁。
3. "LSP-1 勾选高于完成度"——**采纳**：降为 ◐ 库级完成（装配/真机通路
   §5.1/§5.3 待办）。弱断言（type 名比对）已改 isinstance。

**第 4 轮（run-review.sh 复审）：**（待回填）
