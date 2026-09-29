1. 最重要的问题（≤3）
- `specs/016-overnight-batch/reports/PX-report.md:20`(PX-0 表)与 `:99-101`(测试证据节)：声称的"统一为 186/净增 37"修复**在 diff 中不存在**——两处仍是 182 collected，且各自算术不自洽（"新函数 29 + 3 参数化 = 32 ≠ 33"；"9+19+2+3 = 33 ≠ 32"）；树内新增实为 brand_table 9 + conformance 19 + G01 2 + citations 4 + 参数化 3 = 37 → 应为 186。收官声明与产物不符。
- `plugins/assets/prompts/tests/test_prompts_citations.py:33-38`（`test_schema_line_64_is_the_profile_field_gate`）：GAP 引文断言只核 line 64 含 `native_home`+`slots`，"slots parsed" 与 64 行的绑定偏松；且 HM:18/19/20/22、TOML:163/215/270/357、packaging/*:45-46 等大量引文未开卷，"证据链可证伪"仅覆盖小子集（docstring 自认，属保留项而非造假）。
- `plugins/assets/prompts/tests/test_g01_api_purity.py:226-237`：新增测试只证"3 个新文件被扫描到"与点名规则双向，未证这 3 个文件**各自的 import 白名单未被放宽**（contribution.py 需引入 `ordessa_harness_api`，其允许集不在本 diff 呈现范围内，因截断不可核）；建议补一条"新面文件允许集 = 预期集合"的等值断言。

2. fake green 迹象
- **有账实不符/谎报迹象**：报告两处声称"实跑 182/182 passed"，与交付的测试清单（34 函数+3 参数化=186）不符，且第三轮"计数已统一"的声明在产物中查无实据——即报告声称已修而未修。
- 无删断言/空测试/skip 掩盖迹象：G01 白名单仅增项、敌例（`ordessa_harness` 拒绝）仍在且新增双向证明测试；capabilities 的 unknown/unsupported 判定不冒充 supported，compile 诚实拒绝与 AR-6 一致。

3. 结论
**不通过**——代码与测试本体基本可信（写入面未越界、任务-代码一致），但交付报告的计数与"已修复"声明不符属报告失实；把 PX-report 两节改为 186/净增 37（9+19+2+4+3）、复跑留证后即可转通过。
