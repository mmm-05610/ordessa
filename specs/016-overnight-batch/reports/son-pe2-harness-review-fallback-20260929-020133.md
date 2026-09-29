## 1) 最重要问题（≤3）

1. **`plugins/harness/tests/test_qwen_production_template.py:1` — 整文件 202 行断言删除成零测试 docstring，而 `src/ordessa_harness/qwen/production.py`、`adapters/qwen.py` 仍保留在树**（报告 §9 自认"历史件保留"）：保留的生产代码失去全部门禁，摘除口径自相矛盾（删测试 vs 留代码），是本批最大的删断言面。
2. **`plugins/harness/src/ordessa_harness/application/native_evidence.py:108`（`operation_evidence` 内 `distinct = readback_ref != receipt.evidence_ref`）— "独立回读"只用 evidence_ref 字符串不等来判定**，而 receipt 与 readback 均由同一 `ControlledNativeStandIn` 生成、ref 由调用方命名；`complete` 的"独立且一致"证明强度不足，PE2-3 的 C4 对齐口径未真正闭合。
3. **`apps/server/tests/test_asset_hubs.py:207`、`apps/server/tests/test_subagent_harness_round_086.py:252` — 本批 qwen 除名实测打红 server 侧 2 个测试（KeyError 'qwen' / 期望列表含 qwen），仅在报告 §10 转 core**；AGENTS 规则 10 要求已知失败入册 `docs/known-issues.md`，本批未落册即留下跨包红账（另有报告"23 files 全部在 `plugins/harness/**`"与 diff 实含 `specs/**` 报告的小口径出入）。

## 2) Fake green 迹象

- **有删断言/删测试**：qwen 全系（`test_qwen_production_template.py` 整体、`test_family_dialect_tables.py` 的 `is_pinnable("qwen",…)`、capability 矩阵格）——均系用户裁定除名的同步删除且有登记说明，**不是为掩盖失败**；但配套留了生产模块，构成覆盖空洞（见问题 1）。
- **无 skip/无谎报**：继承红给了主树复现证据链（E7–E9 同节点同错），12+3=15 计数自洽，首轮 5 红→2 红的修复记录如实（白名单补 stdlib、`RETIRED_NPM_ROOTS` 显式记账替代删数据），方向合规。
- 一处松断言：`test_native_evidence_controlled.py` 的 `pytest.raises(Exception, match="differs")` 裸 `Exception`，易吞非目标异常。

## 3) 结论

**有保留**——通过项：写入面基本守界、三态测试真实（含 sqlite 注错反例）、qwen 注册面摘除干净且残留有显式登记；保留因：qwen 测试全删而生产模块留存、complete 证据强度不足、下游红账未入册。
