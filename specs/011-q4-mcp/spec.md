# Q4 — MCP 定义与托管

执行者：Qoder。业务需求见 [mcp](../../docs/design/mcp/README.md)，须读每包全部契约/数据/适配/UX/复用/任务与验收文件。

本轮派发授权和所有权以 [共同 spec](../011-plugin-rollout/spec.md)、[plan](../011-plugin-rollout/plan.md) 为准；它们覆盖旧包中越界写入与“尚未派发”的过程文字，不覆盖产品行为。

## 职责
native/managed 唯一连接/关闭 owner，工具目录与授权分离。定义/目录可先做；实际工具调用必须等真实 Permissions 授权接线，不默认放行。Pi 桥的本域组件由本线写，runtime 装载由 C0 提供。

## 写入面
- `plugins/assets/mcp/**`
- 本 feature 的任务、报告、接缝请求、集成清单；其他线的工作树只读。

## 成功条件
原实施包适用任务全部实现、按其证据等级验证，公开接线使用真实 API。保留每个原任务 ID；未通过的生产门不能以纯单元测试替代。结尾报告完成/阻塞/未测三类事实及具体 SHA。
