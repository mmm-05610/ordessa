# N012 安全审查记录（safety-reviewer 全批复查）

2026-10-04。审查对象：030批次全部 `native_clients/*`（13文件）与10个家族 `native_channel.py`。审查代理只读复查，发现清单如下；**严重/中等项已由主执行者修复并补钉回归测试**，较低项如实登记遗留。真实模型0。

## 已修复（附回归钉测）

| 编号 | 严重度 | 问题 | 修复 | 钉测 |
| --- | --- | --- | --- | --- |
| S1 | 严重 | pi失回执后wait_settled假报"no-run"（unknown状态从未赋值） | send_prompt失回执/未知disposition→`_run_state="unknown"`；wait_settled对unknown返回`{"outcome":"unknown"}` | `test_l1_lost_receipt_marks_unknown_not_no_run` |
| S2 | 严重 | codex reply_approval带amendment时静默覆盖decision（decline可变acceptWithExecpolicyAmendment） | amendment必须配显式decision=`acceptWithExecpolicyAmendment`，否则ValueError | `test_declined_decision_is_never_upgraded_by_amendment` |
| M1 | 中 | copilot FORBIDDEN_AUTO_APPROVE_FLAGS死代码，plan_launch不拒 | plan_launch逐token硬拒（含`=`变体） | `test_plan_launch_refuses_auto_approve_flags`（×4） |
| M2 | 中 | goose禁flag仅plan层精确匹配，客户端launch无围栏 | GooseClient.launch spawn前拒收（前缀归一匹配）；plan层支持`=`变体 | `test_launch_refuses_unauthenticated_flag_before_spawn` |
| M3 | 中 | claude/goose/gemini审批模式值直通（bypassPermissions/auto等=auto-approve路径） | compile_config值域守卫：bypass/auto/acceptAll/yolo类一律ConfigRefusal | `test_auto_approve_permission_modes_are_refused`（×4） |
| M4 | 中 | kimi/copilot超时迟到回执被埋`_responses`永不出事件流（违背G4 verbatim承诺） | 迟到回执同时入`_events`（保verbatim） | 既有未知保留测试覆盖，146P回归绿 |
| M5 | 中 | `_http` SSE尺寸上限误按整流累计（长流误报FramingError） | 事件边界重置计数（上限=单事件） | 既有SSE测试回归绿 |
| M6 | 中 | `_http` request_json混淆"未发出"与"已发出失回执" | 发出后I/O失败→`LostReceipt`（unknown语义），未发出→`HTTP_IO_ERROR` | 既有测试回归绿 |
| L1 | 低 | TurnFailed继承ChannelClosed（终态失败被误当可重发） | 改继承ChannelFailure，code=TURN_FAILED | `test_turn_failed_is_not_a_channel_closed_condition` |

另修复L4（`isolated_env`凭据阻断清单补 COPILOT_GITHUB_TOKEN/COPILOT_SDK_AUTH_TOKEN/AWS_ACCESS_KEY_ID/GOOGLE_APPLICATION_CREDENTIALS/HF_TOKEN/NETRC/SSH_AUTH_SOCK/KIMI/QWEN/DASHSCOPE/MOONSHOT/MISTRAL/VIBE/GOOSE API键）与L6的BrokenPipe语义措辞（部分写=unknown）。

## 遗留登记（如实，不隐瞒）

| 编号 | 项 | 现状 | 处置 |
| --- | --- | --- | --- |
| L2 | kimi replay围栏仅覆盖replay在途窗口，晚到重放帧可应答历史审批 | 未修（需上游replay响应内requests计数核对，语义未文档化） | **已知限制**：replay后仍须调用方保持审批不auto；列入待决项 |
| L3 | wait_turn_completed/wait_idle不校验turnId/sessionId（他turn/他session完成可误配） | 未修（需API加过滤参数） | **已知限制**：单session用法不受影响；多session调用方须自行核对 |
| L5 | opencode/claude启动pin声明未完全实现（autoupdate/hooks面） | 各家族report已登记unknown | 保持登记 |
| L6残余 | localhost名字解析依赖NSS、kimi pump重复request帧不进events、copilot protocolVersion非数值抛裸ValueError | 未修（局部语义小缺口） | **已知限制**登记 |
| — | registry注册、L2真实进程、L3/L4 | 见各家族决策报告与矩阵 | 待授权清单 |

## 已核实无问题（审查代理结论摘要）

G11无隐藏retry/reconnect/自动resume（全部等待环带deadline、失回执保留unknown、SSE retry字段只作数据保留）；G7事件表/pending均为实例级无共享；G8仅owned进程清理、无pkill、退出不假completed；G9/G12主审批路径无auto-approve、无凭据注入、环回强制、copilot SDK下载/kimi CDN installer/vibe installer均有围栏。

## 回归命令（主执行者复跑，修复后）

```
pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/native_clients/ -q   # 146 passed, exit 0
pytest plugins/harness/tests/{claude,copilot,goose,...} -q                                     # 49+86 passed, exit 0
```
