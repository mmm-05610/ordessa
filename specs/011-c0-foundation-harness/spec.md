# C0 — 公共基线、Harness 与总集成

执行者：Codex。业务需求见 [harness-v2](../../docs/design/harness-v2/README.md)，须读每包全部契约/数据/适配/UX/复用/任务与验收文件。

本轮派发授权和所有权以 [共同 spec](../011-plugin-rollout/spec.md)、[plan](../011-plugin-rollout/plan.md) 为准；它们覆盖旧包中越界写入与“尚未派发”的过程文字，不覆盖产品行为。

## 职责
先审核 A/C 平台与侧栏，准备 Harness 独立工作；platform-server 由原会话收尾，等其提交交接后才集成 B 并验收剩余缺口。发布 foundation/harness-api，统一 ACP 配置、附件、命令、执行前授权与提交闸门，最后串行整合业务线。

## 写入面
- `plugins/harness/**`
- `plugins/connectors/acp/**`
- `plugins/connectors/ordessa/**`
- `新增 Harness 领域 API 发行包（按 harness-v2 T03 冻结位置）`
- 本 feature 的任务、报告、接缝请求、集成清单；其他线的工作树只读。

## 成功条件
原实施包适用任务全部实现、按其证据等级验证，公开接线使用真实 API。保留每个原任务 ID；未通过的生产门不能以纯单元测试替代。结尾报告完成/阻塞/未测三类事实及具体 SHA。
