# 交付报告 — transport-only Harness 接入链（HD-002 第四轮 / 实施轮）
> **Current owner and evidence note (2026-10-10).** This document contains earlier migration/review evidence. Its body is preserved; old paths and test outcomes below describe the recorded historical snapshot and are not current execution instructions or fresh validation. Current ownership and path mapping:
>
> - `runtime/access-entry.mjs` and the prior plugin-local access chain → `apps/server/src/ordessa_server/composition/native_channels/access_entry.mjs`; it selects brand declarations through `selected_launch_ports.mjs` and uses the Agent transport at `packages/execution/agents/src/ordessa_agents/harness/transport/acp.mjs`.
> - `plugins/harness/tests/access/*.test.mjs` → `tests/integration/harness/access/*.test.mjs`; controlled peer/marker fixtures → `tests/fixtures/harness/access/`; shared sidecar support → `tests/integration/harness/access/support/sidecar_harness.mjs`.
> - `plugins/harness/tests/access/test_acp_boundaries.py` → `tests/architecture/harness/test_acp_boundaries.py`; `plugins/harness/packaging/tests/test_acp_schema_drift_target.py` → `tests/integration/harness/packaging/test_acp_schema_drift_target.py`.
> - Historical shared `packaging/<brand>` npm roots → each leaf's `plugins/harness/<brand>/tooling/npm/`; actual launch declarations remain owned by their brand leaf and are selected by the Server port.
>
> The source-owner receipt `docs/verification/overnight-upper-structure-20261009/harness-access-test-owner-root-applied.json` records 14 source mappings applied. Four shared discovery/CI files were subsequently integrated in `docs/verification/overnight-upper-structure-20261009/current-test-discovery-root-applied.json`; unsafe `verify-clean.sh` remains held and unrun. It is a migration receipt, not a test result. No suite was run for this documentation candidate. Historical wire names, identifiers, and raw results below remain historical evidence.


**状态：IMPLEMENTATION_REVIEW_READY。** 插件范围内的实施与验证已完成，等待主会话审核。
未 push、未合并 main、未 `git add`（`git diff --cached` 为空）。

工作树 `worktrees/harness-desktop-002/bc-native`，分支 `work/hd002-bc-native`，起点 `e996e9d2`。
写入范围：`plugins/agent-box-harness/**`。前端 / Server / Workcore 只读未改。

裁定落地：不保留旧运行链、不做双轨兼容。本轮先改测试与方案，再实施，不以"旧链必须继续通过"
阻止替换（`PLAN-ACP-ACCESS.md` §4 已从门禁改为分类清单，`TEST-REVIEW.md` 同）。

---

## 1. 新目录树（接入链）

```text
plugins/agent-box-harness/
  harnesses/                     # 发现层：一品牌一目录，聚合器无品牌分支
    index.mjs                    #   listHarnesses / isKnownHarness / harnessLaunchContext
    {claude,claude-code,codex,dsh,hermes,kilo,omp,pi,qwen}/launch.mjs
  runtime/
    access-entry.mjs             # ★ 唯一生产入口：NDJSON 控制面 + 字节透明中继
    access-transport.mjs         # 连接句柄（transport id `acp-stdio-jsonrpc/1`）
    profile_extensions.mjs       # 保留：5 个 launch.mjs 的发现数据源
    native-driver.mjs            # 保留：仅因包外消费者存活（见 §5）
    subagent-bridge.mjs          # 保留：同上
    drivers/opencode-native.mjs  # 保留：另一名 agent 未提交的原生能力，须裁定不擅删（见 §6）
    capability_declarations.json # 保留：能力投影，消费者在包外
  third_party/harness_remote/    # 上游桥快照：21 → 10 文件，`transportOnly` 补丁
    bridge/src/acp-client.js     #   新链的实际传输层（计算式动态 import 到达）
    SOURCE.json / PATCHES.md     #   §8 补丁申报、§9 裁剪与许可证
  tests/
    access/access_entry_behavior.test.mjs    # E1–E13 控制面、中继、建立/释放并发
    access/acp_passthrough_target.test.mjs   # T1–T10 目标口径（本轮从红转绿）
    access/{acp_channel_behavior,controlled_harness_self_proof,real_adapter_protocol}.test.mjs
    RETIRED.md                               # 47 个退役用例的逐例处置
  REMOVALS.md                    # 移除清单 + 恢复位置
  DELIVERY.md                    # 本文件
```

`runtime/worker-entry.mjs` 已移除，不在树中。

## 2. 公开接口

**启动形态**：`node runtime/access-entry.mjs`（隔离环境，要求 `AGENTBOX_SIDECAR_ISOLATED=1`）
或 `node runtime/access-entry.mjs --native`（宿主机直跑，此时该 env 必须不为 `1`）。
两者互斥，不匹配就不打开 stdin。

一行一条消息。**解析后 `typeof op === "string"` 且不含 `jsonrpc`/`method`/`result`/`error` 任一字段
⇒ 控制面；其余一切 ⇒ ACP 帧，逐字转发。** 规则只可能把一条消息从控制面挪到数据通道，
不会反过来：一个结构上合法的 JSON-RPC 帧永远走数据通道，即使它带了 `op` 扩展字段（E13 钉住）。
控制词表恰好四个：`harnesses` / `connect` / `status` / `close`。

| op | 入参 | 成功回复的 `result` |
| --- | --- | --- |
| `harnesses` | — | `{provenance:{commit,ref}, harnesses:[9 个 id], transport}` |
| `connect` | `harness`、`launch{command,args?,environment?}`、`directory?`、`credentialEnvironment?` | `{connectionId, harness, transport, launch(含 `source:"explicit"`), discovered, state, provenance}` |
| `status` | —（需已连接） | `{connectionId, harness, transport, connected, state, processId, framesToAgent, framesFromAgent, ended}` |
| `close` | —（需已连接） | `{connectionId, released, processId, signalUsed, tree}`；仍有未确认退出的进程时追加 `unreleased:[{connectionId, processId, tree}]` |

`close` 的 `released` 只由操作系统说了算，且**证明到进程树这一层**：`runtime/access-entry.mjs` 在
POSIX 上以 `detached: true` 启动被调起的桥，使它自成一个进程组，`close` 于是回收"这次启动开出来的
那棵树"而不是一个 pid。回收由 `releaseProcessTree`（`runtime/access-transport.mjs`）做，成员身份取两个
独立来源的并集：① 进程组号等于根 pid 的全部进程（含父进程先退出后被领养的孤儿 —— 只要还有成员在跑，
组号就仍被我们占着，不会被无关进程复用）；② 从根 pid 沿 `/proc/<pid>/stat` 的 PPid 走下来的全部子孙
（自己 `setsid` 逃出组的子进程只能靠这一条找到）。之后组内成员由 `kill(-rootPid, …)` 一次性达到，
组外成员逐个发；宽限期 `RELEASE_GRACE_MS`（2s）用 `SIGTERM`，仍不干净就升级到 `SIGKILL` 再等
`RELEASE_FORCE_MS`（2s），每 `RELEASE_POLL_MS`（20ms）重新观察一次并补发。

