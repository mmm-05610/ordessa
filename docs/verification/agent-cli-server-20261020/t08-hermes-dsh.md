# T08：hermes / dsh 准入（2026-10-21，进行中）

用户已批准：为 hermes 补 prepared `home/config.yaml`、为 dsh 批准额外 root。

## dsh：✅ start 通过（无模型调用，`--skip-prompt`）

- 代码：Server `SESSION_ROOTS` 与 CLI `_SESSION_ROOTS` 增加 `dsh-home`（provider 明确要求 8 个 root，且
  `home != dsh-home`）；未改 environments 契约——export 请求的 `roots` 由调用方按 harness 声明给出。
- 实测（真实 Server + 真实 CLI，临时根、随机端口）：
  - `environments create local` → acquire → export-endpoint：descriptor `rootKeys` 含 **dsh-home**
    （`["cache","config","data","dsh-home","home","state","tmp","work"]`）；
  - profiles create `demo-dsh`（revision 0.1.0，无 declarations）→ `agents.start(fresh)` →
    **completed，state=running，sessionId `07304c81-654d-42ce-9de4-a24258373e67`**；
  - `agents.stop` → completed（terminate/cancellation=requested）；
  - 残留进程：工作区 `[]`（只剩用户自己的 VS Code codex，未触碰）；
  - 本回合 **0 次模型调用**（拿到真实 native session，但未发 prompt）。
- 产物：`/tmp/t08-receipt2.json`（原始 receipt）；脚本 `tmp/t08_dsh.py`（由 T06 脚本改造，gitignored）。

## hermes：⛔ NOT_RUN（技术原因已定位，不是"没时间"）

深入读取契约后确认：hermes **不能用 profile declarations 传配置**——provider 的
`validate_profile` 对任何 declarations 直接 `CONFIGURATION_UNSUPPORTED`；它要求
`context.prepared_configuration_refs` 里存在 `BoundPath('home','config.yaml')`，
而这些 ref 必须在 `environments.export-endpoint` 时作为 `preparedConfigurations` 绑定
（ref 形状 `prepared-configuration-ref/1`，需 issuer/verify + 字节落盘到环境）。
现有 preparation 还明确拒绝 `material_refs`（`material preparation is not available here`）。

需要补的切片（下一步）：
1. environments export-endpoint 的 prepared-configuration 物化路径（写 `home/config.yaml` + digest 校验）；
2. `agents.start` 请求透传 `preparedConfigurationRefs`，preparation 校验并传给 provider；
3. 真实 prompt 1 次（ACP，模型走已批准通道）。

在此之前 hermes 记为 **NOT_RUN**，不伪造 start/prompt。

## 下一步

1. hermes：按 provider 真实 schema 生成最小 config.yaml（模型/凭据走 envFrom），profile 声明注入，再 start + 1 次真实 prompt；
2. dsh：补 1 次真实 prompt（ACP 品牌需要模型通道配置；若不可行如实记 NOT_RUN）。

## hermes 实现配方（契约已核实，2026-10-21 11:4x）

不需要新 wire 操作，现有契约已够：

1. **投放字节**：`environments.files` `write` 到 `home/config.yaml`（rootKey `home`，相对路径 `config.yaml`）。
2. **绑定 ref**：`environments.export-endpoint` 的 `preparedConfigurations` 传一个
   `prepared-configuration-ref/1`：`{schemaVersion, issuer, configurationId, revision, digest, mediaType,
   byteLength, location:{schemaVersion:'bound-path/1', rootKey:'home', relativePath:'config.yaml'}}`；
   export 时 `_verify_configuration` 会读环境里的字节并比对 digest/byteLength。
3. **start 透传**：`agents.start` 的请求契约（`ordessa_agents/instances/contracts.py:52`）已有
   `prepared_configuration_refs`；capability 输入需以 `preparedConfigurationRefs` 透传，lifecycle 会校验
   `PREPARED_CONFIGURATION_NOT_BOUND`。
4. preparation 已支持：`request.prepared_configuration_refs` 校验后放入 `PrepareContext`，并调用
   `endpoints.verify`；不再拒绝（当前只拒绝 `material_refs`）。

13　还需要：hermes 的 `config.yaml` 最小可用内容（模型/端点，密钥用 envFrom 引用而非明文）——这是品牌域知识，
下一步按 hermes 原生 schema 生成并跑 1 次真实 prompt。

## hermes 进一步核实：不只是"写一份 config.yaml"（2026-10-21 12:0x）

读完 `plugins/harness/hermes/src/ordessa_harness_hermes/production.py` 后更正上一条配方的前提：

- hermes 期望的是**已评审的完整配置文档**（`CONFIG_SOURCE="deploy/hermes/config.yaml"`，
  含 `model.base_url`、`providers.custom.api`、`agent.api_max_retries`、输出上限等），
  并且它的运行形态是**受限 guest 内的 runtime artifact**
  （`ARTIFACT_TARGET="/runtime/artifacts/hermes-runtime"`，用 `/usr/bin/python3 -m hermes_cli.main acp` 启动，
  `HERMES_HOME=/runtime/home/.hermes`）。
- 也就是说 host 上直接 `agents.start` + 自造 config.yaml 不足以等价于"hermes 已可用"：
  要么按 production 模板投影一份 reviewed config（并把模型端点/K 用 envFrom 引用接进来），
  要么先做 hermes 的 guest/runtime 投放切片（接近 T09 沙箱输入投放的范围）。

**结论：hermes 记 NOT_RUN**，理由不是缺 config 文件，而是缺"reviewed 配置 + runtime 投放"这一整片；
在 T09 沙箱输入投放打通后一并做，避免现在造一个半真的 hermes 启动。
