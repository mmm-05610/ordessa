# ACP 连接器目标测试评审（TEST_REVIEW_READY）

状态：**TEST_REVIEW_READY** —— 目标测试已写完并实跑；本阶段**未修改任何产品实现**，等待审核批准后才进入实现。

目标（objective）：前端通过后端编排建立 ACP 通道，并复用现有聊天界面。本评审文档说明：测试对应哪些需求、协议事实来源、实跑命令与退出码、现状通过 vs 目标失败、可复用件与最小改动点、依赖清单与未决接缝。

## 1. 职责边界遵守声明

- 仅新增了 `tests/acp-connector/**` 与本文件；未修改既有组件、测试、配置、依赖锁或任何其他文件。
- 工作树中原有的 16 个 modified 文件为进入本会话前的既有改动，本会话未触碰，未 stage/commit/reset/stash/clean/push。
- 未启停既有服务，未读取凭据，未调用模型，未向任何真实后端发请求。全部网络对端为测试内受控 ACP peer。
- `@agentclientprotocol/sdk@1.5.0` 只 pin 在 `tests/acp-connector/package.json`（含该目录自己的 `package-lock.json` 与 `node_modules/`，gitignored），**根依赖锁未被改动**（见 D1）。

## 2. 实跑命令与结果

从仓库根目录执行：

```bash
node_modules/.bin/vitest run --config tests/acp-connector/vitest.config.ts
```

结果（vitest 4.1.10，串行，`fileParallelism:false, maxWorkers:1`）：

- **退出码 1**（设计内的目标失败状态；不是命令错误）
- `Test Files  6 failed | 2 passed (8)`
- `Tests  33 failed | 14 passed (47)`
- 33 个失败全部且仅带有 `TARGET_MISSING:` 前缀，指向同一缺失模块 `plugins/connectors/acp/src/entry.ts`；无一例是断言逻辑失败、skip 或 xfail。

| 文件 | 用例 | 今日状态 |
| --- | --- | --- |
| `fixtures/peer-self.test.ts` | 10 | **全部通过**（fixture 自证，含通道关闭/中止传播） |
| `ui/snapshot-shape.test.tsx` | 4 | **全部通过**（UI 槽位验证） |
| `protocol/chat-loop.test.ts` | R1–R7 (7) | TARGET_MISSING |
| `protocol/streaming-tools.test.ts` | R8–R13 (6) | TARGET_MISSING |
| `protocol/interactions.test.ts` | R14–R18 (5) | TARGET_MISSING |
| `protocol/history-capability.test.ts` | R19–R22, R26 (5) | TARGET_MISSING |
| `protocol/switch-isolation.test.ts` | R23–R25, R27 (4) | TARGET_MISSING |
| `ui/acp-conversation.test.tsx` | U1–U6 (6) | TARGET_MISSING |

## 3. 两态划分（现状通过 / 目标失败）

### 3.1 现状通过的 14 个（证明测试基建与 UI 复用前提，本身不是 ACP E2E）

- **fixture 自证（10）**：在把任何断言交给目标实现之前，先验证受控 peer 本身正确——请求/响应往返、参数原样携带、notification 流 + stopReason 传递、`RequestError` → client 端 rejection 且通道存活、回合内反向请求（`session/request_permission`）由 client 脚本作答、`session/cancel` notification → `stopReason: 'cancelled'`、未宣告 capability 的可选方法得到 method-not-found（宣告后 `session/load` 正常回放）、链路 drop 时 in-flight prompt 双方 promise 都落定，以及**通道关闭传播**：client 侧 `stream.writable.close()`/`.abort()` 会作为 EOF/error 传到对端（否则正确的 `dispose()` 释放会永久卡在 R24 这类断言上）。
- **UI 槽位验证（4，`snapshot-shape.test.tsx`）**：把与 ACP 语义同形的 `AgentSnapshot`（标题、reasoning+tools 消息、interaction 卡、`unknown` 运行态）喂给**真实** facade/`Conversation`/`SessionBrowser` 组件，证明复用槽位存在且语义对号：`.agent-tool`、`.agent-reasoning`（"Thinking"）、`.agent-interaction` 按钮、`.agent-run-state[data-status=unknown]` 不与 cancelled 混淆、原生标题进入列表。文件头部明确声明：**这不是 ACP E2E**，只是界面消费能力证明。

### 3.2 目标失败的 33 个（实现完成后应转绿）

