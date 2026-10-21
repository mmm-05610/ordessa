# T06：工具操作 + 成果取回（codex 原生会话，2026-10-21）

结论：**PARTIAL** —— **工具调用事件真实出现在原生消息里**（模型确实调用了 `exec` 去执行
`apply_patch`），但**产物没有创建**：codex provider 把原生 `thread/start` 固定为
`sandbox=read-only` + `approvalPolicy=never`，工具写入被沙箱**在源头拒绝**。
独立取回（Server 的 `environments.files`）证实 `tools-proof.txt` **不存在**；同一通道读回控制文件
`t06-control-pre.txt` = `t06-control-ok`，证明取回通道本身可用。

通道：**codex/ChatGPT 登录（已批准）**。真实模型调用：**1/2**（计数器 `/tmp/t06-budget.txt` = `1`）。

**不允许的替代**：模型自称"无法创建"没有被当作证据；文件是否存在由 Server 侧
`environments.files` 独立判定（结果同样是不存在），两侧结论一致。

---

## 第 1 步：单轮形态

真实 `ordessa-server`（`--service-config`）＋ 真实 `ordessa` 客户端（wire/1 bearer）＋ 真实本地环境
＋ 真实 codex app-server 线程 ＋ **一次真实模型调用**。

```
environments create local --root /tmp/t06-tools-codex/work
environments.files write/cat t06-control-pre.txt      -> 控制往返（不涉及模型）
environments.acquire -> environments.export-endpoint  -> endpointRef
agents.start (sessionMode=fresh)                      -> sessionId 01a15c58-1edc-7592-96cb-625b4273b2d3
agents.prompt "创建 tools-proof.txt 并读回"            -> 真实模型调用 #1
（等待原生 rollout 写出 task_complete 后解析）
agents.stop -> agents.reconcile -> environments.process-release -> environments.release
environments.files ls / cat tools-proof.txt           -> 独立取回
```

服务配置（`raw/t06-tools-service-config-codex.json`，**只有引用、没有明文密钥**）：

```json
{"harness": {"allowlist": ["codex"],
             "providers": {"codex": {"command": ["/home/maoqh/.local/bin/codex"]}}}}
```

Profile：`credential-binding-1`（`credentials.file` → `~/.codex/auth.json`，只有路径）＋
`codex-model-1`（`codex.configuration` → `model = gpt-5.6-sol`）。

实例：`instance-35bb21b49c3349c3a0339a3253aa3b1d`（namespace `server`），
`bindingDigest = sha256:1492ec903f9c5fdfeabd0bb1bd0d9a0b120240a13531a7951adca1111eb5f8e5`。

---

## 第 2 步：prompt 与模型 answer

prompt（逐字，`agents.prompt` 的 `params.prompt[0].text`）：

```
在你的工作目录创建文件 `tools-proof.txt`，内容写 `ordessa-tool-ok`；然后用命令读取它并只回复文件内容。
```

| 项 | 值 |
| --- | --- |
| prompt operationRef | `agent-operation/f8a260c70a984790890f24410db86e1e` |
| turnId（服务端） | `turn/f2c3bda26c1e447185672228849ebfec` |
| 原生 turnId | `01a15c58-204b-7053-b29a-76da66501a6b` |
| turnStatus / delivery | `completed` / `confirmed` |
| bytesSent / items | `328` / `1` |
| inputDigest | `sha256:750afaab54082853d0457c5628f698ceeca64cb6ffd8c5f034787688055998db` |
| observationDigest | `sha256:a9ca5ada489b61a42ba621cafcc0b50a756b78b257a05990c10785a8a432f561` |
| endpointOperationRef | `environment-operation/47f66c1dff0f46bcac51af6006985efc` |
| **answer** | **`无法创建：当前工作目录为只读。`** |

`observationBytes`（逐字）：

```json
{"answer": "无法创建：当前工作目录为只读。", "bytesSent": 328, "delivery": "confirmed",
 "items": 1, "method": "turn/completed", "protocol": "codex-app-server/1",
 "turnId": "01a15c58-204b-7053-b29a-76da66501a6b", "turnStatus": "completed"}
```

