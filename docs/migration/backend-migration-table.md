# Backend migration table — bc-native → monorepo candidate `tree/`

Source frozen points (contract §1):

- Backend: `/home/maoqh/projects/agent-box/.git`, branch `work/hd002-bc-native`,
  commit `a0b343e0c01651d407adbc4a71c2d40b558840fb` — read via `git archive`
  into `src-tree/` (committed tree only; no `.qoder`, no untracked files).
- Go bridge: `/home/maoqh/ordessa-builds/acp-adapter/.git`, branch `work/round-h`,
  commit `41d9d94ef6b98547df575240c4366b1e5e8ba39b` — extracted into
  `acp-adapter-src/` the same way.

All destinations are relative to `ordessa-migration/backend/tree/`.
"改名" lists renames applied mechanically; "理由" is the retain/retire reason.

## 1. Packages and distribution names

| 旧路径 (bc-native) | 新路径 (tree/) | 改名 | 理由 |
| --- | --- | --- | --- |
| `pyproject.toml` (dist `pacthold` 2.0.0a1) | `packages/pacthold/pyproject.toml` | dist 名不变；console scripts 收敛为 `pacthold=pacthold.cli:main`；删除 `agent-box*` 别名与 `pacthold-server*` 入口；删除 `preview/web/server` extras（指向不进 main 的 retired dists，保留会装不上） | 治理核心独立成包；extras 引用的 dist 不存在会使安装失败 |
| `src/agent_box/`（除 `server/`） | `packages/pacthold/src/pacthold/` | 模块目录与全部 import `agent_box*` → `pacthold*`（work_core, storage, migrations, execution, extensions, service, resource_contracts, cli） | 治理核心 → packages/pacthold（契约 §2/§3） |
| `src/agent_box/migrations/*.sql`（001–009） | `packages/pacthold/src/pacthold/migrations/` | 文件名与序号不变（数据兼容） | 数据库迁移序号是数据格式 |
| `src/agent_box/server/` | `apps/server/src/ordessa_server/` | 包 `agent_box.server` → `ordessa_server`；入口 `python -m ordessa_server`；scripts `ordessa-server`、`ordessa-server-credential` | server 独立发行包，只 import pacthold/ordessa-harness，不复制核心 |
| `plugins/agent-box-harness/` | `plugins/harness/` | dist `agent-box-harness` → `ordessa-harness`；包 `agent_box_harness` → `pacthold.harness_kit`；entry points 指向 `pacthold.harness_kit.entrypoints:*` | 唯一进 main 的后端插件 |
| `plugins/agent-box-harness/src/agent_box_harnesses/`、`agent_box_harness_{dsh,qwen,kilo}/`（alias shim 包） | 不迁（删除） | — | 旧仓多发行名合并的 import-only 兼容 shim（`_compat.py` 自述 "retired distribution names"）；新仓只有单一发行名，所有活动 import 已改写为 canonical `pacthold.harness_kit(.dsh/.qwen/.kilo)`；server bootstrap 两处 `agent_box_harnesses.registry` 调用点改直连 canonical 包。对应 shim 身份测试按新不变量重写（见 §6） |
| acp-adapter Go 源 `41d9d94` | `plugins/harness/adapters/acp-adapter/` | 路径改名，go.mod 上游 module path `github.com/beyond5959/acp-adapter` 保留 | 桥归 harness 内部（契约 §3）；上游标识不改 |

## 2. 数据兼容例外清单（保留旧标识，逐项）

