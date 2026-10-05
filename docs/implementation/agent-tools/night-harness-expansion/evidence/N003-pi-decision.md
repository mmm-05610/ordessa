# N003 Pi 原生通道决策与实现证据

执行：主执行者+家族单元（客户端切片由子代理产出、主执行者复跑；驱动切片子代理中断，主执行者补完）。2026-10-04。真实模型调用0、安装0。

## 通道决策（L0）

- **选定通道**：pi 原生RPC（`pi --mode rpc`，严格JSONL）。官方SDK存在并随主包提供`createAgentSession`；原“未发现SDK”结论撤回。固定SHA13cbf77df2396303013a41646bcfa77b4271ae56的[SDK文档](https://github.com/earendil-works/pi/blob/13cbf77df2396303013a41646bcfa77b4271ae56/packages/coding-agent/docs/sdk.md)已核对。当前选择原生RPC以复用已安装CLI及进程隔离边界，不另造SDK执行引擎；旧pi-acp资产版本不同，不作为本次运行fallback。
- **钉版**：release 0.86.1（受管安装 `install/current-version`）；`@earendil-works/pi-coding-agent` 0.86.1，MIT；artifact `dist/bundle/cli.js`+chunks（cli.js sha256前40位 `e79626f2dd6f94aa45d30f3fa63cd84319a6eefc`，**全量bundle digest登记为未补**）；协议来源 `packages/coding-agent/docs/rpc.md`+`rpc-commands.md`（2026-10-04 WebFetch）。
- **升级边界**：无版本协商（文档未写明），钉版本+升级重钉（G1）。resume/replay语义文档未写明→登记unknown，不臆造。
- **假设攻击结论**：prompt回执≠完成；固定0.86.1真实成功回执没有data.disposition，原文及fixture对此有误，2026-10-05已修消费者。仅agent_settled作为该次稳定观察，agent_end不单独证明稳定；steer/abort区分实现（cancel=abort+可选clear_queue）；extension UI双向id保留；真实版本0.86.1与旧pi-acp资产无关（不沿用旧桥结论）。

## 实现（CODE_READY＋L2 partial）

| 交付 | 位置 | 测试 |
| --- | --- | --- |
| 消费者客户端 | `products/agent-tools/src/ordessa_agent_tools/native_clients/pi.py`（PiRpcClient：initialize=get_state握手、send_prompt原样disposition、wait_settled、cancel、reply_extension_ui、未知保留） | `tests/native_clients/test_pi_client.py` **14P/0F** |
| Harness驱动 | `plugins/harness/src/ordessa_harness/pi/native_channel.py`（channel_report/plan_launch纯计划/compile_config发前拒G3/capability_matrix三态） | `tests/pi/test_native_channel.py` **13P/0F** |
| 真实进程证据 | `N001-vertical-entry.md`＋`N001-vertical-pi-rpc.txt`（get_state握手、能力发现、未知命令/非法JSON反例、exit 0） | L2 partial（主执行者亲跑） |

命令与退出码（主执行者复跑）：
```
python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/native_clients/test_pi_client.py -q   # 14 passed, exit 0
python -m pytest plugins/harness/tests/pi -q -p no:cacheprovider                                                          # 13 passed, exit 0
```

## 分账与缺口

- L0✓（钉版/许可/协议）；L1✓（27 fixture用例）；**L2 partial✓**（真实0.86.1进程隔离握手/状态/能力发现/退出）；L2未覆盖：会话持久化（--session-dir）、prompt受理到settled全链、steer/abort实测、extension UI实测；L3/L4未测。
- capability_matrix 诚实三态：observed仅 unknownExtensions/requestReconciliation（+prompt receipt）；transportFence/resume=无。
- 管理绑定（节点/任务/持久attempt）**依赖阻塞**（029 AT-009/010/011）；不发布runtimeReady。

## 事故记录（诚实登记）

N003客户端切片子代理的**最终报告**出现幻觉内容（提及不存在的xrm/FakeXrmEasy路径与计数），但其**落盘文件**经主执行者全文审查与复跑验证为正确实现（grep无幻觉残留，14P真实通过）；驱动切片子代理中途失败（model request failed），产物截断于plan_launch，由主执行者补完+补测试。子代理报告一律不作为验收依据，只认复跑结果。

2026-10-05更新：上述14P与27用例是历史快照。当前消费者另有真实形状及unknown反例，最终计数按本树status最新复跑记录，不累加旧快照。未新增Pi真实进程/模型证据。
