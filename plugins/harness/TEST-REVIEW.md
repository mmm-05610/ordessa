# TEST-REVIEW — 收敛第一阶段测试审核（第三版 / third revision，2026-09-24）
> **Current owner and evidence note (2026-10-10).** This document contains earlier migration/review evidence. Its body is preserved; old paths and test outcomes below describe the recorded historical snapshot and are not current execution instructions or fresh validation. Current ownership and path mapping:
>
> - `runtime/access-entry.mjs` and the prior plugin-local access chain → `apps/server/src/ordessa_server/composition/native_channels/access_entry.mjs`; it selects brand declarations through `selected_launch_ports.mjs` and uses the Agent transport at `packages/execution/agents/src/ordessa_execution_agents/harness/transport/acp.mjs`.
> - `plugins/harness/tests/access/*.test.mjs` → `tests/integration/harness/access/*.test.mjs`; controlled peer/marker fixtures → `tests/fixtures/harness/access/`; shared sidecar support → `tests/integration/harness/access/support/sidecar_harness.mjs`.
> - `plugins/harness/tests/access/test_acp_boundaries.py` → `tests/architecture/harness/test_acp_boundaries.py`; `plugins/harness/packaging/tests/test_acp_schema_drift_target.py` → `tests/integration/harness/packaging/test_acp_schema_drift_target.py`.
> - Historical shared `packaging/<brand>` npm roots → each leaf's `plugins/harness/<brand>/tooling/npm/`; actual launch declarations remain owned by their brand leaf and are selected by the Server port.
>
> The source-owner receipt `docs/verification/overnight-upper-structure-20261009/harness-access-test-owner-root-applied.json` records 14 source mappings applied. Four shared discovery/CI files were subsequently integrated in `docs/verification/overnight-upper-structure-20261009/current-test-discovery-root-applied.json`; unsafe `verify-clean.sh` remains held and unrun. It is a migration receipt, not a test result. No suite was run for this documentation candidate. Historical wire names, identifiers, and raw results below remain historical evidence.


工作树 `worktrees/harness-desktop-002/bc-native`，起点 `e996e9d2`。
**状态：IMPLEMENTATION_REVIEW_READY（第四轮，实施轮）；第三轮的 `TEST_REVIEW_READY` 记录原样保留在下文，
作为"实施前测什么、红在哪"的历史证据。** 裁定已落地：不保留旧运行链、不做双轨兼容，
**"基线必须继续通过"不再作为阻止替换的门禁**（该门禁原句见 §3.1 与 `PLAN-ACP-ACCESS.md` §4，
两处均已按裁定改写或标注为历史）。第四轮的实测结果、被删用例的逐例替代覆盖与恢复位置：
新增 §11、`tests/RETIRED.md`、`REMOVALS.md`。

**本轮（第三版审核轮）只新增/改写了 `tests/**`、
`fixtures` 与方案文档**：未修改任何运行实现、`harnesses.toml`、deploy 模板、packaging 工件、
`scripts/**`、仓库内核 `src/**`（Work Core / Server 包，非本插件的 `src/`）；
`git diff --cached` 为空（实测 0 条已暂存）；未 push、未合并 main。

> 口径说明：`git status` 里本插件另有 8 条 `M`（`pyproject.toml`、`src/agent_box_harness/{__init__,
> adapters/__init__,generic/factory,plugin,registry/loader}.py`、`tests/test_core_{boundaries,identity}.py`）
> 和四个同级插件目录的 `D`，**都属于上一阶段"单包合并/接入与打包分离"的既有改动**（证据在那一阶段的
> `CONSOLIDATION.md`），不是本轮引入。本轮的产物全部是 `??`（未跟踪的新文件）。

配套方案（已按审核意见拆成两份，`REFACTOR-PLAN.md` 只剩指路桩）：
`PLAN-ACP-ACCESS.md`（接入 ACP）、`PLAN-OPTIONAL-INSTALL.md`（可选安装 / 移交清单）。

## 0. 逐条回应上一轮审核意见

| # | 审核要求 | 本轮做了什么 | 在哪 |
| --- | --- | --- | --- |
| 1 | 暂不批准实施或删除模块 | 未动实现；两份方案里**一条删除都不申请**，`§5`/`§7` 明确"本轮不删" | `PLAN-ACP-ACCESS.md` §5、A-3；`PLAN-OPTIONAL-INSTALL.md` §6、B-5 |
| 2 | 两套夹具自证：成功响应与 error-only 响应可正确接收、记录并结束，无遗留异步异常 | 见 §4：夹具侧 3 条 + 通道侧 3 条，全绿，含"种一个未处理 rejection 证明记录器会响"的反例 | `controlled_harness_self_proof.test.mjs`、`acp_channel_behavior.test.mjs` |
| 3 | 重查相对导入、动态导入与入口消费者；撤回未经证明的"零消费者可删" | 移动目录后 3 个文件的 `pluginRoot` 少一层 `..`（会让 `third_party/...` 解析到不存在的路径），已改并由"真的 import 到桥"这一事实钉住；动态导入与按路径断言逐条标 †/‡；**上一版 17 条"候选删/真零读者"表述整体撤回** | §6.1、§6.2；`PLAN-ACP-ACCESS.md` §5 |
| 4 | 区分 `ExecutionProvider` 与模型 Provider | 实测三角色表：内核 `work_core/registry.py:127`（执行代理）/ `:36`（ResourceProvider）/ `server/model_configs/`（模型 provider，插件内零实现）。**上一版把 `<brand>/provider.py` 当"模型 provider"是错的，已更正** | `PLAN-ACP-ACCESS.md` §6；`PLAN-OPTIONAL-INSTALL.md` §6-4 |
| 5 | 目标测试改为"编排建立连接后，双向 ACP 原样通过"，覆盖请求/通知/成功/错误/扩展字段；不再新增自定义包装 | 重写为 7 条（A1–A4 去程、B1–B2 回程、C1 默认），全部只断言 **ACP 帧本身**；`reverse_request`/`reverse_response` 两个自造名**撤回**（全量 grep 零命中）；通知由基线 #2/#17 覆盖。**这 7 条在下一轮被指出仍在旧信封里，已再重写为 10 条，见 §0.1 第 1 行** | `acp_passthrough_target.test.mjs`；§3.2 |
| 6 | 旧信封测试仅作旧链路回归 | 在 `tests/harness_remote/sidecar_envelope.test.mjs` 头部加了 scope note，43 条旧链回归全绿但不作为目标验收 | 该文件头部；§2.2 |
| 7 | 仍限定插件范围，不自行修改 Server/前端 | 只改了 `plugins/agent-box-harness/**`；需要 Server 同步的三处只**报告**位置 | `PLAN-ACP-ACCESS.md` §3.1 |
| 8 | 补 Codex / OpenCode / Qwen Code / Hermes 真实 adapter 协议测试 | Codex 真做（从 vendor tarball 离线解出真实 `AGENT_METHODS`/`CLIENT_METHODS`/`PROTOCOL_VERSION`，并反向校验夹具只说真方法名）；其余三个**离线无字节可读**，不补 fake 冒充，改为从磁盘推导"为何测不了"的断言 | `real_adapter_protocol.test.mjs`；§5 表 |
| 9 | 加并发反向请求、packaging 构建输入漂移、桥 100 MB 下载限制 | 并发：上一版为 `A3`，本轮重写为 `T7`（5 个不同 id、逆序回答、逐 id 关联）+ 自证第 3 条（4 个并发、只结算一次）。漂移：6 个检测器 + 种入反例。100 MB：**查无此数**，见 §7 实测更正，改为钉住真实存在的界 | §3.2 T7；`test_packaging_boundaries.py`；§7 |
| 10 | 按接入 ACP 与可选安装分开；模型重写测试不再依赖插件内部实现 | 测试与文档都按类分目录/分文件；`T3` 断言"客户端命名 `session/set_config_option` + `_meta` → Agent 收到逐字不变的帧"，**不读别名表**；上一版依赖 `resolveNativeModel` 的基线 #13 已删（不是放宽，是换掉了对内部实现的依赖） | §2.1 目录表；`PLAN-ACP-ACCESS.md` §6-1 |
| 11 | 拆分 `REFACTOR-PLAN.md` 为两份独立文档 | 已拆，两份各自带边界与待批清单；原文件改为指路桩（未删，避免丢失唯一副本） | 两份新文档 |
| 12 | 更新审核文档，重新报 TEST_REVIEW_READY（第二版），列出真实失败原因 | 本文件；每条红测试的**原样**报错文本在 §3.2 | §3.2、§7 |

### 0.1 逐条回应第三轮审核意见（本轮实际做的四件事）

