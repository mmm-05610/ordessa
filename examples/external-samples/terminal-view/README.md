# External sample #3 — terminal/document（非 Chat，sample-terminal/1）

## Owner
`ordessa.sample-terminal`（`ordessa_sample_terminal`）。独立发行 `ordessa-sample-terminal`，
唯一运行时依赖 `ordessa-server-plugin-api`。零 Agent/Chat/Profile——T007-09/T009-07 的三样例之三。

## 公开能力
| 方法 | 语义 |
| --- | --- |
| `sample.terminal.capabilities` | 声明 viewKind=terminal-document、interactionSchema=sample-terminal/1、writable=false、reliableSubmission=unsupported（typed：只读面拒控制请求，不静默降级） |
| `sample.terminal.open` | 打开冻结文档（幂等 requestId 纪律，8..128 字符） |
| `sample.terminal.read` | 只读文档内容（sha256 锚定）；未知 id → NOT_FOUND |

## 缺席行为
未 start/已 stop → typed 拒（ROUND 门）；不支持写入/可靠提交——typed unsupported，绝不空成功。

## 生命周期
安装不启用；仅显式 `server_plugins=(SampleTerminalPlugin(),)` 装配。退出随轮次注销，零数据根写入。

验证：`pip install -e examples/external-samples/terminal-view && pytest examples/external-samples/terminal-view -q`。
