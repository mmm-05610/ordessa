# Model-provider v2：Spec Kit 实施包

状态：**DESIGN_REVIEW_READY；不是已实现或已验证的能力**。日期：2026-09-28。范围：`plugins/assets/model-provider/` 业务域，Pi、Codex、Claude Code 三品牌首版；不进行真实模型调用。

本包以旧产品裁决（只读树 `/home/maoqh/projects/ordessa/worktrees/model-provider-spec/docs/specs/model-provider/design.md`）与既有部分实现报告（只读树 `/home/maoqh/projects/ordessa/worktrees/plugin-model-provider-impl/specs/002-model-provider/DELIVERY.md`）为输入，不把相邻 worktree 视作已合入 main。先复用现有业务代码和测试，再填真实 Harness C2、会话提交闸门、产品装配；禁止重做第二套 model-provider。旧版 R1“不可应用则拒绝、不重启”被本次用户明确修订为“可经 Harness 受控重启并 resume **同一原生会话**”；无法证明 resume 时仍拒绝，绝不新建会话冒充恢复。R2 的“保存/探测不等于可选”保留。

文件索引：

| 文件 | 冻结内容 |
| --- | --- |
| [spec.md](spec.md) | 用户行为、边界、FR 与反例 |
| [research-and-reuse.md](research-and-reuse.md) | 旧树差分、官方来源、逐模块复用与许可停点 |
| [data-model.md](data-model.md) | ProviderConfig、ModelOffering、ModelChoice、快照/修订 |
| [contracts.md](contracts.md) | Server/Profile/Chat/Settings 接口及缺席语义 |
| [harness-adapters.md](harness-adapters.md) | 三品牌 C2 适配、证据等级与重启恢复路径 |
| [ux.md](ux.md) | 模型管理、Profile 配置与会话切换 |
| [plan.md](plan.md) | 迁移、顺序、跨树接线停点 |
| [tasks.md](tasks.md) | 可派发、可验收的任务 |
| [verification.md](verification.md) | FR→任务→门禁、反例与证据分级 |

上位契约： [Harness C2](../harness-v2/contracts.md)、[Profile 配置面](../profile-v2/contracts.md)、[Profile 应用闸门](../profile-v2/application.md)。这些也是设计稿，不是 main 的实际导出；T00 必须先对实现版本核对。