全部通过 `loadAcpTarget()` 动态 import `plugins/connectors/acp/src/entry.ts`；模块不存在即抛 `TARGET_MISSING`，错误信息内含"这是目标测试的预期红色状态，不得 skip/xfail/用 fixture-only 通过冒充"。接缝签名见 §6（**待评审，不是既定公共协议**）。

## 4. 需求 → 测试映射

需求编号引用 objective 原文条目。

| Objective 需求 | 协议层 | UI 消费层 |
| --- | --- | --- |
| 不建立无项目绑定通道；选定项目后取该通道，其上恰好一次 initialize；能力只从 initialize 应答读取 | R1 | U1（未绑项目的草稿不发任何 ACP 帧） |
| 历史：**list 与 load 是两种能力**——list 缺失如实呈现、不自建历史后端；未出现在列表不构成"不能恢复"，恢复被拒只能来自 `session/load` 的 wire 应答；load 可用而 list 不可用时恢复仍合法 | R2, R19, R22, R26 | — |
| 新会话是本地草稿（开项目不建会话）；首次发送才建真实会话（`session/new{cwd}` 用后端权威绑定路径）；列表里 native cwd 命中权威绑定的会话保留项目归属（workspaceId），未知 cwd 不随意绑定 | R3, R7 | U2 |
| 项目必选：编排未提供的项目不得取通道、不得触 wire（反例） | R4 | — |
| 同一 native session 连续两轮 | R5 | — |
| native 标题更新（`session_info_update`）替换标题、不虚构 | R6 | — |
| 文本/思考分流式呈现；一个 toolCallId 一张卡（含反例：不同 id 两张卡） | R8, R9, R10, R11 | U3 |
| 断线/迟到事件不得跨会话串扰 | R12 | — |
| 确认的取消 vs 未知：unknown 不是 cancelled；stop 用同步闸门分验"请求已发出/确认已收到"，只由 `stopReason:'cancelled'` 确认 | R17 | U5 |
| 线程内权限/输入交互：native option id 直通（optionId 取与 kind 不同的值以抓错误映射）；二次作答拒绝且不吞掉下一条 pending 请求；cancel 语义 | R14, R15, R16, R18 | U4 |
| 三态生命周期分离：transport 断开≠取消≠后端 release；切换选择≠dispose（切换只验展示与请求归属隔离，不隐式取消/迁移/重发、不 release）；显式 dispose 单独测（句柄 release 真实发生、在途落定 unknown）；**同一 AgentClient 内**多项目通道即使原生 session id 相同，消息/运行/审批/cancel 也按通道归属隔离、切换往返状态不丢 | R13, R23, R25（隔离/不 release）；R24（显式 release）；R27（单客户端同 id 跨通道隔离） | U5, U6 |
| 复用现有聊天界面（不另做 envelope） | — | U1–U6 全部挂在真实 `createAgentConnections`+`createAgentSessions`+`Conversation` 之后；`snapshot-shape` 4 例 |

明确不测（objective 排除项）：Profile/Provider、模型与思考档切换、布局改版、Git diff、终端、浏览器功能。

## 5. 协议事实来源（全部来自锁定 SDK，不凭记忆）

- `tests/acp-connector/package-lock.json` pin `@agentclientprotocol/sdk@1.5.0`；测试中所有方法名、字段、枚举均取自该包随附 schema/类型：
  - `PROTOCOL_VERSION = 1`；agent 侧 `initialize, session/new, session/load, session/list, session/prompt` + `session/cancel`(notification)；client 侧 `session/update`(notification), `session/request_permission`(request), `elicitation/create`。
  - `SessionUpdate` 判别式：`user_message_chunk / agent_message_chunk / agent_thought_chunk / tool_call / tool_call_update / session_info_update / plan` 等。
  - `AgentCapabilities{loadSession, sessionCapabilities.list}`；`StopReason = end_turn|max_tokens|max_turn_requests|refusal|cancelled`；`ToolCallStatus = pending|in_progress|completed|failed`；`RequestError(code, message, data)`。
  - 连接对象（`AgentSideConnection`/`ClientSideConnection`）**没有** `.close()`；流由 `ndJsonStream(output, input)` 构造，SDK 连接的结束只由底层字节流的 EOF/error 触发（读循环 break → `close()`）。因此 fixture 的 `channel()` 让 `writable.close()/abort()` 把 EOF/error 传播到对端 readable（真管道正是这个语义），`shutdown()`/`drop()` 则直接模拟编排断链；两条路径都有自测。
