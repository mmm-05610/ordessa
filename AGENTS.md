# Ordessa — workspace instructions for agents

This directory is the **Ordessa product monorepo**. One repository holds the
product's active source; the previous multi-repo workspace organisation has
been retired (history and restore paths: `docs/reference/index.md`,
`docs/migration/`).

## What this repo is

- Product/repo name: **Ordessa**. Remote identity: `github.com/mmm-05610/ordessa`
  (renamed from `mmm-05610/agent-box` on 2026-09-29; GitHub redirects the old
  URL) — see `docs/migration/remote-plan.md` before any publish work; **no push
  without explicit user authorisation**.
- `packages/execution/kernel` (Python `pacthold`) — governance kernel and plugin SDK.
  Zero product dependencies. Nothing here may import a plugin, app or product.
- `apps/server` (Python `ordessa_server`) — Ordessa Server. Depends on
  `pacthold`, composes the plugin root, owns wire/transport.
- Current cross-layer Harness access tests live in `tests/integration/harness/access/`; shared peers are in `tests/fixtures/harness/access/`. The Server-owned access entry and selected launch ports are under `apps/server/src/ordessa_server/composition/native_channels/`; brand launch declarations remain in each Harness leaf. See `docs/verification/overnight-upper-structure-20261009/harness-access-test-owner-root-applied.json` for the source mapping receipt. It does not record test execution.
- `plugins/harness/*` — independent brand providers. The root
  `ordessa_harness` aggregate and `ordessa-harness-api` distribution are retired;
  public contracts live in the host-independent `ordessa_execution_api` SDK under
  `packages/interfaces/execution/c1-api`; ownership is not restored through Kernel aliases. Do not restore aliases
  or hidden fallbacks. Remaining runtime/product legacy paths are explicit
  retirement targets in `docs/implementation/specifications/032-architecture-cleanup`.
  Brand bridge internals stay behind public provider ports.
- `packages/engineering` (`ordessa_engineering`) is the sole Engineering source.
  Artifact/review commands, full review predicates, controls and journal share
  the original EngineeringLibrary connection/lock/identity via SQLiteUoWFactory.
  Schema2 remains the default; snapshots/schema3, artifacts/schema4 and reviews/
  schema5, material/schema6 and proposals/schema7 require explicit creation/migration. Actor attribution and captured
  trust DTOs do not authenticate. Production auth/method/reviewer/control ports,
  confirmation/outbox and Server/CLI remain
  incomplete. Raw responses now use explicit same-authority BlobStorePort and
  schema2 ReviewRecord; schema1 remains historical and cannot pass current gate; no legacy fallback. See nightly/status and
  docs/migration/engineering-schema5-reviews.md.
- `packages/interfaces/workbench/*` — independent extension API/runtime/host/loader,
  Workbench and shared UI packages. Desktop privileged bridges live under
  `apps/desktop/electron/{server-bridge,native-bridge}`; the old `packages/frontend`
  source path is retired.
- `apps/desktop` — Electron app shell (its own `AGENTS.md` has the desktop
  host rules). `plugins/*` — desktop plugins. `apps/desktop/packaging/product` — assembly
  manifest for the default product build.
- `packages/execution/agents` (`ordessa_execution_agents`) owns the sole
  Agent/Profile service implementation on the original Pacthold Environment,
  CoreRegistry, store, issuer/verifier and records. UI and CLI are consumers.
  `pacthold.agents` Python imports are retired; the reserved owner, ACL, wire
  and persisted namespace identifiers are preserved. Do not restore aliases.
  The old Agent/Profile backend plugins and server-compat are retired.
  Remaining runtime-compat/product legacy paths are not alternative authorities.
  Assets own their resources under `plugins/agents/resources/`.
  Migration source baseline and retirement map: `docs/implementation/specifications/032-architecture-cleanup`.

## Rules

1. **Feature work branches from the fixed baseline** named in
   `docs/reference/baseline.md`; integration commits to `main` go through review.
2. **Python packages** keep their own `pyproject.toml` and install editable
   (`packages/execution/kernel`, `packages/execution/agents`, `apps/server`, independent Harness leaves). **JS/TS** uses npm
   workspaces at the root. Do not cross-wire package managers.
3. **Import boundaries are load-bearing**: `pacthold` must not import
   `ordessa_server`/`ordessa_harness`; plugins import platform contracts,
   never host internals; the product must not assemble bridge-internal paths.
   Execution Agent services depend on neutral Pacthold/Environment contracts;
   shared packages must not statically import concrete plugins, and plugins
   must not import apps. Boundary tests exist — keep them passing.
