## 三条最重要问题

1. **`test_wire_contract_guard.py:55-90` + `dto.ts:1-5`（RESPONSE_LEDGER 全部 gap 置空、dto 按"实测应答"重写）**：账本的真值源从"契约文档"换成了"当前后端实测应答"，但 diff 中没有任何一处与 `docs/design/mcp/contracts.md` §1/§2 的应答 schema 交叉核对。若后端已偏离契约文档，本次调和即把漂移永久合法化——守护从"钉契约"退化为"钉现状"。这是"调和掩盖漂移"的真实风险点，需补一句 contracts.md 对照证据才能排除。

2. **`CMP-mcp-report.md:23`（"520 collected"）vs `wire-alignment.md:60`（"4 failed, 518 passed, 2 errors"=524 collected）**：同一实测账两处互相矛盾，且只有 524 口径能推出 525（+WCG-03b 一格）。声称"全部真实退出码"的账里有一笔数字不实。

3. **`tests/harness_wiring/test_controlled_chain.py:98-116`**：注释宣称 "observe must hand the SAME receipt back or the service refuses to confirm"，但 fake 只是回显服务传入的 `operation_id/manifest_digest`，本提交未新增"异 receipt 被拒"的用例——receipt 绑定语义是被声称而非被验证；且 `NativeActivationReceipt(...)` 位置参数里看不出 generation 绑定，与报告 §2.2 "绑 operation/generation/manifest" 的表述对不上。

## Fake green 迹象

无经典 fake green：未删断言、未加 skip、未 stub 绿；WCG-05 反空转孪生保留、WCG-04b 活线见证保留、tsc 75 行红如实登记。但注意 WCG-05 #2 在 `TS_RENAMES={}` 后只剩合成数据能触发 stale-rename 分支（真实数据下该分支不可达），属弱化而非伪造。

## 结论

**有保留** —— 修复是真实补做（wire.ts 012 已对齐，dto/账本跟进是正确方向），测试真实性整体成立；但账本真值源缺 contracts.md 对照（问题 1）与实测账自相矛盾（问题 2）需澄清后方可视为完整闭环。
