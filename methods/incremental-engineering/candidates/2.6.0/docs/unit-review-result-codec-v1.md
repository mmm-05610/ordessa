# unit-review-result/1 可消费声明

方法文档schema/template及document binding在method.yaml，所有 `engineering.reviews.request` 节点都声明 `review_source`，指向 `unit-review-result`、冻结schema resource及 `exact_check_key_status/1`。逐CheckKey答案沿原CriterionAnswer，没有新增host DTO。

严格JSON→actual selected method document validator→顶层exact Plan digest→每row原domain.reviews.target_codec.decode_target(check_key.target)及CheckKey(target,criterion_id,claim_id)→原domain.artifacts.ref_codec.decode_artifact_ref(evidence_refs)→CriterionAnswer(check_key,status,evidence_refs,rationale)。键集合必须等原Plan requirement.required_check_keys且每key唯一；缺/重/额外/错target/错claim/错digest拒绝。以原codec和原admission校验scope/ref/current requirements，不把原Plan复制成方法另一权威。最后完整review_observations(plan,standard,answers)，不从body接身份/Grant/evaluated/pass。

通用转换合理owner是Engineering application/orchestration/unit_review；Product只绑定实际方法资源、recorded Unit response和原source/current authority。每项status是reviewer对CheckKey的声明，不是原生Decision/JEV回执或模型质量字段；本Unit输出不得整体重标成JEV结果。该文档只声明shape/codec，不证明生产decoder或真实JEV source已完成。unknown保留；空evidence合法表达没有材料，不表示满足；nominal/status与verified事实和授权不同。此2.6.0 revision按自身显式有限Choice选项和criterion policy归约完整Decision结果，不要求独立的matching-validated-evaluation字段；原来源/请求/问题/材料版本、完整Plan、证据、reviewer identity/current guards仍由原owner验证。人类admission与正式Grant边界保持独立，不改confidence threshold。

原UnitReviewBinding/full Plan/request/delivery/schema/prompt/Unit/operation/native response source在原owner校验并持guard到COMMIT。正文无需复制平台身份；author!=reviewer仍本方法通过宿主通用身份约束表达。schema只检查结构，不证明事实或生产资格。