**只有 `ESRCH` 算确认退出。** `EPERM` 算活着（那是别人的 pid），其它任何错误码（`EACCES`、`EINVAL`、
`ENOENT`…）什么都证明不了，单列为 `unconfirmed` —— 它既不算死亡、也不算存活，但**一定让 `released:false`**。
`released:true` 的充要条件是 `tree.survivors` 与 `tree.unconfirmed` 同时为空，即树里每个成员都被 OS
逐个答复了 `ESRCH`。`tree` 随回复一起给出，就是这份证据：

```
tree: { available, scope, reason, groupPid,
        members:[{pid, group, currentGroup, state, code, check, identity}],
        survivors:[pid], unconfirmed:[{pid, code}], identityChanged:[pid] }
```

`members[].check` 是这一轮新增的那一格：身份核对的结果 `matched | changed | unknown | unavailable`
（口径见第 12 节），`group` 是这次回收**当初认领**它时所在的组号、`currentGroup` 是当前进程表说的组号，
两者不等就是该成员已经离组。

**第 6 轮把这条声称收窄成三件事**（都是"回收算法的边界"，不改架构）：

1. **成员去重与遍历去重分开。** `discoverProcessTree` 先按组号收成员，再沿 PPid 下探；此前两者共用
   一份"已在 members 里就跳过"的判据，于是同组的子进程被收集后**不再被展开**，它下面那个自己
   `setsid` 逃组的孙进程根本不出现在回收集合里。现在队列以"根 + 全部已收集成员"起步，另用
   `expanded` 只挡重复展开。E20 钉住这一条（真实三层进程），E23 钉住"两条规则缺一不可"
   （桥先退出 ⇒ 孤儿只能靠组号找到；孙进程只能靠展开这个孤儿找到）。
2. **读不到进程表时不许声称整棵树。** `scope` 即这次声称的范围，取值和 `spawn` 是否加 `detached`
   同源于一个常量 `PROCESS_GROUP_OWNERSHIP`：POSIX ⇒ `tree`，Windows ⇒ `root-only`。`claim:"tree"`
   遇上 `available:false` 直接 `released:false` + `reason:"PROCESS_TABLE_UNAVAILABLE"`，因为根消失
   只证明根消失；只有本来就声称 `root-only` 的才允许 `released:true`，且 `scope` 留在回执里。
3. **给单个 pid 发信号之前先核对身份。** pid 只是会被重新发放的数字，**同用户的新进程会被成功误杀**
   （§11.1 的 S1b 实测），所以真正的身份是 `spawn` 当场记下的 `(pid, /proc 启动时间)`，记一次不改写。
   凡"数字还在、启动时间已换"的成员：一个信号都不发，单列 `identityChanged`；组信号也必须有一个
   身份核对得上的在组成员当证人，否则退化成逐个发。E21 / E22 用注入身份钉住这两条。
   这一条在第 6 轮还是两态（`replaced` 真/假），"核不了"被并进"没变"里；第 7 轮把它改成三态并补了
   证人必须看**当前**组号这一半，见第 12 节。

`available:false` 的其余口径不变：此时只认领根那一个进程、只按 pid 发信号，**绝不盲发组信号**，
也仍然只按 `ESRCH` 认账。Windows 上桥沿用被复用客户端自己的 `spawn`（那里有 `.cmd`
特判，替换它会悄悄关掉它），因此不宣称组所有权、`tree` 只覆盖根进程 —— 这是写明了的口径，不是遗漏。
进程已经自己退出的，不再向一个可能被回收的 pid 补信号；这一句在现在有了更硬的版本：**同一个 pid
只要身份变了就一律不再补信号**，没变才继续。`processId` 在入口侧独立记录（`ownedPid`），
不依赖桥在 `close()` 后仍会清空内部 `#child` 的行为，所以**父进程先退出时身份也不丢**；释放未确认时
句柄、管道和身份一并留着，`status` 仍报活的 pid。

被动事件：`transport_end`（`reason` = `closed_by_caller` / `adapter_exit`）、`stderr`、
`transport_malformed`，以及 stdin EOF 收尾时若还有进程未确认退出就发 `process_release_unconfirmed`
（带同一份 `released:false` 报告 —— 不静默丢弃，也不谎报）。一进程一连接。

**建立连接不发任何 ACP 帧**：`initialize`/`authenticate`/`session/new`/`session/prompt` 一律由调用方自己写。
请求、通知、result/error、原生 id、扩展字段双向原样保留；不改模型标识、不投影业务事件、
不自动批准或拒绝权限、未应答就是没有回复（不伪造 `cancelled`）、连接退出如实上报。

拒绝码（`{ok:false,error:{code,message}}`）：`HARNESS_REQUIRED`、`HARNESS_UNDISCOVERED`、
`ADAPTER_LAUNCH_REQUIRED`、`ADAPTER_LAUNCH_FIELD_UNKNOWN`、`ADAPTER_ARGS_INVALID`、
`ADAPTER_ENVIRONMENT_INVALID`、`CREDENTIAL_ENVIRONMENT_INVALID`、`CREDENTIAL_MATERIAL_INVALID`、
`ACP_ALREADY_CONNECTED`、`ACP_NOT_CONNECTED`、`ACP_CHANNEL_DEAD`（连接已结束仍写帧）、
`ACP_CONNECT_IN_PROGRESS`（建立中又来了 `connect`，或对中的 `status`）、
`ACP_CONNECT_FIELD_UNKNOWN`、`ACP_CONNECT_FIELD_RETIRED`、`UNKNOWN_OP`、`ENVELOPE_MALFORMED`。
启动期：`SIDECAR_MODE_INVALID` / `SIDECAR_MODE_CONFLICT` / `SIDECAR_ISOLATION_REQUIRED` /
`PROVENANCE_UNREADABLE`（这些不带 `id`，因为还没有消息可关联）；`SIDECAR_FATAL` 是顶层兜底，
在退出前也会关掉自己拥有的 Harness 进程。其中 `PROVENANCE_MISMATCH: <path>` 在打开 stdin 之前
以异常终止 —— 校验不过就不服务任何一条消息。

