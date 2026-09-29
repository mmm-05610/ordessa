**1. 三条以内最重要的问题**

1. `plugins/assets/extensions/src/ordessa_extensions/approval.py:127-134`（`revive()`）——上一轮修复只堵了 `approve()`（:89-96 的 `has_high` 拒绝），`revive` 同样生成 APPROVED 记录却不做 HIGH 注入拒绝、也不校验 `approved_by`/`scope`：shell 一行命令经 revive 即得"approved"记录，正好让诊断面说谎（approve 文档 :70-73 自己宣称的红线被第二入口绕开）。
2. `plugins/assets/extensions/src/ordessa_extensions/error_families.py:57-66`（`to_server_error`）——"未知码→503"的修复无任何测试（tests/ 下没有 error_families/wire 测试文件）；且 `code` 为空时返回 `ServerError("INVALID_REQUEST", …, status=503, retryable=True)`，code 与 status 语义自相矛盾。
3. `tests/test_definitions.py:44-50`（`test_shell_string_command_is_inexpressible`）——测试名声称"不可表达"，断言却是 `definition.command[0] == "bash"`，构造成功即通过、零拒绝断言；与模块文档"shell string 在构造期被拒"的说法不一致（实际构造期只查 tuple 形状，拒绝发生在 security 扫描）。

**2. fake green 迹象**
无删断言/空测试/谎报。三个既有问题确已实质修复：`approve()` 现在拒绝 HIGH（test_loader:64-75 真实验证）；未知码改判 503 非谎报 400；stale-pin 测试（test_loader:36-46）确实装载了仅改 pin 的定义并断言 NOT_APPROVED。问题 3 的命名夸大属测试质量问题，非 fake green。

**3. 结论**
**有保留** —— 通过前需堵 `revive()` 的 HIGH/approver/scope 旁路（与 `approve()` 同一红线）；其余为补测与命名修正。
