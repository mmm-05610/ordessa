# 真实 Jev 贯穿原多候选选择

三个先冻结的合成计划，各7次请求，合计21次；原 `build_assignment_flow` 实际执行六维任务门、`SelectAssignment` 的 `assignment.rank` 及结果路由。官方SDK、原runtime/gateway/持久permit和FileEvidenceSink均复用，未复制排名执行器。

| 计划 | 预期/实际排名 | 原图结果 | 组合/校验 |
| --- | --- | --- | --- |
| preferred-first | proposal_0 | ready，确切提案digest符合 | 1/1 |
| preferred-second | proposal_1 | ready，确切提案digest符合 | 1/1 |
| insufficient | insufficient_evidence | clarify，无提案payload | 1/0 |

排名规则由冻结外部policy提供，候选payload的 synthetic_preference 明确是虚构对照，不是假装真实成本或原生能力。前两条反转相同偏好标记的位置，第三条两个标记均unknown。它们证明闭集选择/拒绝与原图整合，不宣称模型已全面理解真实选型成本或家族能力。准备阶段先以受控provider离线运行原图捕获准确问题，标为 not_evaluated，零凭据/HTTP；真实路径严格核对问题摘要与顺序。

每条保留实际探针和两份依赖源码、计划、typed答案、scope ledger、轨迹、持久run。`independent-verification.json` 独立验证3条hash chain/terminal.commit/result digest/源码/计划/FlowRef及先冻结预期。21个请求均报告usage，费用UNKNOWN，原生效果0，重试0。与此前累计184请求，已报告141209 input/12613 output，3次历史usage未知；未覆盖旧失败。

离线测试原8项通过；再补全局截止及外部取消两项，10项通过。合法ID、两个拒绝ID、tie、未知ID技术失败、坏计划零凭据读取、不可重用已消费attempt、取消传播/未知费用均有反例；假传输质量计数始终0。

离线准备入口（不读凭据）：

```bash
.venv-decision/bin/python packages/backend/decision/evaluation/rank_flow_probe.py prepare --plan packages/backend/decision/evaluation/rank-preferred-first-plan.json --output .decision-tmp/rank-prepare
```
