# T05：同一原生会话连续两轮消息（multi-turn，2026-10-21）

结论：**SUCCESS** —— 同一个 `agents.start` 实例、同一个原生会话，连续两轮 prompt 各自拿到真实模型回答
（**391** / **144**，均正确）；真实模型调用 **2/2**（上限用满，未超）。

通道：**codex/ChatGPT 登录（已上报偏离）**。

---

## 第 1 步：回合形态

真实 `ordessa-server` 进程（`--service-config` 显式配置）＋ 真实 `ordessa` 客户端（wire/1 真实 bearer）＋
真实本地环境 ＋ 真实 Profile ＋ 真实 codex app-server 进程 ＋ **两轮真实模型回答**。

```
environments create local -> acquire -> export-endpoint
agents.start (sessionMode=fresh)          -> 原生 sessionId = 01a15c4c-4f2d-74f3-bee0-ff3e094c62fa
agents.prompt A  "计算 17*23，只回复数字。"   -> 真实模型调用 #1
agents.query  A                            -> 只读复核
agents.prompt B  "计算 12*12，只回复数字。"   -> 真实模型调用 #2（同一个 sessionId）
agents.query  B                            -> 只读复核
agents.query  A（重读一次）                  -> 稳定性复核：B 之后 A 仍不变
agents.stop -> agents.reconcile -> environments.process-release -> environments.release
```

服务配置（`raw/t05-multiturn-service-config-codex.json`，**只有引用、没有明文密钥**）：

```json
{"harness": {"allowlist": ["codex"],
             "providers": {"codex": {"command": ["/home/maoqh/.local/bin/codex"]}}}}
```

Profile 声明（Profile 只带路径，不带字节）：`credential-binding-1`（`credentials.file` →
`~/.codex/auth.json`）＋ `codex-model-1`（`codex.configuration` → `model = gpt-5.6-sol`，
该 ChatGPT 登录模型目录里默认 reasoning 最低的一条，因为 wire 层给每次 `operations.call` 的 deadline 是 30 秒）。

---

## 第 2 步：两轮逐轮结果（同一 `agents.start` 实例）

实例：`instance-e5b971fdc3ef4e4f98c54c2ba4dfc30c`（namespace `server`），
`bindingDigest = sha256:c600c9f287ae06a25207f66f05627abbd5f08eaa1a28ef3d5c097db58f870859`；
start 的 operationRef = `agent-start/70d712168d5446d69a5cb5a75331e5bf`，
`state=running`，原生 `sessionId = 01a15c4c-4f2d-74f3-bee0-ff3e094c62fa`。

| 项 | 第 1 轮（A） | 第 2 轮（B） |
| --- | --- | --- |
| prompt 文本 | `计算 17*23，只回复数字。` | `计算 12*12，只回复数字。` |
| prompt operationRef | `agent-operation/ad8ea8d397604966b33076f46d90013d` | `agent-operation/e5840b6831324bf3ae7f5904266d13cf` |
| turnId（服务端回合） | `turn/0dbc619352ef4d32b3939b8c67314ee0` | `turn/b314c970118d4d0084f7d1bacb580e59` |
| 原生 turnId（codex thread 内） | `01a15c4c-54be-7fb0-860c-2c0270ab6190` | `01a15c4c-7e88-7c72-9cbb-301b1eea53b0` |
| turnStatus | `completed` | `completed` |
| delivery | `confirmed` | `confirmed` |
| bytesSent | `226` | `226` |
| **answer** | **`391`**（17×23，正确） | **`144`**（12×12，正确） |
| sessionId | `01a15c4c-4f2d-74f3-bee0-ff3e094c62fa` | **同上（同一会话）** |
| inputDigest | `sha256:a6a960a606eaf8129117bba117281366a87613eec8dccfd415eca4e95e6bf421` | `sha256:34aadfab9a274d0ab6fef19b6100f4830072c8edbdd6eb023c367cc426fef366` |
| observationDigest | `sha256:a6769902397eb3ddaf6cab97810b0a4d5a9215b5a20d4556413e2572cf15bdeb` | `sha256:1044e14ed8a067f3111b2490e95ee32ed0d83e8fc94ae6426fc9a8d72a61a7e8` |
| endpointOperationRef | `environment-operation/225f2922bf7f4ad4a014cb8bce87641e` | `environment-operation/e83a92891a8e45a2a2564174132a4258` |
| state / revision | `completed` / `3` | `completed` / `3` |

原生消息（两轮 `observationBytes`，逐字）：

```json
{"answer": "391", "bytesSent": 226, "delivery": "confirmed", "items": 1,
 "method": "turn/completed", "protocol": "codex-app-server/1",
 "turnId": "01a15c4c-54be-7fb0-860c-2c0270ab6190", "turnStatus": "completed"}
{"answer": "144", "bytesSent": 226, "delivery": "confirmed", "items": 1,
 "method": "turn/completed", "protocol": "codex-app-server/1",
 "turnId": "01a15c4c-7e88-7c72-9cbb-301b1eea53b0", "turnStatus": "completed"}
```

