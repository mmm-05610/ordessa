# agent-box-harness

## Package layout (2026-09-24)

This is the **only Harness distribution**. The previous `agent-box-harnesses`,
`agent-box-harness-dsh`, `agent-box-harness-qwen` and `agent-box-harness-kilo`
directories have been consolidated here; brands are internal modules.

```text
agent-box-harness/
  pyproject.toml                  # one distribution, existing six registrations
  src/agent_box_harness/
    plugin.py, entrypoints.py     # unchanged public registration semantics
    registry/, adapters/         # declarations, common adapter contracts
    generic/, resources/         # existing shared implementation
    codex/, pi/, claude/, hermes/, opencode/, dsh/, qwen/, kilo/
    native_materialization.py    # existing configuration logic, unchanged
    qoder/, importers/           # existing helpers, not new support claims
    _compat.py                  # aliases only, no duplicated implementation
  src/agent_box_harnesses/       # old import name only
  src/agent_box_harness_{dsh,qwen,kilo}/ # old import names only
  runtime/                      # 接入运行：被 sidecar 执行的桥接代码 + 必要运行资源
    access-entry.mjs            # 唯一生产入口（发现/连接/透明 transport/状态/关闭）
    access-transport.mjs        # 连接句柄：一个连接、一对管道、进程归它所有
    native-driver.mjs, profile_extensions.mjs,
    subagent-bridge.mjs, capability_declarations.json, package.json,
    drivers/opencode-native.mjs
  harnesses/                    # 品牌差异：每品牌一份 launch.mjs + 统一 index.mjs
    index.mjs                   # listHarnesses / isKnownHarness / harnessLaunchContext
    {claude,claude-code,codex,dsh,hermes,kilo,omp,pi,qwen}/launch.mjs
  deploy/                       # 运行链读取的原生配置模板 + 已标注的旧隔离 guard
    README.md                   # 逐文件消费方核查（运行链 / 兼容资产 / 待定性）
  third_party/harness_remote/   # 桥接快照（21 → 10 文件），随视图打包并在校验后使用
    SOURCE.json                 # 逐文件 sha256；启动时全部核对
    PATCHES.md                  # §1/§5/§7 既有补丁，§8 transportOnly，§9 快照裁剪
  packaging/                    # 可选安装打包：npm 根、锁、vendor、SBOM、安装器 provenance
    README.md                   # 为什么运行链不读这里
  tests/
  REMOVALS.md                   # 旧运行链移除清单与恢复位置
  DELIVERY.md                   # 交付报告：接口、移除与恢复、包外旧→新对照、实测数字
  tests/RETIRED.md              # 被删用例 → 替代覆盖逐条对照
```

## Harness 接入的公开接口（transport-only）

统一入口是一个 **NDJSON 进程**：`node runtime/access-entry.mjs`（隔离环境）或
`… --native`（显式原生模式，二者互斥）。**一个进程一条连接**——字节透明的中继若要多路复用
就必须给帧打辨别戳，那正是本入口要取代的信封。

stdin 上一行若解析出的对象带字符串 `op`，**且不含 `jsonrpc`/`method`/`result`/`error` 任一字段**，
它是控制请求；**其它任何行都是 ACP 帧，按原字节转发**。判别只看结构、不看业务词汇表，且这条规则
只会把一条消息从控制面挪到数据通道：一个结构合法的 JSON-RPC 帧即使带了 `op` 扩展字段也走数据通道
（E13 钉住，`op` 与其余扩展字段逐字到达 Agent 并原样返回）。
控制词汇只有四个：

| `op` | 返回 |
| --- | --- |
| `harnesses` | `{provenance, harnesses[], transport}`，无需先连接 |
| `connect` | 连接句柄：`{connectionId, harness, transport, launch{source:"explicit"}, discovered, state, provenance}`；建立中再来一个 `connect` 以 `ACP_CONNECT_IN_PROGRESS` 拒绝（E10） |
| `status` | `{connected, state, processId, framesToAgent, framesFromAgent, ended}` |
| `close` | `{connectionId, released, processId, signalUsed, tree}`（仍有进程未确认退出时 `unreleased[]`，每项带自己的 `tree`），回收**本入口这次启动开出的整棵进程树** |

`released` 由操作系统说了算，且证明到进程树这一层。POSIX 上这次启动以 `detached` 自成一个进程组，
这条事实与"回收范围"读同一个常量 `PROCESS_GROUP_OWNERSHIP`：能自成一组才按 `tree` 声称回收，不能就
按 `root-only`，两边不会各说各话。回收对象 = 组号等于根 pid 的全部进程（含父进程先退出后被领养的
孤儿）∪ 沿 PPid 从根走下来的全部子孙；**"已收集成员"与"已遍历节点"分开去重**，同组成员仍要继续下探，
否则"同组子进程下面那个逃组的孙进程"永远找不到。组内成员由一次 `kill(-rootPid, …)` 达到，组外成员
逐个发。`SIGTERM` → 2s 宽限 → `SIGKILL` → 2s，每 20ms 重新观察一次进程表。**只有 `ESRCH` 算确认
退出**：`EPERM` 算活着，其它任何错误码单列为 `unconfirmed`，既不算死也不算活，但一定让
`released:false`。`tree` 就是这份回执
（`{available, scope, reason, groupPid, members:[{pid,group,currentGroup,state,code,check,identity}], survivors[], unconfirmed[], identityChanged[]}`），
`released:true` 要求 `survivors` 与 `unconfirmed` 同时为空，且声称的 `scope` 不小于这次回收。

