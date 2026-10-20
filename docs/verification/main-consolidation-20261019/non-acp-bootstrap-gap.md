# Non-ACP bootstrap 缺口与封闭原 owner 扩展草案

日期：2026-10-19。状态：**只读调查已完成；扩展待裁定；未批准、未实现、未验证 bootstrap 修复。**
本轮仅新增本文。没有修改 DESIGN、SDK、插件或测试，没有运行品牌/模型测试。

当前模块阶段：SDK 的 Codex/Pi preparation 已有实际代码；正式 Agent start 的非 ACP 协议、来源发布和后续 interaction 未接通。进度受公开契约边界阻塞，不能把纯 LaunchPlan 或旧 L1 测试当成替换迁移完成。

## 1. 范围与证据冻结

当前树 T：`/home/maoqh/projects/ordessa/worktree/main-consolidation-20261019`。
历史保全 R：`/home/maoqh/projects/ordessa-preservation/20261019-main-consolidation-053043/nightly-source-restore-probe`。
设计正文 D：`/home/maoqh/projects/ordessa/worktree/packages-convergence-20261019/docs/implementation/packages-convergence-20261019/DESIGN.md`（只读）。
下面当前路径相对于 T，R 路径相对于 R。行号是本次读取时定位；附录 SHA256 固定实际读取的文件。R 中源码仅作恢复依据，不是可导入依赖。

## 2. 当前缺口的实际执行点

| 当前文件与行号 | 实际限制及影响 |
| --- | --- |
| `plugins/harness/codex/src/ordessa_harness_codex/provider.py:51` | `open_session` 校验 PrepareContext 后无条件抛 `NATIVE_PROTOCOL_BOOTSTRAP_UNAVAILABLE`；descriptor 仍是 `codex-app-server/1`。 |
| `plugins/harness/pi/src/ordessa_harness_pi/provider.py:59` | 同样无条件拒绝；descriptor 仍是 `pi-rpc/1`，没有把它包装成 ACP。 |
| `packages/execution/agents/src/ordessa_execution_agents/sdk/harness.py:92` | ManagedProcess 只给 `open_acp_session(SessionBootstrap)`。插件拿不到 invocation、Endpoint writer、fd 或 Records。 |
| `packages/execution/agents/src/ordessa_execution_agents/instances/lifecycle.py:71` | `_ProcessView` 也只实现该入口。 |
| 同文件 `:84`、`:143` | `_phase` 固定 JSON-RPC/ACP observer；`open` 固定 initialize(protocolVersion=1) 与 session/new(cwd,mcpServers)。 |
| 同文件 `:173`、`:210` | launch 前/后分别拒绝非 ACP；stream target 固定 `protocolId: acp`。只删前一个 guard 不会接通。 |
| `packages/execution/agents/src/ordessa_execution_agents/instances/contracts.py:11`、`:18` | child derivation ordinal 只有 initialize=0/session-new=1；LifecycleWriteBinding 的 phase 也是同一闭集。 |
| `packages/execution/agents/src/ordessa_execution_agents/sdk/manager.py:562`、`:592` | 发布只接受 ACP/session 或 None/None；读取正式来源时要求同一完成的 session/new phase 中 result.sessionId。 |
| `packages/execution/agents/src/ordessa_execution_agents/sdk/interactions.py:529` | `_instance` 只承认 ACP/session 或 None/None；即使强行写入 native binding，消费仍失败。 |
| `packages/execution/agents/src/ordessa_execution_agents/sdk/acp.py:26`、`:125` | 当前 observer 要求 `jsonrpc:2.0`，initialize result.protocolVersion=1；不能直接消费两个原生协议。 |

因此插件内改一处 `open_session` 不足以修复。伪造 ACP、仅放开 protocol enum、绕过来源校验或直接运行旧 client 都不满足原保障。

## 3. §13/§15 约束及已有 native API 的适用边界

