# T04-B：Server 的 `harness.providers` 配置面 + 一次受控真实 prompt 回合（2026-10-21）

结论：**SUCCESS**（真实模型回合，Codex 原生 app-server，真实 answer `391`；真实模型调用 **1/3**）。

---

## 第 1 步：代码

### 改动

| 文件 | 改动 |
| --- | --- |
| `apps/server/deployment/default-product/src/ordessa_server_product/service_configuration.py` | `harness` 段新增**可选** `providers`；新增 `ServiceConfiguration.harness_providers`；新增校验函数 `_harness_providers()`；零配置默认 `providers={}` |
| `apps/server/deployment/default-product/src/ordessa_server_product/service_composition.py` | `build_agent_ports(..., providers=None)` 把配置传给 `PreparationResolver(..., harness_config=providers)`；`build_root_inputs` 传 `configuration.harness_providers` |
| `apps/server/deployment/default-product/tests/test_service_configuration_providers.py` | 新增 31 例（配置校验 + 装配接线） |

### 校验规则（沿用 CLI 的 `harness.json` 规则）

`apps/cli/src/ordessa_cli/composition/agents.py::_read_harness_config` 是规则来源；Server 侧同名规则：

| 规则 | CLI | Server | 结论 |
| --- | --- | --- | --- |
| `command` 必须是字符串数组 | ✅ | ✅（额外限 ≤64 项、每项 ≤4096 字符、禁 NUL） | 更严 |
| `env` 值必须是字符串 | ✅ | ✅ | 同 |
| `env` key 名不得含 `TOKEN/SECRET/PASSWORD/APIKEY/API_KEY/CREDENTIAL` | ✅ | ✅ | 同 |
| `envFrom` 与 `env` 不得同键 | ✅ | ✅ | 同 |
| `envFrom` 值必须是环境变量名 | ✅（`isalnum`） | ✅（POSIX 名 `[A-Za-z_][A-Za-z0-9_]{0,63}`） | 更严 |
| 不得出现明文密钥 | 仅靠 env key 名规则 | ✅ key 名规则 **＋** 值形状检测（已知凭据前缀 / ≥40 字符不透明串） | 更严 |

**净效果**：CLI 能接受的 `command/env/envFrom` 配置，Server 一定接受；Server 额外拒绝 CLI 会放过的“明文密钥字面量”。
`envFrom` 只允许**引用**环境变量名；`env`/`envFrom` 都不允许携带明文密钥。

零配置默认：`default_service_configuration(...)` → `harness_providers = {}`（零配置实例只跑各品牌自己声明的命令）。

### 回归

```
pytest -q apps/cli/tests \
          tests/integration/packages_convergence/test_server_full_stack.py \
          tests/integration/packages_convergence/test_server_http_entrypoint.py
→ 96 passed / 0 skipped   (VERDICT=GREEN_NO_SKIPS)

pytest -q apps/server/deployment/default-product/tests/test_service_configuration_providers.py
→ 31 passed
```

原始输出：`raw/t04b-regression.txt`。

> 如实登记的**既有**（非本次引入）失败，与本次改动无关：
> `apps/server/deployment/default-product/tests/test_host_execution_identity.py` 导入已不存在的
> `ProductCompositionUnavailable`；`tests/integration/packages_convergence/test_agent_submission_capture.py`
> 导入已不存在的 `require_online_execution`；`test_harness_catalog.py` 依赖已被本轮迁移删除的
> `plugins/harness/*/pyproject.toml`。三者都发生在收集阶段，与 `harness.providers` 无关。

---

## 第 2 步：真实 prompt 回合

### 回合形态

真实 `ordessa-server` 进程（`--service-config` 显式配置）＋ 真实 `ordessa` 客户端（wire/1 真实 bearer）＋
真实本地环境 ＋ 真实 Profile ＋ 真实品牌进程 ＋ **真实模型回答**。

服务配置（`raw/t04b-service-config-codex.json`，**只有引用、没有明文密钥**）：

```json
{"harness": {"allowlist": ["codex"],
             "providers": {"codex": {"command": ["/home/maoqh/.local/bin/codex"]}}}}
```

Profile 声明（Profile 只带路径，不带字节）：