- 现有前端契约来源（只读）：`contracts/agent/src/agent.ts`（`AgentClient/AgentSnapshot/AgentConnector/AgentSessions`）（历史路径：C-T018 后该领域契约位于 `plugins/agent/contracts/src/agent.ts`，carrier id `ordessa.agent-contracts` 不变）、`plugins/agent/sessions/src/model.ts`（草稿 + 每 Server 项目门 + localStorage 记忆，FC-0021/0030/0031 语义）、`plugins/connectors/ordessa/src/client.ts`（wire/1 映射参考：按 toolCallId 合并工具卡、断线置 unknown、粘性终态）。
- UI 组件来源（只读、真实挂载）：`plugins/agent/conversation` 视图、`SessionBrowser`、`.agent-interaction` 卡片。

## 6. 提议的接缝（待评审；不是新增公共协议）

`tests/acp-connector/fixtures/target-seam.ts` 定义了测试侧注入面，仅为本套测试可执行而存在。通道模型（已按评审统一）：选择 Server/Harness 后只读项目列表，**不建立无项目绑定的通道**；首次发送前才为选定项目取得通道并在其上 `initialize`，随后 `session/new`/`session/prompt`；草稿不建原生会话，后续对话复用该会话及其通道。

```ts
interface AcpChannelHandle {
  readonly connectionId: string                   // 编排签发的通道实例身份
  readonly binding: AgentWorkspaceInfo            // 权威绑定：binding.normalizedPath 即 session/new 的 cwd
  readonly stream: acp.Stream
  release(): Promise<void>                        // 显式后端释放；stream.close ≠ release
}
interface AcpChannelSpec {
  serverInstanceId: string                        // 实例身份，沿用现有 connector id 规则
  harness: { id: string; title: string }
  listProjects(): Promise<readonly AgentWorkspaceInfo[]>  // 选中即可读，无需通道
  openProject(id: string): Promise<AgentWorkspaceInfo>    // 权威绑定：其 normalizedPath 即 session/new 的 cwd
  acquireChannel(projectId: string): Promise<AcpChannelHandle>  // 显式携带 projectId 的通道获取；名字待与后端对齐
}
// 目标模块：plugins/connectors/acp/src/entry.ts
export function createConnector(spec: AcpChannelSpec): AgentConnector
```

句柄把三种生命周期事件分开：**transport 断开**（链路失效，前端只落定 unknown，不得伪称已 release——R13）、**切换视图/选择**（纯展示移动，不 release、不取消、不迁移——R23/R25/U6）、**显式 release**（唯一让后端通道下场的动作，R24 断言其真实发生）。夹具为**每个项目建独立 peer/通道**；R27 在**同一 Server、同一 Harness、同一个 AgentClient** 内同时持有两条项目通道，两端原生 session id 相同，验证消息/运行/审批/cancel 按通道归属隔离并切回验证状态仍在（R23 的双客户端用例只作连接隔离）。

`acquireChannel` 的显式 projectId 与 `openProject` 返回的权威 `normalizedPath`（cwd 不自行猜）都是本轮评审确定的测试侧约束。objective 声明编排签名与网络路径**未冻结**，`acquireChannel` 的确切函数名/签名待与后端对齐；实现阶段应以冻结后的编排接口替换其供给方，测试断言（wire 语义、UI 消费）预期不变。它不是新增公共协议。

## 7. 复用清单与最小改动点

| 复用件（不重写） | 说明 | 最小改动点 |
| --- | --- | --- |
| `createAgentConnections` 注册表 | ACP connector 以标准 `AgentConnector` 注册即进入现有选择/切换流 | 无（新增 provider 即可） |
| `createAgentSessions` 门面（草稿/项目门/记忆） | U1–U6 原样挂接；draft、`no-project`/`project-invalid` 门语义复用 | 无；若项目门需识别 ACP `cwd` 语义，仅在 connector 侧做映射 |
| `Conversation`/`SessionBrowser`/interaction 卡 | 消息、reasoning、tool 卡、线程内交互、run-state 徽章均有槽位（§3.1 已证） | 无 |
| wire/1 `OrdessaClient` 的投影模式 | toolCallId 合并、unknown-on-disconnect、粘性终态作为实现参照 | 无（仅参考） |
| 真正的新增 | 仅此一项：`plugins/connectors/acp`（ACP client → `AgentSnapshot` 投影 + `AcpChannelSpec` 消费） | — |