D `:1208` 的 §13 规定原 Records 的 start/bootstrap phase、真实 `send_guarded`、同 task/thread 的物理 cut、possibly-written 先于 bytes、等待不持 DB/authority 锁、UNKNOWN 不重发和同 endpoint/protocol 单 reader。D `:1236` 明确：`Plugins receive only ManagedProcess.open_acp_session(SessionBootstrap)`；同段还限定首版 ACP integer1、fresh only，缺失 resume/auth/reverse/multi-send 不能隐式回退。

D `:1353` 的 §15 批准的是已有 session 上的 recorded configuration operation。D `:1396` 精确闭集为：

- `apply` → `_ordessa/session/configuration/apply`；
- `query` → `_ordessa/session/configuration/operation`。

它要求固定原 session、generation、input/config digest 和独立 after-read；非 ACP/provider 不支持时拒绝，不能变成任意 RPC transport。

实现与此相符：`sdk/native_contracts.py:8` 固定两种 METHODS，`:96` 拒绝 protocol_id != acp；`sdk/native_operations.py:12` 先读取已发布 `_instance`，再构造 `protocolId:acp`。`native_query` 读取已有操作记录，不会打开 session。该路径既没有启动前 instance，又没有 bootstrap methods，不能重命名 purpose/method 来复用。

结论：下述草案是对 §13 的**待批准扩展**，不是 §15 已授权能力的机械重接。不得先写代码再将其解释为既有授权。

## 4. Codex：已找到的原契约与原断言

R `plugins/harness/codex/src/ordessa_harness_codex/client.py:1` 记录已固定的 native wire：JSONL、JSON-RPC 风格但可省略 `jsonrpc` 字段；没有 ACP protocolVersion/version negotiation。
R 同文件 `:139` 的 initialize 发 clientInfo/capabilities（experimentalApi=false），收到 response 后发无 id 的 `initialized` notification；notification 没有待等的响应。

R `plugins/harness/codex/src/ordessa_harness_codex/provider.py:325` 的原 start：

1. 原 owner 先持久化 opening/reservation，再打开显式 bound channel。
2. 每个实际动作前重新核对原 source/current start。
3. initialize（包含 initialized notification）。
4. `thread/start(cwd=<原隔离绝对 cwd>)`，读取 `result.thread.id`。
5. `thread/read(threadId=<同 id>, includeTurns=false)`，独立 readback 必须同 id。
6. 原 projection.publish_channel 后，原 Records 才 confirmed；异常保留 unknown，不关闭/杀死/重发来假装确定。

原测试来源（当前 T 文件与对应 R 文件逐字相等，见附录）：

- `plugins/harness/codex/tests/test_provider.py:111` 要求 calls 恰为 initialize/thread-start/thread-read，native sessionId=thread-1，且无 turn/start。
- 同文件 `:119` 的 receipt loss 场景保留 unknown，新 start 不能再次 dispatch。
- `plugins/harness/codex/tests/test_client.py:89` 校验 initialize/thread identity；`:145` overload 不自动 retry；`:164` timeout unknown 且不重发。

这些是旧 API 的原 L1 要求；本次未执行，也不能因其存在宣称当前 SDK 已通过。真实 Codex 二进制/模型兼容性另属 L2。

## 5. Pi：已证实事实与尚未证实的拼接

R `plugins/harness/pi/src/ordessa_harness_pi/client.py:1` 明确：Pi 是 JSONL，**不是 JSON-RPC/ACP**。请求 `{id,type,...args}` 参数在顶层；response 是 `{id,type:response,command,success,data/error}`，未知事件原样保留。无 initialize/version negotiation。