| 标识 | 位置 | 为什么不改 |
| --- | --- | --- |
| 插件入口组 `agent_box.plugins` | `pacthold.extensions.loader.ENTRY_POINT_GROUP`、harness pyproject、测试 pin | brand-rename 守卫测试（order 61）明确钉住为兼容面；外部插件与在跑 hd004b 腿按此发现插件 |
| 环境变量 `AGENT_BOX_HOME`、`AGENTBOX_*` 前缀、`AGENT_BOX_SANDBOX_MODULE`、`AGENTBOX_STRICT_PRESENCE`、`AGENTBOX_W43_WORKER` 等 | `pacthold.work_core.runtime`、server bootstrap、conftest | 用户配置/部署脚本的既有配置键 |
| 数据目录默认 `~/.agent-box`、数据库文件 `agent-box.db` | `pacthold.work_core.runtime` | 用户数据位置 |
| data-root owner 标记 `.agentbox-server-root`（内容 `agentbox-server-r1`） | `ordessa_server.bootstrap.runtime` | 在跑服务写入的盘上数据 |
| 工作记录标题 `"AgentBox Session Turn"` | `ordessa_server.bootstrap.runtime` | 落库数据值 |
| 资源契约 id（`agent-box.skill@1`、`agent-box.profile@1` 等）与模块 `resource_contracts/agent_box_profile_v1.py`、类 `AgentBoxProfileV1` | `pacthold.resource_contracts` | 契约 id 是协议（测试 pin）；模块/类名随契约 id 命名 |
| wire 协议 `wire/1`（`WIRE_VERSION`） | `ordessa_server.wire.handlers` | 协议版本 |
| harness 数据 `harnesses.toml`（driver、harness_type、capabilities、native_home、guest_home、mount/skill/mcp 目标与键） | `plugins/harness/src/pacthold.harness_kit/harnesses.toml` | 部署/观测数据格式，8 个 harness 身份未变 |
| npm 打包产物名 `agent-box-harness-runtime-{claude,codex,pi,dsh,…}` | `plugins/harness/packaging/*/package.json` + `package-lock.json` | 已发布的 npm 闭包产物与 lock（测试 `test_packaging_boundaries.py` 钉住 name==目录） |
| `pacthold` 包内符号 `agent_box_home()`、`PluginContext.agent_box_home/.agent_box_version`、测试 fixture `tmp_agent_box_home` | core/extensions/cli/harness | 以 `AGENT_BOX_HOME` 兼容面命名的 API 符号，改名会与它所绑定的环境变量脱钩 |
| `pacthold/__init__` 对 `version("agent-box-cli")` 的回退查询 | 已删除 | 旧发行名回退在单仓基线不再需要（dist 即 pacthold）；version() 主路径保留 |
| 上游/历史标识：GitHub URL `github.com/mmm-05610/agent-box`、go module `github.com/beyond5959/acp-adapter`、LICENSE、`AGENT_BOX_HOME` 文档字符串 | pyproject urls、go.mod、LICENSE | 第三方/上游标识不改（契约 §3） |
| CLI 提示中 `pip install agent-box-web` | `pacthold.cli` web/launch/doctor 缺 Web Host 时的提示 | 指向真实存在过的 retired dist 名，删除 `pacthold[web]` extra 的误导性提示；该可选组件不在 main |

## 3. 不进 main 的顶层目录（逐项去向与理由）

