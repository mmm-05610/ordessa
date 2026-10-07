# Dot 架构设计交接：源码检查点与产品方向

日期：2026-10-07。此分支提供固定源码快照和新方向文档，不是一次代码迁移，也不是已完成产品的发行。

## 固定源码

选择的检查点：`f5deae2332ae390abdf0b90eb0b7e052f02cf239`（2026-10-07）。

来源分支：`codex/architecture-cleanup`。它包含 Agent Tools 检查点 `20558870b3c1afaf62b1c1b585e6a0739f5acc95`，该祖先关系已用 git merge-base 核对；Decision、Agent/Profile 权威迁核心、Harness 品牌包和 Assets 归位的已提交工作均在快照内。

不收录任何工作树的未提交修改、个人 Token、运行数据或个人 Skill 目录。原工作树继续工作，main 不改变。后续别处的提交不会自动改变这个快照。

## 给设计者的入口

- [产品方向与责任边界](software-engineering-harness-direction.md)：本次讨论的主文档。
- [决定记录](software-engineering-harness-decisions.md)：明确方向、授权与未确认建议的区分。
- [当前迁移证据及缺口](../../specs/032-architecture-cleanup/evidence/delivery.md)：各阶段迁移、验证记录与未退役链。
- [整合来源](../../specs/032-architecture-cleanup/integration-report.md)：源码来源及未纳入成果。
- [Agent Tools 工作记录](../implementation/agent-tools/status.md)：节点配置、材料消费、装配与真实 Harness 验证的范围。

## 可用的含义和不能推断的结论

这是可用于架构设计和源码审阅的较新检查点，不保证开箱即用，不是 PRODUCT_READY。

检查点内记录的验证包括 Codex/Pi/Claude Code 品牌套件 278/318/255 通过、harness-transport 103 通过、persistence-sqlite 43 通过及多个前端工作区通过。它们是来源工作树保存的验证记录，不是本次发布复跑的全量结果。

核心、Server 与部分插件仍有已登记失败。旧链退役只到 Phase 2–4 完成、Phase 5 进行中；runtime-compat 仍有 471 行两块剩余，server-compat、Go 桥、命令适配器及遗留品牌运行时尚未全部退役。不要把新方向文档与当前源码当成已一致。

本次不执行真实模型调用、不安装 Harness、不重启服务、不迁真实数据。个人 DID 工作流 Skill 已制作，但不是 Ordessa 中已接线的工程工作流产品。

本次独立发布树实际复跑：使用现有测试解释器，以 `pytest -q --noconftest packages/backend/pacthold/tests/harness_kit/test_core_boundaries.py` 检查本树文件，5 passed。此套件是文件/AST 层的边界守卫；关闭 conftest 是为了避免引入另一个正在修改的工作树的 editable 依赖，它不构成运行时或全量产品验证。两份方向文档与主树原稿逐字节对照一致。

## 给 Dot 的讨论提示词

> 请基于本分支固定源码及产品方向文档，和我讨论 Ordessa 的新架构：面向软件工程、使用 agent-node 接入各家 Harness、不重写底层 loop；工程工作流、文档标准和判定策略外置加载，允许经验证的版本化改进。先识别哪些现有机制可复用、哪些责任应收窄或独立，再设计运行机制与外置方法的边界。区分已确认方向和 Agent 的建议，不把现存兼容链当作目标，也不要直接生成宏大实施包或开始迁移。重点帮助我看懂每项能力为什么需要、由谁拥有状态、怎样协作，以及哪些重要选择还没确定。
