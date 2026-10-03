# chat-contribution — composer.footer 模型选择器（可选扩展 `ordessa.model-provider-chat`）

迁移自 `plugins/model-provider/chat-contribution` @ `9305563719d25e04076b9221a7284660bd8f8642`
（entry/selector/stub/测试逐字）。本线增量（authored）：

- `src/next-turn-client.ts`：排队消费端——经冻结的 `modelProvider.chooseForSession` wire 排队、
  pending-next-turn 状态、晚到/异会话结果按身份拒绝（MP-07）、draft 无原生会话即类型化拒绝、
  transport 缺席类型化拒绝（与 desktop 侧同纪律）。

**真实 chat-api 消费（2026-09-28 起）**：Z2 发布 chat-api READY（publication `54ad26c15d`，
implementationSha `a3ec20c046`，本树已按固定 SHA merge）。`src/chat-api-entry.tsx` 经真实契约
注册：token `ordessa.chat.contributions.v1`、`chatContribution()` 工厂、`composer.toolbar` 槽、
本域 key `ordessa.chat.model-selector` major 1；scope 关闭/ dispose 撤销即缺席对照。
**槽位映射记录**：设计稿写 "composer.footer"，但冻结 chat-api 的六槽位无 footer——composer
挂点是 `composer.toolbar`；如 Z2 之后冻结 footer 槽，切换是机械改动（一处槽位串+order）。

**stub 边界**：`stub-chat-contract.ts` 及其消费者测试保留为迁移史（E1 转录测试）；生产接线以
`chat-api-entry.tsx` 为准。真实 submit permit 闸门属 C0（REQ-Z3-2，OPEN）。

验证：包目录内 `node_modules/.bin/vitest run --maxWorkers=1` → 21 passed
（8 迁移 stub 测试 + 8 next-turn 消费端 + 5 真实注册表接线；各增量均先红 exit=1 后绿 exit=0）。
