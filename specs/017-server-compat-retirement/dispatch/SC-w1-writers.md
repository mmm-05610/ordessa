# SC 派工 · W-1 写入链死亡（当前唯一可派波次）

- 工作树：`worktrees/017-sc-w1`（复活推进 `codex/plugin-server-compat`，基=main）。
- 写入面：仅 `plugins/server-compat/**` 与 `specs/017-server-compat-retirement/reports/`。
- 参考：本目录 spec/plan/tasks（W-1 节）、两份 retirement-request（W1-W15/R1-R10）、
  seams.md S-08 锁序。
- 时序硬约束：仅 consolidation 后、core S-03 装配前的集成窗内执行；开工前在
  report 记录"窗口确认"（与 pi 对齐的证据）。
- 红线：apps/server/products 侧改动一律 AR 登记不代写；兼容回归退役断言逐条
  留名；无双写窗口声明。