| # | 审核要求 | 本轮做了什么 | 在哪 |
| --- | --- | --- | --- |
| 1 | 目标测试必须从"建立连接并返回 ACP transport"入口开始，建立本身不发送 `initialize`/`session`/`new`/`prompt`；这些帧全部由测试客户端主动发；旧 `register`/`start`/`create`/`prompt` 只作旧链路回归 | **接受并整份重写**：7 条 A/B/C 换成 10 条 T1–T10，客户端自己发 `initialize`→`session/new`→`session/prompt`，T1 直接断言"Agent 自己的记录里第一条 ACP 帧就是客户端的 `initialize`"；旧信封两组测试保留且不在新文件路径上 | `acp_passthrough_target.test.mjs`；§3.2；`PLAN-ACP-ACCESS.md` §3、§3.4 |
| 2 | 纯通道不得按品牌自动批准；不得把"客户端尚未回答"改成拒绝或 `cancelled`；显式拒绝原样通过；断开如实报告传输结束；超时不得冒充用户决策 | 上一版 `C1`"所有品牌一致返回 `cancelled`"的要求**作废并撤回**（一致的拒绝仍是插件在做决定）。改为 `T9`：不配超时/配 500ms 超时 × `dsh`/`codex` 两品牌，Agent 侧都不得出现 `reverse-reply` 行；`T8` 客户端显式 `error` 逐字通过；`T10` 对端被杀只报通道结束、不得伪造 `result` | §3.2 T8/T9/T10；`PLAN-ACP-ACCESS.md` §3.1、§7.1 第 3 条 |
| 3 | 重新列明哪些复用组件能直接提供透明 transport、哪些旧会话/轮次管理要绕开；桥若必须改要申报最小改动与来源记录；不要同时承诺"桥完全不改"和"消除桥内代答" | §3.2 逐项表（12 行，可复用/必须绕开，带实测行号）；§3.3 **甲案**＝改 `acp-client.js` 三处 opt-in + 必须同步 `SOURCE.json` 的 `patched_sha256` 与 `PATCHES.md`，否则 `verifyProvenance()` 让 sidecar 起不来；**乙案**＝插件自带最小 transport、零上游改动，代价是两份分帧代码——**请 I 二选一，本轮不自选**；上一版 A-2/A-5 的矛盾两句**明确撤回**（`PLAN` §7.1 第 1、2 条） | `PLAN-ACP-ACCESS.md` §3.2、§3.3、§7、§7.1 |
| 4 | 仅修测试与接入方案，不扩展安装、打包、模块删除任务 | `tests/install/**`、`packaging/**` **零改动**。本轮实际写入 6 个文件（`find -newermt` 实测）：`tests/access/acp_passthrough_target.test.mjs`（整份重写）、`tests/access/sidecar_harness.mjs`（**只做加法**：新增 `frames` 原始流 + `waitForFrame`/`streamFrames`，没动基线读到的 `events`/`responses` 两个桶）、`PLAN-ACP-ACCESS.md`、本文件，以及**两处一个数字的交叉引用更正**（`REFACTOR-PLAN.md` 与 `PLAN-OPTIONAL-INSTALL.md` 附录 B2 里的"7 条"→"10 条"，因为条数变了、留着就是假话；未新增或删除方案 B 任何条目）。§5/§7 的删除申请依旧不提 | 本轮 diff；`PLAN-ACP-ACCESS.md` §5 |

## 1. 本轮文件清单（只有测试、夹具、方案文档）

| 文件 | 类别 | 实测 |
| --- | --- | --- |
| `tests/access/acp_channel_behavior.test.mjs` | 基线·复用通道层 | 11 用例，全绿 |
| `tests/access/sidecar_boundary_behavior.test.mjs` | 基线·真实 `worker-entry` 端到端 | 12 用例，全绿 |
| `tests/access/controlled_harness_self_proof.test.mjs` | 夹具自证 | 3 用例，全绿 |
| `tests/access/real_adapter_protocol.test.mjs` | 真实 adapter 协议字节 | 6 用例，全绿 |
| `tests/access/acp_passthrough_target.test.mjs` | **目标（按设计红）** | 10 用例，**10 红**（本轮从 7 条重写为 10 条，见 §0.1 第 1 行） |
| `tests/access/controlled_harness.mjs` / `sidecar_harness.mjs` | 受控假 Agent / 共享脚手架 | — |
| `tests/access/test_acp_boundaries.py` | 基线·接入侧边界 | 7 用例，全绿 |
| `tests/install/test_packaging_boundaries.py` | 基线·可选安装侧 | 26 用例，全绿 |
| `tests/install/test_acp_schema_drift_target.py` | **目标（按设计红）** | 17 用例，**2 红 / 15 绿** |

删除的只有本轮自己上一版产生的东西：`tests/harness_convergence/`（迁到 `tests/access/`）、
`tests/test_convergence_boundaries.py`（拆成上面两个 py 文件）、`target_gaps.test.mjs`（被
`acp_passthrough_target.test.mjs` 取代）、基线 #13（模型别名内部依赖，被 `T3` 取代）。

**没有删除、跳过或放宽任何既有测试**，这一点已逐条核对而非声明：`git status` 里 212 条 `D` 全部来自
上一阶段（单包合并）移除的四个同级插件目录 `agent-box-harnesses`/`-{dsh,kilo,qwen}`，其中 35 条是测试路径；
对那 35 条逐个按文件名在 `plugins/agent-box-harness/tests/` 下查对，**每个都有同名对偶存在**
（即"搬走了"，不是"没了"），核对脚本口径见 §6.3。旧链 88 条 JS 回归全绿也与此一致。

## 2. 命令与实测结果（全部为本日重跑）

### 2.1 本轮

```
cd plugins/agent-box-harness
node --test tests/access/acp_channel_behavior.test.mjs        # 11 pass / 0 fail
node --test tests/access/sidecar_boundary_behavior.test.mjs   # 12 pass / 0 fail
node --test tests/access/controlled_harness_self_proof.test.mjs   # 3 pass / 0 fail
node --test tests/access/real_adapter_protocol.test.mjs       # 6 pass / 0 fail
node --test tests/access/acp_passthrough_target.test.mjs      # 0 pass / 10 fail ← §3.2，按设计
node --test tests/access/*.test.mjs                           # 42 tests: 32 pass / 10 fail

source /tmp/hd002-tidy-env/bin/activate   # 每个 Bash 调用都要重新 source
python -m pytest tests/access/test_acp_boundaries.py -q                    # 7 passed
python -m pytest tests/install/test_packaging_boundaries.py -q             # 26 passed
python -m pytest tests/install/test_acp_schema_drift_target.py -q          # 15 passed / 2 failed ← §3.2
```

### 2.2 既有回归（未改实现）

```
node --test tests/harness_remote/*.test.mjs tests/*.test.mjs   # 88 tests: 88 pass / 0 fail
python -m pytest tests -q                                      # 315 pass / 3 fail / 3 skipped
```

那 3 红 = §3.2 的 2 条按设计目标 + §8 的 1 条预存在失败。**本轮引入的意外失败：0。**

> 命令坑（实测）：`node --test <目录>` 在本机 node v22.22.1 下把目录当模块解析并报 `MODULE_NOT_FOUND`，
> 必须显式给 `*.test.mjs`。

## 3. 基线与目标严格分开

### 3.1 基线（钉住现状，未为变绿改断言）

通道层 11 条：乱序回复只结算自己 id；通知含未知 method 与自定义字段逐字到达；能力申报不因未识别而丢失；
反向请求默认拒绝且不被执行；cancel 是 notification；断连不是取消；`close()` 只清理本连接；
watchdog 按会话隔离；**成功/error-only 回复各自可结算且无遗留异步异常**（§4）。

端到端 12 条：只用显式入口 + 项目目录、不写 Agent home、不注入 `npm_config*`、不改 `NODE_OPTIONS`、
不需要隔离标记；注册要求显式入口且环境是**校验**不是信任（凭据形状被拒、声明过的非敏感变量可达）；
权限往返开启时交宿主、选项取自 Agent 自己的列表，并且**这一轮把该事件的实际形状也钉住了**：
`Object.keys(asked.data) == ["expiresAt","options","requestId","toolCall"]`（本插件自己的四个键，不是 ACP 帧）、
`requestId` 是 `randomUUID()` 而不是 Agent 的 JSON-RPC id（`jsonrpc`/`method`/`sessionId` 在此被丢弃），
同时 `toolCall.toolCallId` 逐字到达（宿主侧字段过滤只发生在信封那一层，不发生在 toolCall 内部）——
这三条断言一次通过，证明 §3.2-旧 A1/A3 里两份旧注释的说法是错的，注释已按断言更正；有界授权选中 `allow_always`；往返关闭时答案来自品牌
`permissionMode`（**这条是今天的事实，正是 `T9` 要在 transport 通道上取消的东西**；基线仍如实记录旧链路今天的行为，不改）；cancel/disconnect/close 三件不同事实；
未申报 resume 不被假装成功；Agent 拒载的已存会话不被收养；能力字段过信封不变（含 `jsonrpc`/`method`/
`params.update.content.text` 逐字段）；同会话跨轮身份连续、两会话互不串；Agent 错误原因保留进信封；
关一条连接只释放它自己的进程。

