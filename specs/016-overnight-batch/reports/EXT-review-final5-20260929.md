**1) 最重要的具体问题**

1. `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py:~357`（assess 的 supported 返回）与 `:~372-380`（`_compile` 末端恒定 `_refusal(CAPABILITY_UNSUPPORTED, …)`）：assess 在 pin+target 齐备时给 `supported`，但 compile 无论过几道闸都永不产出 IntentSet——`supported` 这个 status 是调用方分支依据，实际永远兑不了现，与本域"unsupported/unknown 不得虚称"的口径不一致（evidence_ref 的天花板措辞救不了 status 字段）。
2. `plugins/assets/extensions/src/ordessa_extensions/adapters/contribution.py:~325`（`installation.adapter_version != pin` 分支）：`adapter_version=None`（未探查）被判 `unsupported`，而 `native_version=None` 判 `unknown`——按本包自述的分级规则（非第一手不符证据只能 unknown），同一"未探查"语义两套分级。
3. `plugins/assets/extensions/src/ordessa_extensions/security.py:3`：`DIAGONOSABLE` 笔误仍在（第十一轮声称含笔误清理）；另 `tests/test_adapters_conformance.py:~178` `test_keyed_target_without_the_claimed_part_is_not_ours` 只覆盖了 allowed_fields 为空一例，真正"声明了别的 part"（`(("other",),)`）的分支无测试，且该情形下 assess/compile 的理由仍说"runtime supplies no hooks target"，与事实（有 target 但未声明所 claim 的面）不符。

**2) fake green 迹象**：无。断言具体（精确 code/status/reason 片段），round-11 两处改动各有正反测试（`restore` 拒 `unapproved`、空 allowed_fields 不作通配），扫边界测试带自检（合成违例必被抓），无 skip/删断言/谎报。

**3) 结论**：有保留（写入面收敛到位、测试真实；扣在 assess=compile 恒拒的分级不一致、adapter_version 分级不对称与两处清理残渣）。
