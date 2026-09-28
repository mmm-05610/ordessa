# Z1 — Profile v2

执行者：ZCode。业务需求见 [profile-v2](../../docs/design/profile-v2/README.md)，须读每包全部契约/数据/适配/UX/复用/任务与验收文件。

本轮派发授权和所有权以 [共同 spec](../011-plugin-rollout/spec.md)、[plan](../011-plugin-rollout/plan.md) 为准；它们覆盖旧包中越界写入与“尚未派发”的过程文字，不覆盖产品行为。

## 职责
只拥有 Profile 的轻量 API、配置面、存储、覆盖、管理 UI 和 Profile 自己的 Chat glue。复用旧 profile 实现；其他领域的 Profile glue 由该领域写。

## 写入面
- `plugins/profile/**`
- 本 feature 的任务、报告、接缝请求、集成清单；其他线的工作树只读。

## 成功条件
原实施包适用任务全部实现、按其证据等级验证，公开接线使用真实 API。保留每个原任务 ID；未通过的生产门不能以纯单元测试替代。结尾报告完成/阻塞/未测三类事实及具体 SHA。