旧信封字段是**按名拒绝**而非忽略：`profile`、`stateDirectory`、`permissionRoundTrip`、
`permissionTimeoutMs`、`preferredAuthMethod`、`driver`、`title`、`sessionId`、`text`、`model`、
`attachments`、`requestId`、`decision`、`scope`。

**顺序约定**：控制面用微任务派发，因此 `close` 在 Agent 死后仍可回答；代价是调用方必须
**等到 `connect` 的回复**再写 ACP 帧。无连接时写入的帧如实回以 `ACP_NOT_CONNECTED`（E3 钉住），
本入口不排队、不猜测、不代答。

**建立是排他的**：`connect` 在**唯一的 await 之前**同步占用一个 `opening` 名额，此后到达的
`connect` 一律 `ACP_CONNECT_IN_PROGRESS`（E10），对中的 `status` 同样按名拒绝而不是回一个假的
"未连接"。`close` 和 stdin EOF 都先 `settleOpening()` 再释放，且释放的是 `owned` 集合里的**全部**
句柄（正常只有一个；多出来只可能是建立中或已断开没清掉的），所以"先 connect、紧接着 close/EOF"
不可能留下一个没人管的 Harness 进程（E11、E12）。回收的范围是**这次启动自己开出来的进程树**（见上），
信号只发给按"组号 + PPid 血缘"两路认出来的成员，绝不按命令行或工作目录清扫 —— 同一台机器上跑着同样
命令、同样目录的无关进程不受影响（E19 用一个同命令行、同 `cwd` 的诱饵进程钉住这一点）。

完整可运行示例见 `README.md`「Harness 接入的公开接口（transport-only）」一节（与本节同源）。

## 3. 测试实跑结果（本轮，全部实测）

| 命令 | 结果 |
| --- | --- |
| `node --test $(find tests -name '*.test.mjs' ! -path '*opencode*')` | **77 / 77 绿**（第 4 轮 65 → 第 5 轮 71 → 第 6 轮 75 → 第 7 轮 77：新增 E24–E25 两条身份边界用例） |
| `node --test $(find tests/access -name '*.test.mjs')` | **56 / 56 绿**（`tests/access/` 5 文件；第 4 轮 44 → 第 5 轮 50 → 第 6 轮 54 → 第 7 轮 56；此前 54 项一项未删、一项未跳过，只有 E9b / E14 / E15 按本轮口径补了身份证人，见 §12.3） |
| `node --test tests/opencode_*.test.mjs` | **32 / 32 绿** |
| `python -m pytest tests -q` | **315 passed / 3 failed / 3 skipped**（5.38s，与本轮改动前逐项一致） |

3 条 failed 均**不在本任务范围且先前即红**，逐条归属：
`tests/install/test_acp_schema_drift_target.py` 2 条是本文件自声明的"今天应当红"目标测试
（文件头写明 "expected to fail today"：pi 的根 `overrides` 把 `@automatalabs/pi-acp@0.5.0` 声明的
精确 `@agentclientprotocol/sdk` `1.4.0` 静默改写成锁里的 `1.3.0`，属可选安装侧的版本漂移，不是接入链）；
`tests/test_skill_projection.py::test_all_five_registry_targets_are_lossless_and_read_only`
按 `TEST-REVIEW.md` §8 为既有红，已在起点 `e996e9d2` 复现。两处文件与删除前备份逐字节相同，
本轮变更集不触碰 `src/agent_box_harness/**` 的运行实现（唯一例外是 `harnesses.toml` 的一段
**注释**，见 §8）。

新测试全部经过真实生产入口（`runtime/access-entry.mjs` 子进程），覆盖：建立连接零 ACP 帧、
双向完整帧（含未知 method 与自定义字段逐字透传）、反向请求/result/error、未应答不代答、
同 id 隔离、`close` 与崩溃、资源释放与唯一 `transport_end`。夹具自证：
`controlled_harness_self_proof.test.mjs` 先证明受控 harness 自己记录帧，缺席断言才算数（C9–C11、F1–F3）。
逐例处置见 `tests/RETIRED.md`。

## 4. 旧链移除清单与恢复位置

17 个文件被移除：入口 1（`runtime/worker-entry.mjs`）+ 桥快照 11（`third_party/harness_remote/bridge/src/`）
+ 旧链专属测试 5（47 个 `test(` 声明）。逐项依据与"核对后保留"清单见 `REMOVALS.md`。

**恢复位置（唯一权威）**：这些文件在 `HEAD` 中全部不存在（`git ls-files` 只有 26 条），
Git 无法恢复，只能从删除前建立的插件外备份取回：

```
/home/maoqh/projects/ordessa/backups/hd002-transport-only-20260924/
├── README.md · git-status-before.txt · tracked-modified.diff · tracked-modified-files/
└── plugin-tree-before/     # 整目录 cp -a 快照，含全部 17 个被删文件
```

删除前逐一核对：备份内存在 17、插件内已不存在 0。恢复：
`cp plugin-tree-before/<相对路径> plugins/agent-box-harness/<相对路径>`。
本轮未使用 reset / stash / clean，未做宽泛递归删除。

## 5. 包外迁移清单（旧入口 → 新入口；只报，不代改）

**整条产品链目前不可用**：Server 侧仍指向已删除的 `worker-entry.mjs`。以下是需要上层迁移的
全部断点，均在 `plugins/agent-box-harness/**` 之外，本任务未修改。

| 包外位置 | 现在做的事 | 迁移到 |
| --- | --- | --- |
| `src/agent_box/server/bootstrap/runtime.py:531` | 投影/指向 `worker-entry.mjs` | `runtime/access-entry.mjs` |
| `src/agent_box/server/extensions/runtime_composition/sandbox_port.py:129` | 同上 | `runtime/access-entry.mjs` |
| `src/agent_box/server/execution/sidecar.py:264-277` | 固定文件名清单（`worker-entry.mjs`/`native-driver.mjs`/`profile_extensions.mjs`） | 清掉 `worker-entry.mjs`；`native-driver.mjs`/`profile_extensions.mjs` 仍需投影 |
| `sidecar.py` 信封词汇 `register`/`start`/`open`/`create`/`prompt`/`abort`/`status`/`close` | 一次作业一个 op | `harnesses` → `connect`（一次）→ 由调用方自己写 `initialize`/`session/new`/`session/prompt` 帧 → `status` → `close`；轮次/快照状态由 Workcore 在插件外持有 |
| `sidecar.py:1328` 恒为真的 `permissionRoundTrip` / `permissionTimeoutMs` | 声称有一个会决策的超时 | 二者按名被拒。权限由调用方自己应答 Agent 的反向请求；超时不得冒充用户决策 ⇒ 该字段在新契约里没有对应物，建议直接删除 |
| `preferredAuthMethod` / `stateDirectory` / `profile` / `model` / `attachments` / `sessionId` / `text` / `requestId` / `decision` / `scope` | 信封字段 | `connect` 只接受 `harness`/`launch{command,args,environment}`/`directory`/`credentialEnvironment`；`model`、`attachments` 等属 ACP 帧内容，由调用方写在帧里 |
| `runtime.py:1160`、`sidecar.py:276-277` | 消费 `subagent-bridge.mjs` | 该文件已保留，无需即刻迁移；归属见 `PLAN-OPTIONAL-INSTALL.md` §6-6 |