```json
{"declarationId": "credential-binding-1", "configurationKind": "credentials.file",
 "schemaVersion": "1", "action": "value", "requirement": "required",
 "payload": {"sourcePath": "/home/maoqh/.codex/auth.json", "rootKey": "home",
             "relativePath": "auth.json"}}
{"declarationId": "codex-model-1", "configurationKind": "codex.configuration",
 "schemaVersion": "1", "action": "value", "requirement": "required",
 "payload": {"model": "gpt-5.6-sol"}}
```

> `gpt-5.6-sol` 是该 ChatGPT 登录自己的模型目录条目里默认 reasoning 最低的一个
> （`default_reasoning_level = low`）；选它是因为 Server 的 wire 传输层给每次
> `operations.call` 的 deadline 是 **30 秒**（`registry_runtime.py:57`）。

prompt 内容（固定）：`计算 17*23，只回复数字。`

### 逐步结果（attempt 1/3，品牌 codex）

| 步骤 | 结果 | 关键证据 |
| --- | --- | --- |
| `environments create local` | completed | `environment/fc5145bb49e042548b474fa180de4e3e` |
| `environments.acquire` | completed | `useIdentity=environment-use/050c9ff5347f404b8519ae975342f381` |
| `environments.export-endpoint` | completed | `endpoint/b522488feebf474d91109814858c9d8b`，rootKeys 齐全 |
| `agents.start`（sessionMode=fresh） | **completed**，`state=running` | **sessionId = `01a15c29-bc79-7900-8ca4-4e2bf56a50fa`**（codex 原生 thread id）；start operationRef = `agent-start/4bab630dd16644829043d6ee79bf8606` |
| `agents.prompt` | **completed**，`state=completed` | **prompt operationRef = `agent-operation/fe343b36738e4ac4bbbcb3d7b1584c31`**；turnId = `turn/71f084fe16694f5faaa505596dd34c40`；protocol=`codex-app-server/1`，method=`turn/completed`，turnStatus=`completed`，delivery=`confirmed`，bytesSent=226，items=1 |
| **真实 answer** | **`391`** | `observationBytes.answer = "391"`（17×23 = 391，正确） |
| `agents.query` | completed，**与 prompt 完全同一份数据** | 同 turnRef / 同 inputDigest / 同 observationDigest `sha256:c3e2df4c…`（同一回合，不重放） |
| `agents.stop` | **completed**，terminate confirmed | `facts.action=terminate`，`facts.cancellation=requested`，`facts.processState=running`；endpoint operationRef `environment-operation/c08a23ab86af47d088aa6ea7fd604ce1` |
| `agents.reconcile` | completed，`state=exited`，`exitCode=-9` | 进程确实退出 |
| `environments.process-release` | completed | `transportReleased=true`，`processState=exited`，`ioState=closed`，`exitCode=-9`，`resourcePreserved=true` |
| `environments.release` | completed | `resourcePreserved=true`，`rootPreserved=true`（工作目录保留，Use 已释放） |

原生消息（`agents.prompt` 与 `agents.query` 的 `observationBytes`，逐字）：

```json
{"answer": "391", "bytesSent": 226, "delivery": "confirmed", "items": 1,
 "method": "turn/completed", "protocol": "codex-app-server/1",
 "turnId": "01a15c29-bde1-70d1-aeae-a13a089db1f3", "turnStatus": "completed"}
```

### 清理证据

- `agents.stop` → `facts.action=terminate` + `cancellation=requested`；随后 `agents.reconcile` 观察到
  `state=exited`（`exitCode=-9`），即进程真的没了，不只是“发了终止通知”。
- `environments.process-release` → `transportReleased=true`、`ioState=closed`、`processState=exited`。
- `environments.release` → `resourcePreserved=true`、`rootPreserved=true`（Use 释放，工作目录按契约保留）。
- 本轮启动的 codex 进程（`local-process/2064103`）已不存在；`pgrep` 只剩 VS Code 扩展自己的
  codex app-server（PID 1892946，**用户服务，未触碰**）。
- Server 进程由脚本收尾终止（exit code `-15`），无残留。

### 密钥纪律

- 根 `.env` 的值**只**注入到进程环境（`os.environ` → Server 子进程 → 品牌进程环境），
  **没有**写进仓库、配置文件、工作区或任何输出。
- 配置文件里只有 `envFrom` 引用（`{"KILO_PROVIDER_KEY": "OPEN_CODE_GO_API_KEY"}`），没有字面量。
- 全工作区扫描（`/tmp/t04b-attempt1-codex`、`/tmp/t04b-mech-kilo`）：**没有任何文件**包含根 `.env` 的值。
- 凭据文件（`~/.codex/auth.json`）由 Profile 的 `credentials.file` 声明在准备期拷进私有 root，
  落地为 0600（`/tmp/t04b-attempt1-codex/work/home/auth.json`，`-rw-------`），字节不进记录与回执。

