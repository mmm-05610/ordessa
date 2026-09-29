1) 三个最重要的具体问题
- `plugins/assets/prompts/tests/test_g01_api_purity.py:226-235` — `test_boundary_scan_covers_the_new_harness_adapters_files` 的 `expected <= scanned` 两边都出自同一次 `PACKAGE_ROOT.rglob/_all_package_files()`，恒真可过；它并未真正证明"边界参数化的逐文件用例列表"含新子包文件（若参数化另有显式清单，该测试照样全绿），属空转覆盖而非实证。
- `plugins/assets/prompts/tests/test_g01_api_purity.py:183-190` — 注释引用的证明测试名 `test_published_harness_api_is_admissible_but_internals_refused` 与实际函数 `test_published_harness_api_admissible_but_internals_refused` 不一致；且 `_boundary_offenders([...])` 若是对白名单规则的"假想 import 模拟"而非实扫包内真实 import，则该"双向证明"只证明规则本身、不证明新 face 的真实导入面（需确认 helper 语义）。
- `plugins/assets/prompts/tests/test_prompts_citations.py:42-52` — 注释称"排除 registry schema 自身解析面"，实现却全扫 `plugins/harness/src`（含 schema.py）；当前能过反而印证注释失实。另 TOML:31/107/405、schema:64、HM:7/9/15-17 全为硬编码行号，harness/docs 侧一次行漂移即整片红，易诱导后人放宽断言。

2) fake green 迹象
无。未见删断言/skip/谎报：G01 白名单只增两项、敌例保留且另有双向测试；计数自洽（conformance 实数 19、brand_table 9、G01 增 2、citations 5 = 35 新函数 + 3 文件级参数化 = 38，149+38=187 与报告 T07 22→19 一致）；zero-consumers 与 hooks_target 两条主张确有实开核对测试（读真文件、断言真内容）。唯一隐忧是上述恒真式子集断言——属弱测试而非假绿。写入面无越界（仅 prompts/** + api-requests.md + reports/，账本补勾留所有者处置合理）。

3) 结论
有保留：内容与计数诚实、写入面干净，但边界"覆盖证明"存在恒真空转与注释/实名漂移，建议修一处断言口径后再收官。