安装侧 26 条 + 接入侧 7 条：见 `PLAN-OPTIONAL-INSTALL.md` §2 表与 `test_acp_boundaries.py`
（来源清单双向核对、种入篡改/未列文件反例、重复实现检测器、`START_TIMEOUT_MS == 90_000` 时间界钉住）。

### 3.2 目标（今天红，原样报错，无一条被"修绿"）

> **本轮重写**：上一版这 7 条（A1–A4 / B1–B2 / C1）全部经 `register → start → create → prompt`
> 驱动，因此只能证明旧信封还在工作——审核意见指出"把旧信封里的内容换成完整 ACP 帧，仍不等于
> 独立 ACP 通道"，**接受**。目标测试改为从"插件建立连接并交出 transport"入口开始，
> `initialize`/`session/new`/`session/prompt` 全部由测试自己发（`tests/access/acp_passthrough_target.test.mjs`，
> 现 10 条 T1–T10）。旧信封的两组测试（`sidecar_boundary_behavior` 12 条、`harness_remote/sidecar_envelope` 43 条）
> 保留为**旧链路回归**，不再是新通道的必经路径。上一版表格中 7 条的具体报错随之作废，
> 只在 §3.2-旧 留档，以免"改测试把红的改成不存在的"。

10 条 T 组今天红在**同一个位置、同一种形状**——这是本轮最关键的一条实测：

```
AssertionError: strictEqual
  actual: { code: 'NOT_REGISTERED', message: 'NOT_REGISTERED' }
  expected: undefined
```

即客户端自己发的那一帧（`{"jsonrpc":"2.0","id":"client-N","method":"initialize",...}`）被**信封在门口
挡下并回答** `{"id":"client-N","ok":false,"error":{"code":"NOT_REGISTERED"}}`：`worker-entry.mjs:281`
在 `op` 分发前就 `if (!registration && !driver) throw envelopeError("NOT_REGISTERED")`。
帧根本没到 Agent，Agent 的记录里只有 `exec`。根因不是路由，而是**没有那个入口**：
`AcpClient.#child` 只在 `#start()` 内赋值（`acp-client.js:136`），而 `#start()` 必定先发
`initialize`（`:173-177`）再自选并发的 `authenticate`（`:187-194`），所以桥无法"只建立连接不握手"。

| 用例 | 断言的是什么（原样失败发生在哪一步） | 根因位置 |
| --- | --- | --- |
| T1 建立连接不发送任何 ACP 帧 | 客户端自己的 `initialize` 是 Agent 收到的第一帧；`connect` 回执不得带 `sessionId`/`agentInfo` | `#start()` 绑定 spawn 与握手（`acp-client.js:136,173-194`）；信封 `:281` |
| T2 客户端发的每帧逐字到 Agent | 未听说的 capability、自定义 content block 都要原样到达 | 同上（帧未达） |
| T3 客户端指名 `session/set_config_option` 带 `_meta` | 值与 `_meta` 不被改写 | 信封 op 集合无此项；`resolveNativeModel()` 会改写 model |
| T4 Agent 的 `-32601` 逐字回客户端 | Agent 自己的错误词表不被替换 | 帧未达，Agent 无从拒绝 |
| T5 权限请求帧逐字到达、客户端自己回帧 | Agent 的 `id`/`params.sessionId`/`options` 顺序；Agent 收到客户端原样 `outcome` | `:316` emit 后 `:317` 立刻代答；`runtime/*.mjs` 零订阅 |
| T6 未实现的客户端方法被路由而非代拒 | `fs/read_text_file` 必须到达客户端 | `:318`→`:394` `#respondUnsupported` 代宿主回 `-32601` |
| T7 并发 5 个请求逐 id 关联、逆序回答 | 5 个不同 id、各自答案不串 | 帧未达；`pendingPermissions` 键是 minted uuid |
| T8 只有 `error` 的回答也是回答 | `code`/`message`/`data` 逐字到 Agent 且回合结束 | 帧未达；`:326` 还把 error 折叠成 JS `Error` |
| T9 **不代答也不代拒**（不配超时 500ms 超时 × `dsh`/`codex` 两品牌） | Agent 侧 `reverse-reply` 行必须为空——超时、断线、品牌都不构成回答 | `:355-377` 按 `permissionMode` 选择；`:389` 超时被 `catch {}` 吞掉后写 `cancelled`；`profile_extensions.mjs:206` 整条替换造成品牌分裂 |
| T10 对端被杀如实报告通道结束 | 不得用 Agent 没发过的 `result` 收尾客户端在途请求 | `:410-415`→`#rejectPending` 只 reject 桥自己的 `Error`；Agent 在途请求当初已被同步代答 |

PY 组不变（可选安装侧，本轮未动）：

| 用例 | 实测失败原因（原样） | 根因位置 |
| --- | --- | --- |
| PY-1 闭包携带的 schema 满足需要它的 adapter | `pi: ["@automatalabs/pi-acp: declares @agentclientprotocol/sdk@1.4.0 but the lock resolves 1.3.0 at node_modules/@automatalabs/pi-acp/node_modules/@agentclientprotocol/sdk"]`，其余 5 品牌 0 命中 | 症状：落到磁盘的 schema 比 adapter 声明的旧 |
| PY-2 根 `overrides` 不得违反闭包里任何声明 | `pi: ["overrides forces @agentclientprotocol/sdk@1.3.0 (resolved 1.3.0), which violates @automatalabs/pi-acp's declaration @agentclientprotocol/sdk@1.4.0"]` | **原因**：`packaging/pi/package.json:10` 对根自己不依赖的包下了 `overrides`；npm 静默改写，`npm ci` 退出 0 |

**T 组一条都不许靠"没有通道"蒙过负向断言**：每条负向断言之前都先跑一次同连接的
`initialize` 往返（`liveChannel()`），Agent 答了才算活着；所以 T9/T10 今天的红是"活不起来"的红，
不是"什么都没发生"的红。

#### 3.2-旧 上一版 7 条的留档（作废，未删除）

`A1/A2` `no ACP request frame for "session/request_permission" / "fs/read_text_file" reached the host`；
`A3` `only 0 of 3 "session/request_permission" frames arrived; all frames: []`；
`A4` 同 `A2`；`B1` `no set_config_option note; the harness recorded ["exec","initialize","authenticate","session/new"]`
（**这条记录本身就是审核意见的证据**：桥在宿主之前就把握手做完了）；
`B2` `actual 'UNKNOWN_OP'` vs `expected -32601`；
`C1` codex 半段 `{+optionId:'grant-once', +outcome:'selected'} / -outcome:'cancelled'`。
其中 `C1` 的要求（"所有品牌一致返回 cancelled"）**已撤回**：一致的拒绝仍然是插件在做决定，
由 T9 取代。

## 4. 夹具自证（审核意见第 2 条）

两套都要求"成功响应"和"error-only 响应"**各自**能被正确接收、记录、结束，且不留下异步异常。

1. **夹具自身**（`controlled_harness_self_proof.test.mjs`，3 绿）：直接 spawn `controlled_harness.mjs`，
   不经过桥。① 成功答复 → 记录 `reverse-reply` 且回合以 `end_turn` 结束；② error-only 答复 →
   被当作**答复**而非新请求（旧版只在 `result !== undefined` 时才匹配，error-only 帧会被漏掉，已修）；
   ③ 4 个并发请求逆序回答 → 回合**只结算一次**（在最后一个答复之后）。每条都额外断言
   `exit code === 0` 与 `stderr === ""`，即真的没有抛出。
2. **通道层**（`acp_channel_behavior.test.mjs` 新增 3 条，11 绿）：`AsyncFailureRecorder` 在安装时记录
   `process.listenerCount("unhandledRejection")`，settle 后等 30ms 再卸载并断言监听数回到基线；
   ① 自己种一个 `onRejection` + 一个 `onException` 证明记录器会响（反例门）；② 成功回复断言解析值 +
   **只写一帧** + 无遗留；③ error-only 回复断言 `rejects /Internal error: the Agent refused/` + 无遗留。
3. 修 `controlled_harness.mjs` 的同时保留了统一反向请求状态机：`reverse-sent` 记录、`settleIfDone`
   在途计数归零才结算，所以"记下来了但没结束"和"结束了但没记录"两种错都会被上面的断言抓住。

## 5. 反例（每条关键边界都能被证明"会失败"）

