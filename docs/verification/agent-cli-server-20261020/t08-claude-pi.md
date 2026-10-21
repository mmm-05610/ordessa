# T08：claude / pi 真实回合尝试（2026-10-21）

两者都**真实 start 成功**，但 prompt 端受各自本机登录状态限制，没有真实 answer——如实记录，不算通过。

## claude：start ✅ / prompt ⛔（未登录）

- 真实 `agents.start(fresh)` completed，sessionId `6e5b2f80-e8d7-4652-98fe-214bf52de629`；
- `agents.prompt` completed（delivery=confirmed），但原生结果原文：
  **`"result": "Not logged in · Please run /login"`**（protocol `claude-stream-json/1`）。
- 即：协议链路通，**Claude Code 本机未登录**。修法：你在终端 `claude` 里 `/login`，之后同一脚本即可出 answer。

## pi：start ✅ / prompt ⛔（超时，疑似未登录）

- 真实 `agents.start(fresh)` completed，原生 sessionId `01a15cfd-597c-7050-b508-0b488ce8f9ef`（pi RPC）；
- `agents.prompt` → `EFFECT_UNKNOWN: Response was not observed before the timeout`（120s deadline 仍未观测到回合完成）；
- 原生 rollout 无 task_complete 记录 → 与 claude 类似，最可能是 **pi 未登录/无可用模型凭据**，回合卡住直到超时。
- 未重试第二次（预算内但无意义）；需要先在本机完成 `pi` 登录再验。

## 清理

两次运行均执行 stop/reconcile/process-release/release；脚本残留检查 `[]`；无遗留 Server 进程。

## 结论

claude / pi 的**会话与协议链路已打通**（start 真跑），但"真实派活"需要你先在这两台 CLI 里登录；
在登录前它们在 T08 矩阵里记 **PARTIAL（start 通过，prompt 未通过）**，不记为成功。
