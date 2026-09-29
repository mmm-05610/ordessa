## 一、最重要的三个问题

1. **`src/ordessa_extensions/adapters/contribution.py` `verify()`（约 380-420 行，`if seen != expected` 分支）**：`expectedDigest` 与 `observedDigest` 同来自调用方 payload，adapter 从不与自己编译出的 `ContentRef`/intent 对账，任何调用方都能构造 `seen == expected` 轻易拿到 `Match`。docstring 已承认「证明的是评分规则而非样本真实性」，但 `Match` 仍是宿主可机器消费的结论——期望值应来自 adapter 自身状态或显式注入的期望源，否则这个 Match 连"observational placement fact"都不算。对应测试 `tests/test_adapters_conformance.py`（`test_verify_digest_match_is_observational_only` 约 :250）只验证了这个弱评分规则本身。

2. **`src/ordessa_extensions/adapters/contribution.py` `_compile()`（末尾无条件 `return _refusal(CAPABILITY_UNSUPPORTED, ...)`，约 455-465 行）**：`compile` 没有任何成功路径，第二个"gate"不是检查而是硬编码拒绝；`build_codex_intents`/`build_claude_intents` 在生产路径不可达（仅测试直接调用）。这与"refusal 是交付物 / AR-3 定义就绪、投影待通"的自述一致，但需确认任务 EXT-5 原文是否允许"永久拒绝"作为终点——若任务要求本轮至少打通一个品牌面，则属任务与代码不一致（且 `compile` 成功路径缺席意味着 `MountContent` 写入面从未被端到端演练）。

3. **`src/ordessa_extensions/security.py` `_INTERPRETERS`（约 35-38 行）把 `python/python3/node/perl/ruby` 判 HIGH**，HIGH 一律拒绝批准（`approval.py` `_record_for`、`loader.py` `_gate`），叠加 `definitions.py` 中 handler 路线"今晚全部 loader 拒绝"，实际可批准面只剩 `notify-send`/`echo` 这类裸二进制 argv。若任务允许脚本型 hook，这是过度拒绝使交付物不可用；若任务明确"shell one-liner 一律不批"，则 `python3 script.py` 被并入同一 HIGH 也需在任务/known-issues 里明说。另注：`tests/test_dependency_direction.py` `FORBIDDEN_PREFIXES` 禁止 `pacthold`，与 `__init__.py`"只消费 …/pacthold 词汇"自述矛盾（小问题，但会误导后续改动）。

## 二、fake green 迹象

未见删断言/空测试/skip 掩盖失败。反向证据良好：`test_the_sweep_actually_detects_a_forbidden_import` 自测扫描器、`test_point_constants_match_the_harness_handler` 对真常量、`restore()` 的形状校验测试逐字段打伪快照、`verify` 的畸形摘要逐例断言 `VerificationUnknown`。测试断言的是当前（拒绝式）行为，非虚构成功面。唯一冗余是 `test_assess_claims_projected_ceiling_only` 与 round-12 用例完全重复（非 fake green，只是死重）。

## 三、结论

**有保留** —— 诚实性与边界纪律合格（纯内存、无 HOME/网络/进程写入，diff 可见部分全部落在 `plugins/assets/extensions/` 内，未越界写其它包），但 `verify()` 的可伪造 Match 与 `compile()` 永久拒绝的任务一致性需先澄清；截断尾部的 wire/plugin/security 测试无法核验，`ordessa-harness-api`/`server_plugin_api` 形状（`ValueSchema`/`ContributionBatch` 等）只能靠被截断的测试背书，建议跑全量测试后再定稿。