---

## 第 3 步：同一会话证据

**Ordessa 侧（wire 回执）**

1. 两轮 `agents.prompt` 的 `data.sessionId` **逐字相同**：
   `01a15c4c-4f2d-74f3-bee0-ff3e094c62fa`（= `agents.start` 返回的 `sessionId`）。
2. 两轮的 `turnRef.instanceRef` **逐字相同**（同 instanceId + 同 bindingDigest），
   只有 `turnId` 不同 → 同一个实例上的两个不同回合，不是两个实例。
3. 两轮的 `endpointOperationRef` **不同**（`…225f2922…` / `…e83a9289…`）→ 这是两次真实的
   `turn/start` 帧，不是同一个回合被读了两遍。

**原生侧（codex app-server 自己写的 rollout，转录在准备好的私有 home 里）**

`work/home/sessions/2026/10/21/rollout-2026-10-21T10-31-07-01a15c4c-4f2d-74f3-bee0-ff3e094c62fa.jsonl`
—— **文件名里的 id 就是 `agents.start` 返回的 sessionId**；`session_meta.id` = `session_meta.session_id`
= `01a15c4c-4f2d-74f3-bee0-ff3e094c62fa`（与 Ordessa 侧完全一致），`cwd=/tmp/t05-multiturn-codex/work`，
`originator=ordessa-cli`。

两条 `token_usage_record` 的 `thread_id` / `session_id` **都是同一个**
`01a15c4c-4f2d-74f3-bee0-ff3e094c62fa`，`turn_id` 分别是 A、B 的原生 turnId；
第二条的 `thread_token_usage.total_tokens = 26226` 是**两轮累加**的值 → 原生侧确认两轮同属一个线程。

---

## 第 4 步：`agents.query` 不重放证据

`agents.query` 只读复核同一回合，**不重新调用模型**。五条独立证据：

| # | 证据 | 结果 |
| --- | --- | --- |
| 1 | query 与 prompt 的 `agentOperationRef` | A、B 都 `true`（同一个操作，不是新操作） |
| 2 | query 与 prompt 的 `endpointOperationRef` | A、B 都 `true`（同一次原生 `turn/start`） |
| 3 | query 与 prompt 的 `revision` | A、B 都 `true`（都是 `3`，回合没有被推进） |
| 4 | query 与 prompt 的 `observationDigest` / `observationBytes` | A、B 都逐字相同（answer、bytesSent、delivery、native turnId 全部一致） |
| 5 | **B 完成之后再重读 A** | answer 仍为 `391`，observationDigest 仍为 `sha256:a6769902…`，native turnId 仍为 `01a15c4c-54be-…` → `unchanged=true` |

**第 6 条（原生侧计数，最硬的一条）**：本轮一共发了 **3 次 `agents.query`**（A、B、以及 B 之后的 A 重读），
但原生 rollout 里的计数是

| 原生记录 | 次数 |
| --- | --- |
| `session_meta` | 1 |
| `event_msg/task_started` | **2** |
| `turn_context` | **2** |
| `token_usage_record` | **2** |
| `response_item message/user` | 3（其中 1 条是 codex 自己注入的 `<environment_context>`，不是用户提示） |
| `response_item message/assistant` | **2**（`391` 与 `144`） |

即：原生侧只有 **2 次用户提示、2 次助手回答、2 次 token 计费记录**。
3 次 query 在原生侧**没有留下任何 user prompt / assistant message / task_started**，
所以 query 不可能重放了模型。

原生模型消息序列（逐字，来自 `raw/t05-multiturn-codex-native-transcript.json`）：

```
user      计算 17*23，只回复数字。
assistant 391
user      计算 12*12，只回复数字。
assistant 144
```

---

## 第 5 步：清理与残留检查

| 步骤 | 结果 |
| --- | --- |
| `agents.stop`（force） | completed；`facts.action=terminate`、`facts.cancellation=requested`、`facts.processState=running`；operationRef `environment-operation/23d84ead07b542ebb786e29133531321` |
| `agents.reconcile` | completed；**`state=exited`**、`exitCode=-9` → 进程真的退出了（不是只发了终止通知） |
| `environments.process-release` | completed；`transportReleased=true`、`ioState=closed`、`processState=exited`、`exitCode=-9`、`resourcePreserved=true`、`exitClaimed=false` |
| `environments.release` | completed；`resourcePreserved=true`、`rootPreserved=true`（Use 释放，工作目录按契约保留） |

**残留检查**