| 边界 | 正例 | 反例（种违规必报） |
| --- | --- | --- |
| 运行代码不读 packaging | `runtime/**` + 内核 `src/**` 命中 0（正对照 `scripts/server-round1` 命中，证明扫描有效） | `test_packaging_reference_detector_reports_a_planted_file` |
| 只有测试能读 packaging | AST 证明唯一字面量在 `codex/executable.py::official_script_metadata()`，且无调用点 | `test_packaging_read_detector_reports_a_planted_call` |
| 来源清单不丢失 | 清单 21 条 == 磁盘 21 文件，0 hash 不符 | `test_provenance_check_reports_a_tampered_and_an_unlisted_file` |
| 品牌实现单份 | 跨品牌 0 份逐字节相同（`minimum_lines=5`） | `test_the_copy_detector_reports_a_planted_duplicate` |
| 声明 ↔ 锁 | 6 品牌 0 漂移 | `test_the_lock_drift_detector_reports_a_planted_mismatch` |
| vendor ↔ 声明/锁 | codex/pi 0 漂移 | `test_the_vendor_drift_detector_reports_a_planted_stale_tarball`、`test_the_drift_detectors_report_planted_disagreements` |
| SBOM ↔ 锁闭包 | path/version/integrity 全等 | 同上（种入 stale SBOM 条目） |
| 根 override 形状 | 只有 codex/pi 两处对不依赖的包下 override | `test_the_transitive_override_detector_reports_a_planted_third_one` |
| schema pin 可满足性 | 5 品牌 0 违规，未建模范围报 "not modelled" 不猜 | `test_the_schema_pin_detector_reports_a_planted_unsatisfiable_lock` + `..._accepts_a_range_the_lock_can_satisfy`（防"逢报必绿"）+ 10 例范围模型参数化 |
| override 是原因 | codex 强制 `1.3.0` 满足 `^1.3.0` → 不报 | `test_the_override_detector_reports_a_forced_schema_that_breaks_a_declaration` / `..._accepts_...` / `..._is_quiet_without_an_override` |
| 构建器同界 | 7 个构建器 `32768 / 1 GiB` | `test_the_bound_detector_reports_a_planted_divergent_builder` |
| 真实方法名扫描 | 夹具说的每个方法名都在 Codex 表里 | `test the method-name scan is not a detector that matches nothing`（种 `session/not_a_real_method`） |
| 异步异常记录器 | 监听数回到基线 | 种一个 `unhandledRejection` + 一个 `uncaughtException` |
| 权限决策词汇封闭 | 未知 requestId / 伪造 optionId / 非法 scope 各自被拒 | 端到端基线 #11 三条断言本身即反例 |
| 生命周期清理范围 | 关 A 后 A 进程消失、B 仍在 | `alive(pid)` / `waitGone(pid)` 实测，非声明式 |

## 6. 口径与两处撤回（审核意见第 3、4 条）

### 6.1 相对导入 / 入口消费者复查

`tests/access/`、`tests/install/` 是本轮新目录，移动后 3 个 JS 文件的
`pluginRoot = resolve(dirname, "..")` 少了一层，会把 `third_party/harness_remote/bridge/src/acp-client.js`
解析到插件外。现在三份都是 `"..", ".."`，并且**不是靠读代码确认的**：`acp_channel_behavior` 真的
`import()` 了那个路径，`sidecar_harness.mjs:19-21` 真的把 `runtime/worker-entry.mjs` 和
`tests/access/controlled_harness.mjs` 拉起来跑，路径错就是 32 条基线全红。
Python 侧同样复查过一个 `PLUGIN.parents[2]`（会指到 worktree 上层），改为 `parents[1]`。

### 6.2 动态导入 / 按路径断言 / `__all__`

计数口径：AST 遍历全仓 `import`/`from … import`，按 `level` 解析相对导入，旧名/新名归一。三类引用**不进**该计数：

- `tests/test_core_identity.py:54` 用 `__import__(f"{name}.{dotted}")` 动态导入 20 个模块并要求新旧名同对象（表 †）；
- `tests/test_boundaries.py:26` 按路径文本读 `codex/launch.py` 断言含 `class CodexLaunchSpec`（表 ‡）；
- `real_adapter_protocol.test.mjs` 按目录内容判定，不是 import 关系。

**本轮自查出的新证据，也是撤回的直接理由**：`hermes/__init__.py:3-4` 与 `opencode/__init__.py:7-8`
各把 `__all__` 赋值**两次**，第二次覆盖第一次；被抹掉的第一次里列的 4 个（hermes）/ 3 个（opencode）
名字实测**根本不在该包上**（`hasattr` → `False`，只存在于 `profile.py`/`provider.py`/`profiles.py`）。
即第一行 `__all__` 本来就是坏的，第二行赋值恰好把它挡住了。附带：
`opencode.OpenCodeContinuationV1` 的 `contract_id` 没有注解，所以**不是 dataclass 字段**
（`dataclasses.fields()` 只有 `session_id`），frozen 相等比较不看契约 id。
一个连自身公共面都写错的包，不能支撑"按计数说没人用 → 可删"。故撤回，详述在 `PLAN-ACP-ACCESS.md` §5。

### 6.3 "没丢测试"是怎么核对的

不是数一下条数就下结论。口径：取 `git status --porcelain` 中状态为 `D` 且路径含 `test` 的 35 条，
对每条取其 `basename`，在 `plugins/agent-box-harness/tests/` 下 `find -name <basename>`；
有任何一条找不到就报出来。本轮实测 **0 条无对偶**。这个检查只在仓库工作树上做只读查询，
不跑安装、不改文件。

> 该口径的局限要说清：对偶是**磁盘上的文件**，不是 git 里的历史。实测跟踪状态：
> `git ls-files plugins/agent-box-harness/tests` **只有 3 条**（`conftest.py`、`test_core_boundaries.py`、
> `test_core_identity.py`）——整个 JS 测试树未跟踪；`src/agent_box_harness/**` 跟踪 22 条（合并前的
> Python 包），而 `src/agent_box_harness/runtime/`、`packaging/`、`third_party/` 三条路径各命中 **0 条**。
> 也就是说，被移动的那一半（运行链 + 打包 + 桥 + JS 测试）在 git 里既无旧位置也无新位置，
> 所以"丢了没丢"只能按工作树文件系统判定，不能靠 `git show HEAD:<旧路径>` 复现。
> 这是上一阶段合并留下的未提交状态，本轮不自行提交。

## 7. "桥 100 MB 下载限制"——查无此数（实测更正）

上一版把它写成一条已存在的边界，**更正**：`runtime/`、`bridge/src/`、`packaging/`、`scripts/` 全量搜
`100 * 1024` / `100_000_000` / `100MB` / `100 MB` **零命中**。真实存在的首次使用下载约束是**时间形**：

| 常量 | 位置 | 值 |
| --- | --- | --- |
| `START_TIMEOUT_MS` | `acp-client.js:6`（用于 `:108 start()`；注释即"npx 启动的 adapter 首次使用要自己下载"） | `90_000` |
| `REQUEST_TIMEOUT_MS` | `acp-client.js:7` | `30_000` |
| `DEFAULT_START_TIMEOUT_MS` | `opencode-host.js:4` | `15_000` |
| `DEFAULT_MAX_ENTRIES` | `transcript-cache.js:17` | `64`（条数，非字节） |
| `MAX_ENTRIES` / `MAX_BYTES` | 7 个构建器 | `32768` / `1 GiB`（构建闭包，非下载） |

本轮做法：不发明一个 100 MB 去"满足"这条要求，而是把**存在的数**钉成回归（`START_TIMEOUT_MS == 90_000`；
七构建器同界；运行链内 `MAX_BYTES` 命中 0，`MAX_ENTRIES` 命中只允许是 transcript-cache 那一条）。
若 I 认为**应当新增**字节上限，那是实施阶段的设计决定，位置在 `acp-client.js` 的下载路径。

## 8. 预存在失败（单列，未篡改、未计入本轮引入）

| 用例 | 失败内容 | 与本轮关系 |
| --- | --- | --- |
| `tests/test_skill_projection.py::test_all_five_registry_targets_are_lossless_and_read_only` | 期望 `/runtime/home/skills/review`，实际 `/runtime/home/.claude/skills/review` | 上一合并轮已在 `CONSOLIDATION.md` 记录同一项；从 `git archive e996e9d2` 复跑也是同 1 项失败。未放宽断言 |
| `scripts/server-round1/model-validation-42d.test.mjs` | 4 tests：2 pass / **2 fail**（pi、hermes preparation is bounded and secret-free，`8192 !== 64`） | 脚本层既有失败，本轮只读未触碰 |
| `scripts/server-round1/build-opencode-authorization.test.mjs` | 9 tests：7 pass / **1 fail**（`OPENCODE_SOURCE_SYMLINK` vs 期望 `..._NOT_RESOLVED`）/ 1 skip（本机缺 `~/.npm-global/bin/opencode`） | 同上 |

后两条的路径是**仓库根**相对（`cd <repo root> && node --test scripts/server-round1/...`），不在本插件内，
本轮只复跑确认失败数，未读改其实现；第一项才是本插件的。三条今日重跑实测与表格一致。

## 9. 未覆盖（明确承认的缺口）

1. **OpenCode / Qwen Code / Hermes 没有真实 adapter 协议测试**——不是"简单版"，是**没有**。
   磁盘事实：无 `packaging/opencode`、无 `packaging/hermes`（Hermes 是 Python 发行，`hermes_cli`/`acp`
   本机不可导入）、qwen 根只装 CLI 且锁内 ACP 包数 0、claude 声明并锁定 `0.77.0` 但无 vendor 也无 `node_modules`。
   要真测需要打包线先 vendor 进来（或授权联网取包）。