### `env` / `envFrom` 确实到达启动环境（无模型调用的一次证明）

为了证明新配置面的 `env`/`envFrom` 真的进了品牌进程环境（而不只是被解析），做了一次**不含模型调用**的
kilo 回合（`--mechanics-only`）：配置 `providers.kilo.env.KILO_CONFIG_CONTENT` 与
`providers.kilo.envFrom.KILO_PROVIDER_KEY=OPEN_CODE_GO_API_KEY`。

```
== launched harness processes ==
pid=2064414 cmd=node /home/maoqh/.local/bin/kilo acp
pid=2064421 cmd=/home/maoqh/.local/lib/node_modules/@kilocode/cli/bin/.kilo acp
== configured provider environment names (value lengths) ==
{"KILO_CONFIG_CONTENT": 368, "KILO_PROVIDER_KEY": 51}
```

`env` 与 `envFrom` 两个名字都在真实 kilo 进程环境里（`KILO_PROVIDER_KEY` 的**长度** 51 = OpenCode Go 键长；
**值从未被读取、打印或落盘**）。kilo 同样 `agents.start` 成功（原生 sessionId
`ses_ea3d52ff1ffez1RvOh4A8ZrtUF`），`agents.stop` → `exited(-9)` → `transportReleased=true` →
`resourcePreserved=true`，清理路径与 codex 一致。

原始输出：`raw/t04b-provider-env-kilo.log` / `.json`，配置：`raw/t04b-service-config-kilo.json`。

---

## 预算说明

| 项 | 值 |
| --- | --- |
| 允许的真实 prompt 尝试 | 最多 3 次，串行 |
| **实际真实模型调用** | **1 次（attempt 1/3，codex 成功）** |
| 未消耗预算的回合 | 2 次 `--mechanics-only`（kilo 与 codex 各一次，不含 `agents.prompt`） |
| 预算计数器 | `/tmp/t04b-budget.txt` = `1`（脚本在超过 3 时直接拒绝运行） |
| 模型成本 | 1 次短 prompt（17×23），Codex 订阅额度内 |

Codex 首次即成功，因此**没有**第 2、3 次尝试，也没有换品牌重试。

---

## 原始输出

| 文件 | 内容 |
| --- | --- |
| `raw/t04b-real-prompt-attempt1-codex.json` | attempt 1 的完整回执（每一步的原始 envelope + 日志） |
| `raw/t04b-real-prompt-attempt1-codex.log` | attempt 1 的控制台日志 |
| `raw/t04b-provider-env-kilo.json` / `.log` | 无模型调用的 kilo 回合（env/envFrom 证据） |
| `raw/t04b-service-config-codex.json` | attempt 1 的服务配置（只有引用） |
| `raw/t04b-service-config-kilo.json` | kilo 回合的服务配置（只有引用） |
| `raw/t04b-regression.txt` | 回归输出 |

复现脚本在 `tmp/t04b_real_prompt.py`（`tmp/` 已被 `.gitignore` 排除，不进仓库）。

---

## 未完成 / 如实登记

1. **`agents.prompt` 的传输 deadline 是 30 秒**（`apps/server/src/ordessa_server/composition/registry_runtime.py:57`
   写死 `loop.time()+30`）。本回合在窗口内完成；但对慢模型，这个上限会成为真实约束。
   这是传输层契约，不是本次改动引入的。
2. **`agents.query` 与 `agents.prompt` 返回同一份 turn receipt**（同 turnRef / 同 inputDigest /
   同 observationDigest）——回合是只读复核，不重放，符合契约。
3. **`harness.providers` 目前只覆盖 `command` / `env` / `envFrom`**；CLI 同款，没有扩展出第四种键。
4. 本回合用的是 Codex（ChatGPT 登录）。kilo / pi 的**真实模型**回合没有跑（预算未用完，且任务规定
   Codex 优先、Codex 可用即不换品牌）；kilo 只跑到 `agents.start` + 启动环境取证，无模型调用。
5. `exitCode=-9`（SIGKILL）是本地环境 owner 的终止方式；`agents.stop` 回执自身记的是
   `cancellation=requested`，真正的“已退出”由随后的 `agents.reconcile` 观察给出，两条证据都在上面。
