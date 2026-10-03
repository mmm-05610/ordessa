# T010-04 操作语义六项 → 钉面映射

| 语义 | 钉面 | 状态 |
| --- | --- | --- |
| present/unset 字段 | `plugins/agent/contracts/tests/local-owner-port.test.ts`（present+unset 单回执、fields 投影）；selection.ts 全部写点用 unset 清字段 | 既有 |
| provider/model 原子组 | `chat-contribution/tests/next-turn-client.test.tsx`（新）：半对答案拒绝 OPERATION_UNKNOWN、owner 无半对落盘 | 新钉 |
| 点击 seq | `profile/integrations/chat/tests/click-registration.test.ts`（串行点击序、每点击新登记）；glue enqueueClick 序列 | 既有 |
| 异步解析归序 | `next-turn-client.test.tsx`（外来会话迟到 resolution 拒绝、旧序 resolution 拒绝、M12 ack 围栏） | 既有 |
| 目录版本不追改 capture | `profile/integrations/chat/tests/selection.test.ts`（新）：目录 v2 改名/重分组后 capture 身份与标签不变；同预设重选=新操作非改写 | 新钉 |
| 同 Profile 重选新 opId | `local-owner-port.test.ts`（同值重选新 operationId、revision 计数）；`selection-owner.test.ts`（store 层同款） | 既有 |

复核命令（均绿于收口时点）：
- `npx vitest run --root plugins/model-provider/chat-contribution` → 118F
- `npx vitest run --root plugins/profile/integrations/chat` → 93F
- `npx vitest run --root plugins/agent/contracts` → 16F