2. **未跑真实 `npm ci`**：只核对清单/锁/vendor/SBOM 互相一致，未真正离线出包。
3. **真实 Agent 进程、真实模型请求、凭据读取、既有服务启停**按约束一律不测。
4. **Windows 分支**未覆盖（`profile_extensions.mjs` 有 `process.platform === "win32"` 路径，本机 Linux）。
5. **信封全 op 矩阵**未穷举；**多连接高并发压力**未测（只证 `T7` 的 5 请求与"关 A 不影响 B"）。
6. **`harnesses.toml` 逐字段消费者归属**未测（423 行声明，删字段即改 schema 契约）。
7. **`T9` 只测了两个代表品牌**（`dsh` 与 `codex`，即两张策略表各一个），9 个注册 id 未逐一跑；
   理由是同一受控夹具下策略只由 `permissionMode` 决定，但这仍是**推断**，未逐条实测。
8. **新 transport 的正向路径本身未被任何代码证明可行**：入口不存在，所以 T1–T10 今天只证明
   "缺什么"，不证明"照 §3.3 改完就能通"。甲案/乙案的实际可行性要到实施轮才第一次被跑到。
9. **raw 转发的反向压力**未测：客户端在 `connect` 之后发畸形帧、超大帧、非 JSON 行会怎样，
   本轮不发明预期行为（那属于实施细节决定），因此没有对应用例。

## 10. 请求

分别批准（可只批一份、可只批子集）：

- **`PLAN-ACP-ACCESS.md` §7 的 A-1…A-5**：A-1 是"客户端自己发 `initialize`/`session/new`/`session/prompt`、
  双向只有帧、未回答就是未回答"的验收口径（10 条目标测试）；**A-2 本轮改为二选一**——
  甲案改 `acp-client.js` 三处 opt-in 并同步 `SOURCE.json`/`PATCHES.md`，乙案插件自带最小 transport、
  零上游改动，本轮不自选；A-3/A-4 是两项确认（不删、归类更正）；**A-5 已撤回上一版"不改 `third_party`"
  那句**（它与"消除桥内代答"矛盾），只保留不 push / 不合并 / 不为过测试放宽断言。
- **`PLAN-OPTIONAL-INSTALL.md` §7 的 B-1…B-6**：B-3 需要 I 就 pi 的 `overrides` 缺陷选一条路
  （改 override / 改 pi pin / 接受并记录不匹配），本轮不自行选。**本轮按指示未扩展安装/打包/删除任务，
  方案 B 与 `tests/install/**` 零改动。**

两份都**不申请删除模块**，都不动 Server 与前端；§9 的第 1 条（真实 adapter 取包）若要做，请单独授权。
批准后按 `PLAN-ACP-ACCESS.md` §3.3（甲或乙）→ 实施 → 让 §3.2 那 10 条变绿 → 基线 32 条与旧链 88 条保持全绿。

> **第四轮对最后半句的更正**：裁定取消了"基线与旧链保持全绿"这一收尾条件——旧链不保留，
> 其专属用例随链退役（逐例替代见 `tests/RETIRED.md`）。实际选择是 §3.3 的**甲案**
> （给 `acp-client.js` 加 `transportOnly`，最小改动申报与来源记录在 `PATCHES.md` §8）。

## 11. 第四轮（实施轮）实测结果

命令与第三轮同形，只是被删的套件不再存在、目标套件应当全绿。**以下均为本日重跑。**

```
cd plugins/agent-box-harness
node --test tests/access/access_entry_behavior.test.mjs   # 8 tests: 8 pass / 0 fail  ← 新增 E1–E8
node --test tests/access/acp_passthrough_target.test.mjs  # 10 tests: 10 pass / 0 fail ← §3.2 的 10 条转绿
node --test tests/access/acp_channel_behavior.test.mjs        # 11 pass（含 3 条夹具自证）
node --test tests/access/controlled_harness_self_proof.test.mjs   # 3 pass
node --test tests/access/real_adapter_protocol.test.mjs       # 6 pass
node --test tests/capability_claims.test.mjs tests/harness_remote/frame_buffer_lifecycle.test.mjs  # 21 pass
node --test tests/opencode_*.test.mjs                         # 32 pass / 0 fail
# 上述 7 + 6 个文件一次跑：59 pass / 0 fail 与 32 pass / 0 fail

source /tmp/hd002-tidy-env/bin/activate   # 每个 Bash 调用都要重新 source
python -m pytest tests -q                                       # 315 pass / 3 fail / 3 skipped
python -m pytest tests/access/test_acp_boundaries.py tests/test_core_boundaries.py \
  tests/test_pi_production_template.py tests/install/test_packaging_boundaries.py -q   # 52 pass
```

**引入的意外失败：0。** `pytest tests -q` 的 `315/3/3` 与 §2.2 第三轮基线**逐数相同**：那 3 条就是
§8 单列的预存在失败（`test_skill_projection` 1 条 + `test_acp_schema_drift_target` 2 条按设计红），
本轮未放宽任何断言、未跳过任何用例。

因删除 `worker-entry.mjs` 与 `transcript-cache.js` 而必须改写的 4 个 Python 断言（属"安全 / 打包
检测器"，按裁定保留、重定向到新对象，不随旧链退役）：

| 位置 | 原断言 | 第四轮 |
| --- | --- | --- |
| `tests/access/test_acp_boundaries.py` | 读 `worker-entry.mjs` 找 `PROVENANCE_MISMATCH` / `verifyProvenance()` | 改读 `access-entry.mjs`，并**加**一条顺序断言：校验必须发生在 stdin 打开之前 |
| `tests/test_core_boundaries.py:49` | `runtime/worker-entry.mjs` 存在 | `runtime/access-entry.mjs` 存在 |
| `tests/test_pi_production_template.py` | 信封两条路由上每个带 model 的 op 都翻译（3+2 次 `resolveNativeModel`） | 反转为"入口不翻译 model、不出现任何品牌名"（`test_the_access_entry_translates_no_model_and_names_no_brand`）；别名表与本品牌模板的 parity 用例原样保留 |
| `tests/install/test_packaging_boundaries.py:583` | 运行链内 `MAX_ENTRIES` 命中只允许是 transcript-cache | 缓存已随链删除，改为断言命中**为 0**（避免 `all([])` 空转通过） |

§9 承认的缺口中，本轮消掉 3 条：第 8 条（"新 transport 的正向路径未被证明可行"）现由 T1–T10 +
E1–E8 实跑消解；第 9 条（raw 转发压力）由 `transport_malformed` 事件 + `frame_buffer_lifecycle`
部分覆盖，仍未测超大帧；第 5 条（多连接并发）由 E7 覆盖到"两条连接互不释放对方进程"，5 请求级
并发仍只有 `T7`。**仍缺**：第 1 条（OpenCode / Hermes / Qwen 无真实 adapter 协议测试）、第 2 条
（未跑真实 `npm ci`）、第 3 条（真实 Agent / 模型 / 凭据 / 服务，按约束不测）、第 4 条（Windows 分支）、
第 7 条（9 品牌逐一跑 `T9`）。

§3.1 里"往返关闭时答案来自品牌 `permissionMode`"这一条按裁定**不再成立也不再被断言**：
新入口没有 `permissionRoundTrip` 旋钮，`connect` 带它会被 `ACP_CONNECT_FIELD_RETIRED` 按名拒绝（E3），
未应答的请求保持未应答（T9）。该段文字作为第三轮的测量史保留，替代关系以 `tests/RETIRED.md` §1-5 为准。

## 12. 交付入口与两处证据文本订正（同日收尾）

交付报告：**`DELIVERY.md`**（新目录树、公开接口与使用示例、移除清单与恢复位置、
包外旧→新对照表、待裁定事项、复核命令）。`REMOVALS.md` 里"旧→新对照表"的指向已改到
`DELIVERY.md` §5（原先写的是 `PLAN-ACP-ACCESS.md` §迁移，那一节并不存在）。

收尾时另订正了两处**把退役链路描述成存活**的证据文本，两处都不改任何能力结论：

1. `tests/test_capability_declarations.py` pi `attach` 的 `evidence`：点名那条投递链路是
   已退役的信封分发，并说明新入口只逐字转发、不构造附件（结论仍 `not-observed`）。
   实测本文件 **53 passed**。该表的 `evidence` 只要求非空字符串，`NOT_OBSERVED` 一栏不参与
   与 TOML / JS 投影 / 黄金矩阵的等值比对。
2. `src/agent_box_harness/harnesses.toml` pi 段**注释块**追加 3 行同样表述并指向 `REMOVALS.md`。
   纯注释：`tomllib` 不解析，`capabilities` 集合逐字未动 —— 裁定"不要扩展 Profile、
   Provider/model 配置"未被触碰。改后 `pytest tests -q` 仍是 **315 / 3 / 3**。

## 13. 第 4 轮返修：四项实现漏洞的反例与咬合证据

