**1) 最重要的问题（≤3）**

1. `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py:≈388`（`verify()` 的 `seen != expected` → `Match`）+ `tests/test_adapters_conformance.py:≈188` — digest 无任何形状校验，`"aaa"=="aaa"` 也会判 `Match`，且唯一 Match 测试用的是伪 digest `"sha256:ff"`（非 64 hex）；伪造格式的观测可被当成投影证据。
2. `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py:≈355-368`（`_compile()` 末尾）— `compile()` 结构上无条件返回 refusal，写入面今晚为零；EXT-5“配置投影适配器”交付的其实是拒绝语义，靠文档声明 AR-3 兜底，任务-代码一致性需任务方确认这算“完成”而非降级交付。
3. `plugins/assets/extensions/src/ordessa_extensions/approval.py:≈199`（`restore()` 的 `approved_by=row["approvedBy"]`）— 恢复时唯独不校验 `approvedBy`（其余 state/scope/pin/fingerprint 都验），snapshot 注入 `None`/非串即可造出 record，而测试名声称覆盖 "forged-shaped rows"，覆盖面与声明不符。

**2) fake-green 迹象**

无删断言、无 skip、无谎报；refusal 路径的断言与代码行为一致。弱测试两处（非假绿）：`test_adapters_conformance.py` 的 Match 测试用伪 digest；`test_dependency_direction.py:≈48` 的 `test_re_extraction_of_expected_modules` 只是文件名清单，不验证任何边界语义。

**3) 结论**

有保留。