| 旧路径 | 去向 | 理由 |
| --- | --- | --- |
| `plugins/agent-box-{artifacts,git,runtime-local,runtime-wsl,sandbox-bwrap,sandbox-windows,skills,web,terminal-session}`（9 个插件） | 不进 main；经 archive ref 保全 | 契约 §3 明确仅 harness 进 main。已核对的依赖点：server `bootstrap/runtime.py`（惰性 import `agent_box_runtime_wsl.WslConnector`）、`execution/local_channel.py:750`（惰性 `agent_box_sandbox_windows.job.Job`）、`cli/__init__.py`（惰性 `agent_box_web.cli`，有优雅降级）、`execution/ssh_connector.py`（顶层 `WorkerClient/WorkerError`——本轮已改为 try/except 惰性收口：构建/校验路径可用，构造 Worker client 或 typed refusal 时报缺失包名）。收口待办：SSH/WSL 远程腿、tmux/终端会话、web workbench 若回归，需按 `plugins/<name>` 重新接入 |
| `workers/agent-box-worker/`（Rust worker 二进制源码） | 不进 main；archive ref | worker-entry 链已退役（插件 REMOVALS.md；`runtime/worker-entry.mjs` 已从 harness 删除，acp_orchestration 18F/40P 与 sidecar 相关红即此既定事实）。`resource_contracts/runtime_artifacts.py` 的 digest 算法以 Python 实现为准，docstring 中的 Rust 对照为历史说明 |
| `protocols/worker/`（schema + golden） | 不进 main；archive ref | 退役 worker 协议；守护它的 `tests/server/test_worker_protocol_triad_102.py` 随之不迁 |
| `runtime/tools/acp-adapter/`（二进制 acp-adapter、acp-adapter-round-h；build-acp-adapter.sh、handshake-check.py、BUILD-RECORD.md） | 二进制不进 git（原本也未被 git 跟踪）；`handshake-check.py`、`BUILD-RECORD.md` 迁 `plugins/harness/packaging/acp-adapter/` 作 provenance/诊断；v0.3.8 专用 `build-acp-adapter.sh` 不迁（属未迁移的 hd004b 腿），由 round-h 重建脚本替代 | 二进制不进 git；round-h 桥的重建配方迁入（见 §5） |
| `lockfiles/server-windows-py312.txt` | `apps/server/lockfiles/server-windows-py312.txt` | server 的 Windows CPython 3.12 外部闭包记录，属 server 安装材料（注：其中 starlette 1.0 的 TestClient 需额外 httpx；本轮验证环境用 fastapi 0.115+ 实测） |
| `scripts/hd001/`、`scripts/hd002/`、`scripts/hd004b/`、`scripts/server-round1/` | 不进 main；archive ref。例外：`scripts/server-round1/artifact_presence.py` 迁 `tree/scripts/`（tests conftest 的 VERDICT 报告依赖，Order 118 机制）；`scripts/server-round1/{model-validation-42d.mjs,build-*-runtime-artifact.mjs,build-*-runtime-artifact.test.mjs,harness-install-set.py,build-opencode-authorization.mjs}` 迁 `plugins/harness/packaging/builders/`（harness 自有构建/依赖准备与模型文档校验，路径已改到新布局） | 旧轮次 gate/启动脚本绑定旧树绝对路径；hd004b 启动器属在跑腿（不迁移、不干扰）；server-round1 的 QA gate（*-production-chain-gate.py、accept-*.ps1、cleanup-worker-projection.sh、wire_drive_coverage.py）与其证据 docs 随旧线退役 |
| `tools/*.sh`（restructure/checkpoint 脚本） | 不进 main；archive ref | 旧仓一次性重构辅助脚本，对新布局无意义 |
| `docs/`（14MB：server-round1、superpowers、plans、research、demos、branding、adr、archive 等） | 不进 main；archive ref 全量保全 | 均为历史轮次文档；代码与活动测试无运行时引用（仅 harnesses.toml 注释提及，属历史注释）。新根 `docs/`（architecture/baseline/known-issues/reference-index/migration）按方案 §4 由主代理撰写 |
| 根 `AGENTS.md`、`README.md`、`README_CN.md`、`CHANGELOG.md`、`CLAUDE.md`、`CONVENTIONS*.md`、`LICENSE`、`.github/`、`release-please*.json`、顶层 `agent-box` 启动 shim | 不在本代理范围；交主代理决定（新根 AGENTS.md/README 为新写；LICENSE 建议随根保留） | 仓库级文件，monorepo 根由主代理集成 |
| `tests/test_brand_rename.py`（tests/server/ 下原文件） | 重写并移至 `packages/pacthold/tests/test_brand_rename.py`；server 侧新增 `apps/server/tests/test_rename_compat_surfaces.py` | 原 pin 断言旧别名 console scripts 与 `agent_box` import path 存在——与本次迁移决定（退役别名）直接冲突，属"被迁移决策取代的守卫"而非删断言：新文件改为 pin 新不变量（dist=pacthold、import=pacthold、scripts 恰为 `pacthold`），并原样保留兼容面断言（入口组、契约 id、env 前缀、data 目录）。wire/1 与 AGENTBOX_ 前缀断言移到 server 侧新文件 |

## 4. 测试迁移映射（旧 `tests/` → 新位置）