---

## 第 3 步：native 工具事件清单

原生 rollout：`work/home/sessions/2026/10/21/rollout-2026-10-21T10-44-01-01a15c58-1edc-7592-96cb-625b4273b2d3.jsonl`
（文件名里的 id = `agents.start` 返回的 `sessionId`；`session_meta.originator=ordessa-cli`、
`cwd=/tmp/t06-tools-codex/work`）。25 条记录，0 条坏行。

**工具调用（逐字，`response_item/custom_tool_call`，name=`exec`，callId=`call_8c8dd0e4639e4dd99582219fd3a14a95`）**

输入：

```
const patch = "*** Begin Patch\n*** Add File: tools-proof.txt\n+ordessa-tool-ok\n*** End Patch";
const r = await tools.apply_patch(patch);
text(r);
```

输出（`response_item/custom_tool_call_output`，两段逐字）：

```
Script failed
Wall time 0.0 seconds
Output:
```
```
Script error:
patch rejected: writing is blocked by read-only sandbox; rejected by user approval settings
```

**同一回合的原生记录序列**（`event_msg/item_completed` 与 `response_item`，按时间顺序）：

| # | item 类型 | 内容摘要 |
| --- | --- | --- |
| 1 | `UserMessage` | 上面的 prompt |
| 2 | `AgentMessage`（commentary） | `我会创建该文件，再通过命令读取并核对内容。` |
| 3 | `Reasoning` | 空 summary（推理不落明文） |
| 4 | `custom_tool_call`（`exec`） | `apply_patch` 建 `tools-proof.txt` —— 工具操作**已真实发起** |
| 5 | `custom_tool_call_output` | `patch rejected: writing is blocked by read-only sandbox; rejected by user approval settings` |
| 6 | `Reasoning` | 空 summary |
| 7 | `AgentMessage`（final_answer） | `无法创建：当前工作目录为只读。` |

**为什么写不进去（根因，两层证据）**

1. 原生 `turn_context`（逐字字段）：

   ```json
   {"approval_policy": "never",
    "sandbox_policy": {"type": "read-only"},
    "permission_profile": {"type": "managed",
                           "file_system": {"type": "restricted",
                                           "entries": [{"path": {"type": "special",
                                                                 "value": {"kind": "root"}},
                                                        "access": "read"}]},
                           "network": "restricted"},
    "model": "gpt-5.6-sol"}
   ```

   即整个文件系统只读、网络受限、且没有审批通道（`never`）→ 写入没有获批的可能。

2. 源码：`plugins/harness/codex/src/ordessa_harness_codex/provider.py:105-106` 把
   `thread/start` 写死为 `{'approvalPolicy':'never','sandbox':'read-only'}`；同文件 `:55-56`
   又拒绝 profile 里除 `model` 以外的 thread 参数（`SESSION_CONFIGURATION_UNAVAILABLE`），
   所以**通过 Profile 放开 sandbox 目前也不可能**。这是本轮最硬的产品结论。

   这不是本轮引入的，也不是环境能力问题：`environments.exec`/`files` 在该环境里可读写
   （控制文件就是用 `files write` 写进去、`files cat` 读回来的）。

---

## 第 4 步：独立取回证据（Server `environments.files`）

> **身份说明（必须先读）**：本轮脚本在 `agents.query` 前因*脚本自身*的解释器错误（见第 5 步）退出，
> 原 Server 被脚本收尾终止，原环境的独占 Use 再也没被释放（`release` → `pending`
> `ENVIRONMENTS_ORIGINAL_HANDLE_UNAVAILABLE`）。原环境身份上的 `files` 因此被 Use 栅栏拒绝
> （`EFFECT_UNKNOWN`）。物理 work 根 `release` 不销毁（`rootPreserved=true`），
> 所以取回改为**同一个物理根**、**新 Server + 新数据根**、**新本地环境身份**
> `environment/004f5173f9d14e02b7827f296cf6dd66`（`backendId=/tmp/t06-tools-codex/work`）。
> 读的是同一目录的真实字节，但**不是**原环境身份——这一点如实登记，不冒充。
> 另外，`files` 处理器把 acquire 失败统一折叠成 `EFFECT_UNKNOWN`（"file Use unavailable"），
> 因此原身份上被拒的**原始原因**没有出现在回执里；栅栏来自 `store.reserve_use` 的规则
> （`uses and (not sharing or any(not use[0] for use in uses))` → refused），这是我从规则读出的，
> 不是回执显式给出的。

