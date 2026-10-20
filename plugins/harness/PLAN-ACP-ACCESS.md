# 方案 A — 接入 ACP（运行链）｜第一阶段只读 — 2026-09-24
> **Current owner and evidence note (2026-10-10).** This document contains earlier migration/review evidence. Its body is preserved; old paths and test outcomes below describe the recorded historical snapshot and are not current execution instructions or fresh validation. Current ownership and path mapping:
>
> - `runtime/access-entry.mjs` and the prior plugin-local access chain → `apps/server/src/ordessa_server/composition/native_channels/access_entry.mjs`; it selects brand declarations through `selected_launch_ports.mjs` and uses the Agent transport at `packages/execution/agents/src/ordessa_execution_agents/harness/transport/acp.mjs`.
> - `plugins/harness/tests/access/*.test.mjs` → `tests/integration/harness/access/*.test.mjs`; controlled peer/marker fixtures → `tests/fixtures/harness/access/`; shared sidecar support → `tests/integration/harness/access/support/sidecar_harness.mjs`.
> - `plugins/harness/tests/access/test_acp_boundaries.py` → `tests/architecture/harness/test_acp_boundaries.py`; `plugins/harness/packaging/tests/test_acp_schema_drift_target.py` → `tests/integration/harness/packaging/test_acp_schema_drift_target.py`.
> - Historical shared `packaging/<brand>` npm roots → each leaf's `plugins/harness/<brand>/tooling/npm/`; actual launch declarations remain owned by their brand leaf and are selected by the Server port.
>
> The source-owner receipt `docs/verification/overnight-upper-structure-20261009/harness-access-test-owner-root-applied.json` records 14 source mappings applied. Four shared discovery/CI files were subsequently integrated in `docs/verification/overnight-upper-structure-20261009/current-test-discovery-root-applied.json`; unsafe `verify-clean.sh` remains held and unrun. It is a migration receipt, not a test result. No suite was run for this documentation candidate. Historical wire names, identifiers, and raw results below remain historical evidence.


工作树 `worktrees/harness-desktop-002/bc-native`，起点 `e996e9d2`，`git diff --cached` 为空。
本文只管**一条链**：`worker-entry` 信封 ↔ 复用桥 ↔ 原生 Agent 的 ACP 收发与连接生命周期。

**本文不含**：packaging/deploy/gate/`*/production.py`/死代码与模块退役 —— 全部在
`PLAN-OPTIONAL-INSTALL.md`。两份可**各自批准或各自否掉**，互不牵连；唯一共享的前置是本轮只读。

## 0. 边界与口径

- 只读：本轮只新增测试、夹具与本方案，未改任何实现文件、`harnesses.toml`、`src/` 内核。
- 不动 Server / 前端：`src/agent_box/server/execution/sidecar.py` 与信封消费方由上层维护，本文只**报告**需要它们同步的地方。
- 离线：临时目录 + 假凭据 + 受控假进程；不调用真实模型、不读凭据、不启停既有服务。
- 实测优先：下文每个行号、每个数字都是本轮读源码/跑测试得到的；未证明的一律写成"未证明"。

## 1. 运行链事实

1. `runtime.py:1719,1737` 是本插件在内核里唯一的导入点（旧名 `agent_box_harnesses.registry`）。
2. `sidecar.py:263-277` 冻结 bundle 清单把 `runtime/*.mjs` 与 `third_party/harness_remote/bridge/src/*`
   投影到 `/runtime/view/agentbox-sidecar`；`sidecar.py:1328` 硬编码
   `"permissionRoundTrip": True, "permissionTimeoutMs": 60_000`。
3. `runtime/worker-entry.mjs`（459 行）读 NDJSON op，复用 `bridge/src/acp-*.js`。
4. `worker-entry.mjs:258` 仅在 `permissionRoundTrip` 为真时注入 `permissionResolver`；
   `:434` `wireForwarding()` 只订阅 `notification | permission | stderr | exit | service`。

## 2. 目标职责对照（仅接入侧）