发信号之前还要**核对进程身份**：pid 只是一个会被重新发放的数字，同用户的新进程可以被成功误杀，
所以记的是 `(pid, /proc 启动时间)`，在 `spawn` 成功那一刻记一次、之后不再改写。核对结果不是布尔而是
三态——`matched`（核上了）、`changed`（数字还在但启动时间已换，即当初那个进程确实没了）、`unknown`
（这份记录此刻核不了）。**只有 `matched` 允许发破坏性信号**：`changed` 一个信号都不发、单列进
`identityChanged`；`unknown` 也一个信号都不发，记为 `unconfirmed:[{pid, code:"IDENTITY_UNKNOWN"}]`
并回 `released:false`（"核不了"不等于"核上了"，把前者当后者就是这个入口存在的意义被抹掉）。
唯一例外是 `ESRCH`：操作系统已经答了这个数字上是空的，这跟是谁的身份无关，照旧算确认退出。
组号同样只是个数字，所以组信号的证人是**当前表里仍在该组、且当前身份核得上**的成员，
不是"第一次观察时见过它在那个组"——成员中途 `setsid()` 离开，那个号就不再是本回收的组，它自己改逐个发。
读不到进程表（无 `/proc`）时 `available:false`：按 `tree` 声称的回收直接
`released:false` + `reason:"PROCESS_TABLE_UNAVAILABLE"`（根进程消失证明不了它开出的子进程），
只有本来就只声称 `root-only` 的才可以回 `true`，`scope` 留在那儿挡住任何把它读成整棵树的人。
平台压根不记这份身份（`PROCESS_IDENTITY_AVAILABLE` 为假）是另一件事：核对结果为 `unavailable`，
回收照自己的 `root-only` 声称继续，而不是原地停住。
确认不了就报 `released:false` 并保留 `processId` 与句柄，绝不把"信号发出去了"或"桥自己忘了孩子"
说成"进程死了"。
回收只认这两路身份（组号、PPid 血缘）与一次启动记下的 `(pid, 启动时间)`，不按命令行或工作目录清扫，
因此同机同目录跑着同样命令的无关进程不受影响（E19）。上面每一条各有一条反例钉住：
E14/E9b 错误码与树 API · E15 读不到进程表时两种声称各自的结局 · E16–E18 子进程、被领养的孤儿、
逃组的子进程 · E20 同组成员之下逃组的孙进程 · E21 数字被重新发放 · E22 组信号要有核得上身份的证人 ·
E23 孤儿 + 逃组孙进程同时成立（两条收集规则缺一不可）· E24 身份读不到时不发任何破坏性信号（且 `ESRCH`
仍算退出；第三段钉判定顺序：身份核对排在探活答出的错误码之前，"核不上 + `EACCES`"照旧一个信号都不发）·
E25 成员已离开原组：既不能替组作证，也不会因此被漏掉。

出站只有两类：控制回复 `{id, ok, result|error}`，以及事件
`{event:"transport_end"|"stderr"|"transport_malformed"|"process_release_unconfirmed", data, connectionId}`。
`process_release_unconfirmed` 只在 stdin EOF 收尾时仍有进程未确认退出才发——不会静默丢弃，也不会谎报。
建立连接**不发送任何 ACP 帧**：`initialize` / `authenticate` / `session/new` / `session/prompt`
全部由调用方自己写；Agent 自己发起的请求（含权限请求）原样到达调用方，调用方不回就一直不回。

**顺序是契约的一部分**：控制请求不阻塞读循环（否则 Harness 死掉后 `close` 就答不上了），
所以调用方应**等到 `connect` 的回复**再写 ACP 帧；在没有连接时写入的帧会被如实回以
`ACP_NOT_CONNECTED`（E3 钉住），本入口不排队、不猜测、不代答。因此调用方是一段有状态的循环，
而不是一条管道：

