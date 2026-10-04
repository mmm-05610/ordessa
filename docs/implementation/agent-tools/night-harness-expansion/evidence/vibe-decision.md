# N011 Mistral Vibe 原生通道决策与实现证据

2026-10-04。主执行者实现。真实模型0、安装0。官方资料：docs.mistral.ai/vibe/code/use-vibe-in-other-ides（2026-10-04 WebFetch）。

## L0 钉版与通道决策

| 项 | 值 |
| --- | --- |
| 选定通道 | Vibe 实现 **ACP**（ACP registry发布；经IDE/registry接入）。页面**未载独立server命令**→启动argv形状unpinned登记，`plan_launch`的entry由调用方提供、不臆造 |
| 共享home危害（假设攻击点） | Vibe凭据存 `~/.vibe/` 且跨CLI/VS Code复用；agents/skills/MCP/profiles加载自 `~/.vibe/` 与项目 `.vibe/`——实现层 **VIBE_HOME重定向进scratch**＋用户~/.vibe永不读（G12），测试反例钉住 |
| installer危害（假设攻击点） | 上游setup流可能改uv/全局环境→**本夜不运行任何installer**（登记为注意事项） |
| IDE上下文 | 文档以IDE为前提但不保证已提供→登记unknown，不默认具备 |
| 协议 | ACP v1；Vibe ACP扩展未在页面枚举→unknown登记、见到即保留（G4） |
| 认证 | Mistral API key（bundled setup flow）；mistralApiKey配置键拒收 |
| release/许可 | 页面未载→unpinned登记 |

## 实现（CODE_READY＋L1）

复用共享 `native_clients/_acp.py`。`native_clients/vibe.py`（VibeClient）＋`vibe/native_channel.py`。

| 测试 | 数量 |
| --- | --- |
| `plugins/harness/tests/vibe/test_vibe_native_channel.py` | **8P/0F**（VIBE_HOME重定向、凭据键拒收） |
| `products/agent-tools/tests/native_clients/test_vibe_client.py` | **5P/0F**（loadSession能力诚实、_vibe/*保留、hang超时unknown） |

命令/退出码（主执行者复跑）：goose+vibe驱动合跑 15P exit0；goose+vibe客户端合跑 10P exit0。

## 分账与缺口

- L0✓；L1✓（13用例）；**L2=未测**（无本机vibe，且页面无server命令——安装授权后先钉启动形状再测）；L3/L4未测。
- 启动形状/ACP扩展/IDE上下文=文档未写明→unknown。
- 管理绑定依赖阻塞同N001；不发布runtimeReady。**待授权**：安装Vibe后重钉release/启动形状补L2。