4. **No binaries in git.** Build the bridge via its packaging script; pin
   toolchain versions as recorded in `docs/reference/baseline.md`.
5. **Data compatibility**: on-disk formats (data-root layout, DB migrations,
   deployment JSON, extension ids) keep their existing identifiers. Renames
   require an explicit note in `docs/migration/` and user confirmation if
   user data is affected.
6. Old names (`agent_box`, `agent-box`) remain only where they are upstream
   identifiers, URLs, licenses or history documents — listed in
   `docs/reference/naming.md`.
7. **Credentials and user data never enter this repo.** In-place run-data
   directories kept for live services are environment exceptions, listed in
   `docs/reference/known-issues.md` and ignored explicitly — they are not part of the
   source tree, and `.gitignore` is not a substitute for physical removal.
8. Do not kill/restart user-facing services. The live-service registry and
   "may I touch it" status live in `docs/reference/known-issues.md` §services.
9. Real-model test calls require prior user authorisation (scope + cost).
   Controlled tests must not fake green: no assertion deletion, no skips to
   hide failures, no reviving legacy compat chains.
10. The baseline carries registered known issues (`docs/reference/known-issues.md`);
    "not perfect" does not block development, but every known failure must be
    honestly registered there.

## 重构与迁移：彻底替换，不保留隐性旧链

当用户明确要求迁移、合并、替换或清理某项职责时，目标是完成
职责、状态权威、调用入口和产品装配的整体切换，而不是在旧实现旁
增加一套新实现。本规则适用于所有参与本仓库任务的主代理和子代理。

- 不得以“兼容”“避免影响使用”“后续清理”为由，擅自保留用户
  明确要求退役的旧实现、旧入口、转发层、回退路径或重复状态。
- 清理必须覆盖源码、依赖、注册入口、产品装配、测试、脚本和文档。
  删除目录但保留旧调用链，或停止注册但保留可达旧实现，均不算完成。
- 新实现尚缺能力时，应明确标记不可用或拒绝调用，不得偷偷回退旧链。
  用户优先接受结构干净、缺口明确的未完成产品，而不是表面可用、
  内部新旧并存的产品。
- 数据格式、历史标识及用户数据的保留，不等于保留旧执行路径。
  必要迁移工具应独立、显式，不得成为正常运行时的兼容链。
  本规则不授权删除用户数据、降低测试断言或扩大既定修改范围。
- 如确实必须暂留旧实现，必须先取得用户批准，说明精确范围、原因、
  可达入口及退役条件。未获批准不得自行暂留。
- 完成报告必须证明旧职责及旧入口已退役、消费者已切换、
  状态权威唯一。新模块存在或局部测试通过，不构成迁移完成。

禁止把“新增实现完成”表述为“替换迁移完成”。
允许功能缺口，不允许未经批准的架构残留；未完成就明说，
不能用旧链撑出完成的假象。

## Entry points

Current local nightly-development baseline and preserved-source receipts:
`docs/migration/worktree-consolidation-20261007.md`. Work only in the root
checkout unless separately authorized to create a worktree. Archived directories
outside the repository are recovery material, not active source or editable
dependencies. This consolidation does not authorize a push or a main merge.

| I want | Go to |
| --- | --- |
| Build/run/test commands, toolchain versions | `docs/reference/baseline.md` |
| Component map and dependency direction | `docs/architecture/overview.md` |
| Registered known issues & untested scope | `docs/reference/known-issues.md` |
| Where old code/history lives, how to restore | `docs/reference/index.md` |
| Naming map (old→new) | `docs/reference/naming.md` |
| How this monorepo was assembled | `docs/migration/` |

## 2026-10-09 夜间准备与后续重构

本轮用户已明确授权从实时 `c5c0e50b08178cbfb52aa5e423d904aa9c5b5145` 建立
`codex/nightly-restructure-20261009`，工作目录 `worktree/nightly-restructure-20261009`。
这是此前“仅根目录”规则的本轮显式例外；根树/旧成果保持。准备仅改资料、文档和计划，
本主会话已收到 `/goal`，正式实施激活；状态与证据按nightly/status更新。调度权威是 `docs/implementation/nightly/README.md`，
现行文档总入口 `docs/README.md`；详细设计是目标，当前源码按映射与实测状态说明。