## 8. 依赖清单（实现前需用户/产品裁定）

- **D1** `@agentclientprotocol/sdk` 需进根依赖锁（当前只存在于 `tests/acp-connector/`，符合"不动根锁"约束）。
- **D2** 编排接口签名与网络路径未冻结；§6 接缝为候选，冻结后需回填 `acquireChannel`/`listProjects` 的真实提供方（`acquireChannel` 的确切函数名待与后端对齐，测试断言按其"显式携带 projectId"的语义执行）。
- **D3** ACP `session/prompt` 无幂等键：首发的 unknown 结果只能靠上层现有 requestId 语义（`AgentSessions` FC-0031 已持有），连接器不得自动重发（R7 已测）；需确认该策略即产品裁定。
- **D4** `AgentCapabilities` 枚举（reasoning/tools/interactions/stop/history）与 ACP 核心能力（`loadSession`/`sessionCapabilities.list`，其余无宣告位）之间的映射需要产品裁定；当前测试按"能力只从 initialize 应答读出，缺失如实 unsupported"（R1/R2）执行。
- **D5** runId 语义：建议以 ACP 的 prompt 回合（每 session 单 in-flight）映射现有 `runs[runId]`；`stop()` → `session/cancel` notification，`unknown` 直到 `stopReason:'cancelled'`（R17）。需确认。
- **D6** 权限 option id 直通 native（R14–R16）意味着现有 allow/deny 二元交互卡要能携带任意 native id；UI 是否需要泛化待实现期验证（当前 snapshot-shape 证明槽位可承载）。
- **D7** elicitation（输入型交互）在本套中仅覆盖到"未宣告即不虚构"（R2 族）；in-thread 输入卡的完整映射视编排冻结情况二期补测。

## 9. 未决接缝（已报告，未擅自定夺）

- **Q-1 运行中切换策略**（已裁定，测试已按裁定改写）：主会话裁定"切换 UI 选择"**不等于** dispose 旧连接——切换只验证展示与请求归属隔离，不隐式取消、不迁移、不重发；显式 dispose 的释放行为单独测试。据此：R23/R25/U6 只断言隔离（不再要求旧通道关闭或旧运行落定为 unknown；未答的 permission 在切回后仍归原连接所有；并断言切换记录 0 次句柄 release）；R24 单独测显式 `dispose()`：句柄 `release()` 真实发生、其通道终结、在途工作落定为 unknown、之后拒绝新请求。原先"切换即关闭/落定 unknown"的保守假设断言已全部删除。
- **Q-2 项目↔cwd 绑定**（已裁定方向）：cwd 采用后端返回的权威项目绑定（`openProject` 的 `normalizedPath`），连接器不自行猜路径——R3/R4 及 UI U2 已按此断言。剩下的仅是 `acquireChannel` 的确切函数名/签名待与后端对齐（见 D2）。
- **Q-3 历史分页/游标**：`session/list` 的分页参数按 SDK schema 测试了"有则如实展示"（R20），分页策略本身未定。

## 9.1 评审整改记录（本轮只改测试与报告，未动实现）

- **评审项 #3（R18 必然等待）**：R18 改为——回答第一次审批；重复回答第一次被拒后，确认第二次仍待处理，再显式回答第二次；两条审批的 optionId 取与 kind 不同的值（`proceed_first`/`proceed_second` vs `allow_once`），并以跨条作答被拒抓住 id/kind 混映射。正确实现不再被测试卡死。
- **评审项 #4a（通道关闭传播缺失）**：夹具底层 `WritableStream` 补齐 `close`/`abort` 传播（write→enqueue、close→EOF、abort→error），并在 `ndJsonStream` 外包一层持有持久 writer 的桥接流，把外层 close/abort 转发到底层字节管道（SDK 的 `ndJsonStream` 自身不转发 close）。新增 2 条 fixture 自测（peer-self 共 10 条全绿），R24 的 `peer.closed` 前提成立。
- **评审项 #4b（R17 竞态）**：取消测试改用显式同步闸门（`deferred()`）——(A) 观测到 `session/cancel` 已发出且状态为 `stop-requested`（此时对端 held 住响应）；(B) 释放闸门后才收到 `stopReason:'cancelled'` 并断言终态。"请求已发出"与"确认已收到"分开验证，不再竞态。
- **接缝统一（通道模型）**：`openStream()` 改为显式携带 projectId 的 `acquireChannel(projectId)`；选择 Server/Harness 后只读项目列表、不建无项目通道；首发送前取选定项目通道→恰好一次 initialize→`session/new`→`session/prompt`；草稿不建原生会话；后续对话复用该会话及通道。相应改写了 R1–R4、R19–R22（先 `openWorkspace` 绑定项目再读能力/历史）、U1（未绑项目时 0 initialize 帧）、U6/R23/R25（切换=视图移动，非 dispose）。