- R 同文件 `:213`：客户端 initialize 实际仅做 `get_state` round trip，原样返回 data。
- R 同文件 `:222`：`new_session` 返回 `{status:prepared,command:new_session,data:<原data>}`；不会自行 confirmed、制造 sessionId 或断言 resume/replay。
- T/R `plugins/harness/pi/tests/test_client_process.py:206`：握手就是 get_state；`:275` 明确断言 status=prepared、command=new_session、peer-native data.sessionId。
- 当前 `plugins/harness/pi/src/ordessa_harness_pi/rpc_frames.py:46` 的纯 encoder 及 `tests/test_rpc_frames.py` 保留原顶层参数、精确 id/command/boolean success、未知事件和失败信息；不发 I/O。
- vendor `plugins/harness/pi/vendor/acp-adapter/internal/pi/client.go:788` 的 getState 和 `:820` 的 newSession：后者检查 native cancelled。vendor fixture `testdata/fake_pi_rpc/main.go:249` 返回 cancelled=false；`:303` 的独立 get_state 提供 sessionId/sessionFile。它们提供原生字段/受控 peer 依据，不授权选择 ACP wrapper。

**没有找到可核对的 R PiRuntimeProvider/lifecycle 实现**：R 的 `provider.py`、`lifecycle.py` 不存在；`f6d7262a` 的 provider 已是当前 SDK unavailable 形式。因此 `get_state → new_session → get_state` 仅是下文待评审的原生身份 readback 候选，不能写成已保全的 Pi provider 固定 sequence。旧 client 的 prepared 断言必须继续保留。

## 6. 待裁定草案：原 Agent owner 内的封闭协议分派

目标是在同一 start、Records、Endpoint、writer、外部 authority 和 source binding 中恢复真实 native bootstrap；不恢复 Unit online/runtime、不导入退役 client、不新增默认 provider/authority/路径探测、不开放任意 RPC。

### 6.1 插件最小能力与选择边界

建议保持 ManagedProcess 权限原样：不增加 raw send、receive、fd、invocation、writer callback 或任意 `open_native_session(methods)`。正式 start 的原 owner 按**已 allowlist 且已 pin 的 descriptor.protocol_id**选择封闭实现，协议固定为 acp、codex-app-server/1、pi-rpc/1；其余在 launch 前拒绝。

这需要明确修订“所有 provider.open_session 都由相同 ManagedProcess closure 产生结果”的现行生命周期约定：候选 native 分支由 Agent 原 owner 直接执行其封闭 bootstrap，而非调用当前无条件拒绝的插件 open_session。插件继续只产出经过实际 Profile 校验的不可变 LaunchPlan 与真实 protocol descriptor；不得通过返回一个自造 AgentSession 绕过原 observation identity。

此选择是草案，尚未获批。它减少插件权限扩张，但会把两个公开协议的封闭 bootstrap 解释放在 Agent 原 owner 内；需与职责边界共同评审。不得以延迟导入具体插件绕开边界。若否决此 owner 方案，应先定新的有限、纯数据协议合同，再实现；不能偷偷给插件 raw capability。

### 6.2 必须显式版本化的内容

建议引入 `agent-lifecycle-write-binding/2` 与 `agent-lifecycle-frame-request/2`，新增 protocolId、闭合 phase 和明确 ordinal，分别固定每个 native outbound frame。ACP /1 bytes、原 child 派生键及历史记录不改、不重封；新 native phases 只走 /2，不能往 /1 enum 偷塞语义。

新的原 instance/bootstrap provenance 需要显式 /2 来源版本，绑定 protocol、实际 bootstrap phase observations、terminal readback identity 和原 start/profile/plan/directory/endpoint。旧 ACP 来源读取保留原规则；native rows 不按 ACP session-new 校验。AgentSession / AgentStartRequest 若字段不变，不仅为对称强造新 DTO，但公开 lifecycle 能力/合同必须显式标明新版本和支持协议；SDK 发布是否升 agent-harness-sdk/2 留待裁定，不能声称 /1 已含该保证。

数据库 operation/table/历史namespace 不重命名；如存储闭形需要迁移，必须显式 schema/migration 与历史读回测试，不能通过改 payload 后重新算 digest 迁旧事实。