`credentialEnvironment` 只接受环境变量名，值由入口从 `/runtime/secret/credential` 读取后注入子进程
env，且 `TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|AUTH` 类 key 不许在 `launch.environment` 里出现 ——
凭据值不过夜、不上线。

## 6. 需要上层裁定的三件事（本轮不自行决定）

1. **OpenCode 的接入归属。** 本轮上一版把它写成"OpenCode 不说 ACP"，**这个说法不成立，现予更正**：
   官方提供 `opencode acp`，通过 stdio 运行 ACP（官方文档 `https://opencode.ai/docs/acp/`）。
   据此，上一版"**Server 侧为 non-ACP 品牌保留一条独立投影路径**"的建议**一并撤回** —— 它以那句
   错话为前提，且新链不需要旁路。本轮的事实只是：`harnesses/` 里没有 `opencode` 条目，所以
   `connect` 以 `HARNESS_UNDISCOVERED` 拒之（E6 断言的是**注册范围**，不是能力）。本机没有
   `opencode` 可执行文件（`command -v opencode` → not found）、`packaging/` 下也没有它的字节，
   所以"当前版本接得上"是另一个尚未取证的问题。**本轮按裁定不扩大品牌接入范围、不开旁路**；
   最小建议只剩一条：上层裁定是否注册 `harnesses/opencode/`。
   `runtime/drivers/opencode-native.mjs` 与它的 32 例测试照旧保留 —— 那是另一名 agent 未提交的
   原生能力，删它等于丢弃别人的工作，与 ACP 与否无关。
2. **包外信封消费者**（§5）。迁移前 Server 无法启动这条链；本插件不为它们保留兼容层。
3. **释放的清理粒度。** 第 4 轮这一条记的是限制（只向自己 `spawn` 的那一个 pid 发信号，
   Harness 自己再生出的子孙不在承诺之内）。第 5 轮按裁定把它做成了实现：POSIX 上启动即自成一个进程组，
   回收范围 = 组号等于根 pid 的全部进程 ∪ 沿 PPid 从根走下来的全部子孙，`released:true` 必须有逐个成员的
   `ESRCH` 回执（见 §2 与 §10）。**尚未取得证据的仍是真实 adapter 会不会留孤儿子孙**：本轮没有执行过任何
   真实 adapter 进程 —— `real_adapter_protocol.test.mjs` 只读包内 tgz 里的协议表，不安装、不下载、不运行 ——
   所以"回收整棵树"在真实品牌上是被机制覆盖、未被实测。需要实测的话，那是一条新的、要点名品牌的授权。

## 7. 复核命令

```sh
cd plugins/agent-box-harness
node --test $(find tests -name '*.test.mjs' ! -path '*opencode*')   # 77/77
node --test $(find tests/access -name '*.test.mjs')                 # 56/56
node --test tests/opencode_*.test.mjs                                # 32/32
source /tmp/hd002-tidy-env/bin/activate
python -m pytest tests -q                                            # 315 / 3(既有红) / 3 skip
```

## 8. 实施之外还改了两处证据文本（避免"把退役链说成活着"）

| 文件 | 改动 | 为何安全 |
| --- | --- | --- |
| `tests/test_capability_declarations.py` pi `attach` 一栏 | 原来写"投递链路（… → `worker-entry.mjs` → `AcpService.prompt`）在代码上成立"，现明说那条链路是**已退役的信封分发**、新入口不构造附件，结论仍是 `not-observed` | 该表的 `evidence` 只被要求"非空字符串"，且 `observed != OBSERVED` 时不参与任何比对；`declared` 一栏才与 TOML 相等。实测本文件 53/53 绿 |
| `src/agent_box_harness/harnesses.toml` pi 段 | 在既有注释块后追加 3 行，标注同一件事并指向 `REMOVALS.md` | 纯注释：`tomllib` 不解析注释，注册表/JS 投影/黄金矩阵三处等值测试都只比 `capabilities`。**未新增或改动任何声明、Profile、provider/model 字段** |

两处都不改变任何能力结论：pi 的 `attach` 依旧 `not-observed`，`harnesses.toml` 的
`capabilities` 集合逐字未动。

## 9. 第 4 轮返修（实施审核否决四项之后）

上一版实施被否决，四项都是确定的实现漏洞，不需要重做架构。本轮只修这四项：

| # | 漏洞 | 现在的行为 | 反例 |
| --- | --- | --- | --- |
| 1 | `close` 只发出终止信号就报 `released:true`，并清掉进程引用 | 等 OS 确认：SIGTERM → 2s → SIGKILL → 2s 轮询；确认不了报 `released:false` 且保留 `processId` 与句柄（`access-transport.mjs`，该函数在第 5 轮扩成 `releaseProcessTree` 并已改名，见 §10） | E9（真实进程忽略 SIGTERM，实测 `signalUsed:"SIGKILL"`、回复时进程已死）、E9b（注入信号构造"确认不了"那一支） |
| 2 | 并发 `connect` 可起两份进程 | `connect()` 在第一个 await 之前同步占 `opening`；后来者 `ACP_CONNECT_IN_PROGRESS`；`close` 与 stdin EOF 先等建立落定，再释放 `owned` 全集 | E10 / E11 / E12 |
| 3 | 控制面判别可截获带 `op` 的 ACP 扩展帧 | `op` 是字符串**且**无 `jsonrpc/method/result/error` 才算控制面；规则单向，只会把消息挪向数据通道 | E13 |
| 4 | 文档结论错（"OpenCode 不说 ACP"）并据此建议旁路 | 更正，并撤回"Server 保留 non-ACP 投影路径"的建议；本轮不扩品牌范围、不开旁路、不改代码 | 文档订正（§1 树注、§6-1、`REMOVALS.md`、E6 注释） |

