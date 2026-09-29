**1. 三个问题**

1. `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py:~255（assess()）` — assess 不校验 `installation.harness_id == self._pin.harness_id`（verify() 有此校验），异品牌安装只要版本元组恰为 pin 值即判 `supported`，身份 fail-closed 两面不一致且无测试覆盖。
2. `plugins/assets/extensions/src/ordessa_extensions/approval.py:186-192（restore()）` — 形状校验弱于注释声称：digest 只查 `sha256:` 前缀+长度、不查 hex；`pin` 只查 ≤32 字符、不查 X.Y.Z（构造门 `_validate` 会拒），恢复出的记录可携带 `approve()` 永不放行的形状。
3. `plugins/assets/extensions/tests/test_adapters_conformance.py:~205-235` — 新增的 expected-digest 形状分支（"no well-formed expected digest"）零覆盖：所有畸形 expected 用例（`("sha256:ff",…)`、`("aaa","aaa")`、None/""/7 循环）都先在 seen 检查处返回，第四轮"verify digest 形状校验"只证明了 observed 侧。

**2. fake green** 无迹象：三处修复均真实落码（verify hex 双侧校验、restore approvedBy 校验、import 扫描自测 `test_the_sweep_actually_detects_a_forbidden_import`、`records()==()` 等收紧断言），无删断言/跳过/谎报。仅 `test_verify_absent_observed_digest_is_never_a_match` 用畸形 expected "aaa"，未隔离其命名分支——偏弱但不欺骗。写入面未见越界（纯域、无 IO/spawn）。

**3. 结论**：有保留（问题 1、3 需补，问题 2 属声称与实现不符，需收窄注释或补校验）。
