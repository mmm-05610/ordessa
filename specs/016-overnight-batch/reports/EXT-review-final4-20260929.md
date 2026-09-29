**1) 三条以内最重要的具体问题**

1. `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py`（`_matching_targets`，约 435-450 行：`if target.allowed_fields and claimed not in target.allowed_fields`）——空 `allowed_fields` 被当作“无限制”放行，且不校验 target 身份（handle/注册来源），任意 `kind=file, codec=json` 目标都能命中；但 `assess` 的 evidence 写的是“server-issued hooks target”，声称强于代码实际验证的——round 10 的“需 server 签发 target”只挡住了无 target 的情形，没挡住错 target。
2. `plugins/assets/extensions/src/ordessa_extensions/approval.py`（`restore` 的 `if state not in (APPROVED, REVOKED, UNAPPROVED)`，约 197 行）——恢复出的 UNAPPROVED 记录会进 `_records`，此后 `revoke()` 成功而从未记录的同名 hook 抛 `HOOK_UNKNOWN`，三态边界在 restore 面上不对称；另 `_record_for` 里局部重复 import 顶层已导入的 `findings_digest`/`scan_definition`（顶部 `findings_digest` 实际未用），`approve` docstring 写 “approve/revive/revive” 是笔误。
3. `plugins/assets/extensions/tests/test_adapters_conformance.py`（`test_keyed_target_without_the_claimed_part_is_not_ours`，约 205-222 行）——`context = context_for(...claude_settings_target(with_allowed_fields=False))` 建了却没用，测试名声称“无 claimed part 不认”，实际验证的是“限制性 allowed_fields 不含 (hooks,)”，而那个被弃用的 double 恰恰暴露问题 1（空 allowed_fields 被当无限制接受）。

**2) fake green 迹象**
未见。断言具体且有咬合（compile 终局拒绝是被文档化的 AR-3 交付物而非绕过；sweep 有自检测试；restore/scan/approve 的拒绝路径都带 code 断言），无删断言、空测试或谎报测试结果。小瑕疵：`test_shell_metachar_is_high_and_refused_by_loader` 名称含 loader 但只断言 scan；`test_re_extraction_of_expected_modules` 名不符实（只查模块集合）。

**3) 结论**
**有保留**——核心机制真实、边界声明大体诚实，但 `_matching_targets` 的空 allowed_fields 通配使“server-issued hooks target”这一 evidence 与代码不一致（写入面判断偏宽），需收紧或改述。