主协调者独占公共契约/迁移/装配/锁文件/Git索引与提交，最多3子任务（一Sol两Luna），
文件写权不重叠、测试安装构建串行、无递归扩队。不得reset/覆盖/清理用户改动和旧工作树。
必须保留全部Harness、桌面、配置、权限、原生记录；packages/plugins不导apps，公共packages
不静态依赖具体插件，需AST/实际隔离导入/TS与发行检查及植入反例。

模型供应商OpenCode不限定Harness。key只读根`.env`或临时进程环境，不复制/打印/提交。
仅经官方验证域名调用，免费不可用不静默切付费；收费批量/持续先报告预算。
开发授权不等于产品内部可信人类Grant。不推送、不合并main、不重启用户服务、不迁移真实数据库。

当前实际提交、各片实测及未完成项以nightly/status为准。W08唯一Decision/Jev目录切换的实测与提交记录见该入口。Engineering唯一源码已从packages/backend/engineering
整体迁到packages/engineering；保持distribution/import/data标识，不建旧path shim。
packages/interfaces和packages/infrastructure为真实独立发行包，Python同源安装按
python-workspace.json和tooling/workspace/python_workspace.py；root环境不能验证此worktree改动。
access/ACP relay的完整原测试归tests/integration/harness/access，继承断言保留。
新结构只部分生效，旧职责退役与消费者/产品装配仍按各工单验证，不以目录存在报完成。

The original OperationJournal and UnitRecords now belong to
`ordessa_execution_agents.units.records` in the same execution distribution.
The old records distribution/import root is retired without aliases; native
SQLite paths, tables, identities and unknown fences are preserved. Shared
contracts/materialization and the Codex record-codec split remain W06 targets.

Current material commands use interface2 and ArtifactRevision schema2 on explicit schema6; historical schema1 is readable, never a new-schema write fallback. Same-TX material validation shares the original blob table and published Snapshot source helper. Version/artifact-source and generation owners remain unavailable. See docs/migration/engineering-schema6-materials.md and nightly/material evidence; no production auth/trust or whole-product completion is implied.

Schema7 now persists Change/Proposal/control and expands actual review requirements in the original EngineeringLibrary/UoW/journal. Source and installed noneditable Engineering wheel each pass488 tests without skips; scopes overlap and dependencies remain the nightly environment, not a full product distribution. Production auth/catalog/trust, baseline owner, AuthorizationIntent/Grant/outbox and Server/CLI remain incomplete. Pure ActionScope is not permission. Current evidence: docs/implementation/nightly/evidence/W04/proposal-checkpoint.md; migration: docs/migration/engineering-schema7-proposals.md. New Proposal writes with ImplementationIntentSpec explicitly reject until the actual baseline owner is bound.


W10 now selects one InstanceAccessAuthority in the default Server. The instance bearer is a machine identity with no default Engineering grants; original local owner ACLs remain. HTTP/wire/REST/WS share this identity mechanism; missing authority refuses, without the old token fallback. Real SQLite admission/COMMIT, revocation and copied-context negatives are verified. Full production Engineering catalog/receipt, project mapping, CLI and human confirmation remain incomplete. Server now requires Python >=3.12, matching its direct interfaces dependency. See [W10 actual evidence](docs/implementation/nightly/evidence/W10/README.md).

## 2026-10-12 packages 收敛与工程规范

本轮用户已批准修订后的 packages 目标架构及工程组织规范，并授权实施。
先阅读唯一正文 [工程组织与模块边界规范](docs/standards/engineering-standard.md)。
正文按 Library 最新 revision 4 逐字保存，明示规范已确认并将迁移补充约束
纳入当前实施。已批准边界优先于规范中的一般组织建议。

此前关于 kernel、c1-api 的描述记录迁移阶段的实际状态，不是继续保留它们的
目标授权。当前目标及依赖边以该规范和本轮已批准架构为准；既有数据、服务、
凭据、测试断言和无 push／main 合并要求继续适用。

采用 Sol 协调、多个 Luna 执行；写入范围互不重叠、禁止递归扩队，
测试、安装和构建由协调者串行安排。共享工作区清单、锁文件和跨包检查
由 foundation 组统一集成，其他组提交实际文件与接口的精确请求。

2026-10-12 夜间，用户另行明确授权将经核验的开发检查点提交并推送到
现有 `codex/nightly-restructure-20261009` 分支。这是对前述“不推送”约束的
本轮精确例外：仅限该开发分支和明确归属、经核验且不含敏感材料的文件；
不授权合并 `main`、force push、reset、远端删除、历史改写，或纳入未知归属
及敏感文件。Foundation 的 Sol 是唯一 Git 操作者。Sol 负责拆解、协调、
契约审查与整合，多个 Luna 执行常规源码、文档和测试修改；测试、安装、
构建仍由 Sol 串行调度。发布前仍须按精确文件清单核对归属和发布风险。

