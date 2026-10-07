# Qoder ACP 受控探针证据报告（零登录态，P0–P3 + P8）

日期：2026-10-07。执行者：Qoder P2 探针 worker（总协调者授权范围：只读观测）。
被测二进制：`qodercli-1.1.64`（`<HOME>/.qoder/bin/qodercli/qodercli-1.1.64`，
`--version` 输出 `1.1.64`，exit 0）。探针全程隔离 HOME（`mktemp -d` 于
`/tmp/qoder-acp-probe-20261007/`，HOME/XDG_CONFIG_HOME/XDG_DATA_HOME/XDG_CACHE_HOME/
XDG_STATE_HOME/QODER_HOME/TMPDIR 全部指向隔离目录），`env -i` 最小环境
（仅 HOME/XDG/QODER_HOME/TMPDIR/PATH=/usr/bin:/bin/LANG=C.UTF-8），无用户环境变量泄漏。

## 0. 合规声明（先说死）

- **真实模型调用：0 次**。`session/prompt` 从未携带有效 prompt 数组发送；所有
  prompt 探测均为无效参数（缺 `prompt` 字段或 `prompt` 非数组），停在参数校验层。
- **登录/鉴权尝试：0 次**。未发 PAT、未读任何凭据文件、未触碰 `<HOME>/.qoder/.auth`
  用户登录态（隔离 HOME 内进程自建的 `.auth` 目录不在禁令范围——那是探针 HOME 内的
  进程产物，非用户数据）。P3 遇 `-32000 Authentication required` 即止，规则 5 生效。
- **真实 `<HOME>/.qoder` 完好性：已实证未动**。探针前后各做
  `find <HOME>/.qoder -maxdepth 2 -printf '%T@ %p\n'` 全量快照（360 条），P0 后与
  全部三轮结束后各 diff 一次，均为空（REAL_QODER_UNCHANGED）。
- 全程无 push/合并/用户服务操作/`.env` 读取。唯一入库新文件为本报告。
- 证据原件（原始 JSONL/JSON，不入库）：`/tmp/qoder-acp-probe-20261007/` 下
  `p0.stdout.jsonl`、`p0.stderr.txt`、`p0.exitcode`、`p1p3p8-witness.jsonl`（45 帧）、
  `p1-retry-witness.jsonl`（17 帧）、`p8-round3-witness.jsonl`（39 帧）、
  三个 `*-summary.json`、`real-qoder-mtimes-*.txt`。报告只贴方法名/响应码/关键字段，
  用户路径一律脱敏为 `<HOME>`。

## 1. P0：隔离启动，30s 无输入观测

命令（核心）：

```
mktemp -d /tmp/qoder-acp-probe-20261007/home-XXXXXX   # → <PROBE-HOME>
mkfifo <PROBE>/stdin.fifo && ( exec 9> fifo; sleep 90 ) &   # 持开 stdin 但零字节
env -i HOME=<PROBE-HOME> QODER_HOME=<PH>/.qoder XDG_*=<PH>/… TMPDIR=<PH>/tmp \
  PATH=/usr/bin:/bin LANG=C.UTF-8 \
  timeout -k 2 35 <HOME>/.qoder/bin/qodercli/qodercli-1.1.64 --acp \
  < fifo > p0.stdout.jsonl 2> p0.stderr.txt
```

实测记录：

| 项 | 结果 |
| --- | --- |
| 退出码 | **124**（timeout SIGTERM，35.90s；进程在 30s 观测窗内持续存活、阻塞等待 stdin） |
| stdout | **0 字节**——无 banner、无自发 JSONL、无杂质文本 |
| stderr | **0 字节**——启动即静默 |
| 未登录态是否阻塞/报错 | **不阻塞、不报错**。无输入时进程静默等待；鉴权门只在具体方法调用时触发（见 P3） |
| stdout 纯净度 | 观测窗内恒为空 → 无污染。三轮 RPC 会话中 stdout 亦全程纯 JSONL（非 JSON 行 = 0） |

P0 存活判定：**通过**（进程可用、stdio 面干净、未登录不阻断启动）。

