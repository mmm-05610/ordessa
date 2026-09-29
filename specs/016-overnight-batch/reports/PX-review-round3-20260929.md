## 1) 最重要的具体问题

1. **PX-report.md:16(PX-0 表)vs PX-report.md「测试证据」节(~:88)——净增计数自相矛盾**:一处写"净增 33 条(新测试函数 29:…G01 增 1…)",另一处写"净增 32 条(…G01 增 2 函数…)";而 diff 实际新增 G01 测试 2 个(`test_boundary_scan_covers_...`、`test_published_harness_api_...`),即 9+19+2=30 函数 + 3 个新文件的参数化 = 33 才账实相符。第二轮声称"账实相符"但报告内部两节仍各错一处,149+33=182 只在"G01 增 2"口径下成立。

2. **plugins/assets/prompts/tests/test_prompts_adapters_conformance.py:207(`test_plugin_contributes_three_rows_conditionally`)——残留死代码**:先构造 `ServerPluginContext(..., data_root=None, ...)` 赋给 `context` 后完全未用,随即被 `ctx` 覆盖;与本轮"_VERSION 死代码删除"的自洁口径不一致,且 `data_root=None` 那次构造语义上就是无效上下文,易误导。

3. **plugins/assets/prompts/src/ordessa_prompts/harness_adapters/capabilities.py:38-42(GAP/TOML 行号)与 test_prompts_brand_table.py——证据链自证**:所有 `schema.py:64`、`harnesses.toml:31,107,405` 等引用只被断言为"表内字符串包含该子串"(regex `:\d+`),没有任何测试打开被引文件核对行号/事实;"evidence 是真实的"这一主张目前不可证伪,只能算文档级而非实证级。

## 2) fake green 迹象

**无实质 fake green**:未见断言删除/跳过/空测试;G01 白名单增两项有覆盖证明测试(`expected <= scanned`)和双向敌例测试(`ordessa_harness_api` 放行 + `ordessa_harness` 拒绝);compile 一律类型化拒绝而非伪造成功;assess 不高估为 compile 兑现不了的 status。轻微弱点:`test_payload_schema_documented_for_the_landing_day` 首句 `assert schema is not None` 恒真(后半段 enum 拒绝是真断言,可接受);brand_table 测试属自证式一致性检查(见问题 3)。

## 3) 结论

**有保留**——代码面诚实(写入面未越界、任务-代码一致、拒绝式 compile 可信),但 PX-report 的测试计数在两节间仍自相矛盾(本轮修复未收口),外加一处测试死代码与证据引用不可核,修正后可通过。
