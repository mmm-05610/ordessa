1) 三个最重要问题

- `specs/016-overnight-batch/reports/PX-report.md`（测试证据节 / PX-0 表）:称新增 32 项、"brand_table 9 + conformance 23"，但 diff 内实数为 test_prompts_brand_table.py 9 项 + test_prompts_adapters_conformance.py 19 项（+ test_g01 新增 1 项）= 28/29，与 32、与 "181 passed" 的分解不符，账实对不上。
- `plugins/assets/prompts/tests/test_g01_api_purity.py:226` 新增的"双向边界证明"只对 `_boundary_offenders([...])` 合成入参断言，未对 `harness_adapters/{__init__,contribution}.py` 的真实导入做扫描；且 PLUGIN_ALLOWED_IMPORTS 未含 `ordessa_harness_api`——新模块若误引 `ordessa_harness.` 内部，现有测试抓不到，边界保证对新面只落在谓词上。
- `specs/016-overnight-batch/reports/PX-report.md`（复用与自建清单）写"仅扩展白名单一项"，而 `test_g01_api_purity.py` 白名单实加两条并在注释自称 "exactly TWO names"——上一轮已点名"白名单两项账实"，同一事项的口径仍不一致（另 `contribution.py:63` `_VERSION` 正则为死代码，小疵）。

2) fake green 迹象

无删断言/空测试/跳过式假绿：G01 敌例仍在且补了双侧测试，cited 格反例纪律有测试钉住且四家 phase-2 格补齐，compile 走诚实类型化拒绝而非编造 target，assess 不超报 status。唯一疑点是报告的 32/181 计数与树内可见测试数不符——属账实存疑而非断言造假，需执行者复跑给出真实计数。

3) 结论

**有保留**——写入面未越界、任务-代码口径基本一致、测试形态真实；但测试计数账实（32 vs 28）与 G01 边界扫描对新模块的覆盖缺口必须澄清/补测后方可通过。
