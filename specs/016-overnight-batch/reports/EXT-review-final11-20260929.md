1) 三条以内最重要的问题

- `plugins/assets/extensions/tests/test_approval_chain.py:157`（`test_checklist_tightening_forces_reapproval`）——`findings_digest` 导入后未使用，"清单收紧"只是手工把记录里的 digest 换成 `77*32` 的伪造值：它证明的是"任何 digest 不符 → False"，并未证明"规则收紧会改变 `findings_digest()` 输出"。第十七轮修复的测试面偏弱（应改一条真实规则/插入一个 finding 后断言 digest 变化、`matches()` 翻 False）。
- `plugins/assets/extensions/src/ordessa_extensions/loader.py:46`（`_gate` 里 `definition.__post_init__()`）——只捕获 `ExtensionDefinitionError`；被篡改槽位若是非字符串（如 `pin`/`event` 为 int/list），`re.fullmatch` 会抛 `TypeError`，逃出 `load()` 的逐条拒绝契约、整批崩溃而非产出类型化 `LoadRefusal`。这与"fail-closed 边界只此一处、拒绝永不塌成 skip"的自我声明不一致。
- `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py:473`（`cell()`）——`evidence_ref` 在 SUPPORTED 路径硬编码 `"harnesses.toml hooks slot comments"`（丢掉 EXT-4 逐格证据串），其余路径为 `None`；引用只塞进 `reason`。SUPPORTED 分支当前不可达（`projection_path` 全表 unsupported），等于发布面永远拿不到证据引用，与"每格必须带 in-repo 引用"的规则在 wire 层脱节。

2) fake green 迹象

可见区域内未见：断言均为实值断言，`compile` 一律拒绝是 AR-3 明文的 sanctioned deliverable（"refusal IS the deliverable"），非删断言/空测试；qwen 除名、未见证据不上 supported 等都是诚实记录。唯一弱点是上面第 1 条的伪造 digest 测试（测试力度不足，非造假）。注意 diff 截断处之后的 `test_security_scan`/`test_error_families`/`test_plugin`/`test_dependency_direction` 未见，无法完全排除。

3) 结论

有保留（两项收官修复确已入码且 fail-closed 方向正确；建议补真实"规则收紧→digest 变化"测试、修 loader 的未类型化崩溃路径与 capability 行的 evidence_ref 丢失后再合）。
