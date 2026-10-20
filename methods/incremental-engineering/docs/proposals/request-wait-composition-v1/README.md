# 2.5 修订提案：请求、等待与实施包组合

状态：proposal_only；拟议方法身份 ordessa.incremental-engineering@2.5.0。未批准、未编译、未封存、未发布、未执行。冻结2.4与全部旧版本不改。来源：父任务本轮明确修订指示；docs/architecture/software-engineering-harness.md §§4.3、5、6.4、7；原2.4模板/skills；原Engineering当前API只读核对。父任务指示授权起草，不等于批准新方法或产品内部Grant。

## 完整短流程

1. 自然讨论→主Agent保存决定/授权/未决项→按确切DID基线起草提案、逐claim依据映射及重要变化摘要。Artifact/Proposal原owner留档，固定method、标准和所有目标revision。
2. 对来源语义、工程质量/内容、摘要忠实度分别构造完整Plan，调用原reviews.request。completed仅表示requested并得到确切ReviewRequest引用；随后显式wait。真实JEV/人工来源经原reviews.record写入，原owner以完整requirements/current controls/trust/版本重新判gate；通过才前进，block回修订，manual/unknown继续等待。请求完成不产生审核终态。
3. 真实完整审核满足后发布绑定提案/摘要/审核集的notice；prepare_intent按原输入生成确切intent；approvals.request的completed仅绑定pending challenge。显式wait真实用户答复；授权main Agent如实证明会话，原record_conversation与原policy/current guard持至COMMIT产生Grant。拒绝停止；无答复/歧义/过期/旧版本不推进。DID接受与实施权限是不同作用域，不能从审核意见推导授权。
4. 原DID/baseline owner按有效文档接受权限执行CAS应用、回读并生成receipt；workflow只接受原owner验证的before/after/receipt，不能凭客户端event进入已应用态。缺真实owner则阻塞。
5. 主Agent以应用后的DID、变更、有效接受、receipt、源码事实及冻结templates/spec-kit与spec_converter生成完整spec/plan/tasks、双向追溯、contracts/design/实施切片/写权/依赖/验收材料。用原artifacts.create/append_revision保存草稿与原始生成材料。生成是方法策略及Agent任务，不是新packages.derive原子机制；发现重要设计缺口回DID提案。默认主Agent完成；若外派生成，必须另有实际生成任务授权和原Execution记录适配，不能调用依赖已封存package的ImplementationDispatch来绕循环。
6. 对草稿完整实施包及其追溯构造原review Plan→request→wait→真实record→current gate。准备generate_package所需确切ImplementationAuthorizationIntentSpec/Grant；必要的新许可仍走原request→pending→真实会话批准，不因已接受DID而补造实施权限。原ImplementationUseCases.freeze_package封存给定完整Package，核对原proposal intent、baseline、method/resources、actions/验收、actual Grant并消费generate_package。返回dispatchable:false，仅表示已封存。草稿审核不能冒充最终package审核：封存后的确切package仍request→wait→current gate；可复用哪些前置记录由原owner精确target规则决定，不预先豁免。
7. 确切package审核与execute范围的有效Grant均满足后，原ImplementationDispatch固定真实Pi Unit/Profile/源码selection，freeze/query/send/capture及journal；运行未知只reconcile，不重复发送。Pi实施Agent按包执行，重要设计变化回提案。
8. 原记录/Blob/source owner捕获真实执行、输出、测试和baseline/tree事实；原SubmissionUseCases.record绑定exact package/Grant/method/执行身份并记录。保留output范围、Submission绑定、required tests实际结果（exit code/log/tree/environment）和机械source proof；任一缺证据不得成功。
9. 验收复用原reviews.request（purpose=acceptance，standard.acceptance及完整必需检查）→wait→真实record→原current gate，不新增仅换名的acceptance.request。原验收采纳owner按有效采纳权限、确切Submission/Review集合/原目标head做CAS，写adoption receipt并持controls/source至COMMIT。冲突/未知reconcile；验收意见不是采纳授权。
10. 记录结果、未通过/未完成项、验收与采纳证据及feedback；方法改进另提新版本，不覆盖失败事实或降低当前标准。

