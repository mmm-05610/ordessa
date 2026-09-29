1) 三条最重要问题

- `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py:356-366`（`_matching_targets`）：codex（file-whole）分支完全不校验 `target.allowed_fields`，而本 adapter 声明的 claim part 是 `("hooks-document",)`，claude 分支却会按 `("hooks",)` 过滤——目标筛选与 claim 不对称；今天 `compile` 恒拒所以写入面未实际越界，但 AR-3 两闸解除后 `build_codex_intents` 的 `MountContent("hooks/hooks.json")` 会落到未授权 part 的目标上。
- `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py:302-307`（`assess` 请求校验分支）：把"调用方 payload 非法"判为 `status="unsupported"`，与 `capabilities.py` 自己声明的分级语义（unsupported＝第一手证据证明该 pin/路径做不到，且与 unknown 严格不混淆）冲突——请求错误被固化成能力等级；`tests/test_adapters_conformance.py` 的 `test_assess_rejects_bad_payload_and_unevidenced_event` 反而把这个混淆断言成期望行为。
- `plugins/assets/extensions/src/ordessa_extensions/plugin.py:11-12 vs 91-92`：docstring 称 `wire.error-families` 也是"open point"（同批永远有贡献行），但 `open_points` 只声明 `harness.configuration-adapters`；且"a bare test host that wants neither passes False"不实——wire 行无条件贡献，`contribute_harness_adapters=False` 并不能"neither"。open_points 语义（本批打开的点 vs 待宿主绑定的点）需二选一修正声明或文档。

2) fake green 迹象：无（未见删断言/skip/空测试；compile 无条件终拒是任务侧已裁定的 AR-3 交付）。两处诚实性小瑕疵：`test_compile_refuses_on_the_incomplete_native_schema` 名实错位——schema 补齐后该测试仍绿（断言的是无条件终拒路径）；证据字符串只做 `file:line` 格式正则校验（`test_brand_table.py`），从未与仓库实际内容比对。

3) 结论：有保留（通过前请修 codex 目标筛选与 assess 分级混淆；写入面本体无越界，包内无路径/进程/网络接触）。