| 旧路径 | 新路径 | 说明 |
| --- | --- | --- |
| `tests/conftest.py` | `packages/pacthold/tests/conftest.py`、`apps/server/tests/conftest.py`、`tree/tests/conftest.py`（三份，各指向 `tree/scripts/artifact_presence.py`） | import 改 `pacthold.work_core.db`；presence 报告路径改新布局 |
| `tests/_editor_mock.py`、`test_extensions.py`、`test_plugins_cli.py`、`test_resource_contracts.py`、`test_runtime_composition_protocol.py`、`test_work_core_*.py`（7 个） | `packages/pacthold/tests/` | 治理核心测试随包迁移，import 已改 |
| `tests/capability/`（8 个，除 `test_capability_slots.py`） | `packages/pacthold/tests/capability/` | `test_capability_slots.py` 不迁：import `agent_box_runtime_local`/`agent_box_sandbox_bwrap`（不进 main） |
| `tests/server/`（其余 ~74 个文件） | `apps/server/tests/`（含 `fixtures/`） | import 与仓内路径全部改新布局（`tests/server/fixtures` → `apps/server/tests/fixtures`、源码路径 → `apps/server/src/ordessa_server`、`packages/pacthold/src/pacthold`、`plugins/harness`） |
| `tests/server/` 中 15 个文件不迁 | —（archive ref 保全） | 逐项：`test_capability_gate`、`test_harness_sidecar`、`test_home_projection`、`test_pi_gate_cleanup`、`test_shared_session_store`、`test_sidecar_home_projection`、`test_sidecar_lease_keepalive`、`test_state_capture_error_boundary`、`test_worker_home_put_wire_099`、`test_wsl_legs_083`（import 不进 main 的 sandbox-bwrap/runtime-wsl）；`test_gate_script_parity_127`、`test_artifact_absence_is_not_green_118`、`test_gate_worker_defaults`、`test_worker_protocol_triad_102`（subject 为 scripts/server-round1 gate、docs 证据、protocols/worker goldens——旧 QA 线，均不在 main） |
| `tests/server/` 中 10 个文件：round-1 QA gate/docs 的 subject | `apps/server/tests/EXCLUDED-round1-qa__*.py`（改名保留，不收集） | `codex_gate_diagnostics`、`hermes_production_chain`、`opencode_gate_cleanup`、`codex_feature_flag_differential`、`acceptance_cleanup_guards`、`wire_drive_coverage_103`、`wire_artifact_113`、`wire_error_family_closure_115`、`hello_harnesses_105`、`provider_update_keeps_omitted_112`——它们运行/读取 `scripts/server-round1/*-production-chain-gate.py`、`wire_drive_coverage.py`、`docs/server-round1/*`，这些 subject 不进 main。保留文件便于主代理裁定是否随 archive 一起归档或恢复其 subject |
| `tests/server/test_presence_verdict_lnx002.py` | `packages/pacthold/tests/`（路径重映射：conftest 指向 pacthold 包内，presence 指向 `tree/scripts/`） | 守护的是随迁的 presence 机制本体 |
| `tests/acp_orchestration/`（11 文件 + conftest） | `tree/tests/acp_orchestration/` | 原样保留（含 worker-entry 既定红灯）；仅 conftest 的 PLUGIN 路径 `plugins/agent-box-harness` → `plugins/harness` |
| `tests/integration/native/`（14 文件） | 不迁；archive ref | 全部 import `agent_box_sandbox_bwrap`/`agent_box_terminal_session`/`agent_box_runtime_local`（不进 main 的 native 垂直） |
| harness 插件自带 `tests/`（.py 与 .test.mjs） | `plugins/harness/tests/` | conftest 路径逻辑改新布局；mjs（node:test）相对路径不变。逐项改写/剔除：`test_skill_projection.py` 不迁（import `agent_box_skills.store`）；`test_single_distribution.py`、`test_core_identity.py` 按"单一发行名"新不变量重写（旧断言 pin 的是已退役的 alias shim 身份）；`test_core_boundaries.py`、`test_family_dialect_tables.py` 的 alias/零入口断言按新不变量重写（dist=ordessa-harness、pilot 品牌无入口点、src 下无 shim 目录）；`test_packaging_boundaries.py` 的 gate 脚本目录改指 `packaging/builders/`、kernel 改指 `packages/pacthold/src/pacthold`；production-template 测试的 `REPO/"plugins"/"agent-box-harness"` → `plugins/harness`，`model-validation-42d.mjs` → `packaging/builders/` |
| harness `tests/install/test_acp_schema_drift_target.py` 的 2 个失败 | 原样保留（继承红） | 冻结树同轮同样红：pi lock 解析 `@agentclientprotocol/sdk@1.3.0` 与 adapter 声明的 `1.4.0` 冲突——bc-native 已知既存问题，非迁移引入 |