P0 期间隔离 HOME 内可见的进程自建产物（全部在探针 HOME，不涉及用户数据）：
`.qoder/.auth/{.credential-transaction,machine_id}`（未登录也生成 machine_id）、
`.qoder/.bin/runtime-info-linux-x64-*`、`.qoder/.cache/{dns-cache,endpoint-cache,
qoder-client-endpoint-cache}.json`（网络端点缓存被写入——是否发生出网连接未验证）、
`.qoder/entry/qoder` + `.rc-written-sentinel`、`.qoder/installation_id`、
`.qoder/logs/runs/<ts>/`、`.qoder/logs/sessions/<cwd-slug>/`（按 cwd 派生会话日志目录）、
`.qoder/tmp/<cwd-slug>/`、`.qoder/tmp/telemetry/active-runs/`、
`TMPDIR/qodercli-natives-v1.1.64-unknown/`（natives 解压到 TMPDIR，含
node_modules/@img、@lydell、@silvia-odwyer 与 vendor/ripgrep；"unknown" 后缀疑因
env -i 无 USER 变量，未深究）。

## 2. P1：initialize 握手

### 2.1 线形发现（与 ACP 常见实现的差异）

首发 `protocolVersion: "1"`（**字符串**，ACP 规范常见形态）→ 拒绝：

```
-32602 Invalid params
data.protocolVersion._errors: ["Invalid input: expected number, received string"]
```

`protocolVersion: 1`（**数字**）→ 成功。**Qoder 的 protocolVersion 必须是 JSON number**，
这是与 codex-acp（字符串 "1"）等实现的线形分歧，装配侧不得照抄别家形态。

### 2.2 initialize 成功应答（关键字段）

```
result.protocolVersion = 1                       # 数字回显
result.authMethods = [{ id: "qodercli-login",
                        name: "Use qodercli login",
                        description: "Use your existing qodercli login for this
                        agent. If needed, sign in from qodercli first." }]
result.agentInfo = { name: "qoder-cli", title: "Qoder CLI", version: "1.1.64" }
result.agentCapabilities = {
  _meta: { qoder: { promptQueueing: true } },    # 厂商扩展位
  loadSession: true,
  sessionCapabilities: { additionalDirectories: {}, close: {}, delete: {},
                         fork: {}, list: {}, resume: {} },
  promptCapabilities: { image: true, embeddedContext: true },
  mcpCapabilities: { http: true, sse: true }     # 无 "acp" 位
}
```

鉴权要求（P1 面）：initialize **本身不要求登录**；应答仅广播**单一** authMethod
`id="qodercli-login"`（即复用 CLI 登录态，非 PAT 形态——PAT 是否映射到同一 methodId
未验证）。后续 session 系方法被鉴权门挡住（P3）。

stderr 注意：每个失败请求会在 stderr 打印 Node 风格 `Error handling request {…}`
调试转储（三轮合计 3430 + 842 + 3242 字节）。**stderr 非 JSONL，客户端不得解析 stderr
为协议流**；stdout 始终纯净。

## 3. P3：session/new → 遇鉴权门，止于 P3

`session/new { cwd: <PROBE>/cwd, mcpServers: [] }` → 应答：

```
-32000  "Authentication required: Authentication is required."
```

- **鉴权止点：P3**（规则 5 生效分支）。未尝试 `authenticate`/PAT/登录态读取，
  未发任何 prompt。
- **sessionId 形态：UNKNOWN**（未登录不可得）。这关闭不了"sessionId 是 uuid 还是
  slug"类问题，登记为剩余缺口。
- 参数校验先于鉴权门：无效参数的 `session/new` 回 `-32602`（字段级错误），合法参数
  才回 `-32000`——顺序观察明确，装配侧可用 `-32602/-32000` 区分校验层与鉴权层。

## 4. 终止面观察（无 session 态，仅方法存在性/参数面）

| 方法 | 实测 |
| --- | --- |
| `session/terminate` | **-32601 Method not found**（ACP 标准客户端方法，Qoder 缺席） |
| `session/cancel` | **-32601 Method not found**（同上，中断面缺席） |
| `session/close` | **方法存在**：-32602，`sessionId` 必填 string（能力面 sessionCapabilities.close 与方法面对齐） |
| stdin EOF | 进程 **exit 0** 干净退出（收尾路径无悬挂） |

