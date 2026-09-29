**1. 三条以内最重要的具体问题**

1. `plugins/assets/extensions/src/ordessa_extensions/plugin.py:17-18` 与 `:92-93` —— 文档声称"点未绑定则拒绝激活（fail closed）"，但代码把 `harness.configuration-adapters` 声明为 `open_points`，且本 diff 内无任何测试证明"未绑定即拒激活"（`test_plugin_registration.py` 只断言 open_points 标志被设置）；机制/断言两头都缺，属声明大于机制。
2. `plugins/assets/extensions/src/ordessa_extensions/approval.py:8-9` —— "every transition is recorded" 与实现不符：`_records` 以 hook_id 为键，`approve()`/`revive()` 直接覆盖旧记录，`records()` 只给当前态，无任何转移历史；第六轮把边界诚实化了 `restore`，但模块级总述仍是旧的过度声明。
3. `plugins/assets/extensions/src/ordessa_extensions/approval.py:~184`（`restore` 的 `row.get("state")`）—— 文档说"malformed snapshots refuse"，但非 dict 行（如 `["oops"]`）抛 `AttributeError` 而非 `SNAPSHOT_INVALID`，测试 `test_restore_refuses_malformed_or_forged_shaped_rows` 也只喂 dict 行；host 存储层输入没有全形状拒绝。

**2. fake green 迹象**

无。未见删断言/跳过/空测试；第六轮三项（verify/restore 边界声明、claude mismatch 判 unknown、families 取 `server_plugin_api.FAMILIES` 发布集合）均有真实断言对应；测试对拒绝路径、fail-closed 与 schema 不可表达性均有正向验证。

**3. 结论**

有保留 —— 代码诚实度整体良好、无造假，但"未绑定即拒激活"缺证、"每次转移都有记录"仍是超出机制的声明。