| 目标职责 | 当前承担者 | 判断 |
| --- | --- | --- |
| `plugin/service` | `plugin.py`、`_compat.py`（内核旧名入口，必留） | 已具备；`entrypoints.py` 是 12 行兼容壳，本轮不动 |
| `catalog/lifecycle` | 声明 `harnesses.toml`+`registry/schema.py`；连接与清理 `worker-entry.mjs`+`acp-service.js` | 两处都真实存在；需要的是**定性**，不是新建目录 |
| `acp/` | `acp-client.js`（424 行，进程 + 帧 + 关联）与 `acp-service.js`（2124 行，会话表 / 轮次 generation / `promptAndWait`）绑在一起由 `acp-registration.js` 交付 | **对上一版的更正**：上一版写"完全复用、复用正确、不重写"。实测两者角色不同：`acp-client.js` 的**通知路径**已是透明的（`:330` 原样 emit），但它的**连接建立**与**反向请求**都会替宿主做主（§3.2）；`acp-service.js` 正是"后端不代做 initialize/session/prompt"要绕开的那一层。复用哪些、绕开哪些逐条在 §3.2，最小改动申报在 §3.3 |
| `harnesses/<品牌>` | `harnesses.toml` + `<brand>/native.py` + `adapters/<brand>.py` | 5 个 2 行 `pass` adapter 属"没差异还写空壳"→ 收口候选（在方案 B 的删除审批门后） |
| `bridges/` | 当前无插件自写桥；`third_party/harness_remote` 是唯一复用源码 + `SOURCE.json` | 保持，不新建 |

## 3. 接入侧的缺口：没有 transport 入口，而桥在替宿主做主（实测）

上一版本节把缺口写成"反向请求的路由面"。**这个口径太窄，本轮更正**：路由只是症状。真正的缺口有
两个，缺一不可，而且第一个不解决、第二个改了也没用。

**缺口一：没有"建立连接并交出 transport"的入口。**今天到达 Agent 的唯一路径是
`op:start` → `AcpClient.#start()`，而 `#start()` 把 **spawn 与握手绑死**：`:132-136` 起进程后，
`:173-177` 立刻发 `initialize`（`clientInfo` 是 `harness-remote-bridge/0.1.7`，不是宿主的），
`:187-194` 自己挑一个 auth 方法再发 `authenticate`。`#child` 只在 `#start()` 里被赋值一次
（实测 `grep -n "#child =" acp-client.js` → `:136`，其余 `:270/:412` 是清空），
所以**没有任何办法**让桥把进程拉起来而先不握手。`op:create` → `AcpService.createSession()`
再发 `session/new`，`op:prompt` → `promptAndWait()` 再发 `session/prompt`。
所以"把完整 ACP 帧塞进旧信封"仍然不是 ACP 通道：信封本身就在替宿主做 initialize/session/prompt。
（对上一版目标测试的自查更正：那 7 条全部走 `register → start → create → prompt`，因此只能证明
旧信封还在工作。已重写，见 §3.4。）

**缺口二：桥在 `agent-request` 之后立刻自己回答。**`acp-client.js:314-319`：

```js
this.emit("agent-request", message)                                                   // 帧逐字
if (message.method === "session/request_permission") this.#respondPermission(...)
else this.#respondUnsupported(message.id, message.method)                             // :394 → -32601
```

三个可测量的后果：

1. `agent-request` 在 `runtime/*.mjs` 里**零订阅**（全量 grep 只有 emit 一处命中）→ 逐字帧到不了宿主。
2. 非权限的合法客户端方法被桥**代宿主**回答 `-32601`。按 ACP 真实方法表（从 vendored Codex 包
   `package/dist/index.js` 离线读出的 `CLIENT_METHODS`，14 条），`fs/read_text_file`、
   `fs/write_text_file`、`terminal/*`、`mcp/*`、`elicitation/*` 全在这条 `else` 里被吞掉。
3. 权限往返已经被缩成一个自定义协议：resolver 只拿到 `{toolCall, options}`（没有 `sessionId`、
   没有 `_meta`），必须返回一个 `optionId` 字符串，再由桥重组成 `{outcome:"selected",optionId}`
   写回（`:371-375`）。宿主无法原样回答一个 ACP `RequestPermissionResult`，也无法原样拒绝。

