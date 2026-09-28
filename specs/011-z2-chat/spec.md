# Z2 — Chat 展示、创建与输入扩展

执行者：ZCode。业务需求见 [chat-zcode-reuse](../../docs/design/chat-zcode-reuse/README.md)，须读每包全部契约/数据/适配/UX/复用/任务与验收文件。

本轮派发授权和所有权以 [共同 spec](../011-plugin-rollout/spec.md)、[plan](../011-plugin-rollout/plan.md) 为准；它们覆盖旧包中越界写入与“尚未派发”的过程文字，不覆盖产品行为。

## 职责
复用 ZCode 正文/思考/紧凑工具展示；项目弹窗、项目内草稿、共享 +/斜杠菜单、附件贯通。前端 ACP/Ordessa 会话服务由 C0 写，本线提 DTO 和反例。旧 plugins/agent/sessions 只读盘点，是否迁移由 C0 统一裁决。

## 写入面
- `plugins/chat/**`
- `经迁移表证明属于 Chat 的 plugins/agent/conversation/**`
- `Chat 领域轻量 API（位置先对齐现有契约）`
- 本 feature 的任务、报告、接缝请求、集成清单；其他线的工作树只读。

## 成功条件
原实施包适用任务全部实现、按其证据等级验证，公开接线使用真实 API。保留每个原任务 ID；未通过的生产门不能以纯单元测试替代。结尾报告完成/阻塞/未测三类事实及具体 SHA。
