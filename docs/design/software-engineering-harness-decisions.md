# 软件工程 Harness：本轮决定记录

记录版本：1；记录日期：2026-10-07。

本文件只记录当前会话中的明确方向及建议边界，不从历史工作树或旧设计推断本轮批准。无法取得精确消息 ID，使用原话与对话位置定位；消息时间未知，不伪造。

## DEC-SEH-001：产品场景收窄

```yaml
id: DEC-SEH-001
revision: 1
kind: explicit_decision
validity: valid
object: Ordessa 产品方向
scope: 软件工程用途，不是立即迁移代码
source:
  locator: 当前会话，用户在“现在整套流程是怎么样”开头的消息
  time: unknown
  quote: "现在我的想法是做一个适用于软件工程的基于软件工程的harness"
  locator_limitations: 无精确消息ID
supersedes: []
```

上下文：原方向试图做完全开放、可插拔的系统；用户本轮提出明确的软件工程产品用途。

决定：把软件工程作为当前产品方向。没有因此授权删除现有通用能力、清理工作树或全面重构。

## DEC-SEH-002：使用外部 Harness 与 agent-node

```yaml
id: DEC-SEH-002
revision: 1
kind: explicit_decision
validity: valid
object: 实际 Agent 工作的提供方式
scope: 接入与使用边界
source:
  locator: 与DEC-SEH-001相同消息
  time: unknown
  quote: "可接入不同品牌harness，不自己实现loop等底层机制，依赖现在正在实现的agent-node"
  locator_limitations: 无精确消息ID
supersedes: []
```

决定：依赖 agent-node 使用不同品牌 Harness，不重做其底层循环。未确认所有品牌等价、所有原生功能都已接通或 agent-node 已完成。

## DEC-SEH-003：外置工作流与文档标准

```yaml
id: DEC-SEH-003
revision: 1
kind: explicit_decision
validity: valid
object: 工程方法与系统机制的边界
scope: 工作流和标准的加载与演化方向
source:
  locator: 与DEC-SEH-001相同消息
  time: unknown
  quote: "工作流和文档标准都不可以硬编码，内部只做这些能力的加载器，然后外置这些，让他们成为可以自进化的东西"
  locator_limitations: 无精确消息ID
supersedes: []
```

决定：具体工作流和标准外置、可加载，并可持续优化。

未决邻接问题：加载格式、可信扩展、运行机制、方法更新权限与版本切换未定。运行器、权限与版本机制由谁实现，以及怎样保证方法可替换，是设计问题；本句不授权外置任意代码拥有任意执行权。

## DEC-SEH-004：Decision 的独立复用方向

```yaml
id: DEC-SEH-004
revision: 1
kind: interpretation
validity: needs_clarification
object: Decision 与 Pacthold 的关系
scope: 可复用判定能力的目标，尚非物理迁移批准
source:
  locator: 与DEC-SEH-001相同消息
  time: unknown
  quote: "decision模块内置到pacthold了吗，现在又可以准备拿出来了，因为jev有了可以复用的点"
  locator_limitations: 无精确消息ID；该句是方向讨论，不是实施指令
supersedes: []
```

解释：考虑独立 Decision 以复用 Jev 判定。没有确认新目录、模块整体迁出、具体接口或迁移权限。需先核对真实职责，不把批准和执行权随判定能力一起外移。

## DEC-SEH-005：编写本轮方向文档

```yaml
id: DEC-SEH-005
revision: 1
kind: explicit_delegation
validity: valid
object: 本轮想法的详细记录
scope: 本地文档编写，不含业务实施
source:
  locator: 当前会话，本轮文档请求
  time: unknown
  quote: "把我这套想法定成详细的文档"
  locator_limitations: 无精确消息ID
supersedes: []
```

授权：整理方向、展开解释和记录建议。保存到 docs/design；正文区分明确方向、设计建议和未决内容。不修改正式 DID，不借文档请求执行重构。

## Agent 设计建议的状态

主文档第6节的责任划分、第7节的方法包、第8节的具体判定边界、第9节的演化机制及第12节的推进建议，是围绕用户方向的设计展开。它们目前不是用户逐项明确确认的契约。

此前讨论提出的用户低认知负荷、长期 DID 到本次实施包的链路，是本轮上下文；本文件没有为其伪造重新批准记录。若用本文生成正式 DID 变更，需引用对应原始依据、选定标准及有效授权，不把本文保存事实当独立批准。
