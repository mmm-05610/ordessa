**一、三条最重要的问题**

1. **`src/ordessa_extensions/adapters/contribution.py:verify()`（`expected = observed.get("expectedDigest")` 一段，约 400-445 行）— Match 可自证**：`expectedDigest` 与 `observedDigest` 取自同一调用方载荷，任何调用者给两个相等 hex64 即得 `Match`，"expected" 并非来自被 pin 的 managed 内容引用（对比 `build_codex_intents` 里 ContentRef 的 sha256 是真算出来的）。`evidence_ref` 降级措辞（"observational placement fact only"）缓解了声称强度，但测试 `test_verify_digest_match_is_observational_only` 把这条自证路径当成事实来断言——第五轮"expected-digest 分支零覆盖"修的是覆盖，没修证据来源。

2. **`src/ordessa_extensions/approval.py:restore()`（约 178-215 行）与模块声称的"state machine is total, every transition is recorded / revival is an explicit operator decision"不一致**：restore 接受任意 shape 合法的 `state=approved` 行，可把 revoked 的 hook 直接铸回 approved、或为从未批准的 fingerprint 铸造批准，`approve()/revive()` 的门禁全部绕过，`matches()` 随之放行。信任边界有声明（"host 拥有存储"），但那是"内容真值"的让渡，不是"状态转移唯一入口"的让渡——totality 声称只在内存 API 内成立，文档应与代码一致。

3. **`src/ordessa_extensions/adapters/contribution.py:PINS["claude"]` + `assess()`（mismatch 分支）— 评级违反自家定义**：capabilities.py 明文定义 `unsupported` = "first-hand in-repo evidence that THIS pin cannot do it"，而 claude pin 自注"comment-grade observation; not a proven pin"，mismatch 却返回 `unsupported`（应为 `unknown` 才诚实，fail-close 用 supported 之外即可）；且该分支（claude mismatch）无任何测试覆盖，codex 的 mismatch 测试不能代它。

**二、fake green 迹象**

无删断言、空测试或谎报：第五轮三项修复各有真实对应测试（assess 身份闸 `test_assess_foreign_identity_...`、restore 形状 8 例且断言原子性 `fresh.records() == ()`、expected 分支 5 组正反例），`test_dependency_direction` 还带守卫自检。两处偏弱但非造假：`test_brand_table` 的 citation 正则校验是循环断言（`HookCapabilityFact.__post_init__` 在 import 期已强制，测试重实现同一规则）；`test_error_families` 的合法 family 集合是硬编码副本而非取自 `server_plugin_api.FAMILIES`，契约漂移测不出来。

**三、结论：有保留**（写入面干净——纯域、零路径/HOME/网络触碰；问题集中在 verify 证据来源与 restore/评级两处"声称强于机制"）。
