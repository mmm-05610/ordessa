# CLI、Skill与MCP产品契约

以下是目标接口，不是当前命令支持度声明。2026-10-06配置语义更新；实际命令映射须核对已实现的nodes命令与公开schema，不能另建同义agents权威。命令名`ordessa-agent`，默认人类输出；`--json`返回稳定机器包络，stdout不混progress日志，stderr也不得泄露秘密。

## 1. 服务与支持面

```text
ordessa-agent doctor --service <服务别名> --json
ordessa-agent capabilities --service <服务别名> --json
ordessa-agent harnesses list --json
ordessa-agent configuration-kinds list --harness <definitionRef> --json
ordessa-agent resources list --kind <kind> --json
```

连接已有服务，服务别名从受控客户端配置解析；不自动启动服务或切换到其他endpoint。doctor只验证版本/授权/能力/可用性，不调用模型、自动安装或创建节点。token只来自受控秘密设施/环境/受权限保护的配置，不能作CLI明文参数/日志。

支持面至少说明core Agent模块、Profile版本、目录绑定、原生协议、配置kind、动态配置、原生输入查询/幂等、callback持有、detach、停止/恢复。端口方法存在不等于supported。API不兼容明确退出，不fallback到旧Profile/agent服务。

## 2. Profile命令

```text
ordessa-agent profiles list --json
ordessa-agent profiles show <profileRef> --json
ordessa-agent profiles create --file <manifest.json> --request-id <id> --json
ordessa-agent profiles edit <profileId> --file <manifest.json>
  --expected-catalog-revision <rev> --base-manifest <profileRef> --request-id <id> --json
ordessa-agent profiles clone <profileRef> --name <name> --request-id <id> --json
ordessa-agent profiles preview <profileRef> --project <projectRef> --json
ordessa-agent profiles archive <profileId> --expected-catalog-revision <rev> --request-id <id> --json
```

内容版本manifestRevision与目录metadata catalogRevision分开；重命名/归档不重新应用配置。编辑/创建的payload schema由公开配置kind描述，核心不硬编码模型名或工具清单。profile文件不能携带凭据明文或任意执行脚本。

发现provider缺席可保存未解析模板，preview/prepare明确不能用；optional项只允许显式省略并记入报告。名称不能代替固定ProfileRef。preview无作用，不启动MCP/原生实例。

## 3. 项目和节点命令

```text
ordessa-agent projects list --json
ordessa-agent projects bind-directory <projectRef> --purpose <read|write|execute> --json
ordessa-agent nodes prepare --profile-file <profile.json> --directory-binding <bindingRef>
  --request-id <id> --json
ordessa-agent nodes prepare --profile <profileRef> --directory-binding <bindingRef>
  --request-id <id> --json
ordessa-agent nodes list --json
ordessa-agent nodes inspect <nodeRef> --json
ordessa-agent nodes configuration <nodeRef> --json
ordessa-agent nodes apply-profile <nodeRef> --profile-file <profile.json>
  --base-profile <profileRef> --expected-config-revision <rev> --request-id <id> --json
ordessa-agent nodes apply-profile <nodeRef> --profile <profileRef>
  --base-profile <profileRef> --expected-config-revision <rev> --request-id <id> --json
ordessa-agent nodes stop <nodeRef> --request-id <id> --json
ordessa-agent nodes release <nodeRef> --request-id <id> --json
ordessa-agent nodes recover <nodeRef> --request-id <id> --json
```

项目绑定在实际运行宿主重新核实，不相信normalizedPath/UI可访问标记。prepare不发正文；节点身份、provider activation和native runtime epoch分开。客户端执行只是公开服务调用，不能把Skill/MCP/模型Ref自己重新拼给Harness。

管理动作要求对应权限，支持矩阵不足明确拒绝。配置projection来自同一个Harnessowner；Profile来源只是来源。停止不删除历史，recover同一历史不重新应用latest模板。

