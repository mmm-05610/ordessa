# N010 Goose 原生通道决策与实现证据

2026-10-04。主执行者实现。真实模型0、安装0。官方资料：goose-docs.ai/docs/gdk/acp/（2026-10-04 WebFetch）。

## L0 钉版与通道决策

| 项 | 值 |
| --- | --- |
| 选定通道 | **goose 作ACP server**：stdio `goose acp`（client拥有进程生命周期）。备选 `goose serve`（HTTP/WS 127.0.0.1:3284 `/acp`，GOOSE_SERVER__SECRET_KEY+X-Secret-Key/?token=，--allowed-origin精确匹配）不选 |
| 身份区分（假设攻击点） | goose作ACP server ≠ goose用别人作provider——文档明确区分，channel_report固化 |
| 安全（假设攻击点） | `--dangerously-unauthenticated` 上游存在但文档限定本地隔离开发——**实现层硬拒**（plan_launch/compile_config双防线+测试反例）；secretKey配置键拒收 |
| 协议 | ACP v1标准 + goose扩展方法（独立reference页，未审阅）→扩展名登记unknown、见到即原样保留（G4） |
| release/许可 | 页面未载版本与许可（2026-04迁至AAIF，aaif-goose/goose）→unpinned登记，重钉时核实 |
| 会话语义 | 会话/权限细则页面未载→standard ACP处理+登记unknown |

## 实现（CODE_READY＋L1）

复用共享 `native_clients/_acp.py`（N008冻结）。`native_clients/goose.py`（GooseClient）＋`goose/native_channel.py`。

| 测试 | 数量 |
| --- | --- |
| `plugins/harness/tests/goose/test_goose_native_channel.py` | **7P/0F**（含--dangerously-unauthenticated硬拒反例） |
| `products/agent-tools/tests/native_clients/test_goose_client.py` | **5P/0F**（回调id=42保持、caller决定、_goose/*保留） |

命令/退出码（主执行者复跑）：goose+vibe驱动合跑 15P exit0；goose+vibe客户端合跑 10P exit0。

## 分账与缺口

- L0✓；L1✓（12用例）；**L2=未测**（无本机goose CLI，安装待授权）；L3/L4未测。
- goose扩展方法集、会话/权限细则=文档未写明→unknown；version/license=unpinned。
- 管理绑定依赖阻塞同N001；不发布runtimeReady。**待授权**：安装goose CLI重钉版本/许可补L2。