审核否决了上一版实施（四项）。本轮只修这四项，不重做架构、不恢复旧链、不扩功能。
每项都补了反例，并且**用变异测试证明反例会失败** —— 把修复退回原状，看哪个用例红。

### 13.1 四项修复与对应反例

| # | 漏洞 | 修复 | 反例 |
| --- | --- | --- | --- |
| 1 | `close` 只发出终止信号就报 `released:true` 并丢掉进程身份 | 单 pid 版 `releaseOwnedProcess()`（第 5 轮已改名为 `releaseProcessTree` 并扩到整棵树，见 §14）：SIGTERM → `RELEASE_GRACE_MS`(2s) → SIGKILL → `RELEASE_FORCE_MS`(2s)，用 `kill(pid,0)` 轮询；`EPERM` 算活、`ESRCH` 算没。未确认就 `released:false` 且保留 `processId`/句柄。pid 由入口侧 `ownedPid` 独立记录（桥 `close()` 会清 `#child`，事后 `processID` 变 `undefined`） | **E9**（真实进程忽略 SIGTERM）、**E9b**（注入信号：永不确认 ⇒ `released:false` + `["SIGTERM","SIGKILL"]` 都发过；已消失的 pid ⇒ 不再补信号） |
| 2 | 并发 `connect` 可起两份进程 | `connect()` 在**第一个 await 之前**同步占 `opening`（第 221 行检查 ⇒ 第 281 行占用，中间只有同步校验与 `readFileSync`）；`close`/stdin EOF 先 `settleOpening()` 再释放 `owned` 全集 | **E10**（connect/connect）、**E11**（connect/close）、**E12**（启动中 stdin EOF） |
| 3 | 控制面判别可截获带 `op` 的 ACP 扩展帧 | `isControlRequest`：`typeof op === "string"` **且** 不含 `jsonrpc/method/result/error` 任一。规则只会把消息从控制面挪到数据面，不会反向 | **E13**（`session/prompt` 帧带 `op`+`tag` 扩展字段） |
| 4 | 文档结论错："`OpenCode` 不说 ACP" | 更正并撤回"Server 保留 non-ACP 投影旁路"的建议（官方 `opencode acp` 经 stdio 提供 ACP）。本轮不扩品牌范围、不开旁路、不改代码 | 文档订正：`REMOVALS.md` §4/裁定第 1 条、`DELIVERY.md` §1/§6、E6 注释（改述为"注册范围"断言） |

### 13.2 变异测试（插件外一次性副本 `/tmp/hd002-mut-*`，跑完即删）

| 变异（把修复退回原状） | 结果 |
| --- | --- |
| A 去掉 `isControlRequest` 里的 JSON-RPC 优先条款 | **只有 E13 红**（13 pass / 1 fail）；`acp_passthrough_target` T1–T10 仍 **10 pass / 0 fail** ⇒ 新规则没有把透传口径带偏 |
| B `close` 发出 SIGTERM 后即报 `released:true`（不确认） | **E9 红**（13 pass / 1 fail） |
| C 去掉建立预约（`opening` 检查与占用一并拆掉） | **E10、E11 红**（12 pass / 2 fail） |
| D stdin EOF 不再释放 `owned` | **E12 红**（13 pass / 1 fail） |

四个漏洞各有一个会红的反例兜住，且 A 的对照组证明透传目标测试不是靠新判别条款才绿的。

### 13.3 真实进程清理证据（OS 侧测量，非入口自述）

驱动真实 `runtime/access-entry.mjs` 子进程，用 `kill(pid,0)` 与 `/proc` 扫描（命令行含夹具路径
且 `cwd` 属于本次临时工程目录）取证：

```text
item1 忽略 SIGTERM 的 Harness : pid=164182 close_ms=2045 released=true signalUsed=SIGKILL
                               收到回复时 alive=false · 夹具自记 sigterm-ignored · 残留=0
item1 普通 Harness            : pid=164214 released=true signalUsed=SIGTERM
                               收到回复时 alive=false · 残留=0
item2 两个 connect 并发       : 第一个 ok · 第二个 ACP_CONNECT_IN_PROGRESS
                               实际起过的 Harness 进程数 = 1 · close 后残留 = 0
item2 启动中 stdin EOF        : 入口退出码 0（清理完成后才退）· 残留 = 0
item3 带 op 扩展字段的 ACP 帧 : Agent 自己回了 stopReason=end_turn · 没有任何
                               `{ok:false}` 控制回复占用该 id · Agent 侧记录到
                               extensionKeys=["op","tag"]、值原样 `op:"status"`/`tag:"keepme"`
                               · 同一条连接上 `{op:"status"}` 仍是控制面
VERDICT false-releases-or-leftovers: 0
```

夹具自己那一份反证也在：`controlled_harness.mjs` 的 `exec` 记录里带 `sigterm`/`holdOpen`，
`sigterm-ignored` 是一条独立记录 —— 也就是说"升级needed"由进程本身作证，不是断言者的说法。

**整目录残留核对**：`tests/access/` 全量前后各扫一次 —— before `0` 个 `controlled_harness.mjs`
进程、44/44 绿、after `0` 个。

### 13.4 本轮诚实的限制（不假装测过）

1. **E9 的时序前提**：若在 Harness 装好 SIGTERM 陷阱**之前**就 `close`，它真的会被 SIGTERM 打死，
   此时 `signalUsed:"SIGTERM"` 是正确回执而不是 bug。E9/证据脚本都先跑一次 `initialize` 往返，
   确保陷阱已装；我第一版探针正因为没跑往返而读出 `"SIGTERM"`，据此更正而非据此报喜。
2. **E11 的"建立中"窗口在本机不稳定**：变异 C 下 E10 必红，E11 偶红（建立是否在途取决于两次
   写入是否落在同一批微任务里）。把 `opening` 预约钉死的是 **E10**，E11 是补充口径。
3. **EOF 收尾里"预约未落连接"的孤儿分支未被真实进程走过**：E12 变异 D 会红，但它走的是
   "已建立连接后 EOF"这一支；`settleOpening()` 在 EOF 路径的必要性由代码同步性推得，未独立实测。
4. **只回收本入口 `spawn` 的那一个 pid**：无进程组/`detached` 清理，Harness 自生的子孙不在承诺内
   （见 `DELIVERY.md` §6-3）。真实 adapter 是否留孤儿子孙未取证 —— 本轮没有执行过任何真实
   adapter 进程（`real_adapter_protocol.test.mjs` 只读包内 tgz 的协议表）。
   *（本条是第 4 轮的记录，其限制已在第 5 轮实现掉：见 §14 与 `DELIVERY.md` §10。"真实 adapter 未取证"
   这半句仍然成立。）*
5. **`released:false` 无法用真实进程构造**（没有进程扛得住 SIGKILL），故由 E9b 的注入信号路径直接
   测量；E9 测量的是真实进程下入口如何处理"确认得到的释放"。两者合起来才是这一条的完整证据。

## 14. 第 5 轮返修：关闭生命周期（存活探测 + 进程树所有权）

裁定只圈了关闭生命周期两件事，本轮没有越界：并发 `connect`（E10）、ACP 扩展帧透传（E13）、
双向字节透明通道一律原样保留，只做加法。

### 14.1 两项修复与对应反例

| # | 问题 | 现在的实现 | 反例 |
| --- | --- | --- | --- |
| ① | 存活探测把"OS 抛了个错"当成退出，就会假报 `released` | `probeProcess` 把答案分成三种，且**不合并**：`ESRCH`→`gone`（唯一的死亡证明）、`EPERM`→`alive`（那是别人的 pid）、**其它任何码**（`EACCES`/`EINVAL`/`ENOENT`/`UNKNOWN`）→`unconfirmed`。`released` 要求 `survivors` 与 `unconfirmed` **同时为空**，即树里每个成员都被逐个答复 `ESRCH` | **E14**：三种码各跑一遍 ⇒ `released:false`、`processId` 保留、`tree.unconfirmed` 逐字等于 `[{pid, code}]`、且**不混进** `survivors`（"没证明"和"还活着"是两件事，混了就是在替 OS 编答案）；再补一棵"桥真死了 + 子进程探测无解"的混合树，`members.state` 必须是 `["gone","unconfirmed"]` |
| ② | 关闭只回收入口 `spawn` 的那一个 pid，桥自己启动的 Agent 活着继续服务 | 启动侧 `access-entry.mjs`：POSIX 上 `spawn(…, {detached:true})`，这次启动自成一个进程组（Windows 保留被复用客户端的 `.cmd` 特判，不宣称组所有权）。回收侧 `releaseProcessTree`：成员 = 组号 `== rootPid` 的全部进程 ∪ 沿 `/proc/<pid>/stat` PPid 走下来的全部子孙；组内成员**只**由 `kill(-rootPid, …)` 达到，组外逐个发；每 20ms 重新观察并补发，SIGTERM 2s → SIGKILL 2s。`close()` 无条件跑这一遍，不再拿 `client.processID === undefined` 当死亡证明 | **E16**（两个子进程：回执逐成员 `gone`、`survivors:[]`、事后 `/proc` 一个不剩）· **E17**（桥 120ms 后自尽、子进程被领养仍在跑：`released:true` 仍逐个成立）· **E18**（子进程 `setsid` 逃出组，只能靠 PPid 血缘找回）· **E19**（同命令行、同 `cwd` 的诱饵进程：不在 `tree.members` 里，`close` 之后仍存活）· **E15**（`discover` 返回 `null` ⇒ `tree.available:false`，靶子集合恰为 `[child.pid]`，**不盲发组信号**）· **E9b** 重写为树 API（组内成员的靶子集合恰为 `[-4242]`） |