### 3.1 目标口径（本轮改写）

一句话：**插件建立连接并交出 transport；此后双向只有 ACP 帧，且帧只能由客户端发。**

- 去程（Agent→客户端）：完整 JSON-RPC 请求帧逐字交付，`id` 是 Agent 的 `id`。
- 回程（客户端→Agent）：客户端自己那一帧逐字写回；客户端发 `initialize`/`session/new`/
  `session/prompt`，插件不代发、不代答、不改写。
- **未回答就是未回答**（撤回上一版的"一致拒绝"要求）：客户端还没答，通道就不写任何帧；
  超时、断线、品牌策略都不构成一个 ACP 回答。上一版 `C1` 要求"dsh 与 codex 都返回
  `{outcome:"cancelled"}`"——**该要求作废**，因为"一致的拒绝"仍然是插件在做决定。改为 `T9`：
  配了超时、两个品牌，Agent 侧都不得出现 `reverse-reply` 行（见 §3.4）。
- 连接结束要如实报告为"通道结束"，不得把客户端在途请求用一个 Agent 没发过的 `result` 收尾（`T10`）。
- 宿主可指名任意标准 ACP 方法，含扩展字段 `_meta`，帧逐字到 Agent；Agent 的错误应答逐字回宿主。

**命名口径**：入口叫什么（本轮测试里写作 `op:"connect"`）由 I 定，测试随之改一处字符串；
`reverse_request` / `reverse_response` 这类自造 vocabulary 仍然不引入——全量 grep 零命中，
新增包装名本身就是"缩小的业务协议"。断言对象始终是 Agent/客户端自己发的那一帧。

### 3.2 复用清单：能直接交出透明 transport 的 / 必须绕开的

| 组件与位置（实测行号） | 判断 | 根据 |
| --- | --- | --- |
| `acp-client.js:330` 通知路径 | **可直接复用** | Agent→客户端通知原样 `emit("notification", message)`，不筛 method、不改字段（基线 11 条已钉住） |
| `acp-client.js:316` `agent-request` | 帧本身逐字，**但不能原样交付** | 同一函数紧接着 `:317-318` 自行回答；且全链零订阅 |
| `AcpClient.request()` / `notify()`（`:201-250`） | 写路径可用，**语义不够透明** | `:205` 自己铸 `id`（`#nextID++`），宿主拿也发不出自己的 `id`；`:326` 把 `message.error` 折叠成 JS `Error`（`acpErrorMessage :16-22`），`code`/`data` 丢失 |
| `AcpClient.#start()`（`:119-199`） | **必须绕开**（或缺一个开关） | spawn 与 `initialize`/`authenticate` 绑死；`#child` 仅此处赋值 |
| `AcpClient#respondPermission`（`:355-376`）+ `#resolvePermission`（`:378-392`） | **必须绕开** | 无 resolver 时按 `permissionMode` 选 `allow_once`；resolver 超时被 `catch {}` 吞掉后写 `cancelled`（`:389`）——把墙钟变成用户决策 |
| `#respondUnsupported`（`:394-398`） | **必须绕开** | 代宿主宣告 `-32601` |
| `acp-service.js`（2124 行） | **必须绕开** | 会话表、轮次 generation（`:1309-1310,1346,1466`）、`promptAndWait`、`claimSession` 强制 `session/load`（`:644`）、快照写 `stateDirectory` —— 全是"后端代做会话/轮次" |
| `agent-model-catalog.js`（522 行） | **必须绕开** | 第二个 `AcpClient` + 自己的持久状态 + `hiddenSessionIDs`，属模型目录产品功能 |
| `acp-registration.js:44-69` | **必须绕开**（它把上面三件捆绑交付，且 `:58` 要求 `stateDirectory`） | 一次 `createAcpRegistration` 必然同时建 catalog 与 service |
| `harness-profiles.js` / `profile_extensions.mjs` 的 **launch 解析** | 可复用 | 只提供 `command`/`args`；但 `profile.permissionMode` 经 `acp-registration.js:40` 进入 client → **不得进入 transport** |
| `launcher.js`（390 行） | 不复用 | 是 daemon/端口/凭据控制面（`findAvailablePort`、`generateCredentials`、`buildDaemonArgs`），不是 ACP transport |
| `worker-entry.mjs` 的 op 分发与 `wireForwarding`（`:434-450`） | 保留给旧链路，**新通道不走** | 旧链 88 条回归不变 |

