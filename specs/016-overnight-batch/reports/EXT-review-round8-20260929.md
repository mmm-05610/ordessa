1) 三个最重要的具体问题

- `plugins/assets/extensions/src/ordessa_extensions/plugin.py:95` — `open_points=frozenset({CONFIGURATION_POINT})` 在 `contribute_harness_adapters=False` 时仍声明开放点，但此时零贡献行；`test_plugin_registration.py` 的 bare-host 测试只断言 contributions 为空、未断言 open_points，行为不一致未被测试兜住。
- `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py:330-340`（`_compile` 末尾无条件 return）— compile 不存在任何可达路径返回 `IntentSet`，`build_codex_intents`/`build_claude_intents` 从未接入 compile，"两道闸门一抬即可"在代码里没有对应分支结构；若任务口径是「定义就绪、投影待通」可接受，但"意图构造已证"目前只是孤立函数级证明，任务/代码一致性需在任务侧对表确认。
- `plugins/assets/extensions/src/ordessa_extensions/security.py:30,96` — `_GLOB = r"[*?]\Z"` 只锚定结尾，`_SHELL_METACHARS` 不含 `*`/`?`，因此 `("tool","logs/*.txt")` 这类中段 glob 面完全零 finding（既非 HIGH 也非 MEDIUM），检查表对 glob 面存在静默漏判。

2) fake green 迹象：未发现。断言实质性（含 sweep 自检 `test_the_sweep_actually_detects_a_forbidden_import`、restore 伪造行拒绝、验证未知态不升格等），无 skip、无删断言、无谎报；refusal-as-deliverable 在测试里被如实断言为 refusal 而非伪装成功。

3) 结论：有保留 —— 三条均为局部一致性/覆盖面缺口，非红线越界（写入面纯净、fail-closed 立场贯穿 ledger/loader/verify），修 plugin.py 的 open_points 与 glob 漏判后可通过。