**真实进程清理证据**（OS 侧 `kill(pid,0)` + `/proc` 扫描，不是入口自述）、四个变异
（把每项修复退回原状）各自使哪个用例变红、以及本轮**没有**测到什么（E9 的时序前提、
EOF 孤儿分支、进程树粒度、`released:false` 只能注入构造），逐条记在
**`TEST-REVIEW.md` §13**。一句话结论：`released:true` 与"回复时进程已死"两件事在本机
每次实测里同时成立，`tests/access/` 全量跑完 `/proc` 里 `controlled_harness.mjs` 前后都是 **0** 个。

## 10. 第 5 轮返修（只修关闭生命周期）

裁定范围两句话：① 存活探测只有 `ESRCH` 能确认退出，非 `EPERM`/`ESRCH` 的异常要有反例，不得假报
`released`；② 为本次启动建立明确的进程树所有权，关闭时回收桥**及其启动的子进程**，要有真实父子进程测试，
覆盖父进程先退出、子进程仍存活的情况，且不得误杀其他进程；`released:true` 必须有对应的回收证据。
其余范围未动：并发 `connect`（E10）、ACP 扩展帧透传（E13）、透明通道架构、品牌范围一律保留原样。

| # | 改动 | 落点 | 反例 |
| --- | --- | --- | --- |
| 1 | 存活探测三分：`ESRCH`→`gone`、`EPERM`→`alive`、**其它任何码→`unconfirmed`**。`released` 的判据是"成员全部 `gone`"，即 `survivors` 与 `unconfirmed` 同时为空 | `access-transport.mjs` `probeProcess` | E14（`EACCES`/`EINVAL`/`ENOENT` 各一遍：`released:false`、身份保留、`tree.unconfirmed` 逐字报出该码、且**不误记成存活**；再加"桥已死 + 子进程探测无解"的混合树，`members.state` 必须是 `["gone","unconfirmed"]` 而不是被平均成一个结论） |
| 2 | 启动即建立组所有权：POSIX 上 `spawn(…, {detached:true})`，使这次启动自成一个进程组；Windows 不宣称组所有权（保留被复用客户端自带的 `.cmd` 特判），只回收根进程 | `access-entry.mjs` `groupLeadership` | E17（去掉 `detached` 即红，见 §10.2 变异 E） |
| 3 | 成员身份两路取并集：组号 `== rootPid` 的全部进程（含被领养的孤儿）∪ 沿 `/proc/<pid>/stat` PPid 走下来的全部子孙；读不到进程表就返回 `null`，调用方 `tree.available:false`，只按 pid 回收、绝不盲发组信号 | `access-transport.mjs` `discoverProcessTree` / `readLinuxProc` | E18（子进程自己 `setsid` 逃出组，只能靠 PPid 找到）；E15（`discover` 返回 `null` 时打靶只能是根 pid 一个，实测 `targets === [child.pid]`） |
| 4 | 回收按身份分派：组内成员**只**由 `kill(-rootPid, …)` 达到（不逐个发，避免把承诺降级成"逐个碰运气"），组外成员逐个发；每轮 `sweep` 前重新观察进程表，SIGTERM 宽限→SIGKILL 强制，每 20ms 复查并补发 | `access-transport.mjs` `releaseProcessTree` | E16（一次组信号回收桥＋两个子进程，回执逐成员为 `gone`）；E9b 断言组内成员的靶子集合恰为 `[-4242]` |
| 5 | `close()` 不再拿"桥自己忘了孩子"当死亡证明：删掉 `client.processID === undefined ⇒ released:true` 这条捷径，改为**无条件**跑一遍树回收，回收未确认就留住管道/句柄/身份 | `access-transport.mjs` `close` | E17（桥先退、两个子进程仍在服务：`released:true` 且 `survivors:[]`，事后 `/proc` 里一个不剩） |
| 6 | 回执随回复走：`close` 与 EOF 的报告新增 `tree`（`available/groupPid/members/survivors/unconfirmed`），`unreleased[]` 每项也带自己的 `tree` | `access-entry.mjs` `releaseOwned` | 上表全部真实进程用例都以这份回执为断言对象，不采信夹具自述 |

### 10.1 真实进程证据（OS 侧，不是入口自述）

三条场景各起一次真实 `connect`（走 `runtime/access-entry.mjs` 子进程），`close` 之后立刻读 `/proc`。
成员身份、`state` 与"事后进程表里还剩几个"三处同时成立才算数：

```
E16 形态（桥带两个子进程）
  root=219869 childrenBefore=[219878,219879]
  receipt released=true signalUsed=SIGTERM
  members=[{219869,gone},{219878,group:219869,gone},{219879,group:219869,gone}] survivors=[] unconfirmed=[]
  fixtureChildrenIn(project)=[]  harnessPidsIn(project)=[]

E17 形态（桥 120ms 后自尽，子进程被领养仍在跑）
  root=219904 childrenBefore=[219911,219912]（关之前逐个确认 alive）
  receipt released=true  members 三项全 gone  survivors=[]
  close 之后 fixtureChildrenIn(project)=[]

E18 形态（一个子进程 setsid 逃出组）
  root=219933 childrenBefore=[219940]（其 group=219940，≠ rootPid）
  receipt released=true  members=[{219933,gone},{219940,group:219940,gone}]
```

三行回执都是 `close` 的**实际回复体**，不是断言者转述；`members` 里每一项都被 OS 单独答复过 `ESRCH`
（`survivors`/`unconfirmed` 同时为空 ⇒ 才有 `released:true`）。注意 `group:null` 出现在根上：那是
最后一次观察时根已经死了，`/proc/<rootPid>/stat` 读不到组号 —— 回执把这也如实分开，不拿"读不到"当"没了"。

前后各扫一次全机 `/proc`：夹具标记进程 **净新增 0**（扫描命令自身的 argv 会匹配到自己，实测到的
"1～2 个"就是这种自匹配，已逐个核对 cmdline 排除）。`tests/access/` 全量跑完（50 例）后再扫：
`controlled_harness.mjs` 与夹具子进程在本机临时目录下均为 **0**；跑测试期间留下的临时目录只按名字
逐个清理，未做任何递归清扫。E19 的诱饵进程（同命令行、同 `cwd`）在 `close` 之后仍存活，
且不在 `tree.members` 里 —— 这条是"不得误杀其他进程"的正向证据。

### 10.2 咬合证据：把修复退回原状，看哪一例红

变异在插件目录之外的一次性副本上跑，跑完即删（`/tmp/mut`，已删除）。

