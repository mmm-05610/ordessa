# 平台收敛实施入口

顺序：constitution → spec.md → research.md → plan.md → data-model.md → contracts/platform-api.md → tasks.md → quickstart.md。

使用 GitHub Spec Kit 官方模板与 Qoder 项目 skills，不用派工单。已讨论的架构由上述规范细化；未把其他工作树成果视作 main 已存在。
2026-09-27 补充 C6：通用 Connections 迁前端平台，见 contracts/connections-platform.md；FR-015 与 T026–T029 仅修改 C 线。旧 AgentConnections 归属解释以此为准。

2026-09-27 补充 C7：原 C goal 收尾后追加可替换 UI 通用机制。先读 contracts/ui-components-platform.md，再完成 T030–T036；增量报告 reports/C7.md；恢复执行提示词见 prompts/C7-goal.md。完整设计快照在 amendments/ui-components/，其中 12 项领域组件仅供背景，本次不实施。

| 会话 | 工作目录 | 分支 | 本线 |
| --- | --- | --- | --- |
| Pacthold | /home/maoqh/projects/ordessa/worktrees/platform-pacthold | codex/010-platform-pacthold | A |
| Server | /home/maoqh/projects/ordessa/worktrees/platform-server | codex/010-platform-server | B |
| 前端平台 | /home/maoqh/projects/ordessa/worktrees/platform-frontend | codex/010-platform-frontend | C |

方案树 /home/maoqh/projects/ordessa/worktrees/platform-plan 是文档锚点，不另开实现会话。根目录 main 保持不动。
Qoder 开新会话后先读本线规范，SPECIFY_FEATURE_DIRECTORY=specs/010-platform-core。允许阶段提交与本线子代理，不 push/main merge/跨树写。A 的契约 exact SHA 是 B 后半段前置；不需要用户手工复制代码。

整个目录随统一方案提交进入三树。只在自己的树勾 tasks；最终集成时合并勾选记录，不以对方未勾为自己受阻。共享语义更改需报主控。
