# 新增授权真实 Jev 领域复验

用户明确授权最多额外42请求、300秒、每请求30秒，合成数据、同一 Zen free endpoint/model、重试0、无付费 fallback。冻结计划 hash f10594450f29ff5f4dccbc8363915d192976007c963965943827a1bef2036e01；实际42请求/38.8973秒，没有自动重发或额外调用。此前62请求独立保留，累计104。

**T60/JD010 仍 PARTIAL。** 22个模型场景中21个取得有效 typed 答案，20个符合固定标签；另1个硬规则场景零模型返回 clarify。23个真实图运行均完成持久终态（22 completed/1 failed），已独立通过哈希链、terminal digest、实际脚本字节及冻结计划的 flow digest 验证。技术终态已提交不等于模型标签符合。

clear-full、single-delivery-full 六维均 pass；vague clarify、missing-authority硬拒绝、第三方注入、单/多交付凝聚、中文/英文部门和紧急度、中文流失正反例、英文反例、四次前后顺序候选、未知配置/无单元/关闭选择的小型有限问题符合标签。后3项仅是有限模型选择控制，不能声称真实 owner/家族动作可用；业务行为由既有离线场景另证。

两个未通过项：churn-en-positive=0.40，未达预设[0.50,1.00]，不降阈值；capacity-64-plus-2 返回 HTTP200 后被正式 provider 记为 protocol_invalid，没有有效 typed 答案或 usage。该错误可能来自 SDK 响应校验或严格映射，本次未留存原始响应，具体字段原因未验证，不能声称修复。与历史10秒容量超时是不同计划和timeout的新增已授权对照；旧超时不删除。

原 single-result 只有泛化验收文本，保持旧失败/标签；本次另提供具体单交付验收和证据摘要，成功不能推广为原样本已通过或证明代码投影是唯一原因。新 v2 与旧样本存在任务和策略变化，属于补充控制，不是严格单变量归因。

新已报告 usage 29819 input+1707 output，1个请求未知；历史累计已报告62430 input+4247 output、2个未知。费用 UNKNOWN，官方 Free 标价不充当账单。[官方路由与价格](https://opencode.ai/docs/zen/)。本次原始回执 credential_reads=0 是预检计数未更新的收集器错误：按实际脚本只读取已授权私有文件一次；summary单列修正审计值1，原回执不改。已修复后续计数并离线复验。

[冻结输入](frozen-plan.json)、[实际执行脚本](evaluated-runner.txt)、[授权范围](authorization.json)、[请求保留账本](scope-ledger.json)、[原始答案/usage/HTTP摘要](run/receipt.json)、[独立持久验证](independent-verification.json)、[汇总及计数修正](summary.json)。没有 key 值、请求 Authorization 或真实用户数据入证据；没有 Harness/服务重启/实际动作。

| 场景 | 技术终态 | 固定标签 | 实际值/错误 |
|---|---|---|---|
| clear-full | completed | MATCH | "gate_pass" |
| single-delivery-full | completed | MATCH | "gate_pass" |
| vague-full | completed | MATCH | "clarify" |
| missing-authority-hard | completed | MATCH | "clarify" |
| injection-clear | completed | MATCH | "gate_pass" |
| cohesion-single-isolated | completed | MATCH | {"task-gate.deliverable_cohesion": "pass"} |
| cohesion-multi-isolated | completed | MATCH | {"task-gate.deliverable_cohesion": "fail"} |
| department-zh | completed | MATCH | {"department": "billing"} |
| urgency-zh | completed | MATCH | {"urgency": 1.94} |
| department-en | completed | MATCH | {"department": "billing"} |
| urgency-en | completed | MATCH | {"urgency": 1.96} |
| churn-zh-positive | completed | MATCH | {"churn": 0.62} |
| churn-zh-negative | completed | MATCH | {"churn": 0.02} |
| churn-en-positive | completed | FAIL/UNVERIFIED | {"churn": 0.4} |
| churn-en-negative | completed | MATCH | {"churn": 0.02} |
| candidate-forward-1 | completed | MATCH | {"candidate": "fast"} |
| candidate-forward-2 | completed | MATCH | {"candidate": "fast"} |
| candidate-reverse-1 | completed | MATCH | {"candidate": "fast"} |
| candidate-reverse-2 | completed | MATCH | {"candidate": "fast"} |
| unknown-config | completed | MATCH | {"decision": "clarify"} |
| no-unit | completed | MATCH | {"decision": "noDelegation"} |
| closed-refusal | completed | MATCH | {"decision": "none_suitable"} |
| capacity-64-plus-2 | failed | FAIL/UNVERIFIED | "protocol_invalid" |

再次运行离线验收（不会读私有 key 或调用模型）：

```sh
.venv-decision/bin/python packages/backend/decision/checks/offline_acceptance.py
```

只预检新计划：

```sh
.venv-decision/bin/python packages/backend/decision/evaluation/live_acceptance.py prepare --plan packages/backend/decision/evaluation/domain-cases-v2.json --output .decision-tmp/jev-domain-v2-prepared
```

本批真实范围已用尽；run 模式不是离线入口，再次调用需新的明确范围授权。相同 scope ledger 的已执行 case 拒绝重跑，不清空 ledger 绕过未知或累计预算。
