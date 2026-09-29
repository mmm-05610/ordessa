**1) 最重要问题（≤3）**

1. `specs/016-overnight-batch/reports/CMP-mcp-report.md:28`（R3 行）——订正只改到 R2 与 §3（526），R3 仍写"定向 `pytest plugins/assets/mcp`=525 绿"，同一份报告内 525/526 并存，处置 (2) 只做了一半，账目自相矛盾。
2. `specs/011-q4-mcp/reports/wire-alignment.md:26-32`（§二.0）——把 §1 应答承诺定性为"种类级"后，任何字段形制都与之相容，该交叉核对在结构上不可证伪，恰好是上轮担心的"把漂移合法化"；且 §1 原文只作转述未引逐字句，diff 内无法核验。更实质的缺口：真值源被声明为"活注册描述符（守护实读）"，而 dto.ts 实际是按 round-trip **fixture** 的 dispatch 应答校形——对齐来源与所声明的真值源不是同一个东西，报告未消解。
3. `plugins/assets/mcp/tests/harness_wiring/test_controlled_chain.py:252-270`——反例格同时改异 operation id + 异 generation digest + 异 evidence_ref，且只断言 `result.kind == "unknown"`：它钉住了"任意异 receipt → Unknown"，并未隔离出 operation 绑定这一维（若实现只校 generation 也绿），也不能证明 Unknown 来自身份校验而非其他抛错路径；文档声称"the service raises on the identity check"未被断言固化。

**2) fake green 迹象**

无系统性 fake green（无删断言、无 skip、无 legacy 复活）。新反例格在"墙不存在"时会翻红，是真反例。但有轻度"绿得不对因"风险：见问题 3——异 receipt 多字段同时变异，测试可能因任一字段校验而绿，属可误绿的写法；另外 525/526 账目不一致属记录诚实性瑕疵而非测试造假。

**3) 结论**

**有保留**——三项处置方向均成立（#1 补了对照、#2 数字本身 518+4+2=524 自洽、#3 反例格真实存在且会翻红），但 #2 残留 R3 的 525 未订正、#3 未隔离被声称的绑定维度、#1 的"种类级"读法使其不可证伪且真值源与对齐来源不一致；修掉这三点即可通过。
