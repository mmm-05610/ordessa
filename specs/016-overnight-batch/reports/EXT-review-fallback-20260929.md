**1) 三个最重要问题**

1. `src/ordessa_extensions/approval.py:88-100` — `approve()`/`revive()` 对带 HIGH 注入面的定义照常签发 `state="approved"`，红线「no approval can bless a shell one-liner」只落在 loader 层；`snapshot()` 因此会把永不装载的内容报成 approved，诊断面失真。配套 `tests/test_loader.py:55` 直接戳 `ledger._records["load-me"] = ApprovalRecord(...)` 私有属性来制造状态，掩盖了这个缺口。
2. `src/ordessa_extensions/error_families.py:53-58` — `to_server_error` 对未知 code 兜底成 `INVALID_REQUEST`(400)，与同文件 docstring「unknown codes stay UNAVAILABLE-honest … never flattened to a lie here」直接矛盾。
3. `tests/test_loader.py:40` `test_stale_content_and_stale_pin_do_not_load` — 全程未改 pin（`make(hook_id="second")` pin 不变），"stale pin" 半边断言缺失，测试名超报覆盖面。

**2) fake green 迹象**

无删断言/跳过/谎报。但两处弱断言值得记：`test_loader.py:55` 私有属性注入（见上），`test_adapters_conformance.py:~90` `assert "production.py:88" in assessment.reason` 实际是在断言 doubles 自己喂进的 evidence_ref，近乎同义反复。另：diff 本身被截断（`adapters/contribution.py` 的 `assess` 中断于字符串、`capabilities.py` 的 `__all__` 不全、`pyproject.toml` 重复出现两段），该两处无法审阅。

**3) 结论：有保留**（红线分层与 error-family 诚实性两处需修正后方可通过）。