### 6.3 固定阶段和原生结果

| 协议 | 候选固定阶段（每个 outbound frame 独立 durable/guard） | 可发布的身份依据 |
| --- | --- | --- |
| Codex | initialize request → initialized notification → thread/start request → thread/read request | thread/start 原 receipt 的 thread.id 与独立 thread/read 同 id；启动不得发送 turn/start。initialize 结果不要求 ACP protocolVersion。 |
| Pi | get_state request → new_session request → get_state readback（**候选，非原 provider sequence**） | native new_session success 且未 cancelled，加独立 get_state 的有效 sessionId；若 creation data 同时给 id，必须一致。不能凭一个 prepared receipt 发布；无足够身份/字段时保留 unresolved，不制造 id。 |

Pi 是否接受该组合建立当前 Agent 的 fresh session，及 cancelled 缺失/true、sessionId/sessionFile 缺失的精确处理，必须先评审并固定。不能从某个 fake peer 的字段推断真实版本必有该字段；不得把旧 prepared client 的返回值改成 ready 来填缺口。

### 6.4 每阶段 durable / physical guard / UNKNOWN

1. 原 start reservation 唯一；phase id/ordinal、native bytes digest、actual EndpointRef、plan/profile/directory/source 与 startOperationRef 全部固定，先持久化 phase reserved。
2. 使用同一 `communicate.send_guarded` 和原 physical child ledger。实际同步 writer cut 再查 current external start/write rights、原 phase/start、同 task/thread 和固定 bindings；possibly-written 在 bytes 前 durable。插件不能替换 source authority 或跨 task 复制 guard。
3. 不在 response await 中持有 authority/DB lock。response paging/correlation/bytes limits 保留；原生未知字段/通知作为 observation 原样保存，不能误当本 phase receipt。
4. `initialized` 没有 response：只核本通知对应的原 physical observation/ledger。已记录完整发送也仅表示通知发送事实，不是 server ready；不得等待不存在的 result，也不得以通知完成直接发布 instance。后续 thread readback 仍必需。
5. not_sent 是该 phase 的已知发送失败；possibly-written、partial/lost receipt、timeout、malformed/wrong-id/duplicate/contradictory response、cancelled wait 或无法证明物理状态均为 unknown/unresolved。原 native明确 failure 保留失败内容；不自动 resend/新建 session/降格 ACP/杀进程。
6. 同一 endpoint+真实 protocol 的 single-reader fence 覆盖 bootstrap 与后续 interaction。UNKNOWN 保持 fence；同 key replay/cold reopen 仅读原操作，不能从晚到 ACK 推导出可重发资格。
7. 只有完整原 owner observations、独立身份 readback 与当前 source/lifecycle 校验满足后，才在同一真实 Records 事务发布 binding+running start。恢复读取必须重新验证该来源链，不能仅验证 seal/hash。

本草案只讨论 bootstrap。native prompt、turn completion、配置、reverse permissions 和 stop/release 还须逐项迁移其原语义；不能因 start running 就宣称整个 Codex/Pi 或工程 execution 已可用。无授予时绝不自动答 reverse request，保留原 native 请求后进入未解决状态。

## 7. 写域与离线验收矩阵（尚未执行）

协调者拥有公共修改：`packages/execution/agents/src/ordessa_execution_agents/instances/{contracts,lifecycle}.py`、`sdk/{manager,interactions}.py`、必要同 owner 的封闭 protocol observer，以及 lifecycle provenance/physical child 的真实契约和 schema。§15 的 native configuration API 不应为 bootstrap 扩成 arbitrary transport。DESIGN/公开版本/迁移批准由协调者处理。

叶子独占候选：`plugins/harness/{codex,pi}/src/ordessa_harness_*/provider.py`、必要纯 protocol facts/codec、对应 tests/README。不得改 Units、Engineering、registry、Environment resource owner。正式测试使用当前真实 AgentManager/ProfileService/SQLite Records、真实 EndpointFixture/受控 peer；不恢复旧client/runtime、不安装外部包、不访问真实模型。

