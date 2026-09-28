# P-B 派工 · memory

- 工作树：`worktrees/015-b-memory`（新支 `codex/plugin-memory`；基线 = main + merge
  `codex/plugin-model-provider` + merge `codex/plugin-prompts`，**以派出时两支的最新
  实态为准**——建议在 014 及 prompts 收尾并回后开树）。
- 写入面：仅 `plugins/assets/memory/**` 与 `specs/015-runtime-preferences-memory/reports/`。
- 参考（只读）：`specs/015-runtime-preferences-memory/{spec,plan,tasks,api-requests}.md`、
  `docs/design/runtime-preferences/README.md`（§3 上游事实全表）、mem0 server 事实
  （plan.md F5-F7，来源 mem0ai/mem0 main，2026-09-28）。
- 特别约束：
  1. 真实模型调用禁止（E3）；一切抽取/embedding 测试走假 OpenAI 兼容端点（E2）。
  2. Docker/compose 前置缺失时置备器必须返回 unsupported，不得造本地假实现冒充。
  3. mem0 上游代码不拷入本仓；版本 pin + SHA 记录在 report。
  4. `.env`/数据/记忆正文只在产品 data-root（环境例外目录），绝不入库。
- 红线：spec.md 共同红线全条适用。