新用例一律走真实生产入口（`runtime/access-entry.mjs` 子进程），夹具子进程在**自己的 argv** 里带标记
（`tests/access/fixture_child_marker.mjs`），断言由 `/proc` 回读，不采信夹具自述 —— 恰恰是"父进程先退出"
那一支，进程可能还没来得及写任何记录就被打死。

### 14.2 变异测试（插件外一次性副本 `/tmp/mut`，跑完即删）

| 变异（把修复退回原状） | 变红的用例 |
| --- | --- |
| A 未知错误码折进 `gone` | **E14**（仅此一条） |
| B 恢复 `client.processID === undefined ⇒ released:true` 捷径 | **E17**（仅此一条） |
| C 取消树发现，只认根 pid（第 4 轮形状） | **E16 E17 E18 E19** |
| D 保留组身份、删掉 PPid 血缘 | **E18**（仅此一条） |
| E 启动不加 `detached` | **E17**（仅此一条） |
| F 成员身份改成"按 `cwd` 相同即算我的" | **E19** 与 **E7**（邻居连接被误杀） |
| G 删掉组信号且组内成员不逐个发 | 12 条（回收整体失效） |

七处变异全部命中目标用例，没有一处是靠"顺带红别的"才成立；C/E/G 是机制性退化，波及面宽属预期。

### 14.3 真实进程清理证据（OS 侧测量，非入口自述）

```text
E16 桥＋两个子进程   root=219869 children=[219878,219879] released=true signalUsed=SIGTERM
                     members 三项全 gone（两项 group=219869）survivors=[] unconfirmed=[]
                     close 后本临时目录 fixture 子进程=0 controlled_harness=0
E17 桥先退出         root=219904 children=[219911,219912]（关之前逐个 alive）
                     released=true survivors=[] · 事后 fixtureChildrenIn(project)=[] · 残留=0
E18 子进程逃出组     root=219933 children=[219940]（其 group=219940 ≠ rootPid）
                     released=true · 该成员出现在 members 里且 gone
E19 诱饵进程         同命令行同 cwd 的无关进程：不在 members、不在回收集、close 后仍存活
全机 /proc 夹具标记进程计数：本轮三次启动净新增 0
（扫描命令自身的 argv 会匹配到它自己 —— 实测到的"1～2 个"逐个核对 cmdline 后确认都是这种自匹配，
  已在核对时排除，不是残留进程。
  另需记录一次真实泄漏：本轮第一次跑红时 `withSidecar` 的收尾清理自己抛了 ReferenceError，
  于是没清成，留下 5 个夹具子进程 + 1 个桥（pid 185158/185166/185169/185199/185200/185223）。
  逐个核对 cmdline + cwd 确认都属于那次 15:52 的失败运行后按 pid 停掉，连同其临时目录；
  期间 `/tmp/mut` 变异副本另泄漏过 2 个桥进程（195639/205970，其 cwd 已随副本删除），同样按 pid 停掉。
  全程未按名字/前缀批量 kill，未触碰任何既有服务。这条泄漏本身也是 E19 那套"按 /proc 回读"
  的存在理由：红掉的用例不会自述自己泄漏了什么。）
```

### 14.4 本轮诚实的限制（不假装测过）

1. **`detached` 只在 POSIX 生效。** 本机是 Linux，Windows 那一支（不宣称组所有权、`tree` 只覆盖根进程）
   在本轮**没有实测过**，它是代码里的分支和一个 `if`，不是一个观察到的事实。
2. **真实品牌未取证。** 三条场景全是受控夹具（`node -e setInterval`）。真实 adapter 是否会留孤儿子孙、
   它启动的子进程是否落在同一个组里，仍未测 —— 本轮没有执行过任何真实 adapter 进程。
3. **E17 的"父先退"靠一个 120ms 定时器**。断言前 `waitFor` 会确认 root 已死、children 仍活，
   所以它测的是"已观测到的领养状态"，不是任意时刻的孤儿竞态；`waitFor` 超时会明确报在等哪一件事。
4. **组信号与 pid 回收之间没有原子性。** 回收是"观察→发信号→再观察"的循环；一个成员如果在两次观察之间
   自己 fork 出新子孙，那一轮不会被记为成员，但它会落在同一个进程组里，因此下一轮 `observe()` 就把它算进去
   （这是选组身份而非"只信 PPid"的原因之一）。真正没有兜住的是**逃出组、又在下一次观察之前 fork** 的形状，
   本轮没有构造这种用例。
5. **`EPERM` 归入 `alive` 是一个口径选择**，不是 OS 事实：它只证明"这个 pid 存在且不是我们的"。
   本轮把它算作失败（保守方向：宁可 `released:false` 并保留身份），但报告里 `state` 与 `code` 分列，
   没有把 `EPERM` 写成"这个进程还在服务"。
6. **`unconfirmed` 不重试到无限**。它同样受 SIGTERM/SIGKILL 两个窗口约束，超窗即 `released:false` 返回；
   调用方要不要再试一次，本轮不在入口里替它决定（`owned` 集合仍保留该句柄，`close` 可以再调）。

## 15. 第 6 轮返修：回收算法自己的三处边界（同日）

审阅在第 5 轮 50/50 全绿之后又往下查了一层，指出三处**测试没覆盖到的实际漏洞**：子孙遍历把
"已收集成员"当"已遍历节点"用；读不到进程表时根 pid 消失仍被当成整棵树释放成功；以及注释里
"pid 被复用后会 `EPERM` 或存活"这句不成立的话。本轮只做这三件事，未动架构、未扩业务范围。

### 15.1 三项修复与对应反例

| # | 缺陷（审阅原文要点） | 修复 | 反例 |
| --- | --- | --- | --- |
| ① | 桥 A └─ 同组子 B └─ 逃组孙 C：`discoverProcessTree` 只返回 A、B | 队列种子 = 根 **加** 全部按组号收来的成员；另立 `expanded` 集合，**成员去重与遍历去重分开**，B 入了成员也照样下探 | **E20**（三层真实进程）· **E23**（桥先退出 + 逃组孙，两条收集规则缺一不可） |
| ② | `discover → null` 且根已消失 ⇒ `released:true / available:false` | 引入 `claim` 与回执 `tree.scope` / `tree.reason`，和 `spawn` 的 `detached` 共用一个 `PROCESS_GROUP_OWNERSHIP`：声称 `tree` 却读不到表 ⇒ `released:false`；只声称 `root-only` 才允许 `true`，`scope` 留在回执里 | **E15**（同一次运行两种声称，各自结局；原断言一字未放宽） |
| ③ | 个体 pid 回收只存数字，"复用后会 `EPERM`"的注释不成立 | 身份 = `spawn` 当场记的 `(pid, /proc 启动时间)`，记一次不改写；数字还在但启动时间已换的成员**一个信号都不发**，单列 `identityChanged`；组信号也要有一个身份核得上、仍在组里的证人 | **E21**（数字被重新发放：注入身份；同一真实进程的对照组证明"不否决就会杀掉它"）· **E22**（组信号需要证人，同时逐个回收不受影响） |
| — | 那段错注释 | `discoverProcessTree` 的文档删掉"复用后会 `EPERM` 或存活"，换成"组号/身份各管什么"；`readProcessIdentity` 写明 `null` 只是"没有反证"，永远不是确认 | 文本改动，由 §15.2 的 M3 保证行为侧不退 |

### 15.2 变异测试（插件目录内就地改生产文件，先留字节级备份，跑完 `diff` 确认还原）

> **这一条做法已在第 7 轮作废**：共享工作树里还有后端执行者，生产文件即使最终还原，中途也可能被别的
> 会话读到或用于测试。第 7 轮起变异只在插件目录外的副本里跑（见 §16.2）。下表结论不受影响。

| 变异 | 退回的实现 | 变红的用例 |
| --- | --- | --- |
| M1 | 完整退回第 5 轮遍历（只从根起步 + 已在成员里就跳过） | **E20 E23** |
| M1b | 只退回"已在成员里就不下探"（队列仍含全部成员） | **无 —— 该形状下与修复后等价，不是独立缺陷**，如实记录，不充当咬合证据 |
| M1c | 只退回"队列从根起步"（成员仍继续下探） | **E23**（仅此一条） |
| M2 | 表读不到时仍声称整棵树成功 | **E15** |
| M3 | 去掉身份否决 | **E21 E22** |
| M4 | 组信号不看身份 | **E22** |
| M5 | `close()` 不再传 spawn 当场那份身份 | **无 —— 本机第一次观察也能读到同一身份，无可观测差异**；这一条是纵深防御，不假称有用例钉住 |