本轮 foundation 交接入口：
[packages convergence / foundation](docs/implementation/packages-convergence-20261012/foundation/README.md)。

## Ordessa 工程约束

先阅读 docs/standards/engineering-standard.md，并遵守任务范围内更具体的说明。

- 已确认架构是实现与验收的前置约束；owner、依赖方向、公开 API 和
  唯一正式运行链必须与行为回归同时收敛，不得为接通或变绿恢复旧链，
  不得把结构清理推迟为功能完成后的可选优化。按完整可验证切片推进。
- 先确定责任 owner，再决定文件与目录。按职责、依赖和变化原因拆分；
  不实行一类一文件，不按行数强拆，不预建空骨架或对称模板。
- 同级项按父目录的组织问题归属；同级不代表无依赖或相同抽象层级。
- apps 只承载入口与装配。政策归根目录 methods，工程解释与推进归
  engineering，执行机制归 execution；provider 实现在 plugins，
  infrastructure 不承载业务语义。
- 跨 owner 仅用公开 API 或端口，不访问私有实现，不产生依赖环；
  TYPE_CHECKING、import type 和延迟导入不能规避依赖规则。
  owner 内部可直接导入内部文件，无须每层都经 __init__ 或 index 转发。
- 一个语义模型只有一个权威 owner。definitions 只含声明和局部不变量；
  I/O、解析、跨对象验证、装配和运行状态转换放在相应责任处。
- domain 与方法解释器互不依赖；application 经自身端口使用执行能力，
  adapter 对接 execution。decision 与 units、agents、environments 独立。
- 保留 ACP 原生语义，勿另造通用协议重译；engineering 仅经公开端口
  接收方法要求的报告，不扫描外部代码。unit 完成不等于工程验收通过。
- 优先复用语言和已有库的真实接口；不为日志、helper 或一次调用造框架。
- 迁移同步修改调用者、测试、配置和文档；移除旧入口，
  不保留新的 kernel、c1-api 或无期限 legacy 转发层。
- 同一职责、同一操作只保留一条正式运行链，不设隐式回退或双写。
  迁移共存须有负责人、范围、权威路径、退出条件和期限；旧转发层
  不算退役。验收须核查退役引用、实际公开调用链和安装／构建产物，
  demo 与端到端测试必须使用正式装配，必要行为测试不得被删掉绕过。
- 替代就绪、调用方切换且回归通过，就在本批清理旧链；权威歧义、
  反向依赖或双重维护须优先收敛。拒绝新增退役依赖，暂缓项须写明
  能力缺口、负责人和下一检查节点，不得等全部新功能完成再清理。
- 用户指定的清理优先级不得静默降低；主计划列出剩余调用方、目标
  owner 和删除批次。每个检查节点须减少旧依赖或关闭明确前置条件，
  否则主动报告具体阻塞并重排；协调方须核查，不能以无关进展代替。
- 多 agent 写入范围必须清楚且不重叠；共享契约由牵头者协调一人修改。
- 提交时报告实际检查结果；未运行或阻塞须明示。例外须具体且限时。

按规范可判断的局部组织自行决定。改变既定架构、公开契约、重要政策
或授权范围时，先提出明确决策。

## 2026-10-12 独立安全开发检查点发布授权

用户本轮另行授权以独立新分支发布经过审查的开发检查点：
`codex/packages-convergence-publish-20261012`，唯一父提交为已确认的远端
`main` `b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`。此项授权不改写本文件前述
授权或规则，仅增加下述精确例外。

首片仅使用冻结的 Foundation 精确文件清单与该清单中的公开发布计划；不得
加入 SQLite 数据库、凭据、原始日志、私有收据、个人主机元数据或未确认
归属的文件。使用临时 `GIT_INDEX_FILE` 从上述父提交初始化并构造提交；不得
checkout/复制整棵工作树，不得改变现有 nightly 工作分支、`main`、历史、
架构审查树或正常 Git index。只可对该全新分支做非强制 push；禁止 force、
reset、删除远端分支、合并 `main` 或历史改写。

Foundation Sol 是唯一 Git 操作者。其他 owner 仅能在完成契约审查和验证后，
按新的精确冻结文件清单追加其已授权范围；不得以目录白名单扩大首片。
现有其他远端分支及其历史保持不变。
