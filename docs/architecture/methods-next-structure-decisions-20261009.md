---
id: DEC-METHODS-NEXT-STRUCTURE-20261009
revision: 2
kind: explicit_decision
validity: valid
object: "Ordessa Engineering methods 下一轮目标结构与职责"
scope: "methods 设计记录；待统一实施；不构成其它动作模块代码验收"
source:
  locator: "父会话 01a118bc-dd26-7553-b5b6-cf5137c070d6 转交的本轮 codex_delegation 消息"
  time: "2026-10-09；准确消息时刻 unknown"
  quote: "以下是新目标结构与职责，已确认设计、待统一实施，不虚报已落地。"
  locator_limitations: "上述引文来自父会话批准转述；此执行环境没有用户原消息的独立 ID 或完整逐项讨论原文，不编造该定位。"
supersedes: ["DEC-METHODS-NEXT-STRUCTURE-20261009@1"]
---

# Methods 下一轮结构与职责决定记录

本记录保存用户已确认的目标与本轮文档授权。**设计已确认，统一实施尚未开始**。用户已大致认可当前 definitions；其它方法动作模块尚未逐项代码验收。本记录不把设计确认、既有受控测试通过或候选文件同步解释为这些模块的实现验收。

讨论上下文：前轮已将严格解析与格式校验执行移出 definitions，并建立原始捕获 bytes 与不可变派生视图；用户继续审阅 methods，确认下一轮四目录职责，要求晚点统一派一个会话实施。本轮只记文档。

## 已确认决定（explicit_decision）

### 1. definitions：模型、格式与契约

批准目标如下。文件名体现职责；它们不是本轮已落地清单。

```text
methods/definitions/
├─ models/
│  ├─ identity.py
│  ├─ sources.py
│  ├─ capabilities.py
│  ├─ verification.py
│  ├─ loaded.py
│  ├─ compiled.py
│  └─ snapshot.py
├─ schemas/v1.py
├─ contracts/
│  ├─ sources.py
│  └─ validation.py
├─ errors/
│  ├─ diagnostics.py
│  ├─ failures.py
│  └─ results.py
└─ defaults.py
```

- models 定义身份、源内容、能力、证据、加载结果、编译语义和快照等阶段数据；只做自身不变量及摘要/长度等纯派生。
- schemas 保存版本化外部格式数据；contracts/sources 保存源读取接口。
- contracts/validation 保存检查上下文、阶段与报告契约；与 errors 的诊断/结果类型必须有唯一真实 owner，不重复定义。具体引用/导出关系在实施包中明确，不能因为目录名另造一份 ValidationReport、Diagnostic 或结果类型。
- errors 保存错误、诊断、异常携带与结果数据，不承担外部处理流程。
- defaults.py 是共同默认值的唯一 owner。常量和值的归属切换不能保留第二份定义。
- definitions 不做 IO、文本解析、流程编排、外部 schema 校验或工作流执行，不反向依赖 loading/validation/compilation。不得通过 getter 或延迟 import 绕过方向。

definitions README 准入规则须说明：何时允许加入；为何属于该职责；唯一 owner；公开导出；版本与兼容边界；验证测试。README 不能将普通工具函数、动作流程或延迟反向导入合理化为数据定义。

### 2. validation：检查算法与阶段报告

```text
validation/{structure,values,references,workflow,compatibility,policies,schema,validate}.py
```

分别执行格式、JSON 值、引用、控制流、宿主兼容、策略跨字段、文档 schema 等检查，阶段入口汇总报告。消费 definitions；外部上下文均由调用方传入，不读文件、查库或启动 Harness，不反调 loading/compilation。

检查算法放 validation，不强行制造规则 DSL。模型自身不变量仍归模型；parser 不可分割的语法拒绝以及有界读取安全仍在发生阶段完成；这些规则不复制为另一份清单。

### 3. loading：读取、捕获、解析与组装

```text
loading/{loader,parsing,captured}.py
```

接收来源、源读取接口与限制：读取 manifest，完成该阶段基础格式验证，再按声明读取资源；边读边做限额、路径和摘要核验；捕获原始 bytes，调用唯一严格 parser，组装绑定原内容的不可变派生视图及 LoadedMethod。可读取可选验证证据，但不把存在的 lock/golden 当作已可信证据。