| 检查 | 结果 |
| --- | --- |
| `environments.files ls` | `completed`，**77** 条条目 |
| 其中是否列出 `tools-proof.txt` | **否**（`artifactListed=false`） |
| 其中是否列出 `t06-control-pre.txt` | **是**（`controlListed=true`） |
| `environments.files cat tools-proof.txt` | `status=unknown`、`error.code=EFFECT_UNKNOWN`（文件不存在：`LocalFileArea.read_text` 抛 `FileNotFoundError`，被映射成 `EnvironmentOperationUnknown`） |
| `environments.files cat t06-control-pre.txt` | `completed`，`content = "t06-control-ok"`（证明读通道确实读的是这个 work 根） |
| 宿主机直读 | `/tmp/t06-tools-codex/work/tools-proof.txt` **不存在** |
| 原环境身份（`environment/c48e3ade2ea3431b9e7597c0fd6c1bb0`）上的控制往返（回合前） | `files write` completed（14 B）；`files cat` completed = `t06-control-ok`，`matches=true` —— 读通道在原环境身份上**当时就能用** |

请求的期望内容（用于将来成功回合的比对，本轮**没有字节可比**）：

| 项 | 值 |
| --- | --- |
| 期望内容 | `ordessa-tool-ok`（15 B） |
| 期望 sha256 | `sha256:585b62bb7a3e776473d3d81d718df4a7a0bb3f2a1a8da53e8c88a9de500f0450` |
| 实际产物 | **不存在**（无路径、无字节、无 sha256） |
| 控制文件 | `t06-control-pre.txt`，14 B，`sha256:2338fa885eceb380e2446f204440d6220c26c83e76b8b5a1ecd42b925b6b5645` |

`files ls` 的顶层条目（`entrySample`，截断）：

```
["t06-control-pre.txt", "home/.sandbox_migration", "home/auth.json", "home/goals_1.sqlite",
 "home/sessions/2026/10/21/rollout-2026-10-21T10-44-01-…jsonl", …]
```

—— 控制文件在、原生 rollout 在、**`tools-proof.txt` 不在**。

---

## 第 5 步：清理

**先说缺陷**：本轮脚本 `tmp/t06_tools.py` 用系统 `python3` 启动，`agents.query` 的
`query_projection()` 需要 `ordessa_agents`，于是抛 `ModuleNotFoundError: No module named
'ordessa_agents'`（脚本收尾的 `finally` 终止了 Server，`serverExitCode=-15`）。因此
`stop → reconcile → process-release → release` 这条链**没有在当轮执行**，`agents.query` 也没跑。
修复方式：用 `.venv-w1/bin/python` 运行（若重跑）。

重启同一个数据根补做清理（`raw/t06-tools-recovery.json`）：

| 步骤 | 结果 |
| --- | --- |
| `agents.get`（我传了 `instanceRef`） | `refused / INVALID_INPUT` —— **我的输入错误**：`agents.get` 的入参是 `startRequestId`（`packages/execution/agents/src/ordessa_agents/capability/instances.py:79`） |
| `agents.reconcile` | `unknown / EFFECT_UNKNOWN`（实例的运行时句柄随第一个 Server 进程消失） |
| `agents.stop`（force） | `unknown / EFFECT_UNKNOWN`（同上） |
| `environments.process-release` | `refused / PERMISSION_DENIED`（endpoint 由已消失的 issuer 进程签发） |
| `environments.release` | `accepted / pending`，`code=ENVIRONMENTS_ORIGINAL_HANDLE_UNAVAILABLE` |

第二遍用正确入参复查（`raw/t06-tools-instance-get.json`）：