- 本轮启动的 codex 进程：`local-process/2068232`（`node …/codex app-server -c model="gpt-5.6-sol"`）
  与子进程 `2068239` —— 清理后 `/proc` 中**均已不存在**（脚本内 `launched_processes(workspace)` 复查结果 `[]`，
  事后 `ls /proc/<pid>` 复核同样为空）。
- Server 进程由脚本收尾终止（exit code `-15`），无残留。
- 宿主机上剩下的 codex 进程只有 **用户自己的** VS Code 扩展 app-server
  （PID `1892946`，`/home/maoqh/.vscode/extensions/openai.chatgpt-26.1007.21434-…/codex app-server`）——
  **未被触碰**，回合前后都在。

**密钥纪律**

- 根 `.env` 的值只注入进程环境（`os.environ` → Server 子进程），没有写进仓库、配置、工作区或任何输出。
- 全工作区扫描（`/tmp/t05-multiturn-codex`，**381 个文件**）：根 `.env` 的 `OPEN_CODE_GO_API_KEY` /
  `DEEPSEEK_API_KEY` **命中 0 次**。
- 凭据文件由 Profile 的 `credentials.file` 声明在准备期拷进私有 root（0600，
  `/tmp/t05-multiturn-codex/work/home/auth.json`），**字节不进记录与回执**；本文件与
  `raw/t05-multiturn-*.json` 里都不含账号标识与令牌。

---

## 第 6 步：预算

| 项 | 值 |
| --- | --- |
| 允许的真实模型调用 | **最多 2 次**（A/B 各一），计数器文件 `/tmp/t05-budget.txt` |
| **实际真实模型调用** | **2 次**（A=调用 #1，B=调用 #2；计数器 = `2`，脚本在超过 2 时直接拒绝运行） |
| 失败重试 | **没有**：两次都成功，因此没有第三次，也没有换品牌重试 |
| `agents.query` 调用 | 3 次（只读，不消耗模型预算） |
| token 用量（原生记录） | 第 1 轮 `total_tokens=13103`（input 13098 / output 5）；第 2 轮 `total_tokens=13123`（input 13118 / output 5），线程累计 26226 |
| 模型成本 | 2 次短 prompt（17×23、12×12），Codex 订阅额度内 |

第 2 轮的 input tokens（13118）比第 1 轮（13098）多 20 —— 原生线程把上一轮上下文带了下来，
这本身就是“第二轮跑在同一个会话里”的旁证。

---

## 原始输出

| 文件 | 内容 |
| --- | --- |
| `raw/t05-multiturn-attempt1-codex.json` | 本轮完整回执（每一步的原始 envelope + 逐行日志 + 残留/密钥扫描） |
| `raw/t05-multiturn-attempt1-codex.log` | 本轮控制台日志 |
| `raw/t05-multiturn-codex-native-transcript.json` | 由原生 rollout 派生的转录摘要（会话 id、消息序列、token 记录；不含账号标识与凭据） |
| `raw/t05-multiturn-service-config-codex.json` | 本轮服务配置（只有引用） |

复现脚本在 `tmp/t05_multiturn.py`（`tmp/` 已被 `.gitignore` 排除，不进仓库）；
它由 T04-B 的 `tmp/t04b_real_prompt.py` 复制改造而来，两轮 prompt、预算上限 2、逐轮取证与清理链都在脚本里。

---

## 未完成 / 如实登记

1. **`agents.prompt` 的传输 deadline 仍是 30 秒**（`apps/server/src/ordessa_server/composition/registry_runtime.py:57`
   写死 `loop.time()+30`）。两轮都在窗口内完成；但对更慢的模型，这仍是真实约束。这是传输层契约，
   不是本次引入的。
2. **`agents.query` 返回的就是该回合的同一份 turn receipt**（同 operationRef / 同 endpointOperationRef /
   同 revision / 同 observationDigest）。这是契约定义的只读复核，不是重新观察；
   “不重放”的**独立**证据来自原生 rollout 的计数（第 4 步第 6 条）。
3. **本轮只覆盖 codex 品牌**。kilo / pi 的多轮真实模型回合没有跑（预算上限 2 已按任务要求用满，
   且任务规定 Codex 优先、Codex 可用即不换品牌）。
4. **本轮 codex 的 `providers` 配置只有 `command`**，没有 `env`/`envFrom`，因此“配置的环境变量名与长度”
   这项证据在本轮是空集 `{}`（与 T04-B 的 codex 回合一致）；`env`/`envFrom` 的落地证据仍以
   `raw/t04b-provider-env-kilo.*` 为准。
5. **原生 rollout 转录位于工作区的私有 home**（`work/home/sessions/…`），本文件只引用其**派生摘要**，
   没有把原始 rollout 复制进仓库。
6. `exitCode=-9`（SIGKILL）是本地环境 owner 的终止方式；`agents.stop` 回执自身记的是 `cancellation=requested`，
   真正的“已退出”由随后的 `agents.reconcile` 观察给出（两条证据都在第 5 步）。
