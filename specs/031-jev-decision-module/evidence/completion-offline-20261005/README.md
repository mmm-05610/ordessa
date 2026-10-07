# 继续实施离线复验

完整套件 232 passed；67 个离线场景逐项 PASSED；固定基线/当前 57 个核心定向 ID 均通过且一致。回执 HEAD 为执行前检查点，source_digest 绑定实际被测源码。T60 在此离线入口仍 NOT_RUN，历史真实 Jev 结果仍 PARTIAL。

本次新增：任务证据摘要及引用进入问题/签名；只投影外部策略允许的字段，信任分类保持数据身份；公开 owner 退役/替换的观察窗口拒绝旧回执；记录写文件尝试及已有文件内容变化；冻结领域评测计划，预检在读 key 前完成，答案即时落盘，跨进程预算和未知调用不释放、不自动重发。假传输回执真实请求和模型质量计数均为 0。

原 single-result 正例只有泛化验收要求，不能据此断言 acceptance_unknown 是模型错误。旧失败、标签与阈值不改；新增完整 TaskBrief 及单维控制用于后续真实复验。原 9×6 编译错误混淆不同领域，prepare.py 改用冻结的 23 场景/42 请求计划，不追认旧计划有效。

[完整套件](full-suite.txt)、[机器回执](receipt.json)、[新评测预检](evaluation-prepared.json)、[评测收集器测试](evaluation-tests.txt)、[第一次收集器测试失败](initial-evaluation-failure.txt)。第一次收集器测试 3F/3P：持久目录未创建，修复后 6P；没有删断言或隐藏失败。公开 retire 测试先暴露测试未调用 drain，现按原生命周期完成退役并验证拒绝。新 core 测试 10P，任务门 31P。

真实 Harness/旧家族能力未验证，JD009 保留 PARTIAL；原生效果 0。完整 Server/Harness 继承红项未重跑；Python 3.10、真实断电、远程 FS 未验证。只写本树，没有服务重启、用户数据迁移、merge/push。