即：Qoder ACP 的终止/清理面是 **`session/close`**，而非 ACP 标准的
session/terminate + session/cancel 组合；会话内中断（interrupt）路径在 ACP 面无对应
方法，SDK 文档提到的 interrupt 属另一协议面（stdio JSONL control），未在本探针验证。

## 5. P8：方法能力矩阵（逐方法无效参数，仅记响应码）

三轮共发 **32 次 JSON-RPC 请求**（P0 观测 0 请求；round1=14、round2=5、round3=13），
全部收到应答（无 NO_RESPONSE）。判定规则：`-32601`＝不支持；`-32602`＋字段错误＝
支持（参数被 schema 校验，附观测到的必填字段）；`-32000`＝支持但鉴权门。

实测确认的 Qoder ACP 方法子集（**只列实测确认项**）：

| 方法 | 判定 | 实测证据（参数校验面） |
| --- | --- | --- |
| `initialize` | 支持 | protocolVersion 必须 number；clientCapabilities 含 fs/terminal 接受 |
| `authenticate` | 支持 | -32602 `methodId` 必填 string |
| `session/new` | 支持（鉴权门） | -32602 `cwd`(string)、`mcpServers`(**array 必填**)；合法参数→-32000 |
| `session/load` | 支持 | -32602 `cwd`、`mcpServers`(array)、`sessionId`(string) 全必填 |
| `session/prompt` | 支持 | -32602 `prompt`(**array 必填**，parts 数组)；sessionId 给 string 时无字段错（校验层通过，未到会话层） |
| `session/close` | 支持 | -32602 `sessionId` 必填 string |
| `session/delete` | 支持 | -32602 `sessionId` 必填 string |
| `session/fork` | 支持 | -32602 `cwd`、`sessionId` 必填 |
| `session/resume` | 支持 | -32602 `cwd`、`sessionId` 必填 |
| `session/list` | 支持（鉴权门） | 空参数即过校验 → -32000（参数面宽松，业务面被鉴权挡） |

实测确认**不支持**（-32601 Method not found，响应 data.method 回显方法名）：

| 方法 | 备注 |
| --- | --- |
| `session/cancel` | ACP 标准客户端方法，缺席 |
| `session/terminate` | ACP 标准客户端方法，缺席 |
| `session/update` | agent→client 通知，agent 侧无此入站方法（方向性缺席，属预期） |
| `session/additionalDirectories` | 能力面有 `sessionCapabilities.additionalDirectories:{}` 但无同名方法——**能力对象≠方法名**，机制未知 |
| `session/setMode` | 无 |
| `session/set_permissions` | 无（权限面方法名未知） |
| `session/request_permission` | 无 |
| `fs/readTextFile` / `fs/writeTextFile` | agent 侧无入站实现（ACP 中属 agent→client 方向，预期） |
| `terminal/create` / `terminal/output` / `terminal/kill` | 同上（方向性缺席） |
| `qoder/nonexistent-method` | 对照组：-32601，证明 -32601 语义为方法不存在 |

矩阵小结：**支持 10 项 / 不支持 16 项（含 1 对照）**；鉴权门后的行为（成功路径、
session/update 通知流、权限应答、fork/delete/list/resume 实际效果）全部未验。

## 6. 与文档的差异（对照 acp.md 文档核查结论，status.md §Qoder ACP文档核查）

| 文档/既有认知 | 探针实测 |
| --- | --- |
| ACP 方法集文档缺席（G1），不得推测 | 本报告给出实测子集矩阵（§5）：方法集**非 ACP 标准全集**，Qoder 自有裁剪＋扩展 |
| 协议细节外链规范页 | 线形分歧实测：protocolVersion 必须 number；`session/new.load` 的 `mcpServers` 为 **array 必填**（与 codex-acp t00 探针发现的"缺字段即 -32602"同型） |
| 鉴权 PAT/浏览器登录 | ACP 面仅一个 authMethod `qodercli-login`（复用 CLI 登录）；`authenticate.methodId` 必填 string；session 系方法 `-32000` 挡驾。PAT 在 ACP 面的映射未验证 |
| （文档未言） | 新发现：无 `session/cancel`/`session/terminate`，终止面为 `session/close`；`sessionCapabilities` 广播 6 项但 `additionalDirectories` 无对应方法；`promptQueueing` 为 `_meta.qoder` 厂商扩展位；`mcpCapabilities` 仅 http+sse 无 acp 位；stderr 带 JS 调试转储非 JSONL；stdin EOF 干净 exit 0；启动即向 HOME 写 `.auth/machine_id`、端点缓存、telemetry 目录 |
| 版本口径 | 本次实测 **1.1.64**（本机已装）；文档核查记录 npm latest 1.1.65——版本偏移未对齐，登记 |

