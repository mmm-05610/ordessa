# N003 Pi 原生通道决策与实现证据

执行：主执行者+家族单元（客户端切片由子代理产出、主执行者复跑；驱动切片子代理中断，主执行者补完）。2026-10-04。真实模型调用0、安装0。

## 通道决策（L0）

- **选定通道**：pi 原生RPC（`pi --mode rpc`，严格JSONL）。官方SDK：未发现需比较的独立公开SDK（docs仅RPC/extension UI页）；ACP非主入口，不选。
- **钉版**：release 0.86.1（受管安装 `install/current-version`）；`@earendil-works/pi-coding-agent` 0.86.1，MIT；artifact `dist/bundle/cli.js`+chunks（cli.js sha256前40位 `e79626f2dd6f94aa45d30f3fa63cd84319a6eefc`，**全量bundle digest登记为未补**）；协议来源 `packages/coding-agent/docs/rpc.md`+`rpc-commands.md`（2026-10-04 WebFetch）。
- **升级边界**：无版本协商（文档未写明），钉版本+升级重钉（G1）。resume/replay语义文档未写明→登记unknown，不臆造。
- **假设攻击结论**：prompt回执≠完成（disposition started/handled；仅agent_settled稳定）——实现按此；steer/abort区分实现（cancel=abort+可选clear_queue）；extension UI双向id保留；真实版本0.86.1与旧pi-acp资产无关（不沿用旧桥结论）。

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