| 场景 | 状态 | 结果 | 日志 |
|---|---|---|---|
| T01 | PASSED | 6 passed in 0.31s | [证据](T01.txt) |
| T02 | PASSED | 2 passed in 0.22s | [证据](T02.txt) |
| T03 | PASSED | 4 passed in 0.27s | [证据](T03.txt) |
| T04 | PASSED | 2 passed in 0.27s | [证据](T04.txt) |
| T05 | PASSED | 3 passed in 0.25s | [证据](T05.txt) |
| T06 | PASSED | 3 passed in 0.12s | [证据](T06.txt) |
| T07 | PASSED | 1 passed in 0.04s | [证据](T07.txt) |
| T08 | PASSED | 1 passed in 0.04s | [证据](T08.txt) |
| T09 | PASSED | 1 passed in 0.04s | [证据](T09.txt) |
| T10 | PASSED | 2 passed in 0.23s | [证据](T10.txt) |
| T11 | PASSED | 1 passed in 0.07s | [证据](T11.txt) |
| T12 | PASSED | 1 passed in 0.08s | [证据](T12.txt) |
| T13 | PASSED | 1 passed in 0.07s | [证据](T13.txt) |
| T14 | PASSED | 4 passed in 0.26s | [证据](T14.txt) |
| T15 | PASSED | 1 passed in 0.08s | [证据](T15.txt) |
| T16 | PASSED | 4 passed in 0.18s | [证据](T16.txt) |
| T17 | PASSED | 1 passed in 0.04s | [证据](T17.txt) |
| T18 | PASSED | 1 passed in 0.04s | [证据](T18.txt) |
| T19 | PASSED | 2 passed in 0.18s | [证据](T19.txt) |
| T20 | PASSED | 2 passed in 0.22s | [证据](T20.txt) |
| T21 | PASSED | 7 passed in 0.28s | [证据](T21.txt) |
| T22 | PASSED | 12 passed in 0.78s | [证据](T22.txt) |
| T23 | PASSED | 1 passed in 0.07s | [证据](T23.txt) |
| T24 | PASSED | 8 passed in 0.59s | [证据](T24.txt) |
| T25 | PASSED | 15 passed in 0.13s | [证据](T25.txt) |
| T26 | PASSED | 6 passed in 0.10s | [证据](T26.txt) |
| T27 | PASSED | 6 passed in 0.56s | [证据](T27.txt) |
| T28 | PASSED | 3 passed in 0.14s | [证据](T28.txt) |
| T29 | PASSED | 4 passed in 0.07s | [证据](T29.txt) |
| T30 | PASSED | 3 passed in 0.22s | [证据](T30.txt) |
| T31 | PASSED | 17 passed in 0.13s | [证据](T31.txt) |
| T32 | PASSED | 5 passed in 0.06s | [证据](T32.txt) |
| T33 | PASSED | 8 passed in 0.27s | [证据](T33.txt) |
| T34 | PASSED | 5 passed in 0.18s | [证据](T34.txt) |
| T35 | PASSED | 12 passed in 0.20s | [证据](T35.txt) |
| T36 | PASSED | 17 passed in 0.21s | [证据](T36.txt) |
| T37 | PASSED | 9 passed in 0.23s | [证据](T37.txt) |
| T38 | PASSED | 3 passed in 0.23s | [证据](T38.txt) |
| T39 | PASSED | 2 passed in 0.18s | [证据](T39.txt) |
| T40 | PASSED | 2 passed in 0.18s | [证据](T40.txt) |
| T41 | PASSED | 1 passed in 0.17s | [证据](T41.txt) |
| T42 | PASSED | 1 passed in 0.18s | [证据](T42.txt) |
| T43 | PASSED | 13 passed in 0.13s | [证据](T43.txt) |
| T44 | PASSED | 1 passed in 0.08s | [证据](T44.txt) |
| T45 | PASSED | 6 passed in 0.10s | [证据](T45.txt) |
| T46 | PASSED | 4 passed in 0.09s | [证据](T46.txt) |
| T47 | PASSED | 2 passed in 0.09s | [证据](T47.txt) |
| T48 | PASSED | 3 passed in 0.11s | [证据](T48.txt) |
| T49 | PASSED | 14 passed in 0.40s | [证据](T49.txt) |
| T50 | PASSED | 8 passed in 0.10s | [证据](T50.txt) |
| T51 | PASSED | 6 passed in 0.09s | [证据](T51.txt) |
| T52 | PASSED | 1 passed in 0.08s | [证据](T52.txt) |
| T53 | PASSED | 4 passed in 0.09s | [证据](T53.txt) |
| T54 | PASSED | 6 passed in 0.32s | [证据](T54.txt) |
| T55 | PASSED | 4 passed in 0.34s | [证据](T55.txt) |
| T56 | PASSED | 1 passed in 0.13s | [证据](T56.txt) |
| T57 | PASSED | 12 passed in 0.17s | [证据](T57.txt) |
| T58 | PASSED | 11 passed in 0.29s | [证据](T58.txt) |
| T59 | PASSED | 8 passed in 0.41s | [证据](T59.txt) |
| T61 | PASSED | 2 passed in 0.20s | [证据](T61.txt) |
| T62 | PASSED | 4 passed in 0.21s | [证据](T62.txt) |
| T63 | PASSED | 1 passed in 0.21s | [证据](T63.txt) |
| T64 | PASSED | 1 passed in 0.02s | [证据](T64.txt) |
| T65 | PASSED | 7 passed in 0.14s | [证据](T65.txt) |
| T66 | PASSED | 3 passed in 0.32s | [证据](T66.txt) |
| T67 | PASSED | 3 passed in 0.21s | [证据](T67.txt) |
| T68 | PASSED | 4 passed in 0.25s | [证据](T68.txt) |

失败日志导出只移除了行末空格，原始日志保留于 .decision-tmp/completion-evaluation-tests.txt。

扩展后的默认离线入口实跑：完整232项通过后，67场景逐项通过。首次扩展运行已通过完整套件和T01，但 full_suite.command 中 PosixPath 不能JSON编码；改成字符串后全入口重跑通过。[保留失败](first-expanded-entry-failure.txt)，不是产品行为失败，未改变断言。