按阶段调用 validation，不另建重复规则。**LoadedMethod 只证明加载捕获，不代表完整验证通过或可执行。**源读取接口改归 definitions/contracts。

不丢失现有 snapshot/content 功能：持久化读取归适配层，源重建复用 loading，内容检查归 validation，冻结保存由上层协调。实施时必须逐项对照真实消费者与现有事务、授权、历史读取边界；不能只删 loading/snapshot.py 或 content.py 后宣称迁移完成。

### 4. compilation：编译语义与规范编码

```text
compilation/{compiler,workflow,standards,decisions,documents,skills,capabilities,encoding}.py
```

以 LoadedMethod 为输入，调用完整 validation，绑定精确来源，生成类型化 CompiledProgram 及规范编码/摘要，不隐式加载文件。路径到编译的便利流程由上层组合。

模型与纯派生仍归 definitions；序列化实现归 encoding，避免模型反向 import compilation。以上名字明确职责位置，不强迫每项立刻独立文件；少量相近内容可以合并，但唯一职责、状态权威和消费者必须清楚。

目录名保持 definitions/validation/loading/compilation。

### 5. 依赖方向与权威

```text
definitions：最底层
validation → definitions
loading → definitions + validation
compilation → definitions + validation
```

若编译边界需要重建并核验源派生结果，应通过清晰的纯机制或上层组织实现，不隐藏反向依赖。原始源 bytes 唯一权威、不可变派生视图非信任凭证、现代类型化编译语义唯一权威和独立历史存储格式的既有决定继续有效。

## 本轮授权（explicit_delegation）

```yaml
id: DEL-METHODS-NEXT-RECORD-20261009
revision: 1
kind: explicit_delegation
validity: valid
object: "保存并同步本次 methods 决定记录"
scope: "nightly/docs/architecture 独立 Markdown；同一记录同步 architecture-review"
source:
  locator: "同一父会话本轮 codex_delegation"
  time: "2026-10-09；准确消息时刻 unknown"
  quote: "当前任务仅写设计记录，不再改源码、不开始新实现。"
  locator_limitations: "父会话转交授权；不虚构用户原消息 ID。"
supersedes: []
```

本轮只允许新建独立记录并检查冲突后单向同步；不改两树 README 主入口、共享 pins/registry，不 git add/commit，不开始统一实施、测试或新的业务迁移。用户决定所有更改晚点统一派一个会话实施；本记录没有提前激活该实施。

## 当前实现事实（fact_observation）

观察来源：2026-10-09 只读目录清单与直接 import 检查。施工树 HEAD 为 `751707e1f1558d6b868a8761aed7c5a8dfbd4ef2`（`codex/nightly-restructure-20261009`）；审阅树 HEAD 为 `db34f9057e220a2fc8e423b5c2fc2c9ab6703ef7`（`codex/architecture-review`）。候选仍有未提交改动，HEAD 不代表所有候选源码内容。前轮精确候选与验证边界见 `docs/verification/methods-parser-boundary-20261009.json`；本轮没有重新跑测试。

| 当前事实 | 与批准目标的区别 |
| --- | --- |
| models、schemas/v1.py、errors 包已存在；默认值实际在 models/defaults.py。 | 尚未迁到目标 definitions/defaults.py。 |
| 源读取及 snapshot/content/catalog 等 ports 仍在 loading/ports.py；definitions/contracts 尚不存在。 | 需要按接口职责迁移，不能把所有端口一并视为源读取契约。 |
| validation 使用 graph.py、method.py；已有 structure/values/references/compatibility/policies/schema。 | workflow.py、validate.py 的目标入口尚未切换。 |
| compilation 目前是 compiler.py、hashing.py、selectors.py、policies.py。 | 未按目标编译职责整理，不以目标文件名清单冒充已实现。 |
| compiler.py 与 validation/method.py 直接依赖 loading.captured.verify_loaded_method。 | 不满足目标 compilation/validation 的依赖方向。 |
| validation/compatibility.py 及 loading 的 loader/captured 等引用 compilation.hashing。 | 共享纯摘要机制的归属/调用需要统一处理，不能复制摘要算法。 |
| loading/snapshot.py 协调编译核对与发布；content.py 有内容检查及读取接口。 | 现有能力尚未完成上层/适配层/validation 的整体职责切换。 |