| 变异 | 退回的实现 | 变红的用例 |
| --- | --- | --- |
| A | 未知错误码折进 `gone`（等于"探测报错就当它没了"） | **E14**（仅此一条） |
| B | 恢复 `client.processID === undefined ⇒ released:true` 捷径 | **E17**（仅此一条） |
| C | 取消树发现，只认根 pid（第 4 轮的形状） | **E16 E17 E18 E19** |
| D | 保留组身份、删掉 PPid 血缘 | **E18**（仅此一条） |
| E | 启动不加 `detached`（不再自成一组） | **E17**（仅此一条） |
| F | 成员身份改成"按 `cwd` 相同即算我的" | **E19** 与 **E7**（邻居连接被误杀） |
| G | 删掉组信号、组内成员又不逐个发 | 12 条（回收整体失效，含全部生命周期用例） |

每一处修复都至少有一条用例只因为它而绿；没有一条新用例是靠放宽断言过的。

## 11. 第 6 轮返修（补关闭回收的三处边界，不扩业务范围）

审阅在 50/50 全绿之上又往下找了一层，三处都是**回收算法自己的边界**，架构没动：

| # | 被指出的问题 | 落点 | 钉住它的用例 |
| --- | --- | --- | --- |
| ① | `discoverProcessTree` 把"已收集成员"当"已遍历节点"用：同组的子进程入了集合就不再下探，它下面逃组的孙进程不在回收集合里 | `access-transport.mjs`：队列以"根 + 全部已收集成员"起步，另立 `expanded` 只挡重复展开 | **E20**（桥 + 同组子进程 + 逃组孙进程，三层真实进程）· **E23**（再加"桥先退出"，证明两条收集规则缺一不可） |
| ② | 读不到进程表时，根 pid 消失仍被报成整棵树释放成功 | 新增 `claim`/`tree.scope`，与 `spawn` 的 `detached` 同源于 `PROCESS_GROUP_OWNERSHIP`；`tree` 声称 + 表不可读 ⇒ `released:false` + `reason:"PROCESS_TABLE_UNAVAILABLE"` | **E15**（重写为两种声称各自的结局，原断言一字未放宽，只是收窄了声称） |
| ③ | 注释里"pid 被复用后会 `EPERM` 或存活"不成立：同用户的新进程可能被**成功**误杀 | `spawn` 当场记 `(pid, /proc 启动时间)`；数字还在但启动时间已换 ⇒ 一个信号都不发，单列 `identityChanged`；组信号也要有核得上身份的在组成员当证人 | **E21**（数字被重新发放，注入身份 + 真实进程对照）· **E22**（组信号需要证人；同时仍逐个回收没跑的成员） |

### 11.1 真实进程与真实身份证据（OS 侧测量，非入口自述）

```text
E20 桥 257761 └─ 子 257768(ppid=257761, pgrp=257761) └─ 孙 257775(ppid=257768, pgrp=257775)
   discoverProcessTree(root) = 三项齐全，孙的 group=257775 ≠ rootPid（它已逃组，只能靠血缘）
   回执 released=true signalUsed=SIGTERM scope=tree available=true reason=null
   members 三项全 gone · survivors=[] · unconfirmed=[] · identityChanged=[]
   waitAllGone(子,孙)=[]  fixtureChildrenIn(project)=[]  harnessPidsIn(project)=[]

E23 同上形状，但桥先自尽：root=257789 已死，子 257796(ppid=4567 ← 被领养, pgrp=257789 仍是我们的组号)
   孙 257803(ppid=257796, pgrp=257803)
   discoverProcessTree(root) = [{257789,group:null,identity:null}(根已死),{257796,...},{257803,...}]
   回执 released=true members 三项全 gone · waitAllGone=[], 残留 0

S1a 真实进程 pid 257825（真实启动时间 3125197），把它记成别人的 3124197：
   发出的信号=[]（一个都没发） · released=true · identityChanged=[257825] · survivors=[]
   该进程 close 之后仍存活=true —— 身份不符 ⇒ 绝不补信号
S1b 对照组：同一个进程、按真实启动时间记录
   发出的信号=[[257825,"SIGTERM"]] · released=true · 该进程仍存活=false
   —— 这就是审阅指出的那点：同用户发信号会成功。数字错了，一次误发就杀掉一个无关进程；
      `EPERM` 不是安全网，身份核对才是。
本机夹具标记进程数：before 0 / after 0（`/proc` 全机扫描；扫描命令自身 argv 会匹配到自己，本轮未出现）
```

### 11.2 咬合证据：把每一处修复退回原状

本轮变异是**在插件目录内就地改生产文件**，先留字节级备份（`/tmp/r6mut/access-transport.orig.mjs`），
跑完立刻还原，并用 `diff` 确认还原后与备份逐字节相同。这一点与第 5 轮"目录外一次性副本"不同，
如实记在这里。**第 7 轮起这条做法作废**：共享树里还有后端执行者，生产文件即便最终还原，中途也可能
被读到或用于测试；此后的变异一律只在插件目录外的副本里跑（§12.4）。本节表格的结论不受影响。

| 变异 | 退回的实现 | 变红的用例 |
| --- | --- | --- |
| M1 | 完整退回第 5 轮的遍历（只从根起步 + 已在成员里就跳过） | **E20 E23** |
| M1b | 只退回"已在成员里就不下探"（队列仍从全部成员起步） | **无**：在这一形状下与修复后等价（成员都已是种子）。诚实记为"不是独立缺陷"，不拿来充当咬合证据 |
| M1c | 只退回"队列从根起步"（成员仍继续下探） | **E23**（仅此一条：父链路断了、只有组号能领到孤儿时，种子必须含成员） |
| M2 | 表读不到时仍声称整棵树释放成功（去掉 `unaccounted`） | **E15** |
| M3 | 去掉身份否决（`replaced()` 恒 false） | **E21 E22** |
| M4 | 组信号不看身份（`inGroup` 即可发） | **E22** |
| M5 | `close()` 不再传 `rootIdentity`（只在第一次观察时取身份） | **无**：Linux 上第一次观察同样能取到身份，这一条是"spawn 当场那一次才是最强证据"的纵深防御，本机无可观测差异 —— 不假称有用例钉住它 |

### 11.3 本轮真实改动文件（全部在 `plugins/agent-box-harness/**`）