结论：**透明 transport 不能靠"原样调用现有入口"得到**，无论怎么组合。要么给桥加开关（§3.3 甲），
要么插件自带一份最小的 spawn+分帧（§3.3 乙）。上一版同时写了"完全复用不重写"和"消除桥内代答"，
这两句不能同时成立，本轮撤回前一句。

### 3.3 若要桥停止代答，最小改动申报（撤回上一版 A-5 的"不改 third_party"）

**甲案（改桥，一个文件、三处、全部 opt-in）** — 位置都在 `third_party/harness_remote/bridge/src/acp-client.js`：

1. 新增构造参数（如 `transportOnly`）：`#consumeMessage :317-318` 在开关为真时**只 emit 不回帧**；
2. 同一开关下 `#start :172-198` 跳过 `initialize`/`authenticate`，只建立子进程与帧循环（不填
   `#agentInfo`/`#promptCapabilities`/`#sessionCapabilities`）；
3. 加一个"宿主自带 id 发一帧、按该 id 收原始响应帧"的入口（≈20–30 行；`#pending` 已是 Map，
   键类型不限制，故主要是把 `:205` 的铸 id 与 `:326` 的 error 折叠绕开）。

缺省（不传开关）时 `#respondPermission`/`#respondUnsupported`/`#start` 的代码路径**一行不改**，
所以旧链 88 条与基线 32 条按构造不受影响——这也是本方案唯一可接受的桥改法。

**来源记录的硬约束（实测，不是流程偏好）**：`worker-entry.mjs:28-36` 的 `verifyProvenance()`
对 `SOURCE.json` 每个文件按 `patched_sha256 ?? current_sha256 ?? upstream_sha256` 校验，
`:140-145` 不匹配即 `PROVENANCE_MISMATCH` 直接退出。所以改 `acp-client.js` 必须**同时**更新
`SOURCE.json` 的 `patched_sha256` 与 `PATCHES.md` 的条目（该文件已有 `PATCH (AgentBox Work Order 40-A)`
等先例，格式沿用）。二者缺一即整个 sidecar 起不来。

**乙案（不改桥）**：插件自带 `acp/transport.mjs`，自己做 spawn + NDJSON 分帧 + 按 id 关联
（分帧逻辑与 `acp-client.js:275-297` 一份重复，约 40 行），并在 `SOURCE.json` 之外按"插件自研"
记录来源。**代价**：与复用源码有两份协议框架代码，日后上游修 bug 不会自动跟。**收益**：零上游改动、
零 provenance 变更。

请 I 二选一；本轮不自选。

### 3.4 对应测试（本轮重写）

`tests/access/acp_passthrough_target.test.mjs`，10 条，今天**全红**：

- `T1` 建立连接不发任何 ACP 帧（Agent 自己的记录里，第一条 ACP 帧就是客户端的 `initialize`）；
- `T2` 客户端发的每一帧逐字到 Agent（含未听说的 capability 与自定义 content block）；
- `T3` 客户端指名 `session/set_config_option` 带 `_meta` → Agent 收到逐字帧，回执逐字回来；
- `T4` Agent 的 `-32601` 逐字回客户端（不被改成本插件的错误词表）；
- `T5`/`T6` Agent→客户端请求逐字到达、客户端自己回帧（`session/request_permission`、`fs/read_text_file`）；
- `T7` 并发 5 个请求逐 id 关联、逆序回答；
- `T8` 只有 `error` 的回答也算回答：送达且回合结束；
- `T9` **不代答也不代拒**：不配超时/配 500ms 超时、`dsh`/`codex` 两个品牌，Agent 侧都不得出现 `reverse-reply`；
- `T10` 对端被杀 = 如实报告通道结束，且不得用 Agent 没发过的 `result` 收尾客户端在途请求。

