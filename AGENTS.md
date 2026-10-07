# Ordessa — workspace instructions for agents

This directory is the **Ordessa product monorepo**. One repository holds the
product's active source; the previous multi-repo workspace organisation has
been retired (history and restore paths: `docs/reference-index.md`,
`docs/migration/`).

## What this repo is

- Product/repo name: **Ordessa**. Remote identity: `github.com/mmm-05610/ordessa`
  (renamed from `mmm-05610/agent-box` on 2026-09-29; GitHub redirects the old
  URL) — see `docs/migration/remote-plan.md` before any publish work; **no push
  without explicit user authorisation**.
- `packages/backend/pacthold` (Python `pacthold`) — governance kernel and plugin SDK.
  Zero product dependencies. Nothing here may import a plugin, app or product.
- `apps/server` (Python `ordessa_server`) — Ordessa Server. Depends on
  `pacthold`, composes the plugin root, owns wire/transport.
- `plugins/harness/*` — independent brand providers. The integrated baseline
  still contains the retired-target `ordessa_harness` aggregate; remove it by
  `specs/032-architecture-cleanup`, never add a new consumer or hidden fallback.
  Brand bridge internals stay behind public provider ports.
- `packages/frontend/*` — independent extension API/runtime/host/loader,
  Workbench, UI and bridge packages; `frontend/` itself is not a package.
- `apps/desktop` — Electron app shell (its own `AGENTS.md` has the desktop
  host rules). `plugins/*` — desktop plugins. `products/desktop` — assembly
  manifest for the default product build.
- Agent/Profile authority belongs to Pacthold; UI and CLI are consumers.
  The remaining legacy plugins in this integrated baseline are explicit
  retirement targets, not alternative authorities. Assets own their resources.
  Migration source baseline and retirement map: `specs/032-architecture-cleanup`.

## Rules

1. **Feature work branches from the fixed baseline** named in
   `docs/baseline.md`; integration commits to `main` go through review.
2. **Python packages** keep their own `pyproject.toml` and install editable
   (`packages/backend/pacthold`, `apps/server`, independent Harness leaves). **JS/TS** uses npm
   workspaces at the root. Do not cross-wire package managers.
3. **Import boundaries are load-bearing**: `pacthold` must not import
   `ordessa_server`/`ordessa_harness`; plugins import platform contracts,
   never host internals; the product must not assemble bridge-internal paths.
   Boundary tests exist — keep them passing.
4. **No binaries in git.** Build the bridge via its packaging script; pin
   toolchain versions as recorded in `docs/baseline.md`.
5. **Data compatibility**: on-disk formats (data-root layout, DB migrations,
   deployment JSON, extension ids) keep their existing identifiers. Renames
   require an explicit note in `docs/migration/` and user confirmation if
   user data is affected.
6. Old names (`agent_box`, `agent-box`) remain only where they are upstream
   identifiers, URLs, licenses or history documents — listed in
   `docs/naming.md`.
7. **Credentials and user data never enter this repo.** In-place run-data
   directories kept for live services are environment exceptions, listed in
   `docs/known-issues.md` and ignored explicitly — they are not part of the
   source tree, and `.gitignore` is not a substitute for physical removal.
8. Do not kill/restart user-facing services. The live-service registry and
   "may I touch it" status live in `docs/known-issues.md` §services.
9. Real-model test calls require prior user authorisation (scope + cost).
   Controlled tests must not fake green: no assertion deletion, no skips to
   hide failures, no reviving legacy compat chains.
10. The baseline carries registered known issues (`docs/known-issues.md`);
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

| I want | Go to |
| --- | --- |
| Build/run/test commands, toolchain versions | `docs/baseline.md` |
| Component map and dependency direction | `docs/architecture.md` |
| Registered known issues & untested scope | `docs/known-issues.md` |
| Where old code/history lives, how to restore | `docs/reference-index.md` |
| Naming map (old→new) | `docs/naming.md` |
| How this monorepo was assembled | `docs/migration/` |
