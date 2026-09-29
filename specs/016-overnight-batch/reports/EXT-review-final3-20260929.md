1) 三条以内最重要的具体问题

- **adapters/contribution.py `assess()` 末尾 `return Assessment(status="supported")`（约 :355）** — 机器可读状态与同文件自相矛盾：`configuration_capabilities()` 把 `content`/`set`(projection_path) 判为 `unsupported`，且 `compile()` 无条件走 refusal（永远写不出一条 intent）。`status="supported"` 是 host 会直接键入的字段，prose 里的 "effect ceiling projected" 只是散文对冲，仍属对该面的轻度过度声称（能识别 placement ≠ 能投影）。

- **approval.py `restore()`（约 :200）与 `approve()` 文档承诺冲突** — restore 只做形状校验、不重跑 security/审批门，可装载 `state=approved` 且指纹匹配 shell 一行的记录；随后 `matches()` 返回 True、`records()` 显示 approved，直接违背 `approve()` docstring「no approval record for content no gate will ever load would make the diagnostics lie」。loader 仍靠 scan 拦下不会真装载，但"诊断不撒谎"这一域内红线在 restore 面不成立（文档自认边界，但与 approve 强承诺互相打脸）。

- **security.py `_SHELL_METACHARS`（约 :25）漏掉引号 `"` `'` 与 `(` `)`** — 该清单威胁模型明确是「品牌把 argv 拼成 shell 行」，在此模型下引号/括号是注入面却未被标记，HIGH 闸欠拒（危险方向）；而 `\\` 反被误判 HIGH（over-refuse 的假阳性）。

2) fake green 迹象：**无**。未见删断言/空测试/跳过掩盖/谎报；`test_the_sweep_actually_detects_a_forbidden_import` 还做了守卫自检，compile 各路 refusal 都被真实断言（"refusal 即交付"是显式契约而非掩盖失败）。

3) 结论：**有保留**。写入面未越界（compile 一律拒绝、包内无 path/spawn/network，intent 仅构造不落地），任务与代码一致（AR-3 缺口被诚实登记为拒交），测试真实；扣分点是上述 assess 机器字段的轻度过度声称、restore 红线盲区、注入清单欠拒，均为诚实性/一致性缺口而非造假。