每条的**原样**报错文本见 `TEST-REVIEW.md` §3.2。旧信封测试
（`tests/harness_remote/sidecar_envelope.test.mjs` 43 条、`sidecar_boundary_behavior.test.mjs` 12 条）
定位仍是旧链路回归，**不再被本文件经过**。

### 3.5 实施这项需要上层同步的三处

1. `worker-entry.mjs` 需要新增"建立连接并交出 transport"的入口与 raw 转发；`:434` 的订阅集合是旧链路的，不动；
2. `sidecar.py:1328` 恒为真的 `permissionRoundTrip/permissionTimeoutMs` —— 在新通道上这两个字段
   没有意义（超时不是决策），Server 侧要不要改用词由上层定，本文只报告；
3. Server 侧事件消费与宿主 UI 的授权入口（本插件不动）。

## 4. 基线（第四轮改写：裁定落地后，本节不再是门禁）

> **上一版的表述保留在此，不再适用**："必须不变的基线（32 条已绿，实施时一条都不许红）"。
> 裁定为：不保留旧运行链、不做双轨兼容，且**不再以"旧链必须继续通过"阻止替换**。
> 所以本节从"不许红"的门禁改成**分类清单**：哪些保留、哪些随旧链退役、退役的替代覆盖在哪。

接入侧仍然最关键的四条事实一条没少，只是换了断言位置：请求关联按 id 且容忍乱序（`C1`）；通知含
未知 method 与自定义字段逐字透传（`C2`、`T2`）；能力申报不因未识别而缩水（`C3`）；
cancel / disconnect / close 是三件不同的事实（`C5`+`C6`+`C7`，端到端 `E4`+`E7`+`T10`）。

第四轮的实测处置（逐例对照见 `tests/RETIRED.md`，被删文件与恢复位置见 `REMOVALS.md`）：

| 类别 | 内容 |
| --- | --- |
| 随旧链退役 | 5 个测试文件、47 个 `test(` 声明：`sidecar_boundary_behavior`(12)、`sidecar_envelope`(6)、`snapshot_seams`(13)、`four_harness_component`(9)、`turn_completion_facts`(7) |
| 重定位到新入口 | `tests/access/access_entry_behavior.test.mjs` E1–E8（实跑 8/8） |
| 与链无关、原样保留 | `acp_channel_behavior`(11)、`controlled_harness_self_proof`(3)、`real_adapter_protocol`(6)、`capability_claims` + `frame_buffer_lifecycle`(21) |
| 目标转绿 | `acp_passthrough_target` T1–T10（上一版全红，实跑 10/10） |

**第四轮实测（本日重跑，不是引用上一版）**：node 侧 `tests/access` + `capability_claims` +
`frame_buffer_lifecycle` 共 59/59 绿，`tests/opencode_*` 32/32 绿；Python 侧 `pytest tests -q`
→ 315 passed / 3 failed / 3 skipped，3 条失败逐条列在 `TEST-REVIEW.md` §8，均在接入链之外。
夹具这一轮仍只做**加法**（`frames`/`waitForFrame`/`streamFrames`），没有改动保留用例读到的任何桶。

> **计数口径更正**：先前版本把 `sidecar_envelope.test.mjs` 写成"43 条"、把基线写成"32 条"。
> 按 `grep -c '^test('` 实测是 **6** 条；四条基线套件相加是 11+12+3+6 = **32**（巧合同数，含义不同：
> 32 只数这四组，不数旧信封与被删的快照接缝）。

## 5. 撤回：上一版"零消费者即可删"的结论

上一版 §5 把 17 个模块列为"候选删"，其中多个标成"真零读者"。**本轮撤回这个表述**，理由是可测量的：

