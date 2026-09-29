**1. 三个最重要问题**

1. **`src/ordessa_extensions/approval.py:158`（`restore()`）** — 第二轮修复只堵了 `revive` 这扇门，`restore` 是未设防的第三扇门：`rows` 直接重建 `ApprovalRecord`，不校验 `state ∈ {unapproved,approved,revoked}`、不重跑 `_gate_inputs`/HIGH 扫描，一行伪造快照即可为 shell 一行命令铸造 `APPROVED` 记录——正是 approve/revive 文档里声明"绝不允许"的「diagnostics 说谎」不变量（loader 会拦装载，但 `matches()`/`records()` 会给出绿灯）。且 `restore` 的 `Mapping[str, Any]` 注解与 `isinstance(rows, list)` 检查自相矛盾，无对应拒绝测试。
2. **`src/ordessa_extensions/adapters/contribution.py:~380`（`verify()`）** — `seen is None`（无 `observedDigest`）时直接落到 `return Match`：零观测也判匹配，与 "Match 仅是 placement fact" 的诚实声明冲突；且 `native_load_event` 的 "event 永不为证据" 拒绝排在 mismatch 检查之后，一个 load event 携带不同摘要会产出 `Mismatch` 而非 `VerificationUnknown`。测试只覆盖 `seen == expected` 路径。
3. **`tests/test_adapters_conformance.py:103-104、:165-166`** — 析取断言（`A or B`、`startswith("sha256:") or len()==64`）使证据文本/摘要形态写错一半也能绿，弱化了第二轮"测试真实性"修复的力度。

**2. Fake green 迹象**：未发现删断言/跳过/谎报；第二轮三项修复均有对应实现与测试（revive 三闸 + `test_revive_cannot_bless_a_shell_one_liner_either`、未知码→UNAVAILABLE/503 + 两条测试）。上述问题是漏堵的旁路与弱断言，非造假绿。

**3. 结论：有保留**——`restore()` 旁路与审批链自身声明的不变量直接矛盾，须补闸后再合入。
