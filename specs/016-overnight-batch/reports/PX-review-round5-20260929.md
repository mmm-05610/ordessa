1) 三条以内最重要的具体问题
- `specs/016-overnight-batch/reports/PX-report.md`（T07 行,「三 adapter+22 项 conformance 测试」）:与同报告 PX-0/测试证据节的「conformance 19 函数」不一致,实数为 19(`test_prompts_adapters_conformance.py` 共 19 个 test 函数),"22 项"无出处——本轮专为计数失实收官,交付物内仍残留一处对不上的数字。
- `plugins/assets/prompts/tests/test_prompts_citations.py:33-40`:只证 `harnesses.toml` 无 instruction_target/instruction_key 且有 skill_target/mcp_target,但 `capabilities.py` GAP 与报告仍声称"zero consumers in plugins/harness/src"、"hooks_target 均在"未被任何断言打开——引用纪律自称"可证伪",这两条主张目前仍是文档级。
- `plugins/assets/prompts/src/ordessa_prompts/harness_adapters/contribution.py:compile(~L248)`:外层仅捕获 `ContractError`,`context.targets`/schema 的非契约异常(如 AttributeError/ValueError)会从 compile 面抛出而非返回类型化拒绝——拒绝式适配器在自身缺陷时也应 fail-closed 成 refusal,而不是把异常交给宿主。

2) fake green 迹象:无。G01 白名单只做增项且有双向证明测试(`ordessa_harness_api` 可入/`ordessa_harness.` 拒入),无断言删除或 skip;新测试均断言真实行为(拒绝码/status/引文行实开),`assert schema is not None` 之后跟有真实 enum 校验;9+19+2+4=34 函数 +3 文件级参数化 = 37,149+37=186 自洽,计数本轮已对齐;写入面仅 `plugins/assets/prompts/**` + `specs/016-overnight-batch/{api-requests.md,reports/}`,与声明一致,无越界。

3) 结论:有保留(实现与测试通过,仅需修正报告 "22 项" 计数措辞并补齐/降格两条未证主张)。