1. **`__all__` 不能当公共契约的证据。** 实测 `hermes/__init__.py` 与 `opencode/__init__.py` 各把
   `__all__` 赋值**两次**（后者见 §7），第一次列出的 4/3 个名字**根本不在该包上**
   （`hasattr(module,'create_plugin')` → `False`，`hasattr(module,'OpenCodeExecutionProvider')` → `False`）。
   一个连自己声明的公共面都写错的包，无法支撑"没人用所以可删"的推理。
2. **三类引用不进 import 计数**，删之前必须逐条处理：`test_core_identity.py:54` 用
   `__import__(f"{name}.{dotted}")` **动态**导入 20 个模块并要求新旧名同对象；
   `tests/test_boundaries.py:26` 按**路径文本**读 `codex/launch.py` 断言含 `class CodexLaunchSpec`；
   `real_adapter_protocol.test.mjs` 按**目录内容**判定品牌是否有真实协议材料。
3. **上一版自己也记错了两处计数**：`codex.launch` 被写成"零读者 ‡"，实际被路径断言钉住；
   `importers.models` 被写成疑似"不可导入"，实测 `importlib` 可导入（隐式命名空间包），是"无人导入"。

结论改为：**本阶段不申请任何删除**。删除/移交只在方案 B 里按"每一条单独批准"提，且必须附
"动了它哪条测试会红"的反证。

## 6. 更正：`ExecutionProvider`（执行代理）≠ 模型 Provider

上一版把 `<brand>/provider.py` 归入"provider 属产品模型管理 → 移交候选"。**这个归类是错的**，本轮更正。
实测三个不同的角色：

| 角色 | 定义在哪 | 方法/形状 | 本插件里的实现 | 是否模型供应商 |
| --- | --- | --- | --- | --- |
| `ExecutionProvider`（执行代理） | 内核 `work_core/registry.py:127` Protocol | `descriptor/capabilities/input_limits/start/observe` | `claude/provider.py:27`、`hermes/provider.py:27`、`opencode/provider.py:73`、`pi/provider.py:27`、`codex/interactive/provider.py:32`、`generic/execution_provider.py:8` | **否**——`provider_id = f"{harness_type}-execution"`，`capabilities()` 返回 `pty/direct-stdio/observe` 等执行特征 |
| `ResourceProvider`（资源解析） | 内核 `work_core/registry.py:36` Protocol | `resolve()` 类 | `generic/profile_store.py`（`PROVIDER_ID = "harness-profile"`）、`*/continuation*.py` | **否** |
| 模型 Provider（产品模型供应商） | 内核 `server/model_configs/service.py:15 ProviderModelService`、`repository.py:26`，按 `providerId/modelId` 走线（`wire/handlers.py:377`） | 内核所有 | **插件内零实现**；插件唯一沾模型的东西是 `runtime/profile_extensions.mjs` 的别名表（§6-1）与 `native_materialization.py::render_codex_provider_section()`（写 `[model_providers.<id>]` TOML，属方案 B） | 是 |

意义：上一版因为把"ExecutionProvider"当成"模型 Provider"，把 6 个执行代理类误列为"模型管理、移交候选"。
更正后它们的问题不是"归属错层"，而是**在原生接入链上无人调用**（EXT 消费者只来自测试），属方案 B 的移交清单。

### 6-1 模型别名表（唯一的真·模型管理项，仍上报不删）

`runtime/profile_extensions.mjs` 的 `AGENTBOX_MODEL_ALIASES`(`:222`) + `resolveNativeModel()`(`:239`)
在帧到达 Agent 前改写 model id。目标测试**不再依赖这个内部实现**：`T3` 断言的是"客户端命名
`session/set_config_option` 并带 `_meta`，Agent 收到的帧逐字不变"。别名表删与不删是
Server 可发送语义的决定 → 上报，本轮不自删。

## 7. 待批（只有本文范围）

- **A-1** 批准 §3.1 的行为目标作为验收口径，含 §3.4 那 10 条目标测试：建立连接不发送 ACP 帧；
  此后双向只有客户端与 Agent 自己发的帧；未回答就是未回答（不代答、不代拒、不把超时当决策）。
  入口命名由 I 定，行为不缩水。
