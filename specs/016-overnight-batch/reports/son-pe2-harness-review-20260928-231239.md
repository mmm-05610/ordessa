**1) 三条以内最重要的问题**

1. `plugins/harness/tests/test_capability_declarations.py:221` + `plugins/harness/src/ordessa_harness/harnesses.toml:86-97`：多处把 `specs/014-plugin-release/reports/P-D-probe-transcript.json`、`P-D-report.md`、`P-D-claude-attachments.md`、`claude-production-packaging.md §8` 作为第一手证据引用，但这些文件**不在本 diff（分支）中**——"完整 diff"里没有它们，attach 翻绿的证据链在仓库内不可核验。
2. `plugins/harness/src/ordessa_harness/claude/attachments.py:153`（`assemble_attachment_blocks`）：整条附件通路只被测试调用，未接入任何实际 prompt 投递链；而 `capability_declarations.json:14` / `harnesses.toml` 已把 `attach` 宣告为 observed——观察到的是 JS 探针直连适配器的行为，不是本插件生产通路，声明与交付能力之间有落差。
3. `plugins/harness/packaging/claude/attachment-probe.mjs:2`（`test:attachments`）：探针依赖 `packaging/claude/node_modules` 存在且需本机跑 60s 级进程链，未见任何 CI/pytest 门使其成为强制门禁；"observed" 翻绿建立在一次未入库的本地运行上。

**2) fake green 迹象**

无删断言/空测试/跳过掩盖。`attach` 由 `(False, NOT_OBSERVED)` 翻 `(True, OBSERVED)` 及 `capability_claims` golden `False→True` 都是随证据更新的正常翻转，且 audio/超限/哈希不符等负路径断言完整。但存在**证据未入库即翻绿**的变体风险（见问题 1）——不属篡改，属"结论先于可核验证据"。

**3) 结论：有保留**

代码与测试本身真实、写入面未越界（全部落在 `plugins/harness`）；保留项是证据文件缺失于分支、attach 声明超前于生产通路接线。补上报告/转录入分支（或改为可重跑门禁）后可转通过。
