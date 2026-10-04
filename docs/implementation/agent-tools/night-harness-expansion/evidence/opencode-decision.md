# N004 OpenCode 原生通道决策与实现证据

2026-10-04。主执行者实现。真实模型0、安装0。官方资料：https://opencode.ai/docs/server/（2026-10-04 WebFetch两次，首次超时后重取成功）。

## L0 钉版与通道决策

| 项 | 值 |
| --- | --- |
| 选定通道 | 本地 HTTP Server（`opencode serve`）＋ SSE事件流（OpenAPI 3.1 规范运行时可取 `GET /doc`） |
| 备选比较 | headless/一次性CLI=有限能力不选；TUI内嵌serve（随机端口）语义不冒充独立server |
| release | **未钉**：官方文档未给release号，本机未安装CLI（不授权安装）→ artifact digest=unknown，登记"重装/安装后重钉" |
| 许可 | MIT（仓库许可，重钉时核实） |
| 启动 | `opencode serve [--port N] [--hostname 127.0.0.1]`（默认127.0.0.1:4096环回） |
| 认证 | `OPENCODE_SERVER_PASSWORD` basic auth（传输层）；provider凭据走 `PUT /auth/:id` |
| 会话 | `POST /session`（{parentID?,title?}）真实会话id；`GET /session/status` |
| 发送 | `POST /session/:id/message`（parts）= 回执≠完成；`POST /session/:id/prompt_async`=204受理 |
| 取消 | `POST /session/:id/abort`（显式停止） |
| 事件 | `GET /event`（server.connected→bus事件）/`GET /global/event`；**事件payload schema文档未写明**；全局事件按session过滤文档未写明→客户端按payload过滤、登记unknown |
| SSE断开 | 文档未写明与任务关系；abort是唯一显式停止→**断开≠完成**已固化实现+测试 |
| 升级边界 | 无版本协商（health报version）；升级重钉（G1） |

## 实现（CODE_READY＋L1）

| 交付 | 位置 | 测试 |
| --- | --- | --- |
| 客户端 | `native_clients/opencode.py`（OpenCodeClient：环回强制、health握手、session/message/prompt_async/abort、SSE未知保留、断开≠完成） | `test_opencode_client.py` **9P/0F** |
| 驱动 | `opencode/native_channel.py`（plan_launch环回+随机端口纯计划、compile_config发前拒、capability_matrix无observed-yes） | `test_opencode_native_channel.py` **11P/0F** |

反例：非环回拒（example.com/0.0.0.0/https）、500 typed且不重试（服务端计数==1）、SSE未知事件保留、断开非完成、未知路由typed、close后ChannelClosed、配置发前拒。
命令/退出码：`pytest plugins/harness/tests/opencode -q` 11P exit0；`pytest tests/native_clients/test_opencode_client.py -q` 9P exit0。

## 分账与缺口

- L0✓（文档钉协议；release未钉登记）；L1✓（20用例fake upstream标注）；**L2=未测**（本机无opencode CLI，安装待授权）；L3/L4未测。
- 事件payload/按session隔离/SSE断开终局=文档未写明→登记unknown，实现不臆造。
- 管理绑定依赖阻塞同N001；不发布runtimeReady。
- **待授权清单**：安装opencode CLI后重钉release/digest并补L2。