- **A-2** **（本轮改写）**批准 §3.3 里选一条实现路径：**甲案**给 `acp-client.js` 加三处 opt-in 开关
  并同步 `SOURCE.json` + `PATCHES.md`；**乙案**插件自带最小 transport、零上游改动。
  上一版 A-2 只写了"`wireForwarding` 订阅集合 + op 分发"，不足以覆盖 §3.2 测出的事实。
- **A-3** 确认 §5 的撤回：本轮**不申请删除**任何模块。
- **A-4** 确认 §6 的更正归类，并确认 `harnesses.toml` 字段裁剪、`_compat.py`、`entrypoints.py` 均维持原状。
- **A-5** **（本轮更正，不再承诺"桥完全不改"）**本轮仍然不改任何实现，但上一版"不改 `third_party`
  复用源码与 `SOURCE.json`"与 §3"消除桥内代答"**互相矛盾，前一句已撤回**。不改的是：不 push、
  不合并 main、不为过测试放宽断言；`third_party` 是否改动由 A-2 单独批准。

## 7.1 本轮明确撤回的三句上一版表述

1. "`acp/` 完全复用 `acp-client.js`/`acp-service.js`/`acp-registration.js`，复用正确、不重写"（§2 已改写）；
2. "不申请改 `third_party`，同时消除桥内代答"（A-5 已改写，改为甲/乙二选一）；
3. "无人应答一律拒绝（品牌无关）"（改为"一律不作答"，§3.1；旧 `C1` 目标作废，新 `T9` 取代）。

## 附录 A1 — 接入侧逐模块实测（EXT=插件包外消费者，INT=包内引用）

计数口径与其盲区见 `TEST-REVIEW.md` §6。**"归属"列不是删除申请**：本文不申请删任何模块（§5）。

