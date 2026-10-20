# 渐进工程方法 2.4.0 候选：独立人工语义审核

独立身份：`ordessa.incremental-engineering@2.4.0`，manifest schema1 / compiled program schema2。父已批准有限人工语义审核，Engineering原owner已冻结外部声明合同；**本交付仅验证资产加载/编译，尚未证明实际consumer、真实人类答复或正式ReviewRecord已产生。** 旧2.1/2.2/2.3、确认policy及真实证据保持。

## 最小增量与身份

相对2.3：method release及source-review revision升2.4.0，resource rawSHA更新；仅claim_coverage与claim_support的checks[0].bindings新增human_review_admission，指向独立产品policy的exact id/revision/raw SHA。source_integrity、quality及其余标准不新增该声明；原词表/问题、全部原policy、nominal_answer_conversion、quality_admission、iteration/all_declared_claims/empty_claim_set/reduction不变。source-delta.diff保存包括独立policy新增在内的精确diff。

- source-review raw SHA256：`7be5c02a8782d01b309c63e4bca3ca17e8ea684cfd660b53ec34f118f8321496`
- 独立policy raw SHA256：`833be965ff8e43b0fec817e205a4d2f7817f45b7b36777a405a905fff44ec008`
- MethodRef snapshot SHA256：`fa51512abd24167856217ee58b4ba26903247a4f6e319ed9d80d20dc4c8c800c`

独立policy位于policies/product-chat-human-review.v1.yaml，id为ordessa.product.v1.chat-attested-human-review、revision1。该文件不是原确认policy的替换，也不是实施Grant。标准资源在source snapshot中冻结exact policy digest引用；policy原字节独立保存和索引，实际消费须由原Product authority返回真实选中policy原字节并持guard至COMMIT，不从方法引用自行选择授信级别。

## 实际消费所需的边界

完整合同见consumer-contract.md。只对获声明的两semantic criteria，受信独立人工答复可按实际产品选中policy处分：satisfied→pass、violated/insufficient→block、unknown→manual；Engineering原Observation归约为pass/fail/indeterminate。出处必须是真实agent-attested问答，并冻结exact Plan、完整CheckKey集合、版本、policy及当前角色/来源。DTO、自报approved、实例bearer或ActorRef本身不证明人类来源。

先向用户明确展示完整清单及必要上下文，再出现明确“这些审核项全部通过”时，原source owner可忠实展开完整集合。仅“继续实施”不能反推审核答复；缺答/含混保持pending、无答复不写Record。本policy文件只声明允许条件，没有保存这类真实答复。

独立人工语义审核不改变机械字节/版本/来源proof校验，source_integrity无human声明，不能覆盖机械失败。自动JEV仍按原nominal/quality规则：缺匹配已验证evaluation仍manual/indeterminate，不自动通过。人类review与实施Grant分开，review不会创建Grant或授权实施。

范围仅两项不意味着完整工程审查已通过：质量标准尚未新增人工处分声明；其门禁及所有完整review requirements仍必须实际满足，不通过扩大本policy范围回避。

## 验证与未完成项

tests/validate_candidate.py使用真实loader/compiler验证typed FrozenObject及stored roundtrip，两个criterion声明逐项匹配policy id/revision/rawSHA与处分全集；source_integrity typed声明不存在；删除新增字段后标准与2.3完全相等。原source-support问题字节、自动nominal/quality/policy不变；resource篡改与stale release lock拒绝。2.1/2.2/2.3的214项哈希不变，结果见tests/validation-result.json。catalog仍fixture-only，未发布/选用候选。

tests/human-cases.json列13项待原consumer执行的边界规格，未伪造人类答复或模型运行。Engineering需完成原EngineeringHumanReviewAdmission、schema2/CAS完整Record链及反例；产品需真实policy/source/current角色guard。无真实人类审核证据、校准数据、JEV/Pi调用、ReviewRecord或Grant产生，最终验收尚未完成。
