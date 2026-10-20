# Engineering 固定 Skill bundle 退役

用户在 2026-10-09 明确要求处理 Engineering 内旧 `skill_bundle`。当前设计的 Skill 内容归对应方法资源，通过 MethodSnapshot 冻结和引用；本次不增加替代包，不修改受保护的 domain、包内 methods、顶层 methods、它们的专属测试或设计原件。

已退役：

- 包内11份静态资源、`resources.py` 加载器及其源码完整性入口。
- setuptools 的 Skill bundle package-data 声明。
- C09 fixture 的材料生成、Proposal字段和输入ref。
- 旧Workflow的必须依赖、固定包验证及新application receipt绑定。
- 新 `skill-bundle` 材料导入；有限错误 `material_kind_retired`。
- 带旧 `refs.skill_bundle` 或 Proposal `skill_bundle_ref` 的可执行输入；有限错误 `retired_skill_bundle_binding`。检查在run状态、acceptance、step/effect写入前完成。可选 `refs.method` 必须是实际method且与run的method_ref一致，不能把退休材料藏在别名中。

本次不退役整个 EngineeringWorkflow，不改变其其他材料审核/CAS机制，不触碰 Agents/Harness 自有Skill资源能力。

## 历史数据及迁移边界

没有改DDL、表名、data-root、schema version或历史标识；没有运行任何用户数据库迁移。原 `materials` 中 kind=`skill-bundle` 的 bytes/digest、Proposal、receipt、run refs全部保留。原 Library 的 exact `read/head` 和原run_status继续查询历史事实；读取不授权续跑。没有把旧ref静默删掉后恢复执行，没有重新计算历史摘要。

registry源码闭包显式 revision12→13；旧method/run中的ref不重写。包内受保护的两个历史方法仍pin revision11，这一完整性拒绝在本轮开始前已经存在，且继续保留。默认 C09 demo目前不可执行；没有降低完整性门或创建运行时repin。

不存在自动迁移或兼容执行链。未来要使用旧材料，应基于新方法明确重新构造新的工程输入及其新身份；不能沿用旧run的执行授权。

## 来源与恢复

源快照 HEAD：`751707e1f1558d6b868a8761aed7c5a8dfbd4ef2`。
被移除资源原路径：`packages/engineering/src/ordessa_engineering/skill_bundle/`。
11份原bytes及摘要由Git该HEAD和本次证据中的资产清单保留，未复制为另一份可达运行实现。

[C09历史材料](../implementation/agent-core-engineering/evidence/C09/README.md)、[R0025历史裁定](../implementation/agent-core-engineering/rulings.md)及V32/V33原报告保持原字节；其中旧资源loader探针与wheel清单只适用于历史快照，不能在当前树作为活动验证入口使用。

本轮实际删除、保护边界、源码/wheel验证及未完成范围见[退役证据](../implementation/nightly/evidence/skill-bundle-retirement/README.md)。
