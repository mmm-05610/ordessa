# Harness v2：运行适配与配置贡献实施包

原方案日期：2026-09-28；2026-09-30 所有权修订已获用户授权，实施中。历史基线和完成声明不因此更新。

采用 GitHub Spec Kit 的 spec → research/plan → data-model/contracts → tasks → checklist 结构；不是派工单，不声称已运行 Spec Kit 命令。本文是目标设计，不是现状或测试通过报告。

## 一句话裁定

**Harness 管“怎么运行、各品牌怎么接入资源、怎么安全应用”；业务插件管“资源是什么、内容/目录/存储/UI”；Profile 管“保存哪一套、当前会话覆盖哪些项”。**

各品牌原生配置适配位于 Harness 对应品牌目录的 configuration/；品牌 registration 汇聚实际能力，复用现有 C2 点。业务插件只解析资源选择与版本，不处理品牌文件格式、原生 option 或 restart/resume。实现与研究依据见 [所有权修订](resource-boundary-amendment.md)和[多 Harness 源码研究](multi-harness-organization-research.md)。

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
- [Profile v2](../profile-v2/README.md)的会话覆盖、下一次输入生效、失败不清覆盖、隐藏缺席配置面等语义全部保留。本包细化其中 native intent 的所有者：**由 Harness 品牌内的配置适配模块编译**，不是 Profile、资源插件或通用应用引擎集中写品牌分支。
- [分包决策](../plugin-layout-and-preparation-decisions.md)中的 assets 是插件族，不是总服务。本包不新建 assets 加载器，不改变已另行修订的前端 UI 方案。
- 当前已有 ACP access、原生 materialization、Claude 官方 adapter 替换，均为迁移资产；没有已实现的本包契约。旧 README、历史 DELIVERY 不可替代源码与本次验收。

## 当前基线与批准边界

只读核查时根树 main 为 `cd7d31f3cf`。平台参考：Pacthold `9e33a4df51`、Server `f02228cc9f`、Frontend `82b7ef1fc3`；Server 工作树另有未提交修改，以上**不是可直接开工的组合基线**。

本文未切分支、未改生产代码、未动其他工作树、未提交/合并/push、未运行真实模型。实施 worktree 必须从平台验收并集成后的指定 SHA 创建，根树保持 main。
