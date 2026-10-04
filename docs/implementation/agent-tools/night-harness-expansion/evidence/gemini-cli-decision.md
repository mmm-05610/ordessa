# N008 Gemini CLI 原生通道决策与实现证据

2026-10-04。主执行者实现。真实模型0、安装0。官方资料：geminicli.com/docs/cli/acp-mode/＋agentclientprotocol.com/protocol（2026-10-04 WebFetch）。

## L0 钉版与通道决策

| 项 | 值 |
| --- | --- |
| 选定通道 | **官方ACP**：`gemini --acp`（stdio JSON-RPC 2.0）。headless JSON=有限备选，不冒充持续双向通道（假设攻击点已固化） |
| 协议 | ACP v1规范（agentclientprotocol.com/protocol/v1/schema）：initialize版本协商、session/new、session/prompt、session/cancel（通知）、session/load（可选）；反向 session/request_permission、fs/read_text_file、fs/write_text_file（proxied FS：agent只碰client允许的文件）、terminal/*、elicitation/*；`_`前缀自定义方法与`_meta`=未知扩展保留约定（G4） |
| 文档差异登记 | gemini页面用驼峰名（newSession/loadSession等）且未写terminal回调；ACP规范原文为session/new等+terminal集——按规范实现，页面级未写明登记unknown |
| release | 未钉（本机无gemini CLI，不安装）→ digest=unknown |
| 特性边界 | `unstable_setSessionModel`（不稳定，登记不依赖）；`setSessionMode`审批级；同引擎≠TUI全命令可用（文档无清单→登记unknown） |
| 认证/遥测 | authenticate方法；`GEMINI_TELEMETRY_*` env存在→计划中钉false（G12）；用户~/.gemini不读 |

## 实现（CODE_READY＋L1）

**共享抽取决策**：gemini/goose/vibe三家同消费ACP v1→按design§3「只有实际复用才抽取」冻结 `native_clients/_acp.py`（AcpClient基类：initialize版本协商、session/*、request_permission同id应答永不auto、cancel通知、未知/`_`方法保留、G11失回执）。

| 交付 | 位置 | 测试 |
| --- | --- | --- |
| 客户端 | `native_clients/gemini_cli.py`（GeminiCliClient(AcpClient)） | `test_gemini_cli_client.py` **8P/0F** |
| 驱动 | `gemini_cli/native_channel.py`（telemetry钉false、oauthToken发前拒、unstable登记） | `test_gemini_cli_native_channel.py` **8P/0F** |

反例：权限回调id保持（77）且caller决定、`_gemini/customEvent`原样保留、cancel通知不阻塞、hang方法超时→RequestTimeout unknown、远程错误typed、oauthToken/未知键发前拒。
命令/退出码（主执行者复跑）：`pytest plugins/harness/tests/gemini_cli -q` 8P exit0；`pytest tests/native_clients/test_gemini_cli_client.py -q` 8P exit0。

## 分账与缺口

- L0✓（ACP规范+gemini页面双源）；L1✓（16用例）；**L2=未测**（无本机CLI，安装待授权）；L3/L4未测。
- terminal回调在gemini页面未写明→按ACP规范声明、页面级unknown登记；TUI特性差距清单=文档未写明。
- 管理绑定依赖阻塞同N001；不发布runtimeReady。
- **待授权清单**：安装Gemini CLI后重钉版本/digest、补L2、核实setSessionMode与审批流实际形态。
