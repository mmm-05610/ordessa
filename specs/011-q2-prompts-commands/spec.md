# Q2 — Prompts 与命令模板

执行者：Qoder。业务需求见 [prompts](../../docs/design/prompts/README.md)、[command-templates](../../docs/design/command-templates/README.md)，须读每包全部契约/数据/适配/UX/复用/任务与验收文件。

本轮派发授权和所有权以 [共同 spec](../011-plugin-rollout/spec.md)、[plan](../011-plugin-rollout/plan.md) 为准；它们覆盖旧包中越界写入与“尚未派发”的过程文字，不覆盖产品行为。

## 职责
两个独立域可派两个单包子代理。Prompts 默认跟随正文修订、提交时冻结；模板引用固定批准版本，展开到可编辑用户草稿且不自动发送；不要强行统一二者版本语义。

## 写入面
- `plugins/assets/prompts/**`
- `plugins/assets/command-templates/**`
- 本 feature 的任务、报告、接缝请求、集成清单；其他线的工作树只读。

## 成功条件
原实施包适用任务全部实现、按其证据等级验证，公开接线使用真实 API。保留每个原任务 ID；未通过的生产门不能以纯单元测试替代。结尾报告完成/阻塞/未测三类事实及具体 SHA。
