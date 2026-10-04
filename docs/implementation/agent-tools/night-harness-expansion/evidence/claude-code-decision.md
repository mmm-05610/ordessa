# N005 Claude Code 原生通道决策与实现证据

2026-10-04。主执行者实现。真实模型0、安装0。官方资料：code.claude.com/docs/en/agent-sdk/overview＋/headless（2026-10-04 WebFetch）。

## L0 钉版与通道决策

| 项 | 值 |
| --- | --- |
| 选定通道 | **Claude Agent SDK**（运行Claude Code二进制）；CLI headless `claude -p --output-format stream-json` 为可直接驱动的JSONL面；ACP仅备选（本页无证据启用） |
| 明确区分 | Agent SDK ≠ Anthropic Client SDK（API客户端）≠ Managed Agents（托管）——已在channel_report固化 |
| release | **未钉**（本机无claude CLI/SDK实物，不安装）→ digest=unknown，登记待安装重钉 |
| 协议 | stdout stream-json消息类型：system/init（含capabilities数组如interrupt_receipt_v1）、system/api_retry、system/plugin_install、assistant/user（parent_tool_use_id）、stream_event、permission_denied、result（终态：result文本、session_id、cost、permission_denials）。stdin侧 `--input-format stream-json` 仅SDK面存在、headless文档未钉→**登记unknown不臆造** |
| 会话 | result记录携带session_id；`--resume <id|jsonl路径>`/`--continue`（v2.1.223+跨目录） |
| 取消 | SIGINT结束turn；SDK `interrupt()`；capabilities `interrupt_receipt_v1` |
| 权限 | SDK `canUseTool`回调；CLI `--permission-mode`/`--permission-prompts`。**永不auto-approve** |
| 认证/条款 | API key为官方认可路径；**claude.ai OAuth/订阅登录不得对第三方产品提供**（文档明示，本实现不读用户订阅token）；商用受Anthropic Commercial Terms约束（组件LICENSE可覆盖）——逐项记录于channel_report.license_terms |
| 升级边界 | 无版本协商（init的capabilities作特性探测）；升级重钉（G1） |
| G11注意 | 上游自带API级重试（system/api_retry：attempt/max_retries）——作为事实透出，**本栈不加任何重试** |

## 实现（CODE_READY＋L1）

| 交付 | 位置 | 测试 |
| --- | --- | --- |
| 客户端 | `native_clients/claude_code.py`（ClaudeCodeClient：system/init握手+capabilities、wait_result终态、api_retry事实透出、SIGINT取消、未知记录保留） | `test_claude_code_client.py` **5P/0F** |
| 驱动 | `claude/native_channel.py`（双身份claude/claude-code不改名、plan_launch纯计划、subscriptionToken等发前拒、capability_matrix无observed-yes） | `test_claude_native_channel.py` **11P/0F** |

反例：subscriptionToken/hotModelSwitch/未知键发前拒（G3/G12）、api_retry事实不隐藏不加码（G11）、未知记录保留（G4）、wait超时→unknown不重发（G6/G11）、close后ChannelClosed。接缝补强：`ProcessChannel.sigint()`（仅信号owned进程G8）；`next_message`关闭语义收紧（关闭后一律ChannelClosed，反例测试抓到旧缺陷并修复）。

命令/退出码（主执行者复跑）：`pytest plugins/harness/tests/claude -q` 11P exit0；`pytest tests/native_clients/test_claude_code_client.py -q` 5P exit0；全 native_clients 回归 88P exit0。

## 分账与缺口

- L0✓（协议+条款）；L1✓（16用例）；**L2=未测**（无本机CLI/SDK，安装待授权）；L3/L4未测。
- stdin stream-json消息形状、canUseTool请求形状=文档未写明→unknown登记。
- 管理绑定依赖阻塞同N001；不发布runtimeReady。
- **待授权清单**：安装Claude Code CLI/Agent SDK后重钉版本与digest、补L2，并复核SDK分发条款适用性。