- `agents.get {"startRequestId":"start-1"}` → `completed`，**`state=running`**，但此时该实例的
  codex 进程已经不存在（`/proc` 扫描为空）。→ 崩溃重启后实例记录**不会**自动纠正为 `exited`，
  `reconcile` 也无法给出退出观察。这是本轮发现的**真实恢复缺口**，已如实登记。

**进程残留检查**

- 按 `cwd` 落在 `/tmp/t06-tools-codex/**` 扫描 `/proc`：**`[]`**（本轮 codex app-server 与
  子进程都不在了；它们随第一个 Server 的终止一起退出）。
- 宿主机上仅剩**用户自己**的 VS Code 扩展 codex（PID `1892946`，
  `…/openai.chatgpt-26.1007.21434-linux-x64/bin/…/codex -c features.code_mode_host=true app-server`），
  回合前后都在，**未被触碰**。
- 本轮启动的 Server 进程均由脚本收尾终止（exit `-15`）。
- 遗留：原环境的独占 Use 仍是 `active` 栅栏（`release` 只能停在 `pending`），
  环境资源目录本身按契约保留（`resourcePreserved=true`、`rootPreserved=true`）。目录在 `/tmp` 下，
  不含用户数据。

**密钥纪律**

- 本轮走 **codex/ChatGPT 登录**：根 `.env` 的值只留在脚本进程环境里；codex provider 声明里
  没有 `env`/`envFrom`，因此没有任何根 `.env` 值被送进 harness 进程。
- 登录凭据只以 Profile 的 `credentials.file` **路径**声明（`~/.codex/auth.json`），
  字节不进 Profile、回执、日志或本文档。
- 未打印、未复制、未提交任何密钥；本轮新增的 `raw/t06-*` 已扫描（`creator_user_id` /
  `creator_account_id` / `sk-…` / `Bearer …` / `eyJ…`）：**0 命中**。

---

## 第 6 步：调用次数与预算

| 项 | 值 |
| --- | --- |
| 允许的真实模型调用 | **最多 2 次**，本轮按"单轮"只计划 1 次；计数器 `/tmp/t06-budget.txt` |
| **实际真实模型调用** | **1 次**（调用 #1；计数器 = `1`，脚本在 ≥1 时拒绝再跑） |
| 失败重试 | **没有**（工具写入被沙箱拒绝是产品行为，不是可重试的传输错误） |
| `agents.query` | **0 次**（脚本在 query 之前崩溃；原生 rollout 是本轮的权威观测） |
| token 用量（原生记录，**同一回合的 2 次推理请求**：一次发起工具调用、一次给出终答） | 第 1 条 `total_tokens=13165`（input 13047 / output 118，含 reasoning 48）；第 2 条 `total_tokens=26448`（input 26254 / output 194，含 reasoning 108）—— 同一 `thread_id`/`session_id` |
| 回合耗时（原生 `task_complete.duration_ms`） | `11329` ms |

模型成本：1 次短 prompt（创建文件），Codex 订阅额度内。

---

## 原始输出

| 文件 | 内容 |
| --- | --- |
| `raw/t06-tools-attempt1-codex.json` | 本轮完整回执（prompt、turn、answer、控制往返、预算；含脚本崩溃原文与逐行日志） |
| `raw/t06-tools-attempt1-codex.log` | 本轮控制台日志（逐字） |
| `raw/t06-tools-native-transcript.json` | 由原生 rollout 派生的转录（session_meta、turn_context、消息、**工具调用逐字输入/输出**、token 记录；不含账号标识） |
| `raw/t06-tools-recovery.json` | 重启同数据根后的清理链（get/reconcile/stop/process-release/release）与残留扫描 |
| `raw/t06-tools-instance-get.json` | 用正确入参 `startRequestId` 复查实例状态（`state=running` 但进程已不存在） |
| `raw/t06-tools-retrieval.json` | `environments.files ls/cat` 的完整取回证据（77 条条目、控制文件读回、产物缺失） |
| `raw/t06-tools-service-config-codex.json` | 本轮服务配置（只有引用，无明文密钥） |