| 模块 | 公共接口 | 消费者（实测） | 归属 |
| --- | --- | --- | --- |
| `plugin.py` | `create_plugin()`, `HarnessesPlugin` | EXT=5：`tests/test_codex_wiring.py`、`plugins/agent-box-web/tests/{test_harness_host_integration,test_harness_profile_e2e,test_quick_launch_catalog}.py`、`tests/integration/native/test_extension_catalog.py`；INT=1 | 接入入口。web 插件在读 → 不改对外契约 |
| `_compat.py` | `ALIASES`, `install()` | EXT=4：`src/agent_box_harness_{dsh,kilo,qwen}/__init__.py`、`src/agent_box_harnesses/__init__.py` | **必留**：内核 `runtime.py:1719` 用旧名导入 |
| `entrypoints.py` | `_Plugin`, `create_profile_store()`, `create_<brand>()` | EXT=1：`tests/test_core_identity.py` | 兼容入口；六个既有注册项仍指向它 → 本轮不动 |
| `registry/loader.py` | `load_registry()`, `load_builtin_registry()`, `HarnessRegistry`, `RegistryDiagnostics` | EXT=7（`test_capability_declarations`、`test_core_identity`、`tests/server/test_asset_hubs`、`test_capability_truth_table`、`test_harness_capability_integration`、`test_posture_config_write`、`test_profile_permissions`） | 内核唯一入口，**签名不改** |
| `registry/definitions.py` | `REGISTRY`, `DEFINITIONS` | EXT=1：`test_core_identity.py` | 保留（新旧名同对象已被钉） |
| `registry/capability_claims.py` | `capability_claims()` | EXT=1；INT=3 | 保留（能力不得外露缩水，正是 §4 第 3 条的根据） |
| `registry/schema.py` | `Identity`/`ExecutableSpec`/`ProfileSpec`/`LaunchMode`/`RuntimeSpec`/`InputSpec`/`CredentialSpec`/`ContinuationSpec`/`HarnessDefinition` | EXT=1；INT=1 | 声明结构保留；`ProfileSpec`/`CredentialSpec` 是否仍属接入 → 归方案 B §6-5 |
| `harnesses.toml` | 8 段 `[[harness]]`（423 行） | 经 `registry.loader` | 保留；字段裁剪属方案 B §6-8 |
| `registry/validation.py` | `validate_registry()` | 静态 EXT=0 INT=0；**被 `test_core_identity.py::MOVED_MODULES` 动态导入钉住** | 归属待定（方案 B §6），**非"可删"** |
| `resources/{executable,profile_codec}.py` | `resolve_executable()` / `canonical_json()` | EXT=0 INT=1；同上被钉 | 归属待定（可执行解析真实在 `codex/executable.py`；Profile 编解码属 Profile） |
| `bridge/src/acp-client.js` | 进程 + 分帧 + 请求关联 `#pending`、反向请求分发 | `#child` 仅在 `#start()` 赋值（`:136`），`#start` 内 `:173-194` 必发 `initialize`+`authenticate`；`:314-319` emit `agent-request`（**全链零订阅**）后立刻代答；`:394` `-32601`；`#respondPermission:355-376` 无 resolver 时按 `permissionMode` 选择；`:389` 超时被吞后写 `cancelled`；`:326` error 折叠成 `Error` 丢 `code`/`data` | **不能原样交出透明 transport**；逐条判断与最小改动见 §3.2 / §3.3 |
| `bridge/src/acp-service.js` | 多轮/取消/会话归属 | `:644` `claimSession` 强制 `session/load`；`:1309-1310,1346,1466` turn generation（`abort()` 递增 generation，使被取消轮次自身的 `stopReason` **有意不被归属**） | 旧链路保留（基线 #14/#15/#16 钉住）；新 transport **绕开**（§3.2） |
| `bridge/src/acp-registration.js` | profile → client+catalog+service | `:44-69` 一次调用必然同时建 `AcpClient`、`AcpAgentModelCatalog`、`AcpService`；`:40` `permissionMode: profile.permissionMode`；`:58` 要求 `stateDirectory` | 新 transport **绕开**（捆绑了品牌策略与产品目录，见 §3.2） |
| `bridge/src/agent-model-catalog.js` | 模型目录（第二个 client + 持久状态） | 522 行；由 `acp-registration.js:49-56` 无条件构建 | 新 transport **绕开**；属可选安装/产品功能（方案 B） |
| `bridge/src/launcher.js` | daemon/端口/凭据控制面 | `findAvailablePort`、`generateCredentials`、`buildDaemonArgs`、`startManagedOpenCode` | **不是 transport，不复用**（§3.2） |
| `third_party/harness_remote/SOURCE.json` | 唯一复用源码来源 | upstream `giuliastro/harness-remote` v3.0.2 @ `21ce6db…`，Apache-2.0，21 文件 | 保留 + `verifyProvenance()` 启动校验（已钉） |
| `runtime/worker-entry.mjs` | 信封 ↔ 桥 | 459 行；`:251` `resolveHarnessProfile`；`:258` 仅 `permissionRoundTrip` 时注入 resolver；`:434` `wireForwarding` | §3 的实施位置 |
| `runtime/profile_extensions.mjs` | 品牌 profile + 能力映射 + 模型别名 | `:206` `REGISTERED = {...HARNESS_PROFILES, ...AGENTBOX_HARNESS_PROFILES}`（整条替换）；5 条 `permissionMode:"deny"`；`:AGENTBOX_MODEL_ALIASES` 6 品牌；`resolveNativeModel()` | 能力映射保留；别名表见 §6-1 |
| `runtime/capability_declarations.json` | 声明上限 | 被 `sidecar.py:268-271` 投影 | 保留 |
| `runtime/native-driver.mjs` | 显式入口 + 项目目录启动 | 基线 #9 | 保留（不生成配置/不换 home/不装依赖/不引沙箱，已实测钉住） |
| `runtime/drivers/opencode-native.mjs` | opencode 专用驱动 | 唯一 drivers 文件 | 保留（真实品牌差异） |
| `runtime/subagent-bridge.mjs` | stdio MCP 委派桥 | `sidecar.py:276-277` 投影；`runtime.py:1160` 写视图；另一端 `server/execution/delegation.py` | 归属见方案 B §6-6，本轮不动 |