`runtime/access-transport.mjs`（遍历、身份、`claim`/`scope`/`reason`、`PROCESS_GROUP_OWNERSHIP`、
`close()` 传 `rootIdentity`、被指出的那段错注释）· `runtime/access-entry.mjs`（`detached` 与 `claim`
同源于一个常量）· `tests/access/access_entry_behavior.test.mjs`（E15 重写、E20–E23 新增、
`parentOf`/`groupOf` 直接读 `/proc` 作见证）· `tests/access/controlled_harness.mjs`（新增
`AGENTBOX_FIXTURE_GRANDCHILDREN`：由子进程自己 `setsid` 生出孙进程）· `README.md` · `DELIVERY.md` ·
`TEST-REVIEW.md`。前端 / Server / Workcore 一字未动；未 `git add`、未提交、未推送。

### 11.4 这一轮仍然没做的事（不假装测过）

1. **`identityChanged` 与 `released:true` 同时出现是有意的**，但含义要说清：它说的是"当初记下的那个
   进程已经没了"（pid 不会在持有者还活着时被重新发放），**不是**"这个数字上的进程已经没了"。
   后者我们故意不去证明，也绝不向它发信号。
2. **PID 重新发放没有被真实制造出来。** 本机无法按需让内核把某个号再发给新进程，E21/E22 的"身份已变"
   是注入的记录值与 `/proc` 真实值不一致；S1a/S1b 用真实进程证明了否决的效果与"不否决就会杀掉它"。
3. **Windows 分支仍未实测**（`scope:"root-only"` 那一支）；**无 `/proc` 的 Linux** 现在会稳定回
   `released:false` + `reason`，这是本轮特意换来的保守口径，代价是那台机器上 `close` 之后句柄与管道
   会留着等一次能读表的回收 —— 没有实测过这条路径，因为它需要一台那样的机器。
4. **真实品牌进程仍未执行过**，与第 5 轮同一条限制：树回收是被机制覆盖，不是被真实 adapter 实测。

## 12. 第 7 轮返修：身份判断改三态（同日）

审阅独立复跑 54/54 全绿，确认第 6 轮 ①② 已修好，但指出 ③ 里还剩一处**"未知即放行"**：
`replaced(pid)` 在读不到当前身份时返回 `false`，而组信号用 `!replaced(pid)` 找证人 —— 于是
"核不了身份"被当成"身份核上了"，仍然发出组信号。审阅用生产函数注入"当前身份不可读"，实测记录到
`SIGTERM` + `SIGKILL` 两次组信号；个体 pid 分支同理。本轮只做这一小段。

### 12.1 改了什么

| 位置 | 改前 | 改后 |
| --- | --- | --- |
| `identityState(pid)` | 布尔 `replaced()`，读不到身份 = `false` | 三态 `matched / changed / unknown`（外加"这台机器压根不记身份"= `unavailable`，与 `unknown` 是两件事） |
| 谁能被发破坏性信号 | `!replaced()` | **只有 `matched`**。`unknown` 记 `unconfirmed:[{pid, code:"IDENTITY_UNKNOWN"}]` 并 `released:false` |
| 组信号的证人 | 历史 `group` + `!replaced()` | **当前表里组号仍等于根 pid、且此刻身份 `matched`** 的成员；历史组号不再作证据 |
| 观察记录 | 只有首次认领的 `seen` | `seen`（首次认领，声称的对象）+ `current`（每次 `observe()` 重读，发信号的根据）两份，互不覆盖 |
| `ESRCH` | 算确认退出 | 不变，且优先级排在身份核对**之前**：数字空了这个事实不依赖是谁 |
| 回执 | `members:[{pid,group,state,replaced}]` | `members:[{pid,group,currentGroup,state,code,check,identity}]` |

`classify` 的判定顺序本轮自己写错过一次，值得记下来：第一版把"OS 答了个怪异错误码"排在身份核对之前，
于是**身份核不上 + 探测 `EACCES`** 的成员虽然被判成不确认，却仍会走进"没结算就补发信号"那一支 ——
正是本轮要堵的那类"绕开否决"。现在的顺序是：`ESRCH` → 身份 `changed` → 身份 `unknown` → 怪异错误码 →
`survivor`。身份否决排在"死活"之前，因为一个错误码描述的是**此刻占着这个数字的进程**，而那个进程可能
根本不是当初记下的那个；顺序本身就是规则的强度，所以 E24 第三段专门钉这一格（变异 R7-E）。
另外 `check === "unknown"` 时先重探一次再下结论 —— 探活与读 `/proc` 之间进程正好退出的 race
应当诚实落成 `gone`，而不是变成一次"没人确认的释放"。

### 12.2 两条新反例

- **E24 身份读不到 ≠ 身份核过了。** 成员带着记录身份、进程活着、`identify` 返回 `null`：
  `delivered=[]`（一个破坏性信号都没发）、`unconfirmed=[{pid, code:"IDENTITY_UNKNOWN"}]`、
  `survivors=[]`（也不谎称看见了活进程）、`released=false`、`members[].check="unknown"`。
  同一例第二段是规则必须留的口子：一样的读不到身份，配上 `ESRCH` ⇒ `released:true`，且不补任何信号。
  第三段钉判定顺序：读不到身份**又**探到 `EACCES` 的成员照旧一个信号都不发、按身份理由记
  （`code:"IDENTITY_UNKNOWN"`），不会因为"错误码那条支路先命中"而被补发信号。
  **没有放宽任何既有断言来换这几条**——第 6 轮靠 `ESRCH` 认账的用例全部照旧绿。
- **E25 成员已经离开原组。** 首次观察它在组里（于是被按组号认领），此后 `setsid` 出去了：
  组号 `-4848` 一次都没被瞄准（历史组号不再是证据），而它本人被逐个发信号回收、`released:true`。
  回执同时留 `group=4848` 与 `currentGroup=4849`，让"认领时的组"和"现在的组"分列而不是互相顶替。

### 12.3 为三态口径补身份证人的既有夹具（披露）

三态规则一旦生效，"注入一个不存在的 pid" 的夹具如果没有身份证人就会落进 `unknown` 而**不再被发信号** ——
那会让它们测的分支消失。本轮按最小改动补证人，断言一处未放宽：

| 用例 | 补的东西 | 为什么不算放宽 |
| --- | --- | --- |
| E9b（`EPERM` 不死） | 注入成员 `identity:"1000"` + `identify: () => "1000"` | 它测的是"杀不掉 ⇒ `released:false`"，身份必须核得上才走得到那条分支；断言原文未动 |
| E14 第一段（`EACCES`/`EINVAL`/`ENOENT`） | 同样补 `identity` + `identify` | 它测的是"怪异错误码不等于死亡、且仍然照旧补发尝试"；否决排在错误码之前之后，没有身份证人的成员根本走不到"补发"那一步。`released`/`unconfirmed`/`survivors`/`delivered` 四条断言原文未动 |
| E14 第二段 `mixed` | 未改 | 它只断言回执里 `state` 是 `gone` 还是 `unconfirmed`（OS 答了什么），不断言发没发信号，因此身份未知不影响它要测的那一格 |
| E15（读不到进程表，两种声称） | 两段各补 `rootIdentity: procField(child.pid, 19)`（真实启动时间，测试自己读 `/proc`） | 它测的是"声称范围"，补身份只是让根进程照旧可被逐个回收；`released`/`scope`/`reason`/`targets` 四条断言原文未动 |
| E21、E22 | 未改 | 第 6 轮就已经注入身份，本轮规则对它们正好成立 |

