# Operation handoff — 2.1.0 integration candidate

来源：docs/architecture/software-engineering-harness.md §4–9；docs/decisions/software-engineering-harness.md DEC-SEH-001/002/003 与建议状态；docs/implementation/nightly/design-source/ordessa-design/DESIGN.md Engineering/Methods/Decision/Units 责任。

下面是方法需要的行为合同，不是已注册能力清单。名称带 candidate 的新 operation 等待 Engineering owner 冻结；不能仅添加 catalog 就宣称 adapter 或可信入口实现。

| 步骤 | operation / 边界 | inputs（均精确版本） | outputs | role / checks |
| --- | --- | --- | --- | --- |
| 自然交流 | 主 Agent 的 Harness input；不要求用户填 JSON | 会话、当前 work、已有决定和上下文 | 原始消息来源 | main_agent；最小必要读取、不复制秘密 |
| 决定沉淀 | candidate engineering.decisions.capture，或 artifacts.create/append_revision 的受支持配置 | context、source captures、document.decision_context | decisions_ref | decision_record；决定/授权/解释/问题分类、出处限制、冲突/替代关系 |
| DID 提案 | candidate engineering.proposals.author，或 author skill + artifacts/proposals.create | baseline、decisions、sources、standard_profile | proposal_ref、exact target、summary_ref | did_author；ECP/NOR/support-map、增改删/保持、影响、未决 |
| 来源语义审核 | engineering.reviews.request purpose=provenance_support | proposal、基线、依据全文/上下文/反证、标准、精确问题 | review_ref + native JEV result refs | semantic_judge→真实 JEV；逐条语义支持而非引用存在 |
| 工程与摘要审核 | engineering.reviews.request purpose=quality | proposal、standard_profile原文/裁剪接受、summary、源事实 | quality/summary review refs | did_review；实质工程条款、影响完整性、摘要忠实度 |
| 实际告知 | candidate engineering.notices.publish，或可信approval provider支持的正式展示步骤 | proposal、reviews、summary | notice_ref、实际发送文本/回执 | main_agent；不能以准备摘要冒充已发送 |
| 可信确认 | approvals.prepare_intent/request | exact proposal、reviews、notice、baseline、目标动作范围 | intent/challenge/grant refs | trusted_human；机器身份、自报approved、JEV意见不得产生Grant |
| DID 生效 | candidate engineering.baselines.apply | proposal/NOR、document acceptance + 写权限、reviews、baseline CAS | apply_receipt_ref、target_baseline_ref、readback_ref | did_apply；冲突复审、unknown不重发、旧确认不覆盖新目标 |
| 转换实施包 | engineering.packages.derive | applied DID/receipt、有效接受、源树、standard profile | package_ref，spec/plan/tasks/baseline/change-map/acceptance refs | spec_converter；完整双向追溯、不填重要未知 |
| 包审核 | engineering.reviews.request purpose=quality | package、原/目标DID、receipt、授权范围、源码 | package_review_set_ref | package_review；忠实/可分工/写权/依赖/成功拒绝退役验证 |
| Pi 实施 | engineering.executions.dispatch | package、独立 implementation grant、package reviews、method skills | execution_ref、native Pi evidence | executor→真实 Pi；原生skill/附件、权限、scope、unknown占用 |
| 结果留档 | engineering.submissions.record | execution/package/输出树/测试/原生记录 | submission_ref | executor；自述与权威捕获分开 |
| 验收与采用 | engineering.acceptance.request/adopt | submission、冻结验收、review set、baseline CAS | reviews/adoption refs | acceptance reviewer；exit0不是验收、失败证据保留 |
| 反馈 | candidate engineering.feedback.capture，或 artifacts.create | result/adoption、失败/缺口/质量证据 | feedback_ref | main_agent；实现/设计/方法路由，规则修改另起版本 |

共同要求：stable request_id + payload digest 幂等；context/ref 与 frozen method 一致；服务端重新验证权限/控制集合/CAS。unknown 需查询同一调用并核对外部效果，不重试副作用。意见、实际告知、接受、DID写权限、实施权限分开。

待冻结：新增operation是否复用通用artifact命令；inputs/output slots/outcomes/config schema；真实 notice 与 baseline owner receipt；逻辑角色的受信注册；JEV上下文映射与质量评测。不存在的能力必须不可用，不能回退offline/fake/旧工作流。

## Engineering owner 第一检查点答复

实读 `docs/implementation/nightly/evidence/engineering-convergence-20261011/v1-method-bridge/interface-checkpoint.md`：artifacts.create/append_revision的实际interface version为2，proposals.create/withdraw/supersede为1；完整input schema来自真实Facade，不是本目录fixture catalog的1.0.0。

- capture可存method-defined decision-context为artifact(kind=other)，取得真实revision ref，不新增同义operation。
- author由Pi在事务外产draft，再调用真实proposals.create；author不能做create转发别名。
- feedback正文可artifact留档，但Submission/Adoption真实绑定尚缺。
- notice推荐独立immutable exact领域记录，approval展示引用它；普通artifact和展示文本不足以认证实际告知。
- baselines.apply尚不能接通，缺Baseline/Grant/ApplyRecord与同TX规则。继续停在await_did_applied，不能复用旧did.apply作为隐性后备。

当前workflow的三个新增事件、proposal扩展refs、prepare_intent/derive附加inputs均为精确需求，尚未冻结宿主合同。Fixture catalog可编译不表示现代MethodBridge能执行：后者目前只认五个真实handlers；其合同不能把completed/rejected解释成passed/blocked/manual。

额外发现并已发给owner：新command_capabilities的有限结果键为outcomes，实际methods workflow validator需要workflow_outcomes；手构CompiledProgram的桥测试可能漏掉真实外置loader/compiler接缝。须由owner统一合同键/摘要，再刷新任何实际host pin；不能由方法方临时添加键和改hash冒充已注册合同。替代方法当前review operation尚未实现，只证明同compiler可替换；运行待owner校准。

## 用户已裁定的 v1 确认修订

以 docs/decisions/user-confirmation-v1.md 和 policies/product-chat-confirmation.v1.yaml 为准。主Agent如实转交明确用户问答，可由产品配置的v1policy作为决定/确认依据；actual source refs可用则记录，缺平台验证标agent-attested和限制，不伪造独立认证。问题/必要上下文/回答/exact object versions/scope/policy/dedup evidence均需绑定；歧义、越界、新实质版本pending。无需再点浮窗；强provider可选，不再作为v1硬阻塞。

前文“可信人类provider”及强认证建议以此修订为当前v1策略：工程owner可以通过获准主Agentattestation来源签发正式接受/许可回执，不接受无来源approved=true。普通method不能自行选择policy提升权限。原设计文件不改，旧run/receipts保持原绑定。

Engineering rev31已修复此前真实compiler接缝：合同使用workflow_outcomes，capability digest统一method_digest("capability-contract", contract)。2.1.0 fixture catalog已复制其三个实际handler合同（artifacts.create/append version2、proposals.create version1）并更新requires pins；其他pending描述仍明确fixture-only，不因此变成可执行。
