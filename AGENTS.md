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
- `packages/pacthold` (Python `pacthold`) — governance kernel and plugin SDK.
  Zero product dependencies. Nothing here may import a plugin, app or product.
- `apps/server` (Python `ordessa_server`) — Ordessa Server. Depends on
  `pacthold`, composes the plugin root, owns wire/transport.
- `plugins/harness` (Python `ordessa_harness`, dist `ordessa-harness`) — agent
  harness lifecycle, ACP adaptation, and the Go ACP bridge at
  `adapters/acp-adapter`. Bridge internals (build flags, binary paths, Pi CLI)
  are **harness-internal**; upper layers consume start/connect/close only.
- `packages/desktop-platform/*` — extension api/loader/host, native bridge,
  contracts. Independent npm packages under one umbrella.
- `apps/desktop` — Electron app shell (its own `AGENTS.md` has the desktop
  host rules). `plugins/*` — desktop plugins. `products/desktop` — assembly
  manifest for the default product build.
- Profile / Provider / Workboard continue as **independent repositories
  outside this monorepo** (archived refs kept here, live trees listed in
  `docs/reference-index.md`). They are not part of this baseline; no
  placeholder implementations for them belong in `main`.

## Rules

1. **Feature work branches from the fixed baseline** named in
   `docs/baseline.md`; integration commits to `main` go through review.
2. **Python packages** keep their own `pyproject.toml` and install editable
   (`packages/pacthold`, `apps/server`, `plugins/harness`). **JS/TS** uses npm
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

## Entry points

| I want | Go to |
| --- | --- |
| Build/run/test commands, toolchain versions | `docs/baseline.md` |
| Component map and dependency direction | `docs/architecture.md` |
| Registered known issues & untested scope | `docs/known-issues.md` |
| Where old code/history lives, how to restore | `docs/reference-index.md` |
| Naming map (old→new) | `docs/naming.md` |
| How this monorepo was assembled | `docs/migration/` |
