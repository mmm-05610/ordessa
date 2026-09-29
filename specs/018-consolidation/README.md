# Consolidation 记录（2026-09-29，018）

**状态：13 支全部并入 main，containment 归零；分支保留供下轮复活。**
用户授权执行；流程同 014 收口口径。

## 并入清单（全部 `--no-ff` 留痕）

profile(104)、mcp(179)、skills(142)、subagents(96)、chat(51)、
model-provider(77)、lsp(42)、harness(29)、prompts(32)、extensions(25)、
runtime-preferences(25)、permissions(10)、command-templates(27)。
合并后逐支 `diff(main...)`=0。

**冲突 3 处，全部取 main（联合版为权威）**：
- chat：`specs/016.../api-requests.md`（AA，main 含 AR-3/AR-6 回填）
- model-provider：`specs/014.../seams.md`（main 含四阻塞答复增节）
- harness：`specs/016.../reports/PE2-report.md`（main 含 §5 审阅结论）

## 完整性

新落位目录（main:plugins/assets 由 1→10：sandbox + command-templates/
extensions/lsp/mcp/model-provider/prompts/runtime-preferences/skills/
subagents）；工作区净；六关键域 `compileall` 过。组合级测试未在本记录内跑——
归 IR-1 联测（pi）与产品装配验证。

## 解锁队列（按序）

1. **pi 侧**：`codex/core` 并入 main（013 线收口后）→ S-01/S-03 装配
   （profile 三扩展 + server 默认插件集）；INT-02 根锁干净重算（五 workspace
   条目，需本 consolidation 后的组合树）；下游 qwen 11 文件同步。
2. **017-W1**（server-compat 写入链死亡）：本 consolidation 后、S-03 前同窗执行。
3. IR-1 联测（PE1+PE2 双事实 → ready 翻转）。
4. 新品牌（mcode/qoder/zcode-tui）入 roster 裁定后实测排期。

## 补录（同日）

- `codex/plugin-memory`（015-B，26 文件）经用户授权随即并入 main——
  plugin 支全零，1+x 归 1+0。

## 未随本合并

~~`codex/015-b-memory`~~ 已收口（见上补录）；
`codex/core`（归 pi）；归档 refs 不动。