| 组 | 需要保留或新增的同场景断言 | 来源/目的 |
| --- | --- | --- |
| Codex wire/identity | 无 ACP protocolVersion；initialize参数与initialized通知原形；thread-start cwd 为批准隔离目录；thread-read 同id；无 turn-start | R client/provider + 原 test_provider/test_client |
| Pi wire/identity | 顶层id/type参数，精确id/command/success，get-state握手；new-session prepared原断言保留；cancelled/缺id/不一致readback不发布 | R client + test_client_process；当前rpc_frames；候选新Agent来源测试另立 |
| Notification | initialized 精确一次原 writer；不等response；not-sent/partial/lost observation分支；不得直接发布 | 新 owner phase 的必要反例 |
| Durable/replay | 每frame先reserved、再possibly-written；每阶段crash/late response/cold restart，同key不同输入冲突，同key不重发 | 原 guarded bootstrap、receipt-loss、UNKNOWN保障 |
| Authorization | physical cut前撤权；复制invocation/guard、跨task/thread、替换endpoint/plan/profile/directory/source均拒绝且无bytes | 复用原 Agent生命周期/EndpointFixture负例 |
| Parsing/receive | 拆分LF、超限/重复key/非finite/非法UTF8/wrongid、重复response、未知native通知原样保存；stderr非协议 | 原 client/framing断言，不让ACP parser重解释 |
| Publication/corruption | 实际launch与readback后才running；任一phase未知无instance binding；篡改phase/source/protocol/nativeid后seal不能替代来源；冷读拒绝 | 原 publish_started_instance/validate_instance_origin要求 |
| Reader/fence | 同真实endpoint/protocol并发bootstrap/turn互斥；未知流不释放；等待无DB/authority锁；不同合法流不串线 | 原单reader/physicalwriter保障 |
| Regression/boundary | ACP /1旧bytes与原assert全留；未知协议launch前拒绝；无Unit/host/plugin反向import；插件仍无raw权限 | 当前 test_agent_guarded_bootstrap + owner边界检查 |
| Distribution | 当前source及独立非editable wheel使用同真实协议/合同；注册pin和公开schema一致 | 不能以源码局部绿代替发行闭包 |

以上是待实施验收条件，不是 PASS 记录。历史 client/API 测试当前未迁移的 RED 要求必须单独列账，不能删除/skip/xfail来获得品牌全绿。真实 L2/native版本兼容性、凭据与真实模型测试不在此次授权内。

## 8. 待裁定项与退出条件

需要裁定：是否扩展 §13 支持封闭 native owner dispatcher；插件 open_session 的版本化约定；phase/provenance /2 与历史读取；Pi 候选组合的 readiness/identity 语义和证据阈值。未经裁定不写公共实现。

该缺口关闭需同时具备：已批准协议/版本边界、正式调用者与唯一state authority切换、上述原断言和新增纵向反例、隔离发行验证及明确剩余L2限制。新增模块、纯codec或某个受控peer通过均不独立构成关闭。

## 附录：本次读取内容 SHA256

这些 hash 是来源冻结证据，不是能力批准或测试执行收据。

