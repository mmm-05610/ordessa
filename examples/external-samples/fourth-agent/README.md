# External sample #1 — fourth controlled agent (`sample-agent/1`)

## Owner

`ordessa.sample-fourth-agent`（`ordessa_sample_fourth_agent`）。独立发行
`ordessa-sample-fourth-agent`，唯一运行时依赖 `ordessa-server-plugin-api`。本包是
spec 026 T007-09 外部样例 #1：证明公开合同能容纳**异协议**参与者（非三品牌、非 ACP），
且不依赖 Agent/Profile/Chat。

## 公开能力

| 方法 | 语义 |
| --- | --- |
| `sample.agent.capabilities` | 声明 `interactionSchema: "sample-agent/1"`（≠acp）、`reliableSubmission: "unsupported"`（typed 声明：无指纹/无 durable intent；可靠请求发前拒，raw 不受影响）、`history: "unsupported"` |
| `sample.agent.status` | 只读状态（受控假交互，零模型调用） |
| `sample.agent.echo` | 稳定 requestId 幂等账：同 id 同 payload 重放同 receipt；同 id 异 payload → typed `REQUEST_DIGEST_CONFLICT`（绝不二次派发） |

## 缺席行为

- 未 start 的 round 上所有方法 typed 拒（`ROUND_NOT_STARTED`）；stop 后随轮次注销。
- 不提供订阅/流/交互应答面；不声明任何 capability 给其他插件消费（`provided_ports={}`）。
- 无真实 Agent：echo 是确定性假交互，不是模型能力。

## 生命周期

安装不启用（无 entry point）；仅显式 `server_plugins=(SampleFourthAgentPlugin(),)`
装配。退出：`runtime.stop()` 后方法注销、内存幂等账随组合销毁、无数据根写入。

验证：`pip install -e examples/external-samples/fourth-agent && pytest examples/external-samples/fourth-agent -q`。
