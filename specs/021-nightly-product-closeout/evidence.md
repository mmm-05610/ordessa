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

## Phase 1+（待填）

（每条真实构建/安装/启动/E2E 证据按上表格式追加，注明时间与 checkpoint 关联。）
