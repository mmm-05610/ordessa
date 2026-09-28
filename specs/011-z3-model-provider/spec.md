# Z3 — Model-provider v2

执行者：ZCode。业务需求见 [model-provider](../../docs/design/model-provider/README.md)，须读每包全部契约/数据/适配/UX/复用/任务与验收文件。

本轮派发授权和所有权以 [共同 spec](../011-plugin-rollout/spec.md)、[plan](../011-plugin-rollout/plan.md) 为准；它们覆盖旧包中越界写入与“尚未派发”的过程文字，不覆盖产品行为。

## 职责
优先复用旧部分实现与反例；Provider/Model 原子选择，下轮应用，双会话隔离，必要时重启并 resume 同一原生会话。拥有本域品牌 adapter 与 Profile/Chat glue。

## 写入面
- `plugins/assets/model-provider/**`
- `旧 plugins/model-provider/** 的本域保真迁移`
- 本 feature 的任务、报告、接缝请求、集成清单；其他线的工作树只读。

## 成功条件
原实施包适用任务全部实现、按其证据等级验证，公开接线使用真实 API。保留每个原任务 ID；未通过的生产门不能以纯单元测试替代。结尾报告完成/阻塞/未测三类事实及具体 SHA。