### 12.4 咬合证据（全部在插件目录外的一次性副本 `/tmp/r7mut/plugin3` 跑）

第 6 轮"在插件目录内就地改生产文件"的做法本轮作废：共享树里还有后端执行者，生产文件即使最终还原，
中途也可能被读到或用于测试。这次是 `cp -a` 整份插件到 `/tmp`，变异脚本只写副本，主树
`runtime/access-transport.mjs` 全程未再被写过（跑完 `diff` 与副本原始备份比对）。

**必须披露的一次跑错**：第一轮电池里有一条命令把 `sed -i` 和它依赖的 `cp` 串在同一个 `&&` 里，
`cp` 失败后 `sed` 没执行，于是那一轮静默地打在了一个旧副本 `/tmp/r7mut/plugin2` 上，R7-E 报成 GREEN。
发现后把路径固定到 `plugin3`，先 `diff` 证明 `plugin3` 里的模块与测试文件与主树**逐字节相同**，
再整轮重跑；下表是重跑后的结果，R7-E 由 GREEN 变回 RED。也就是说：这条咬合证据不是靠"最后一次跑对的那轮"
之外的什么得来的，但那次误跑本身说明副本脚本也需要被核对，记在这里。

| 变异 | 退回的实现 | 变红的用例 |
| --- | --- | --- |
| R7-A | `identify` 读不到 ⇒ 当成 `matched`（**就是审阅指出的那个洞**） | **E24** |
| R7-B | 组证人按 `seen`（历史组号）而不是 `current`（当前组号） | **E25** |
| R7-C | 组证人只看当前在不在组里，不看身份（第 6 轮 M4 重跑） | **E22** |
| R7-D | `unknown` 不再短路，成员照旧被轮询并被逐个发信号 | **E24** |
| R7-E | 探测答出的怪异错误码排在身份核对之前（§12.1 那个自己发现的顺序缺陷） | **E24** |
| R6-M3 重跑 | 身份比较整个去掉 | **E21 E22** |
| R6-M2 重跑 | 表读不到仍声称整棵树成功 | **E15** |
| R6-M1 重跑 | 完整退回第 5 轮遍历 | **E20 E23** |
| R6-M1c 重跑 | 只退回"队列从根起步" | **E23** |
| R6-M1b 重跑 | 只退回"已在成员里就不下探" | **无**（与修复后等价，第 6 轮的结论照旧，不充当咬合证据） |
| R6-M5 重跑 | `close()` 不再传 `rootIdentity` | **无**（本机第一次观察也能读到同一身份，纵深防御那条照旧） |

五条新变异各自只打中它该打中的那一例，没有一例靠"顺带红别的"成立。

### 12.5 真实 OS 侧证据（`/tmp/r7mut/evidence.mjs`，读真实 `/proc`、发真实信号）

```text
A 身份本身：真实进程 336463 启动时间 3616905，重读一致；SIGKILL 之后重读 = null
B 组号是现值不是历史值：python3 子进程起步 pgrp=336453（我们自己的组），os.setsid() 之后
  pgrp=336464，生产 discoverProcessTree 两次报的 group 跟着变（336453 → 336464）
  —— 证人必须看当前组号这条规则读的正是这个会变的量
C 审阅那个洞的实物版：真实进程 336465（identity=3617113）活着，注入 identify()=>null
  发出的信号=[]  该进程仍存活=true  released=false
  unconfirmed=[{pid:336465, code:"IDENTITY_UNKNOWN"}]  identityChanged=[]
  members=[{group:336465, currentGroup:336465, state:"alive", check:"unknown", identity:"3617113"}]
D 同一个真实进程，身份按实值记录：发出的信号=[-336465] 该进程仍存活=false released=true
  unconfirmed=[]
E1 本脚本遗留进程 = []（三段真实进程全部确认消失）
```

C 与 D 是同一台机器、同一形状的进程，唯一差别就是身份核不核得上：核不上时一个信号都没发出去，
核得上时一次组信号就收干净。第 6 轮的实现会在 C 这一格发出两次组信号。

### 12.6 本轮真实改动文件（全部在 `plugins/agent-box-harness/**`）

`runtime/access-transport.mjs`（`identityState` 三态、`PROCESS_IDENTITY_AVAILABLE`、`seen`/`current`
两份记录、`inGroupNow`、`classify` 顺序与重探、回执 `members` 新增 `currentGroup`/`code`/`check`、
`IDENTITY_UNKNOWN`、`identityChanged` 改按核对结果列、`readProcessIdentity` 与 `releaseProcessTree`
的注释）· `tests/access/access_entry_behavior.test.mjs`（E24、E25 新增；E9b、E14 第一段、E15 补身份证人；
文件头 E 例地图）· `README.md` · `DELIVERY.md` · `TEST-REVIEW.md`。前端 / Server / Workcore 一字未动。

### 12.7 这一轮仍然没做的事（不假装测过）

1. **`identityChanged` 与 `state:"gone"` 同时出现仍是有意的**：`ESRCH` 说的是这个数字现在空了，
   `changed` 说的是最后一次答它的进程不是记下的那个；两条各说各的事实，谁也不顶替谁。
2. **身份"第一次被观察到"不等于"spawn 当场"**。根进程的身份在 `spawn` 成功那一刻记；子孙的身份是
   关闭时第一次读到 `/proc` 那一下，因此一个"在关闭之前就已经换过手"的子孙号在本机测不出来 ——
   这条限制与第 6 轮同一条，本轮没有假装解决。
3. **PID 重新发放仍未真实制造**（内核不按需重发号），E21/E22/E24/E25 靠注入；真实进程侧的证据是
   §12.5 的 C/D 与第 6 轮的 S1a/S1b。
4. **Windows 分支未实测**：`unavailable` 与 `unknown` 分开是为了让 Windows 还能回收它的根，
   但这台机器上没有 Windows，那条分支只有代码路径可查。
5. **真实品牌进程仍未执行过**，与前几轮同一条限制。
