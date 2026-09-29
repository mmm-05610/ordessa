# checkpoints.md — 绿色 checkpoint 台账

每个 checkpoint 记录：timestamp / commit / gates / real-product evidence /
known limitations / rollback target。后续改动不得无意识破坏最近绿色 checkpoint；
高风险修改失败且无法快速修时，回滚到最近绿色 checkpoint。

目标序列：C0 nightly baseline → C1 deb builds → C2 installed app launches →
C3 first real Harness → C4 Profile runtime path → C5 Skill/MCP → C6
multi-Harness → C7 hardened candidate → C-MC1 first Morning Candidate →
C-FINAL final release。

## 已达成

| ID | 时间 (Asia/Shanghai) | Commit | Gates | Real-product evidence | Known limitations | Rollback |
| --- | --- | --- | --- | --- | --- | --- |
| C0 | 2026-09-29 23:53+ | 见 evidence.md E-P0-4（本分支控制面首 commit） | 控制面 only：repo clean @ main `b4bf7cd909`；branch/worktree 建立；无产品改动 | n/a（Bootstrap） | 全部产品验收项未验证 | n/a（= main baseline） |
| C1 | 2026-09-30 00:5x | `aa3918092c`（NIGHTLY_TRUNK，deb 由该树构建） | `npm ci`✓；`npm run build`✓；`build:deb`✓；`npm test` 24/39（红全预存在，零新增）；桥可复现（`714044a5…` 二跑逐字节同） | deb `ordessa_0.1.0_amd64.deb`（205MB）sha256 `d7e4727e2720f1a590fb23d54a0556b096abf27004d34ee1eb069d5b8df55941`；payload 抽验：bundled python 可导入 ordessa_server/pacthold、`bin/acp` 与 manifest 一致、desktop entry/图标齐全 | 启动即崩（B-001）；deb 缺 server 闭包与 harnesses（B-002）；装机零扩展（B-003）→ C2 未达 | `aa3918092c` |

## 待达成

| ID | 定义 |
| --- | --- |
| C1 | NIGHTLY_TRUNK 上 `npm run build:deb` 成功，产出 amd64 deb |
| C2 | deb 真实安装成功，installed 应用正常启动（主窗口/renderer/extension 发现/bundled server） |
| C3 | 一个真实 Harness 完整任务：project→session→prompt→streaming→tool call→approval(如支持) |
| C4 | Profile 创建→Session 启动→配置实际进入 Harness runtime |
| C5 | Skill 产品级 smoke + MCP 产品级 smoke（Profile→MCP→Harness→Tool→Conversation UI） |
| C6 | 第二 Harness 真实 multi-harness 证据（同一 Session UI，session identity 隔离） |
| C7 | persistence/restart/error-handling 加固后的 candidate |
| C-MC1 | acceptance.md §Morning Candidate 18 条同时满足 |
| C-FINAL | 最终冻结 deb + SHA256 + final-report.md 完整 |
