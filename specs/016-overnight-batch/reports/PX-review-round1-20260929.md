**1) 三条最重要问题**

1. `plugins/assets/prompts/src/ordessa_prompts/harness_adapters/capabilities.py:39-41` — `HM` 用 `"docs/design/prompts/harness-configuration-hm".replace(...)` 拼出的是 `docs/design/prompts/prompts/harness-adapters.md`（目录 `prompts/` 重复），与 contribution.py 文档串里的 `docs/design/prompts/harness-adapters.md` 不一致；全部能力格的引用都是错路径，而 `test_prompts_brand_table.py:51` 只做 `"harness-adapters.md:9" in evidence` 子串断言，错引用照样全绿。
2. `plugins/assets/prompts/tests/test_g01_api_purity.py:189-195` — 任务口径是「G01 白名单仅扩一项」，实际扩了**两项**（`ordessa_prompts.harness_adapters` + `.contribution`）；且注释称修订「documented in PX-report.md」，但本 diff 里没有 PX-report.md（diff 远未到 120KB 截断线），R0 补账/修订记录在本次改动中无处可查。
3. `plugins/assets/prompts/tests/test_prompts_brand_table.py:24-35` — 测试名宣称 counterexample discipline，却对 `counterexample` 零断言（多数格子反例为空也通过），与 EXT-01「每格须有反例」口径不符；同理 `test_g01_api_purity.py` 注释声称 `ordessa_harness_api`「只在子模块内可导入、由 exact-prefix 规则管辖」，diff 中未见任何测试证明该管辖对新模块（contribution.py 顶层即 import `ordessa_harness_api`）生效。

**2) fake green 迹象**

无删断言、无 skip、无谎报；G01 仅扩白名单未动断言，compile/assess 一致按 AR-6 fail-closed。但存在"弱断言放行坏数据"（错路径引用经子串断言过关）和名不副实的测试（counterexample 断言缺位、`assert schema is not None` 形同虚设），属测试不够真而非 fake green。

**3) 结论**

有保留：写入面无越界（compile 全拒、claims 为空、仅经发布 point 注册），任务与代码基本一致，但 HM 引用路径 bug 与"白名单仅扩一项/PX-report 补账"两处账实不符需修正后才可放行。