所有wait的通知仅是唤醒信号。推进由原owner查确切request/challenge、版本、control、full requirements、policy及权限；状态改变与Work CAS必须由原机制组合验证。不能添加未经注册的event名称就宣称wait已实现。实质变更使受影响旧审核/批准失效，不把2.4材料重标2.5。

## 最小原子操作与真实机制需求

已有操作按实际契约重新绑定，而不是名称修补：artifacts.create/append_revision、proposals.create、reviews.request/record、notices.publish、approvals.prepare_intent/request/record_conversation、changes.apply、packages.freeze、ImplementationDispatch、submissions.record。新增声明必须从原handler产生exact descriptor；只有有限Facade已注册项可视为现成可调用。

最小新增业务写操作候选只有 **acceptance.adopt**（暂用逻辑名，精确API/版本/合同待Engineering冻结）：原Engineering/目标baseline owner在一次原UoW/CAS下核对完整验收review/current controls、有效采纳权限、Submission/package/目标head/source，写唯一adoption receipt及journal。不得以客户端passed或review记录为采纳许可。若原目标owner已有等价原子API，采用其真实合同，不重复实现。

另需补齐真实机制，不能以“只有注册问题”掩盖：

- 原Work wait/resume：接原Review/Approval/current predicates并在推进COMMIT保留同authority/version guard。这是中立运行机制，不新增方法自有gate状态或审批中心；具体read/admission API尚待owner冻结。
- 原DID/baseline CAS应用及真实Git/tree/source owner绑定；当前caller Git DTO拒绝不能靠声明补足。
- 实际test/output/effect来源采集及完整Submission/验收检查；纯图引用校验只能作部分机械实现。
- 自动JEV三choice转换沿2.4声明；没有匹配validated evaluation仍manual。人工admission只保留已批准coverage/support范围，不顺带扩大quality/summary/acceptance豁免。
- 真实host catalog reader与相应能力注册；fixture catalog/test-host只验证，不能发布生产或建正式用户待办。

已有但未完整注册/适配：包freeze、dispatch、Submission记录、schema/source机械校验、nominal/human admission、图scope/binding校验。它们不能自动代表完整method capability。真缺机制：上述wait推进原authority闭合、真实源owner/完整tests检查、最终采纳；derive改为组合策略后，不再要求原子生成器，生成职责与验证仍完整保留。

## 下一版声明变化（待冻结）

reviews.request和approvals.request/prepare_intent使用当前真实command输入/版本/digest及completed/rejected分支；completed进入专属wait，不出现passed/granted分支。真实结果从原记录重新读取得出。

packages.derive替换为草稿生成wait/Artifact存储步骤与原packages.freeze；acceptance.request替换为原reviews.request的验收阶段。保留所有适用标准和机械/语义检查，不减少必需检查换取catalog通过。standards中引用的具名checks要由原owner冻结真实adapter合同，partial kernel不得宣称完整。

编译器当前只有operation/wait/stop可用时，方法不新增Agent节点DSL：主Agent作者阶段以wait收到确切原Artifact refs，由原guard验证；若这种wait/任务推进接缝未实现，明确列为机制阻塞。不得用提示词保证代替不可绕过的门禁。

## 验证计划（全部未执行）

request completed但无record/Grant不得前进；复制/伪造wait事件、漏列requirements、撤销/过期/旧request版本/current method失效必须拒绝；旧审核不覆盖新target；freeze_package没有generate_package Grant拒绝，freeze成功不自动dispatch；草稿审核不覆盖封存package；正文claim缺证据/矛盾和自动evaluation缺失保留阻塞/manual；真实测试失败/缺required run/output越界/Submission错误绑定不可洗；adoption无许可/旧head/CAS冲突拒绝；未知外部结果不得自动retry。编译/原SQLite及installed隔离检查随后按冻结机制串行验证，真实Pi/JEV最终验收另留实测证据。