| 范围 | 相对路径 | SHA256 |
| --- | --- | --- |
| D | `DESIGN.md`（上文绝对路径） | `fcb1178dddf952c7e09eb0731fa796475b1ff2b3ea70b1b3a031f301e5ec44be` |
| T | `plugins/harness/codex/src/ordessa_harness_codex/provider.py` | `8a0afc11e1e1c490f05f96c2888c293d69cb58ab1f979bee6fa45e768087619c` |
| T | `plugins/harness/pi/src/ordessa_harness_pi/provider.py` | `fc190ebd54bccc6a591cb4ddfdad12f5ca93bf36377f518c561452b603543f8e` |
| T | `packages/execution/agents/src/ordessa_execution_agents/sdk/harness.py` | `4aa72e33717c24b518dda0994573f0c70153ee641b6b537b881bc22b2f8f0c5c` |
| T | `packages/execution/agents/src/ordessa_execution_agents/instances/lifecycle.py` | `f2554af1489a3f06be653f3934244c4e42d9ff1c73cff37bb5b3785c90960bd5` |
| T | `packages/execution/agents/src/ordessa_execution_agents/instances/contracts.py` | `c006149d77d4249c84892e0fcdc3f1b0ef0151aa269524a3dfb74b10b1f24e76` |
| T | `packages/execution/agents/src/ordessa_execution_agents/sdk/manager.py` | `247b14ff91fb74b8d59e7f17b5baeaf9b8e482f3db94a0f1a76a0d8200bea1cc` |
| T | `packages/execution/agents/src/ordessa_execution_agents/sdk/interactions.py` | `95510984c478cf5d5a7640f51bd458270c380c2fb2e7df8be9e4bcfdd6cf5d58` |
| T | `packages/execution/agents/src/ordessa_execution_agents/sdk/acp.py` | `7ffabc4992a2fd71882d4571521f07928b5531f5bc59764a7c2a1324555f41a7` |
| T | `packages/execution/agents/src/ordessa_execution_agents/sdk/native_contracts.py` | `cea3654638f7ed3a1d65c215d688ed1bc8b5d010b7c0e249c4c9762db543fb49` |
| T | `packages/execution/agents/src/ordessa_execution_agents/sdk/native_operations.py` | `ebc7bcbb889665c4080a035a4f801eaa86bedc56d188e8a25799c08d7dc87946` |
| T | `plugins/harness/pi/src/ordessa_harness_pi/rpc_frames.py` | `32555f4daf71a6c7aad40a86cfe55c783a8a1f35ea97e68b48236d1437de1afd` |
| T | `plugins/harness/pi/tests/test_rpc_frames.py` | `577b7a10f93eb0d7e94e7564117fdf258b80d283a37e1c9d0c52b9ee8d5696f0` |
| T | `plugins/harness/pi/vendor/acp-adapter/internal/pi/client.go` | `ad343a8583157329f3579cc7c583373868cf5c32c72117944d45a57038e71619` |
| T | `plugins/harness/pi/vendor/acp-adapter/testdata/fake_pi_rpc/main.go` | `179fbe3aeec3e6ae0af4035a1e862e36e2b98a5033b3692cb137138ad39e3dbd` |
| T | `tests/integration/packages_convergence/test_agent_guarded_bootstrap.py` | `cb80aaab9bd0c6191e2f4cb1ec721584a0cdd07962137c3e3bfe6ef52636e6a2` |
| R | `plugins/harness/codex/src/ordessa_harness_codex/provider.py` | `b7be4792d356d8e2fbabd45718b40726728fcef9e5e9c0834e90a952e2beddc6` |
| R | `plugins/harness/codex/src/ordessa_harness_codex/client.py` | `5285860311395fd68862ce7b18ab8b59b1e5f5447b2534a3ad985d43d790b8b3` |
| R | `plugins/harness/pi/src/ordessa_harness_pi/client.py` | `424e473f67c9dddd1fb247c85020237c87564ef13e6060da712955cca5c3ec3c` |
| T = R 原测试 | `plugins/harness/codex/tests/test_provider.py` | `98bb8e869caf50f9d5aa257e9feaad6e4ae6d17434026fb04e32c8cf48f5a80c` |
| T = R 原测试 | `plugins/harness/codex/tests/test_client.py` | `ff914d3d6ae3ad4bb84c06acafbdc361f306ad627939827d993f00d544417989` |
| T = R 原测试 | `plugins/harness/pi/tests/test_client_process.py` | `e9c78b703393e21fe1d4eff194d51ba0af931c624c9d40a706f53e787fd8e3d2` |
