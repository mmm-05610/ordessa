# T08：kilo 真实 prompt（OpenCode Go / deepseek-v4.1-flash）

## 结论：✅ SUCCESS（真实模型调用 1 次）

链路：真实 `ordessa-server`（显式配置，`requestDeadlineSeconds=120`）+ 真实 `ordessa` 客户端
+ local environment + kilo Profile（revision 0.1.0）+ kilo ACP provider。

- `agents.start(fresh)` → completed，真实 sessionId `ses_ea310d773ffelel6SEqNt2vBUD`
- `agents.prompt`（「计算 17*23，只回复数字。」）→ **completed**，
  turnId `turn/8212a44e…`，`delivery=confirmed`，`state=completed`，observationBytes 含 ACP `session/update` 帧
- **真实 answer `391`**（从 `session/update` 的 `content.text` 提取，不是模型自述转述）
- 模型/通道：`deepseek-v4.1-flash` @ `https://opencode.ai/zen/go/v1`，
  key 经 `envFrom: KILO_PROVIDER_KEY ← OPEN_CODE_GO_API_KEY` 注入进程环境（未落盘）
- 清理：`agents.stop` completed（terminate requested）；process-release/release exit 0；工作区残留进程 `[]`
- 预算：**1 次**真实调用（此前 30s deadline 的一次尝试因超时返回 EFFECT_UNKNOWN，未产生 answer；
  本次用新加的 `access.requestDeadlineSeconds=120` 成功——这是 deadline 可配置特性的第一个实战验证）

## 附：第一次失败（保留）

30s 默认 deadline 下 prompt 返回 `EFFECT_UNKNOWN`（客户端超时），但 Agent 会话真实创建成功；
说明 kilo 的 ACP 回合 >30s，**必须**可配置 deadline。原始日志在 `raw/t08-kilo-prompt.log` 的两次运行片段。