### 3.1 配置正文与请求信封

Profile正文沿用harnessDefinitionRef、schemaVersion、declarations与可选metadata；declarations沿用declarationId/configurationKind/schemaVersion/action/requirement/payload/resourceRefs。模型、提示词、Skills、MCP及Harness内置sandbox通过动态配置种类表达，核心不硬编码字段全集。不把外置sandbox/worktree编排塞入Profile。

一次准备请求必须且只能有一种配置来源：完整profile JSON或精确ProfileRef；两者同时出现、两者都缺失、同名latest猜测全部拒绝。原核心负责归一化、结构验证、内容摘要及不可变快照，之后复用同一Assembly/Operation链。临时清单不要求用户命名或预存，不自动创建可见预设。返回精确快照引用、operationRef和可用时的nodeRef；accepted不代表启动完成。

requestId、nodeRef、DirectoryBinding、基础版本、应用策略和权限均在配置正文之外的请求信封/受控上下文。生命周期API可以使用JSON编码的通信信封，但不能因此把stop/start/pause等塞进Profile。prepare是否包含start沿既有冻结契约，不能顺手发明新状态机；发送任务、停止、释放、恢复均无需重新提交配置正文。

### 3.2 更新、并发与删除语义

运行中标准配置入口接受整份新清单或其精确引用，调用方不再必须手工构造ConfigurationChangeRequest。系统复用原管理协调器派生配置变更，不在CLI/Server增加另一套品牌差异逻辑；低层typed变更端口保留为内部机制，已发布入口不得无声改义，也不新建legacy兼容层。

更新须绑定基础期望快照与expectedConfigurationRevision，后者来自owner观察，不是Profile/catalog版本。客户端可提供便捷读取但不能静默刷新版本覆盖冲突；两个调用方基于同一版本更新时至多一个通过原scope接纳，另一个conflict。原生缺CAS时保留公开保证范围，绝不伪造强CAS。

以declarationId对应旧/新声明；同ID改kind/schema只在provider明确支持转换时接受，否则发前拒绝。整个清单相同可返回经权威事实核验的无变化结果；不能只因JSON摘要相同就判定actual已一致或跳过未完成项。runtime未知结果不得重发。

新清单遗漏旧声明时不推断删除、默认值或重置：返回需明确处理的声明ID，不产生该次原生作用。调用方必须为这些ID写reset或disabled；owner不支持时typed拒绝。reset/disabled沿既有配置协议，不携带值/资源；未知required拒绝，可选未应用逐项报告。此规则同样适用于用另一份预存清单替换实例配置。

同节点更新不允许更换harnessDefinitionRef或修改受控DirectoryBinding身份；前者明确要求新节点，后者走已有独立环境/项目机制。本版不扩展外部环境编排。修改命名Profile仅生成预设版本，不自动应用实例；更新实例也不自动覆盖来源预设。

### 3.3 应用结果与生命周期授权

新清单通过数据验证不等于实际应用成功。保留submitted/期望快照引用、操作状态与逐项结果；actual只从原owner读，失败/未知时不复制JSON当实际值。默认不承诺跨配置项原子性；要求全原子而owner不能提供时发前拒绝，不能部分执行后声称回滚。

逐项结果沿用applied/deferred/restartRequired/rejected/conflict/unknown。实际执行需原授权/claim，效果确认需原owner证据。缺资源解析/SecretRef授权或provider能力时发前拒绝，不靠临时JSON放宽已有安全门。

配置变化不会隐式启动、暂停、停止、恢复或重启。默认只报告restartRequired；仅独立生命周期调用或既有明确逐次重启授权政策允许处理，授权在操作信封外部且须覆盖具体节点/范围和损失政策，不从JSON推断、不自动追加授权。没有原生暂停能力明确unsupported。允许的重启也必须沿原生命周期与operation链，不能新建“配置专属启动器”。