这些观察用于后续实施包的输入，不是当前代码缺口已经修复的声明。用户此前对 definitions 的大致认可，不扩展成上述动作模块的逐项代码验收。

## 待实施审查的风险与未决细节（open_question）

以下是需要统一实施包明确的实现问题，不撤销已批准职责，也不在本记录内自行选择替代架构：

1. **源与派生视图核验入口**：移除 compiler/validation 对 loading.captured 的反向依赖，同时保留真实 bytes 与用户可构造缓存的核验。明确纯机制或上层组织的 API、输入输出与调用顺序；不能只新增 Verified 标记或接受任意用户构造的缓存。
2. **检查契约唯一 owner**：为 contracts/validation 的上下文/阶段/报告与 errors 中诊断/结果逐类型列 owner、引用和公开导出。当前 ValidationReport、ValidationPhase 在 errors/diagnostics；具体类型迁移或引用组织尚未选定，禁止双份定义。
3. **序列化与纯派生界面**：划清模型的数据投影/纯派生和 compilation/encoding 的序列化实现；保持 canonical 字段、省略/显式默认、排序、版本及所有摘要域。不得用模型延迟导入 encoding，也不得保留竞争编码/摘要实现。
4. **读取/发布端口分工**：区分源读取接口、内容读取、持久化 snapshot store、宿主 catalog、发布身份索引。源读取进入 contracts/sources；其它端口的准确归属需对照上层与适配层实有消费者，不能无依据合并或删除。
5. **snapshot/content 完整迁移**：逐函数映射现有加载、内容验证、模板/技能字节读取、冻结发布、真实 blob 读取、显式历史重建、同事务核验与释放身份冲突处理。逐消费者切换，保留拒绝规则；不能用旧路径回退撑出完成状态。
6. **入口与辅助算法整理**：graph/method 到 workflow/validate，以及现有 selectors/policies/hashing 到目标职责的实际映射、是否合并少量文件，需统一实施包列明。目录/职责已经决定，不将文件分割数量本身当作完成标准。
7. **格式与规则唯一性**：目前的分阶段基础格式检查与完整 schema 校验、模型自身约束、parser 语法拒绝、有界读安全须保持各自发生阶段、错误优先级和唯一规则来源，不擅自新增 DSL 或改变方法语言。
8. **验证与同步范围**：实施包列明真实边界导入/反例、非法与歧义输入、缓存篡改/源绑定、完整受控回归、golden/历史字节和发行检查；先核对 shared pins 与所有实际消费者，由其 owner 协调。审阅树候选完整性和用户验收单独记录，不把局部测试通过当作产品或发行完成。

## 统一实施包交接补充（revision 2；仅事实与后续任务）

本次补充不改变上文已确认设计。revision 1 的完整原记录保存在 `methods-next-structure-decisions-20261009.r1.md`，原 SHA256 为 `8c0ec09ce0e89e69e9e12344d9c6ef98a1db7f5b60fa5ea2ff974dd31290fb81`。原用户设计决定、Agent 观察与本次 common 交接证据分开；新事实不能自动变成代码验收或提前实施许可。

来源：父会话 `01a118bc-dd26-7553-b5b6-cf5137c070d6` 本轮交接，以及审阅树 `docs/verification/common-responsibility-20261009/` 的 `domain-final.json/.stdout`、`direct-final.json/.stdout`、`strict-current.stdout`、`pin-handoff.json`。本轮仅只读核对日志、现有测试与模型字段，未重新运行这些测试。以下计数是 common 会话报告并保存的当时结果，不是本记录作者的新测试结果，也不是完整产品验收。