## 5. scripts / packaging（新布局）

| 新路径 | 来源/内容 |
| --- | --- |
| `tree/scripts/artifact_presence.py` | 来自 `scripts/server-round1/`，conftest VERDICT 机制依赖（Order 118） |
| `tree/scripts/start-server.sh` | 新写：127.0.0.1 高位端口 + 临时 data-root 启动 `python -m ordessa_server`（只 import 树内包，无旧树路径） |
| `tree/plugins/harness/packaging/builders/` | 来自 `scripts/server-round1/` 的 harness 构建脚本（见 §4），PYTHONPATH/digest 引用改为 `pacthold.resource_contracts.runtime_artifacts`（bwrap 插件只是该实现的 re-export），路径全部新布局 |
| `tree/plugins/harness/packaging/acp-adapter/` | `build-acp-adapter-round-h.sh`（新写，配方 `CGO_ENABLED=0 go build -trimpath -buildvcs=false -ldflags "-buildid=" ./cmd/acp`）、`README.md`（pins 与验证）、`handshake-check.py`、`BUILD-RECORD.md`（历史 provenance，含 v0.3.8/hd004b 记录） |

## 6. server/harness 对核心与其余 9 插件的依赖结论

- **pacthold（core）**：不 import 任何插件；对 `agent_box_web` 仅存在 `cli` 的惰性、可降级引用（提示安装），属可选组件守卫，非链路依赖。核心不反向依赖产品/插件 ✓。
- **ordessa_server**：只 import `pacthold`（治理核心）与自身；`bootstrap` 惰性加载 `pacthold.harness_kit.registry`（main 内插件 ✓）。对不进 main 插件的残留依赖点共 4 处，均已如实收口/待办：`ssh_connector`（本轮改惰性+typed shim，错误信息点名缺失包）、`bootstrap.runtime` 惰性 `agent_box_runtime_wsl.WslConnector`、`local_channel` 惰性 `agent_box_sandbox_windows.job.Job`、`cli` 惰性 `agent_box_web`——全部保持旧行为语义（缺包时 placement/功能明说拒绝），未删除、未隐藏，pyproject 不声明这些 dist（声明了会装不上）；README 与本表登记为待办。
- **pacthold.harness_kit**：只 import `pacthold`（resource_contracts/work_core/extensions）。原 pyproject 对 `agent-box-terminal-session` 的依赖声明被移除：全包源码 0 处 import 该插件（仅测试 `test_skill_projection.py` import skills 插件，该测试不迁），声明会使 `pip install ordessa-harness` 失败。
- **harness 对其余 9 插件**：无 import 依赖；仅 npm 打包锁（packaging/*/package-lock.json）与 deploy 脚本引用各 harness 目标，属其内部配置。

## 7. 显示层改名（非兼容面，已改并在此登记）

CLI help 描述（`Agent-Box Work Core` → `Pacthold work core…`、`Import a Codex login into AgentBox Server` → `…the Ordessa Server`）、`__main__` 描述（`independent AgentBox loopback Server` → `Ordessa loopback Server`）、FastAPI OpenAPI title（`AgentBox Server` → `Ordessa Server`）、`pacthold/__init__` 与若干 docstring/注释中的旧路径表述。无测试、无数据、无协议依赖这些字符串。
