# evidence.md — 真实证据登记

规则：不要只写"测试过，正常"。每条记录：command / exit code / relevant output
summary / artifact path /（deb：文件名 + SHA256）/ install 命令与结果 / 进程与日志
位置 / 真实 Harness、临时验收项目、Profile、Skill、MCP、approval、restart 结果。
真实 Harness E2E 使用独立可丢弃测试项目（`/tmp` 或 tonight data-root 下极小 git
project）；不让验收 Agent 修改 Ordessa 自己的源码仓库。

## Phase 0 · Bootstrap（2026-09-29 23:53–24:00+ Asia/Shanghai）

| ID | 证据 |
| --- | --- |
| E-P0-1 | `git status --porcelain=v1 -b` → `## main...origin/main`（干净、与远端同步）；`git rev-parse HEAD` → `b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`；当前 branch `main`。 |
| E-P0-2 | `git worktree list`：root @ main；仅一个历史 worktree `worktrees/consolidated-core` @ `codex/core`（c20ce5853d，今晚不动）。`git branch -a`：无 `nightly/021-*`；`worktree/` 目录不存在 → 判定可安全创建，无覆盖风险。 |
| E-P0-3 | `/worktree/` 追加进 `.git/info/exclude`（本地排除，未改项目 `.gitignore`）。`git worktree add -b nightly/021-ordessa-product-closeout worktree/021-ordessa-product-closeout main` 成功，checkout 于 `b4bf7cd909`。 |
| E-P0-4 | C0 控制面 commit：`specs/021-nightly-product-closeout/` 10 份文档落入 NIGHTLY_TRUNK；SHA 由 Lead 在提交后回填于此：`58430188716b3350b9cf91657e1ac4a468b2c784`（C0-a 控制面文档；本条回填为 C0-b bookkeeping commit，分支头 SHA 见晨报）。 |
| E-P0-5 | 现状阅读：`docs/baseline.md`（工具链钉版、npm test 聚合 25 suites、Python 四套件期望、inherited reds）、`docs/architecture.md`（依赖方向、data compatibility、装配以 extension id 为数据）、`docs/known-issues.md`（inherited red 台账、UI debts、live services 不碰）、`docs/naming.md`、`specs/018-consolidation/README.md`（13 支并入 main）、`specs/020-runtime-compat-retirement/inventory.md`（波 1 小刀/波 2 搬家 epic）。 |
| E-P0-6 | 装配/打包面盘点：`products/desktop/extensions.json` enabled=14（contracts/agent-contracts/commands/workbench/connections/agent-connections/agent-sessions/agent-server/agent-acp/chat-api/chat/profile-api/profile-frontend/profile-chat）；root scripts：`build`、`build:deb`(node packaging/build-deb.mjs)、`test:packaging`、`test:packaging:clean`(clean-machine-accept.sh)、`test:agent-shell`、`test:electron`、`test`(tooling/test-all.mjs)。skills/mcp/prompts/permissions/model-provider/memory/lsp/subagents/runtime-preferences 不在默认桌面装配 → ledger W-001。 |
| E-P0-7 | E2E key 落位与保护：用户提供 key 置于 nightly worktree 根 `key.txt`（首版 51B OpenCode Go，00:14:03 换为 35B DeepSeek 官方）；初查发现从 nightly worktree 视角**未**被 ignore（`?? key.txt`）→ 共享 `.git/info/exclude` 追加 `/key.txt`，复查 `git check-ignore -v key.txt` 命中、status 干净。内容全程未读入任何上下文。详见 api-key-usage.md。 |
| E-P0-8 | 零 token 探针（00:14 后）：`curl https://api.deepseek.com/models -H "Authorization: Bearer $(cat key.txt)"` → **HTTP 200**；models=`deepseek-flash`（DeepSeek-V4.1-Flash，1M ctx，393K max out，text+image，effort low/high/max）、`deepseek-v4-pro`（text-only，1M ctx）。key 有效、网络可达、无 token 消耗。 |

## Phase 1 · Establish Reality（2026-09-30 00:20–01:00）

| ID | 证据 |
| --- | --- |
| E-P1-1 | RE-1 全链构建：npm ci 532 包（018 合并后正常增长）；typecheck 31 条预存在 TS 错；`npm test` 24/39 绿、失败全预存在（RE-1 报告 §B/C 逐套件）；桥二跑复现 `714044a5…`；**deb 产出** `packaging/.out/ordessa_0.1.0_amd64.deb` sha256 `d7e4727e2720f1a590fb23d54a0556b096abf27004d34ee1eb069d5b8df55941`，build-id `20260929-aa3918092`。RE-1 另建 nightly worktree `.venv`（baseline 锁文件 + 018 补全 editable 清单）→ server-bridge 跨语言门 48/48 PASS。`git status` 仅流水线产物两处（bundle-manifest.json、ui-preview 截图）。→ **C1 达成**。 |
| E-P1-2 | RE-1/SC-2 独立复现 P0：`apps/desktop/dist/electron-main.cjs` require 即 `TypeError: Invalid URL`（bundle 内 `var import_meta = {}`，`data-root.ts` 顶层 `new URL(LAYOUT_SOURCE, undefined)`）；复现日志 `/tmp/021-direct-launch.log`。→ ledger B-001。 |
| E-P1-3 | SC-2 deb 解剖：build-deb 仅装 3 个 Python 包（缺 products/server 闭包→SERVER_PRODUCT_MISSING 风险）；无 `/opt/ordessa/harnesses` staging（→BUNDLED_RUNTIME_MISSING）；`runtime.ts:62` 把 python **目录**当可执行；装机扩展发现解析到 `/opt/products/desktop/dist`（node 算术复现）；clean-machine-accept 需 `packaging/.cache/ubuntu-base.tar.gz` 且不启动 GUI（不能单独当 C2）。环境探针：sudo 不可用、userns `unshare --map-root-user` 可用、python3.12.14 在、无旧安装残留、磁盘 108G。→ B-002/B-003/W-018。 |
| E-P1-4 | SC-1 W-001 定性：桌面 23 扩展包 vs 14 enabled（8 缺，`ui-components` 故意缺席有测试钉）；`default_plugins()` 仅 8 插件；3 个扩展 entry 形态损坏（激活必抛/必失败）；permissions 后端已组合+admission 已接线但前端三件套未装配、chat 只渲染 composer.toolbar、生产 approve 走未过闸门 `respond()`；skills/mcp 三段链 UI/存储/物化各有断点（详 SC-1 矩阵）。→ B-004 + EA-1 seam 裁决。 |
