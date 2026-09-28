# P-A 派工 · runtime-preferences

- 工作树：`worktrees/015-a-runtime-preferences`（新支 `codex/plugin-runtime-preferences`，
  **基于 main 直接拉**，不 merge 任何插件分支）。
- 写入面：仅 `plugins/assets/runtime-preferences/**` 与 `specs/015-runtime-preferences-memory/reports/`。
  其余一律只读；需要别域改动时写入 api-requests 回报。
- 参考（只读）：`specs/015-runtime-preferences-memory/{spec,plan,tasks,api-requests}.md`、
  `docs/design/runtime-preferences/README.md`、`docs/design/harness-configuration/*`、
  `plugins/assets/model-provider/adapters/`（形制范本，不 import）。
- 红线：spec.md 共同红线全条适用；证据等级=文档级起步，逐键升级靠固定源码/受控探针；
  不 fake green。