```js
// 隔离环境：env AGENTBOX_SIDECAR_ISOLATED=1；宿主机直跑：改用 "--native" 且不要设那个 env。
// 两者都不满足时入口不开 stdin，直接回 SIDECAR_ISOLATION_REQUIRED。
const child = spawn(process.execPath, ["runtime/access-entry.mjs", "--native"],
                    { stdio: ["pipe","pipe","pipe"] })
const send = (line) => child.stdin.write(`${JSON.stringify(line)}\n`)

send({ id: 1, op: "connect", harness: "codex", directory: "/srv/project",
       // 用 discovery 给出的 launch 就等于接受网络取包；离线部署要显式点名工件入口
       launch: { command: "/opt/adapters/codex-acp/bin/codex-acp", args: [] } })
// …读回 {"id":1,"ok":true,"result":{connectionId,transport:"acp-stdio-jsonrpc/1",…}} 之后才可以：
send({ jsonrpc: "2.0", id: 1, method: "initialize",
       params: { protocolVersion: 1, clientCapabilities: {} } })
send({ jsonrpc: "2.0", id: 2, method: "session/new",
       params: { cwd: "/srv/project", mcpServers: [] } })
// Agent 自己发起的请求（session/request_permission 等）会以它发出的原帧出现在 stdout 上；
// 不回应就一直没有回应，本入口不代答、不超时、不伪造 cancelled。
send({ id: 3, op: "close" })
```

`connect` 只接受 `harness` / `launch{command,args,environment}` / `directory` /
`credentialEnvironment`。旧信封的 `profile`、`stateDirectory`、`permissionRoundTrip`、
`permissionTimeoutMs`、`preferredAuthMethod`、`driver`、`sessionId`、`text`、`model` 等
一律以 `ACP_CONNECT_FIELD_RETIRED` **按名拒绝**（不是忽略）；品牌启动路由由
共享描述符和 profile 表决定，调用方的具体启动参数仍在 `launch` 中；入口本身
不含任何品牌名。

`src/ordessa_harness/launch-descriptors.json` 是 Python registry loader 与 JS access
index 共用的 canonical/alias 路由清单。`registry_identity_version_matches()` /
`registryIdentityVersionMatches()` 只比较 TOML 声明的 identity version；返回
`true` 不证明已安装的 native/adapter 版本或运行能力。别名版本没有这份声明的证明，
返回 unknown (`None`/`null`)。`access-entry-files.json` 列出 sidecar
入口运行所需的相对路径；仓内 staged-copy 测试按该清单运行真实入口。当前产品接线
使用传入的 `plugin_root`，没有消费这份清单的发布器，发布时仍须确保整个目录闭包
随入口部署。

端到端行为由 `tests/access/acp_passthrough_target.test.mjs`（T1–T10）与
`tests/access/access_entry_behavior.test.mjs`（E1–E13）钉住。



`runtime/` 与 `deploy/` 属于接入运行：主运行链按部署文档里显式声明的
`adapter.command` / `adapter.args` / `adapter.driver` 与
`projectionFiles[].source` 读它们。`packaging/` 属于可选安装打包：只在人工
执行 `npm ci` / 构建 Agent 工件时被读取，**主运行链从不读它**，缺失也不会
触发任何自动安装或路径猜测。运行链需要的 `runtime/package.json` 只承载
sidecar 视图自身的 ESM 包根信息，依赖钉版按品牌各自一份
（`packaging/codex/`、`packaging/pi/`）。

Install this distribution instead of the four retired ones. Existing upper-layer
`agent_box_harnesses.*` imports remain supported and resolve to the same canonical
module objects. Do not install old distributions alongside this one in a fresh
environment. Existing environments need an explicit uninstall of retired
distributions before reinstalling this package; no user environment is changed
by this source-tree migration.

For checkout-based Server startup use `--plugin-root "$PWD/plugins/agent-box-harness"`.
All other Server options remain unchanged. Runtime artifacts retain their prior
separate build procedure; consolidation does not build an ACP adapter or install
Agent CLIs. No Profile, provider, protocol, or session behavior is added here.

The following existing capability documentation is retained; it is not a claim
that every brand has been live-tested by this consolidation.

This is the single Harness distribution. It contains Codex, Claude Code,
OpenCode, Hermes, and Pi native adapters, all discovered through the shared
versioned registry and unified `harness-profile` store.

The official multi-Harness extension package. Codex is currently the first
official Harness integration.
It owns the Codex Harness descriptor, versioned Profile repository, exact
`ProfileRef`, selector, digest validation, and execution-scoped projection.

The Harnesses distribution is the sole Codex owner. It directly registers the
App Server and tmux interactive modes and owns profile, projection,
credential-locator, and launch-spec handling.

Native continuation is represented by the Harness-owned
`codex-continuation` ResourceProvider. A continuation candidate is only
offered from a terminal Execution with an observed native SessionRef; it
creates a new Execution and never reopens the source.

Build from a clean checkout with the Web static tree first, then build the
Web and Harness wheels:

```sh
npm --prefix ../agent-box-web/frontend run build
python3 -m build
```

Profiles are immutable JSON revisions under the plugin data directory. Only
non-secret configuration and credential locators are accepted. The projection
manifest contains identity and references, never credential values.

Codex official subscription login uses the fixed `codex-login/default`
`CredentialRefV1` locator. Dispatch prepares an execution-scoped read-only
SecretMount for `/runtime/home/auth.json`; no auth symlink, path, value, hash,
or raw credential editor is supported. Other Harness credential materializers
remain deferred.