| common 候选交接结果 | 当时证据与限制 |
| --- | --- |
| domain/架构：193 passed | `domain-final.json` exit 0；命令覆盖 domain tests 与 Engineering layers 架构检查。 |
| application/SQLite/canonical：352 passed、1 failed | `direct-final.json` exit 1；包含 application、persistence、canonical encoding tests。失败是下述旧快照构造方式，并非已证明源校验算法错误。 |
| strict prototype：1 failed | `strict-current.stdout` 显示旧源 pins 仍读取已退役 `domain/common/refs.py`，报 `operation_registry_source_unavailable`；不放宽 gate、不恢复旧文件。 |

### 精确失败定位与原断言意图

施工树实际定位：`packages/engineering/tests/persistence/test_material_limits.py:70`，测试函数 `test_actual_captured_manifest_fault_uses_finite_source_error`。

测试先发布真实受控方法，再从原 manifest 中删除首个资源的 `id`，把损坏的 bytes 存入同一 EngineeringLibrary 的真实测试 blob store，在原事务内调用 `verify_snapshot_source`。原断言为 `pytest.raises(MethodFailure)` 且 `failed.value.error.code == 'SNAPSHOT_SOURCE_INVALID'`；注释明确该调用是唯一源 helper 的故障注入，不声称损坏快照可通过外层 codec。

当前调用使用 `replace(snapshot, manifest_ref=captured)`。实际 MethodSnapshot 构造字段只有 `source_bundle`、`program`、`snapshot_digest`；`manifest_ref` 是从 `source_bundle.manifest_ref` 转取的 property。因此现有日志报 `TypeError: MethodSnapshot.__init__() got an unexpected keyword argument 'manifest_ref'`，发生在构造被替换对象时，尚未进入 `verify_snapshot_source`。

统一实施时应保留损坏真实捕获内容、同事务调用、有限错误类型及原 `SNAPSHOT_SOURCE_INVALID` 断言，按新组合结构调整测试输入后复验。建议的输入形态仅用于交接说明，**本轮未修改或执行**：

```python
replace(snapshot,
        source_bundle=replace(snapshot.source_bundle, manifest_ref=captured))
```

不能删除/skip 测试、改断言接受 TypeError、放宽拒绝规则，或用此构造建议宣称原源校验断言已经通过。实施会话须先验证该用例，再复验原 application/SQLite/canonical 范围，并检查与 methods 原 bytes/缓存绑定、历史 wire、事务语义的集成。

### 源闭包与 C09 pins 统一交接

以审阅树 [common pin-handoff.json](../verification/common-responsibility-20261009/pin-handoff.json) 为交接证据；其状态为 `DEFERRED_TO_COORDINATOR`，common 本轮没有写 source pins。该文件分别列出旧 ENGINEERING_FILES 中缺失的路径、剩余 common 模块、迁移后的业务 owner/直接消费者及退役路径，不能只刷新旧名单的 digest。

待 methods/application/common 实际源码稳定后，由统一协调者核对合并后的真实源闭包、版本与摘要，**精确同步两份 C09 registry_ref**，随后重跑严格 prototype 与相关 gate。保留历史持久化 registry/method refs、检查和拒绝语义，不加 fallback、不复活旧模块。本记录不选择新的 registry 版本或凭空给出未核验摘要，也不修改共享 pins。

### 本次补充的授权边界

本轮父会话明确转交“补充交接记录即可，不改测试/源码”，用户仍要求等会统一派。授权仅限此记录与其旧版本保存、冲突检查后的同文档同步；不提前修复该测试，不更新闭包/pins，不开始统一实施，不改 README 主入口、不 git add/commit。

## 与既有依据的关系及本次保存范围

这是一份新目标决定记录，不悄悄重写前轮实现/验证回执，不把历史技术结果提升为审批。前轮 `methods-authorities`、`methods-typed-authority`、`methods-parser-boundary` 记录继续作为当时实现事实和候选来源；它们不是本轮完整目标已经实施的证明。

本文件在两树采用同一相对路径。初版新增前均检查不存在；revision 2 更新前核对两树旧记录摘要，并保存原 revision 1 副本。本次同步仅涉及本文和该历史副本，保留其它既有文档。内容摘要在交付回复提供，摘要证明内容一致，不证明授权或代码验收。README、源码、测试、pins、Git index 与提交均不属于本次写入范围。
