**1) 主要问题（≤3）**

1. `pi.py:170-186`（`_compile_params` maxTokens 分支）— 用 `before` 样本重写整棵 `providers.<name>` 子树（`{**dict(provider_sample), "models": rewritten}`），保留旧 `baseUrl/api` 而丢弃 `desired.endpoint`/dialect：端点变更 + maxTokens 同时出现时端点被静默吞掉；且原样写回非本 facet 所有的字段，写入面越界（budget 只该改 `maxTokens`）。
2. `bridge.py:189` + `types.py:88-101` — `_local_request` 直接调 `RequestParams.from_record`，非法 `requestParams` 抛裸 `ValueError` 而非 typed refusal；且 wire schema 的 `retry` 允许缺键、`from_record` 要求恰好三键，两处校验口径自相矛盾。
3. `pi.py:197-207` / `bridge.py:148-152` — retry 写入新建 `pi.settings.json` handle（注释自认 host 未必签发），并绕过 `context.target_handle` 自行构造 `TargetHandle`：声明本身即扩大本 facet 写入授权面，只靠 bridge 侧 `UnauthorizedTargetError` 兜底。

**2) fake green 迹象**

无删断言/无 skip/无空测试，断言覆盖拒绝路径与回归，整体真实。但两处名实不符：`test_request_params.py:54-55` docstring 称 "byte-for-byte" 回归钉死，断言只查了 `reconfiguration` 与单一 field_path；`codex.py:90` 的 `assert extra is not None` 是死断言（`extra` 恒为 list）。另需核对：`specs/016-overnight-batch/` 目录内容未随批提供（`cat: Is a directory`），**任务↔代码一致性本批无法核对**；`types.py` 续行 `\` 在粘贴中疑似丢失，请以工作树原文确认非语法错误。

**3) 结论**

有保留（pi 预算分支的端点丢弃/子树整写须先修，spec 缺失需补交后复核一致性）。