### 第二轮评审整改（本轮）

- **受管理句柄**：`acquireChannel(projectId)` 不再裸返回 stream，改为 `AcpChannelHandle{connectionId, binding, stream, release()}`（§6）。三态生命周期就此可分测：**transport 断开**（R13 增断言：断开后 `released` 仍为空——前端不得把断链伪称成后端释放）、**切换视图**（R23/R25/U6 增断言：切换记录 0 次 release）、**显式 dispose**（R24 改为断言句柄 `release()` 真实发生且恰好一次，再验链路终结与在途落定 unknown；不再靠 `stream.close` 猜测）。
- **R22 重写 + R26 新增**：原 R22 把"未出现在列表"当成"不能恢复"，会逼前端自行否决原生 load 能力。现 R22 改为对端宣告 loadSession 且 `session/load` 真实返回 `RequestError`——断言连接器确实发过帧（不许预防性拒绝）、失败如实上抛（含 wire 原因为主文案）、不伪造选中/内容。新增 R26 覆盖合法的另一侧：load 可用而 list 不可用时，凭已知原生 id 直接 `session/load` 恢复成功。
- **R20 归属保留**：列表条目的 native cwd 命中当前权威项目绑定（`/repo/app` ↔ `ws_app`）时 `workspaceId` 必须给出关联（不再钉 `undefined`）；同用例加入未知 cwd（`/mnt/elsewhere`）条目，断言**不**随意绑定——关联两头都不许瞎猜。
- **每项目独立通道 + R27**：夹具为每个 offered project 建独立 `HarnessPeer`/句柄（`connectTargetFor`）；新增 R27：两个项目通道各自铸造**相同**原生 session id（`acp-session-1`），消息投影与 cancel 路由必须按通道归属隔离，互不串扰。
- **R27 重写（第三轮评审）**：原 R27 误用 `twoHarnesses()`（两个 Server、两个 AgentClient），只测到连接隔离，测不到真正的项目串扰问题。现改为：**同一 Server、同一 Harness、同一个 AgentClient** 内取得 ws_a/ws_b 两条项目通道，两端各自铸造相同的原生 session id（夹具已证 `wireA === wireB`），切换项目后逐项验证**消息投影、运行状态、审批、cancel 路由**全部按通道归属隔离（A 的 held 审批已答/在跑、B 已 completed，stop 只落在 A 通道），再切回 A 验证原状态仍在；整个多通道回合 0 次 release。R23 的双客户端用例保留作连接隔离，不替代本项。
- **R27 异步同步点（评审通过后补齐，场景与范围不再改动）**：`createAndSend` 的契约语义是"会话创建且首发受理"，不要求整轮结束（A 的回合被自己的审批 held，等整轮会死锁）。其返回后的一切读取改为**有界 `waitFor` 等事实出现**（无固定 sleep）：两条 prompt 帧先等到线再比对 native id；A/B 流式文本先各自投影落地再断言互不渗入；带外 update 等前端投影；B 的 run 先等到终态再要求 `completed`；A 的 running 态、审批出现、`respond` 后对端收到答案（`answerA`）、审批在前端投影为 `resolved` 同样逐一等待；cancel 只落 A 通道的反证挪到 A 落定之后。整个场景体包在 `try/finally`：断言无论在哪一步失败，`finally` 都释放 held 闸门并关闭两个 peer，不留挂起回合。
- 本轮仍只改测试与报告：`tests/acp-connector/**` 与本文档；产品实现、根配置与依赖锁零改动。

## 10. 性质声明

本套测试为**受控对端的协议/消费层仿真测试**（controllable ACP peer + 真实前端 seam），不是对真实 Harness/真实编排后端的 E2E 验收。实现完成后，R1–R27、U1–U6 应无需改动断言即转绿；届时的真实后端 E2E 需另行立项，不在本阶段范围。

---

**结论：TEST_REVIEW_READY。** 等待审核；未经主会话明确批准，不修改产品实现。
