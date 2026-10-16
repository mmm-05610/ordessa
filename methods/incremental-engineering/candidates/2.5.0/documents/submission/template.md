# 实施提交（方法正文schema_version=2）

执行Unit通过原结果通道提交summary/change_notes/reported_outcome、remaining_issues、fixed_delivery_refs、requirement_results和reported_facts。作者complete不等于审核或验收通过。

## 固定交付与结构化报告

fixed_delivery_refs固定commit hash、snapshot或ArtifactRevisionRef，不用latest/可变路径。引用可由执行Unit报告；有原capture/import返回的引用可复用。宿主绑定原work/step/attempt和Unit来源、保留不可变Submission及pending-review，**不要求提交前宿主采集全部实际文件/test/effect事实**。原source身份/codec仍由宿主通用机制检查。

requirement_results逐条列要求ID、自述状态、交付引用下标、evidence_ids及说明。evidence_index解释补丁/测试日志/原生记录。reported_facts中的执行者事实一律asserted；未独立核实的测试事实明确自报，不能填写verified。保留失败、部分输出、取消与未知。

## 独立审核与返工

本方法要求独立审核Unit对同一固定交付版本检查真实性、完整要求/CheckKeys、范围及测试。宿主只提供通用身份匹配/约束检查，不把不同于作者硬编码到所有方法。系统保存审核Unit实际来源、检查内容/证据及asserted/verified边界；引用或角色标签不能升级真实性。

缺材料保留insufficient/unknown；重要设计缺口回DID，普通修复在原scope内返工。新交付新固定引用及SubmissionRef，旧报告/失败/review保留；旧target审核不覆盖新版本。审核通过不产生采纳权限，原工程机制保存结果并按有效权限/CAS推进。
