# Ordessa incremental engineering 2.1.0

这是第一套完整工程方法的集成候选资产，取代本目录1.1.0小样本作为当前编辑目标；尚未完成真实Pi/JEV端到端验收。`method.yaml`、资源bytes及`bundle-lock.json`固定方法身份与编译快照。`contracts/capability-catalog.json`仍明确fixture_only，只用于编译契约验证，不能注册为生产实现。

自然交流→决定上下文和依据留档→DID增改删及影响/摘要→来源语义审核与工程质量/摘要审核→真实告知/可信确认→正式DID应用→完整Spec Kit实施包→包审核/独立实施权限→真实Pi→结果/验收→反馈。流程来源及每步operation需求见[operation-requirements](docs/operation-requirements.md)。

[主Agent Skill](skills/main-agent/SKILL.md)将自然交流转换为方法正文，用户无需结构化输入或逐页阅读DID。独立Skill负责记录/作者/审核/应用/转换/包审核。`documents/`提供七种新增正文schema与模板；`templates/spec-kit/`提供完整spec/plan/tasks/baseline/change-map/acceptance结构，全部被method资源摘要捕获。

[校准与选择](docs/calibration-and-selection.md)列出未批准的具体DID标准/条款裁剪和JEV评测候选。所有语义supported目前也路由manual，没有臆定生产阈值。源支持、工程完整性、摘要忠实度及package双向追溯分开；意见不产生用户接受或权限。

`await_notice`、`await_did_applied`、`await_feedback`显式等唯一owner的受认证真实回执；宿主尚未实现事件及扩展proposal refs时保持阻塞。方法不自建状态库，不直接改DID文件绕过owner，不用offline/fake补这些接缝。manifest的pending_owner_events不是已实现声明。

[验证说明](VALIDATION.md)与[资产验证器](tests/validate_assets.py)记录结构/编译证据。[12条判断向量](tests/judgment-cases.json)是供人工裁定及真实JEV评测的候选，预期不冒充模型结果。[极小替代方法](examples/alternate-method/README.md)更换文档名/标准/步骤组合，同compiler可编译，尚待Engineering证明无需application改动可以实际执行。

`examples/minimal-change/`及`contracts/hash-golden.json`保留先前1.1.0合成样本及引用关系，不属于2.1.0真实运行证据；没有改写旧Grant覆盖新snapshot。`methods/c09-prototype/`历史未修改。不得用旧`tooling/checks/method-fixture`重建器覆盖本版方法。

当前v1确认以[明确问答决定](docs/decisions/user-confirmation-v1.md)及外置product-chat-confirmation.v1 policy为准：获准主Agent如实记录明确问答可作为依据，不要求再次点击浮窗或独立验签。actual出处限制、agent-attested等级、exact版本/scope及正式owner回执仍需保留；旧强验证建议不再作为v1硬阻塞。

2.1.0记录用户明确问答确认修订；实际artifact/create/append和proposal/create合同副本按Engineering稳定公开handler更新，其他catalog行仍pending fixture，不能完整执行。
