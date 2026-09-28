# 开发分支归并（2026-09-28）

**状态：归并完成，不代表功能验收通过。main 未修改、未推送、未启动任何 agent。**

当前开发分支为 **1 + 22**：`codex/core` 和每个有开发增量的插件一条分支。
所有插件分支直接基于同一个 core 提交，互不嵌套；其相对 core 的差异只在自己的插件目录。
内核分支相对 main 不修改任何 plugins 路径；产品装配、根锁、方案、报告与公共工具全部归 core。
这些是开发中间态：独立分支不保证产品可启动，依赖插件需一起组合验证。没有把未完成的工作标成完成。

## 分支清单

| 分支 | 归属 | 改动路径数 |
| --- | --- | ---: |
| `codex/core` | core | 819 |
| `codex/plugin-agent-connections` | agent-connections | 9 |
| `codex/plugin-agent-contracts` | agent-contracts | 7 |
| `codex/plugin-agent-conversation` | agent-conversation | 3 |
| `codex/plugin-agent-sessions` | agent-sessions | 5 |
| `codex/plugin-command-templates` | command-templates | 27 |
| `codex/plugin-mcp` | mcp | 160 |
| `codex/plugin-model-provider` | model-provider | 67 |
| `codex/plugin-prompts` | prompts | 25 |
| `codex/plugin-sandbox` | sandbox | 101 |
| `codex/plugin-skills` | skills | 129 |
| `codex/plugin-subagents` | subagents | 83 |
| `codex/plugin-chat` | chat | 47 |
| `codex/plugin-connections` | connections | 7 |
| `codex/plugin-connector-acp` | connector-acp | 16 |
| `codex/plugin-connector-ordessa` | connector-ordessa | 6 |
| `codex/plugin-harness` | harness | 96 |
| `codex/plugin-permissions` | permissions | 120 |
| `codex/plugin-profile` | profile | 69 |
| `codex/plugin-runtime-compat` | runtime-compat | 61 |
| `codex/plugin-server-compat` | server-compat | 36 |
| `codex/plugin-workbench` | workbench | 14 |
| `codex/plugin-workspace` | workspace | 8 |

`plugin-connections`、`plugin-workbench` 只记录旧插件目录退役；新实现已进入前端平台。
没有为未修改的 commands 创建空开发分支。assets、agent、connectors 按业务叶子拆分，而非把整个插件族混成一支。

## 保全与历史

旧分支头均保存到 `refs/archive/20260928-consolidation/heads/<原分支名>`。
每棵旧工作树的完整源码快照保存到 `refs/archive/20260928-consolidation/worktrees/<目录名>`；C0 完整快照使用 `011-c0-foundation-harness-full`。
快照包括 Q3/Q4 未提交源码；C0 冲突文件的工作副本和暂存新增文件均保全并归并。
旧工作树不删除、不清理缓存、不重装环境；仅解除它们对旧开发分支的占用。不要继续在这些冻结树开发。
旧的 Profile/Skills/模型实现、早期 desktop-workbench 和 backend-multi-harness 作为已被后续架构替代的历史输入保全，
没有把其旧宿主代码重新塞回当前架构。既有远端、tags、refs/reference、原 refs/archive 一律不变。

## 冲突处理与完整性

- Profile 的 modify/delete 冲突保留 Z1 最终实现；并逐目录核对六条领域线与所有者快照完全一致。
- 平台旧方案冲突保留已有 C7/C8 补充和已完成记录；不回退到旧任务状态。
- Q5 最新源与 C0 已处理的 Sandbox/Permissions 接缝通过三路归并保留双方增量。
- 全部分支重组后必须逐 blob/mode 重建出总成果树，差异为零；核心/插件写入范围分别校验。
- 只做 Git/文件完整性与 Python 语法检查，不以业务测试是否全绿阻止用户授权的归并。

## 后续使用

公共接缝在 `codex/core` 修改；具体插件只在对应分支修改。后续更新内核后，各插件显式同步 core。
无需再发布每个阶段一条 ready 分支；以提交 SHA 交付。main 集成和远端发布仍需独立授权。
本次归并没有创建无人值守目标、会话或自动任务。
