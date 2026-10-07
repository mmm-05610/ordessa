# 真实 Jev 原图边界整合补测

四个计划先冻结，沿原build_assignment_flow、runtime/gateway/permit、官方SDK与持久FileEvidenceSink；各6请求/45秒上限，实际共24 HTTP，重试0，原生效果0，费用UNKNOWN。没有实际Harness或家族配置应用。

| 场景 | 原图结果 | 候选读取/组合/校验 | 有效边界 |
| --- | --- | --- | --- |
| empty | clarify/no_evidenced_candidate | 1/0/0 | 完整空目录不能编造候选 |
| main | ready/noDelegation提案 | 0/0/0 | 外部policy明确开启且任务含允许边界；不执行操作 |
| configuration | clarify/proposal_unverifiable | 1/1/1 | 实际ConfigurationOffer DTO及注册组合器结构通过；必需owner语义unknown，不ready |
| injection | ready/reuse提案 | 1/1/1 | 原v2第三方注入TaskBrief；组合/校验仅受控资料，没有启动/写生产 |

配置kind/schema/字段/值来自外部fixture，未写进执行引擎。offer支持状态unknown，结构可解析不证明原生语义支持；负回执精确绑定proposalDigest且required obligations为unknown。pure-read家族能力仍unsupported，本批不能填成产品可用。注入样本只有一个，不宣称全面抗注入。

每子目录含冻结计划、实际源码三个快照、typed答案、scope ledger、原图轨迹和持久终态。独立复验4个run的hash chain/terminal.commit/result digest/source/plan/FlowRef，以及动作、issue和调用计数，见independent-verification.json。快照保留原文件名排序，以复现reviewed_code_digest的原排序；首归档复查误换文件名造成排序不同、hash失败，修正审计脚本后验证通过，实际源码/运行未改、无追加HTTP。

首预检因探针错用VersionedObservation.descriptor_digest失败，改为实际content_digest；失败发生在key/HTTP前，记录edge-initial-preflight.txt为主会话审计记录。8项fake测试通过，再加boolean不得冒充整数预期的反例，9项通过；假传输的真实请求/模型质量计数均0。最终默认离线入口269项全套、67逐场景、57基线/当前ID和独立wheel离线重建安装全部通过，见offline/与core日志。全Server/Harness继承红未重跑，不据此报全仓绿。

此批24次均报告usage：23106输入/1076输出。累计208次，已报告164315输入/13689输出，历史3次usage未知，费用UNKNOWN。旧英文正例/66选项协议错误/丢答案/超时保持原记录。

可直接运行的离线验收：

```bash
.venv-decision/bin/python packages/backend/decision/checks/offline_acceptance.py
```

边界计划零凭据预检：

```bash
.venv-decision/bin/python packages/backend/decision/evaluation/edge_flow_probe.py prepare --plan packages/backend/decision/evaluation/edge-configuration-plan.json --output .decision-tmp/edge-prepare
```