M1 与 M1b/M1c 的差本身就是结论：**两处去重混用**才是缺陷，任何单独一处都不是；用例因此必须同时
覆盖"成员由组号领到"和"父链路已经断了"两种形状（E20 + E23），少一条就漏掉一半。

### 15.3 真实进程证据（OS 侧测量）

E20 / E23 / S1a / S1b 的原始读数、`/proc` 前后计数与逐项核对记在 `DELIVERY.md` §11.1，此处不重复。
关键三行：E20 的孙进程 `pgrp` 不等于根 pid（组信号打不到它）却出现在 `tree.members` 里且 `gone`；
E23 里根已死、孤儿的 `ppid` 已变成 4567（被领养）而 `pgrp` 仍是根 pid；S1a 对身份不符的真实进程
`发出的信号=[]` 且该进程仍存活，S1b 记录同一进程的真实身份后 `SIGTERM` **成功杀掉它**。

### 15.4 本轮仍然没做的事

1. **PID 重新发放没有被真实制造**：内核不会按需把某个号再发给新进程，所以"身份已变"靠注入；
   否决的效果与"不否决会误杀"是真实进程实测（S1a/S1b）。
2. **`identityChanged` 与 `released:true` 同时出现是设计**：它声称的是"当初记下那个进程已没了"
   （pid 不会在持有者活着时被重发），不是"这个数字上的进程已没了"。后者故意不声称、也故意不动手。
3. **Windows / 无 `/proc` 的 Linux 两条分支未实测**；后者现在会稳定回 `released:false` + `reason`，
   是本轮特意换来的保守口径，代价（句柄与管道留着等一次能读表的回收）写在 `DELIVERY.md` §11.4。
4. **真实品牌进程仍未执行过**，与第 5 轮同一条限制。

## 16. 第 7 轮返修：身份核对的"未知即放行"（同日）

审阅结论：54/54 独立复跑绿，第 6 轮 ①② 已修，③ 里剩一处 —— `replaced(pid)` 在读不到当前身份时
返回 `false`，组信号又用 `!replaced(pid)` 找证人，于是**"核不了身份"被读成"身份核上了"**；个体 pid
分支同病。审阅自己用生产函数注入"当前身份不可读"，记录到两次组信号（`SIGTERM` + `SIGKILL`）。
本轮只补这一小段，未动架构、未扩业务范围。

### 16.1 修复与反例

| 缺陷 | 修复 | 反例 |
| --- | --- | --- |
| 身份判断是布尔，"读不到"落在安全的那一侧 | `identityState` 三态 `matched / changed / unknown`，另设 `unavailable` 表示"这台机器压根不记身份"（与"记了但核不了"是两件事）；**只有 `matched` 许可破坏性信号** | **E24**：注入"身份读不到" ⇒ 一个信号都没发、`unconfirmed=[{code:"IDENTITY_UNKNOWN"}]`、`released:false`；同例第二段证明 `ESRCH` 仍算确认退出（这条口子不新铺用例就会悄悄变成"永远不确认"） |
| 组证人用历史组号 + `!replaced()` | 证人必须**当前表里组号仍等于根 pid**且**此刻身份 `matched`**；观察记录拆成 `seen`（认领的是什么）与 `current`（现在 OS 怎么说），后者每次 `observe()` 重读 | **E25**：成员先被按组号认领、随后 `setsid` 离组 ⇒ 组号一次都没被瞄准，而它本人照旧被逐个回收 |
| 个体 pid 分支同样把"未知"当"没变" | `unknown` 短路成 `unverified`：不发信号、不轮询、进 `unconfirmed`，`released:false` 且句柄与 `processId` 保留（`close` 可再试） | **E24** 第一段 + §16.2 的 R7-D |
| 探活与读 `/proc` 之间的退出 race 会被误报成"没人确认的释放" | `check==="unknown"` 时重探一次，`ESRCH` 就落成 `gone` | 真实进程侧见 `DELIVERY.md` §12.5 A/B 段 |
| 回执把"认领时的组"和"现在的组"混成一格 | `members[]` 增 `currentGroup / code / check / identity`，`identityChanged` 改按核对结果列（与 `state:"gone"` 可以并存） | E25 断言两格分列 |

`classify` 的顺序最终是 **`ESRCH` → 身份 `changed` → 身份 `unknown` → 探测答出的怪异错误码 → 存活者**，
而不是"先问 OS 再问身份"。第一版确实按后者写过，于是一个"身份核不上 + 探测 `EACCES`"的成员虽然被
判成不确认，却仍落进"没结算就补发信号"那一支 —— 正是本轮要关的那类洞被自己的顺序从旁边又开了回去。
身份核对因此必须排在探活的回答之前：核不上身份就没有发信号的许可，OS 答成什么错误码都不改变这件事。
第 6 轮 E14 的既有口径（怪异错误码不等于死亡、且照旧补发尝试）不受影响，因为那一例现在补了身份证人，
走得还是同一格。E24 第三段专钉这个顺序，变异 R7-E 只把它退回去就红。

### 16.2 咬合证据（只在插件目录外的一次性副本 `/tmp/r7mut/plugin3` 跑）

本轮改掉了第 6 轮"就地改生产文件"的做法：整份 `cp -a` 到 `/tmp`，变异脚本只写副本，主树的
`runtime/access-transport.mjs` 全程未被写过；跑完把主树文件与副本的原始备份 `diff`，输出
`SHARED-TREE-UNCHANGED-BY-MUTATION`。基线在副本里 56/56 绿，每条变异跑完即还原。

**一次需要披露的跑错**：第一轮电池里 `sed -i` 与它依赖的 `cp` 串在同一个 `&&`，`cp` 失败后 `sed`
没执行，那一轮因此静默打在旧副本 `/tmp/r7mut/plugin2` 上，R7-E 报成 GREEN。修好路径后先把
`plugin3` 的模块与测试文件和主树 `diff` 证明逐字节相同，再整轮重跑；下表是重跑结果。这条记录同时
说明"副本脚本自己也要被核对"，不能只看它自称在副本上跑。

| 变异 | 变红的用例（各只打中自己那一条） |
| --- | --- |
| R7-A 读不到身份当成 `matched`（**审阅指出的洞本身**） | **E24** |
| R7-B 证人看历史组号而非当前组号 | **E25** |
| R7-C 证人只看当前在不在组里、不看身份（= 第 6 轮 M4 重跑） | **E22** |
| R7-D `unknown` 不短路，照旧被发信号 | **E24** |
| R7-E 怪异错误码排在身份核对之前（§16.1 那个自己发现的顺序缺陷） | **E24** |
| 第 6 轮 M3 / M2 / M1 / M1c 重跑 | **E21 E22** / **E15** / **E20 E23** / **E23** |
| 第 6 轮 M1b、M5 重跑 | **仍为无**：两条与修复后等价或本机无可观测差异，照旧只作纵深防御记录，不充当咬合证据 |

### 16.3 夹具改动的披露（没有一条断言被放宽）

`tests/access/` 由 54 → 56。三态规则生效后，"注入一个不存在的 pid"这类夹具若不补身份证人就会掉进
`unknown`、走不到它本来要测的分支，因此：E9b 补 `identity`+`identify`（它测 `EPERM` 杀不掉），
E14 第一段（`EACCES`/`EINVAL`/`ENOENT`）同样补 `identity`+`identify`（它测"怪异错误码不等于死亡、
且照旧补发尝试"，没有证人就压根走不到补发那一步），E15 两段各补 `rootIdentity`（真实启动时间由测试
自己读 `/proc`，不复用被测模块）。**三条用例的原有断言一句未改**；E14 第二段 `mixed` 只断言回执里
`state` 答了什么、不断言发没发信号，身份未知与它无关，因此未改；E21 / E22 未动（第 6 轮就已有身份）。
明细表在 `DELIVERY.md` §12.3。`README.md` 的 E 例地图与 `DELIVERY.md` §2/§12 同步。

真实 OS 侧读数（真实身份、真实 `setsid` 改组、真实进程在"核不上身份"时一个信号都没收到）记在
`DELIVERY.md` §12.5，此处不重复。

### 16.4 本轮仍然没做的事

1. **子孙的身份是"关闭时第一次读到"而非"spawn 当场"**：一个在关闭之前就已换手的子孙号本机测不出来，
   这条与第 6 轮同源，本轮没有假称解决。
2. **PID 重新发放未被真实制造**，注入承担规则本身，真实进程承担"不否决就会杀掉它"的效果。
3. **`unavailable` 分支（Windows / 无身份来源）未实测**，只有代码路径可查。
4. **真实品牌进程仍未执行过**，与前几轮同一条限制。
