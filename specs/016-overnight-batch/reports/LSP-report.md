# LSP-report · 016 夜批（son-lsp，支 codex/plugin-lsp）

日期：2026-09-28 深夜。执行者：**zcode 代打**（qoder 不可用，见下）。
写入面自查：本包只写了 `plugins/assets/lsp/**` 与本 report；`git status`
无域外文件。

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
| LSP-1 域骨架 + facet `assets.lsp` 注册进 C2 | ✅ | `adapters/src/ordessa_lsp_adapters/points.py`：真点 `harness.configuration-adapters`(v1) 上贡献批；`registry.py` 的 `LspAdaptersServerPlugin`；形制仿 sandbox/model-provider（只仿不 import，`test_dependency_direction.py` 钉死） |
| LSP-2 定义模型 | ✅ | `api/src/ordessa_lsp_api/definitions.py`（server/formatter 定义、语言映射、选择与 session/profile 作用域、引用制）；`transcription.py` 字节稳定转录 |
| LSP-3 品牌收窄 | ✅（含两处 F6 修正） | 三家 descriptor（pi/codex/claude-code，全部带证据 unsupported）；hermes/opencode/kilo 投影入口 `PHASE2_DEFERRED`；qwen `BRAND_REMOVED`（`.lsp.json` 行跳过并登记）。**修正 1**：pi 无原生 LSP 面（见 §3）；**修正 2**：dsh 有原生 lsp-stdio（17 键），非 unsupported，归阶段二 |
| LSP-4 可用性诚实检查 | ✅ | `probe.py` 注入式 PATH 探测（默认 `shutil.which`，不 spawn）；缺席=`absent-executable`+原因，不产假配置（`test_probe.py`、`test_projection_golden.py` 反例） |
| LSP-5 受控测试 | ✅ | golden 转录字节稳定（`tests/golden/lsp-projection-golden-v1.json` 按字节比较）+ 两会话隔离（`test_sessions.py`）+ 缺席可执行反例；42 passed |
| LSP-6 report.md | ✅ | 本文件 |

## 2. 测试与命令（真实执行）

```
$ cd <son-lsp 工作树>
$ PYTHONPATH=plugins/assets/lsp/api/src:plugins/assets/lsp/adapters/src:plugins/assets/lsp/adapters/tests \
  /home/maoqh/projects/ordessa/.venv/bin/python -m pytest plugins/assets/lsp -q
42 passed in 0.12s
```

构成：api 13（定义模型正反例/转录字节稳定）+ adapters 29（探测 4、C2 形制与
品牌门 12、golden/反例 5、两会话 2、依赖方向 2、其余 4）。测试环境说明：
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
2. pi 侧若白天裁"pi 扩展 LSP"路线，先补官方扩展 API 证据再扩 adapter。
3. C2 通路真机验证（stage_contributions 产品级）未做——本包未动 host，
   与 EXT-5 同口径登记。

## 6. 审阅

（待 run-review.sh 执行后回填）