复现脚本（`tmp/` 被 `.gitignore` 排除，不进仓库）：`tmp/t06_tools.py`（由 `tmp/t05_multiturn.py`
复制改造的单轮工具验证）、`tmp/t06_recover.py`（清理补跑）、`tmp/t06_retrieve.py`（取回与转录派生）。
**必须用 `.venv-w1/bin/python` 运行**，否则 `agents.query` 的 `ordessa_agents` 导入会失败。

---

## 未完成 / 如实登记

1. **产物未创建 → T06/T10 的第一步没有达成"成果取回"。** 根因是 codex provider 写死
   `sandbox=read-only` + `approvalPolicy=never`（`provider.py:105-106`），并且拒绝 profile 里的
   `sandbox`（`:55-56` `SESSION_CONFIGURATION_UNAVAILABLE`）。要跑通 T06，必须先做产品决策：
   是否允许 Profile/装配层选择 sandbox 与审批策略；这不是测试脚本能绕过的（绕过就是伪造）。
2. **本轮只覆盖 codex 品牌**，未换品牌重试（预算与任务都要求 codex）。
3. **取回的身份偏差**（第 4 步已说明）：读的是同一个物理 work 根，但由新 Server/新数据根下的
   新环境身份完成；原环境身份被无法释放的 Use 栅栏挡住。
4. **`environments.files cat` 读不存在的文件返回 `unknown / EFFECT_UNKNOWN`**，而不是一个
   明确的 not-found 拒绝。这是本轮实测的契约行为，对"缺失即失败"的判定不友好（真假难分）。
5. **崩溃恢复缺口**：Server 重启后 `agents.get` 仍报 `state=running`（进程已不存在），
   `agents.reconcile` 给 `EFFECT_UNKNOWN` 而非 `exited`；`environments.release` 只能 `pending`
   （`ENVIRONMENTS_ORIGINAL_HANDLE_UNAVAILABLE`）。本轮由脚本 bug 触发，但暴露的是产品恢复语义。
6. **`agents.query` 未执行**（脚本崩溃在它之前）。本轮的"不重放/只读"结论未由 query 复核，
   原生 rollout 的 `task_started=1`/`task_complete=1`（单回合）、回合内 2 次推理请求（2 条 `token_usage_record`）与 `AgentMessage` 序列是替代观测。
7. **30 秒 wire deadline 仍在**（`apps/server/src/ordessa_server/composition/registry_runtime.py:57`）；
   本轮回合 11.3 秒，未触线。
8. 模型在工具被拒后仍给出了自述性回答；本轮**没有**用该回答冒充文件验证——判定来自
   Server 侧取回（同样为"不存在"）。

---

## 重测：sandbox 放开为 workspace-write 后（2026-10-21 11:02，SUCCESS）

用户批准 `sandbox=read-only → workspace-write` 后重跑。真实调用 **1 次**（本轮预算上限 2，用 1）。

| 项 | 结果 |
| --- | --- |
| 原生工具事件 | `custom_tool_call`（exec/apply_patch）成功写入 `tools-proof.txt`；原生 transcript 中 `tools-proof.txt` 与 `ordessa-tool-ok` 均出现 |
| 模型 answer | 与写入内容一致（自述不作为判定依据） |
| **独立取回（Server environments.files）** | `ls` 89 条，`tools-proof.txt` 在列；`cat` → completed，内容 `ordessa-tool-ok\n`，**sha256 `sha256:80153bea…f74d`**（16 字节） |
| 控制文件 | `t06-control-pre.txt` → `t06-control-ok`（取回通道对照） |
| 清理 | codex 进程随 Server 终止消失；工作区残留进程 `[]`；Server exit -15（测试主动终止） |
| 密钥扫描 | 114 文件，`OPEN_CODE_GO_API_KEY`/`DEEPSEEK_API_KEY` 命中 **0** |

判定：**SUCCESS**——"工具写入 + 独立成果取回"闭环成立，不是模型自述。
原始件：`raw/t06-tools-sandbox-{attempt2-codex.log,retrieval.json,native-transcript.json,cleanup.json,service-config-codex.json}`。
