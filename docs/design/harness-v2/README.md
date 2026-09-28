# Harness v2：运行适配与配置贡献实施包

日期：2026-09-28。状态：**DESIGN_REVIEW_READY；尚未授权实施**。

采用 GitHub Spec Kit 的 spec → research/plan → data-model/contracts → tasks → checklist 结构；不是派工单，不声称已运行 Spec Kit 命令。本文是目标设计，不是现状或测试通过报告。

## 一句话裁定

**Harness 管“怎么运行、怎么安全应用”；业务插件管“这项配置是什么、各 Harness 怎么表达”；Profile 管“保存哪一套、当前会话覆盖哪些项”。**

例如 Skills 的 Claude/Pi 适配写在 Skills 内，Model-provider 的 Codex/Claude/Pi 适配写在 Model-provider 内；它们注册到 Harness 的配置扩展点。Harness 的品牌运行适配器负责实例配置根、启动、协议控制、重新加载和恢复，不重新解释 Skill 或供应商业务。

“一步到位”指这次范围内完成所有权迁移、生产接线、旧入口删除与反例验证，不保留双写、兼容 facade 或成功空桩；**不等于把八家官网所有配置项在本批实现出来**。未实现的具体能力诚实不提供，不是兼容债。模型与 Skill 是本批两个真实配置消费者，不能只交付注册框架。

## 阅读次序

1. [spec.md](spec.md)：用户结果、范围、FR 与成功条件。
2. [plan.md](plan.md)：目录、依赖、执行顺序和非目标。
3. [contracts.md](contracts.md)：两个注册点、应用服务、原生写入和协议所有权。
4. [data-model.md](data-model.md)：版本、事务、恢复与数据归属。
5. [research-and-reuse.md](research-and-reuse.md)：已读代码、可复用实现与证据限制。
6. [migration.md](migration.md)：旧模块去向、删除与升级规则。
7. [tasks.md](tasks.md)：有依赖的实施任务及逐条验收。
8. [verification.md](verification.md)：正反例、独立装包、受控联调、执行记录。
9. [blockers.md](blockers.md)：执行前必须锁定的输入，不许执行者自行扩大架构。

## 与既有方案的关系

- [配置调研](../harness-configuration/README.md)提供上游事实和缺口，不代表当前集成能力。
- [Profile v2](../profile-v2/README.md)的会话覆盖、下一次输入生效、失败不清覆盖、隐藏缺席配置面等语义全部保留。本包细化其中 native intent 的所有者：**由业务插件内的 Harness 配置适配模块编译**，不是 Profile 或 Harness 集中写品牌业务分支。
- [分包决策](../plugin-layout-and-preparation-decisions.md)中的 assets 是插件族，不是总服务。本包不新建 assets 加载器，不改变已另行修订的前端 UI 方案。
- 当前已有 ACP access、原生 materialization、Claude 官方 adapter 替换，均为迁移资产；没有已实现的本包契约。旧 README、历史 DELIVERY 不可替代源码与本次验收。

## 当前基线与批准边界

只读核查时根树 main 为 `cd7d31f3cf`。平台参考：Pacthold `9e33a4df51`、Server `f02228cc9f`、Frontend `82b7ef1fc3`；Server 工作树另有未提交修改，以上**不是可直接开工的组合基线**。

本文未切分支、未改生产代码、未动其他工作树、未提交/合并/push、未运行真实模型。实施 worktree 必须从平台验收并集成后的指定 SHA 创建，根树保持 main。