同requestId同规范化正文、来源绑定和版本前置只查询/复用原操作；同ID异内容冲突。原生接受后回执丢失返回unknown，不自动重试或换ID。临时快照、操作与引用绑定需要崩溃恢复证据；孤立快照不得被误认成已创建或已更新的实例。

## 4. 任务消费命令

```text
ordessa-agent tasks run <nodeRef> --input-file <task.txt> --request-id <id> --wait --json
ordessa-agent tasks inspect <operationRef> --json
ordessa-agent tasks watch <operationRef> --timeout <seconds> --json
ordessa-agent tasks result <operationRef> --json
ordessa-agent operations reconcile <operationRef> --json
```

第一版`run --wait`由协议客户端持有明确授权lease；不默认承诺detach。任务正文从文件读，避免进入进程argv。持久捕获在现有服务的受控input store；CLI本地可保存非秘密operationRef，但不是唯一request ledger。

`run`在消费者适配层实现一次受控任务提交，不意味着core新增sendMessage。原生帧、反向请求、未知字段和错误保持原生；CLI提供安全task summary/result指针，不将任意原生能力都重新实现成CLI命令。未处理审批返回waitingForInteraction及真实关联，不能自动approve。

可靠输入claim与native idempotency/query两种保证分开。unsupported query不禁止第一次发送，但失去接受证据后保留unknown且不能自动重试。用户请求强可靠/自动安全重试而原生能力不足时，事前guaranteeInsufficient。`tasks run`重放同request-id只能返回同attempt/结果，不能再发原生正文；同id不同输入拒绝。

没有可靠detach持有者时CLI被关闭、断网或超时不自动stop/retry；从服务证据核实。watch超时只是观察超时，不代表任务取消/失败。原生取消须真实能力及证据，不能以本地SIGINT代替。

## 5. JSON与退出语义

```json
{
  "apiVersion": "agent-tools/1",
  "requestId": "caller-stable-id",
  "serviceRef": "authorized-service",
  "operationRef": "canonical-operation-ref",
  "status": "pending",
  "data": {"nodeRef": "canonical-node-ref"},
  "evidence": {"level": "intentRecorded"},
  "error": null
}
```

上例是逻辑示意，不能用裸字符串ref代替真实canonical范围。status包括confirmed/pending/refused/partial/unknown；任务completed与配置confirmed、节点ready分开。error含code、安全message、是否retryable及恢复动作；retryable=true仅在能证明重试不会重发未知作用时使用。

| Exit | 含义 |
| --- | --- |
| 0 | 命令成功完成；长操作已受理时JSON明确pending，不伪称任务完成 |
| 2 | 参数/schema无效 |
| 3 | 认证/授权拒绝 |
| 4 | 版本/能力不支持或服务不可用，具名code区分 |
| 5 | 前置revision/target/lease冲突 |
| 6 | partial/unknown需核实，不可自动重试 |
| 7 | 本地观察超时，操作本身可能继续 |

Skill必须同时看exit和status/evidence，不以exit0推断Agent已完成任务。命令断网只表示该次客户端缺证据，不自动换服务、生成新request-id或重跑。

## 6. 后续MCP映射

工具初始面：profiles_list/read/create/edit/preview、nodes_prepare/inspect/apply_profile/stop/release/recover、tasks_run/inspect/result、operations_reconcile。名称最终映射同一公开schema。准备与配置更新可接受Profile正文或精确引用，生命周期和任务工具没有必填Profile正文。与CLI同operations同权限，不独立维护状态或自动常驻原生客户端。

配置/准备/提交/停止是写操作，不因MCP工具可调用就获得权限。Profile编辑和应用工具分开；危险动作的授权不藏在“查询进展”里。MCP schema严格限制payload大小/schema/资源scope，秘密引用不以工具结果展开。

工具包装是有意提供的子集，不声称等于完整Harness原生入口。需要完整能力的消费者获取受授权原生入口；不能为扩展新workflow给core补一条业务翻译。