## 7. G1–G11 未知点：本次关闭/未关闭

> 说明：G2–G11 清单原文在树内 status.md 仅存指针（"G2-G11未知点清单已登记"，清单
> 本体未落树内文档）。下表按 status.md §1175-1183 的语境映射；总协调者如有清单原文
> 请复核编号对应。

| 未知点 | 状态 | 依据 |
| --- | --- | --- |
| G1 ACP 方法集文档缺席 | **部分关闭** | §5 实测矩阵：10 支持/16 不支持，方法集现为实测确认（非推测）；但鉴权门后成功路径未验，矩阵非全生命周期 |
| 鉴权面（语境推断的 G 系项） | **关闭（无登录态分支）** | initialize 不要求登录；单一 authMethod=qodercli-login；session 系 -32000；参数校验先于鉴权 |
| 会话生命周期方法面（推断） | **关闭（方法存在性层）** | new/load/prompt/close/delete/fork/list/resume 存在；cancel/terminate 缺席 |
| MCP 能力面（推断） | **关闭（广告层）** | mcpCapabilities={http:true,sse:true}；mcpServers 必填 array；真实注入行为未验（需登录） |
| prompt 能力面（推断） | **关闭（广告层）** | promptCapabilities={image:true,embeddedContext:true}；prompt 为 parts 数组 |
| 终止/中断面（推断） | **关闭（方法面）** | close 存在，cancel/terminate 缺席，EOF exit 0 |
| G11 npm 1.0.50 / PyPI 1.0.15 不同步 | **未关闭** | registry 问题，与 ACP 探针无关，仍挂起 |
| CN/INTL 双包口径 | **未关闭** | 本机仅测 INTL 变体二进制 |
| SDK 服务条款许可再分发审查 | **未关闭** | 许可审查项，探针范围外 |

## 8. 剩余缺口（不得据本报告推断的部分）

1. **sessionId 形态**（P3 鉴权止点，UNKNOWN）。
2. **authenticate 成功流**：methodId="qodercli-login" 的实际交互（浏览器跳转/PAT 接受面）
   ——需登录授权，未验。
3. **session/prompt 真实派发**、session/update 通知流形状、权限请求/应答面、附件、
   resume/fork/delete/list/close 的成功路径——全部需登录态，未验。
4. `sessionCapabilities.additionalDirectories` 的真实机制（无同名方法；疑为
   session/new 的参数位或其他方法名，未验）。
5. `_meta.qoder.promptQueueing` 语义未验。
6. agent 是否会向 client 发起 fs/terminal 入站调用（ACP 方向性预期有，Qoder 实现未验）。
7. 启动期端点缓存写入是否伴随真实出网连接（未做网络层观测）。
8. 版本偏移：实测 1.1.64 vs registry 1.1.65；矩阵是否逐版本成立未验。
9. G2–G11 清单原文未落树，本报告 §7 的编号映射需总协调者按清单原文复核。

## 9. 命令与计数汇总（回报面）

- 探针进程：4 个（P0 观测 1 + P1/P3/矩阵轮 3），全部 `env -i` 隔离 HOME 启动。
- RPC 请求总数：**32**（P0=0，round1=14，round2=5，round3=13），全部收到应答。
- 方法矩阵：**26 个方法名实测**（25 候选 + 1 对照），支持 10 / 不支持 16。
- 退出码：P0=124（timeout 杀）；三轮 RPC 会话 stdin EOF 后均 exit 0；无残留进程
  （pgrep 复核 NO_LEFTOVER）。
- 真实 `<HOME>/.qoder` 前后快照 diff 为空（360 条目，两处复核）。
- **无模型调用声明：真实模型调用 0 次；无登录尝试 0 次；无凭据读取 0 次；
  无 push/合并/用户服务操作。**
- 未验范围：§8 全部 9 项。

（本报告为本次任务唯一入库新文件；探针脚本与原始证据仅存隔离 tmp，未入库。）
