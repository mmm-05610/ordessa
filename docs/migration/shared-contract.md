# Ordessa Monorepo Migration — Shared Contract v1

Written by the lead agent (ZCode GLM-5.3), 2026-09-25, under the plan
`control/product/ordessa-monorepo-baseline-plan.md` and the user's authorization
of 2026-09-25. Every subagent reads this file first and follows it. Conflicts:
the plan document wins; report the conflict, do not improvise.

## 1. Frozen source points (measured 2026-09-25 ~21:00, all clean trees)

| Role | Repo (git common dir) | Branch | Commit |
| --- | --- | --- | --- |
| Backend candidate | `/home/maoqh/projects/agent-box/.git` | `work/hd002-bc-native` | `a0b343e0c01651d407adbc4a71c2d40b558840fb` |
| Desktop candidate | `/home/maoqh/projects/agent-box-desktop-next/.git` | `work/hd002-fc-functional` | `450944bd7a3569f8e6733d8bdb333f1efaa981b5` |
| Go ACP bridge | `/home/maoqh/ordessa-builds/acp-adapter/.git` | `work/round-h` | `41d9d94ef6b98547df575240c4366b1e5e8ba39b` |
| Remote identity to keep | `https://github.com/mmm-05610/agent-box.git` | `main` | `6c14ea8db8130f1e219328835840b4159fe8c9e7` (= local backend `main`) |
| Independent plugin Profile | `repos/harness-profile` | `work/initial-plugin` | `1191a41b9bf623eb1657adf0cf154ac72a1a6b68` (clean, protected, NOT into main) |
| Independent plugin Provider | `repos/harness-provider` | `work/initial-plugin` | `e925f23175ce9af3d70943e32eac78f447526f98` (clean, protected, NOT into main) |
| Independent plugin Workboard | `repos/harness-workboard` | `work/initial-plugin` | `9168313313c37bbcd663daa357360710d2ab685b` (clean, protected, NOT into main) |
| Control record | `/home/maoqh/projects/ordessa/control/.git` | `main` | `e2ab7409eeb02bfd9aa35da35aae5107ef56e5ec` + 56 dirty entries (checkpoint required) |

Sources are read at the committed tree only (`git archive`), never from a dirty
working copy. `.qoder/` untracked dirs are session settings — never copied.

## 2. Target monorepo layout (final root = /home/maoqh/projects/ordessa, built first at /home/maoqh/projects/ordessa-monorepo-candidate)

```text
apps/desktop/                    Electron app (from fc-functional apps/desktop)
apps/server/                     Ordessa Server (ordessa_server) (from bc-native src/agent_box/server + service wiring)
packages/pacthold/               governance core: pyproject + src/pacthold (work_core, storage, migrations, execution, extensions, service, resource_contracts, cli)
packages/desktop-platform/       extension-api, extension-loader, extension-host, native-bridge, contracts/* (keep independent npm packages under this umbrella)
plugins/harness/                 pacthold.harness_kit + adapters/acp-adapter (Go source) + packaging + tests
plugins/commands|workbench|connections|agent/*|connectors/*   (from fc-functional, unchanged paths)
products/desktop/                (renamed from products/agent-desktop — check references before renaming)
scripts/  tests/  docs/          root build/start/verify, cross-component tests, architecture/baseline/known-issues/reference-index/migration
package.json (npm workspaces) + package-lock.json + AGENTS.md + README.md
```

## 3. Naming map (decided by lead; agents apply mechanically, list exceptions)

| Old | New | Notes |
| --- | --- | --- |
| pyproject `pacthold` (already named) | `packages/pacthold`, dist `pacthold`, import `pacthold` | module dir `src/agent_box` → `src/pacthold`; all `agent_box`/`agent_box_harness` imports in ACTIVE code renamed; keep DB/config/data-format identifiers unchanged (data compat) unless individually justified |
| `src/agent_box.server` (+ its service entry) | `apps/server`, dist `ordessa-server`, import `ordessa_server` | server must import `pacthold`, never embed core |
| `plugins/agent-box-harness` | `plugins/harness`, dist `ordessa-harness`, import `pacthold.harness_kit` | only this backend plugin enters main |
| acp-adapter Go module | `plugins/harness/adapters/acp-adapter` | keep upstream Go module path; internal to Harness |
| desktop root pkg `ordessa-desktop` | monorepo root name `ordessa` | workspaces globs extended to packages/desktop-platform/* |
| `products/agent-desktop` | `products/desktop` | verify no hardcoded path first |
| Other bc-native plugins (artifacts, git, runtime-local, runtime-wsl, sandbox-bwrap, sandbox-windows, skills, terminal-session, web) | NOT in main | stay in archive refs; listed in migration table with reason |
| URLs, upstream Go module paths, LICENSE, history docs mentioning agent-box | keep old names | third-party/upstream identifiers are never renamed |

Data-compat rule: on-disk artifacts (data-root layout, DB, deployment JSON
keys, plugin ids like `agent-box-harness` if persisted by running services)
keep their old identifiers in this round; any unavoidable rename is listed
individually with migration/compat statement. The still-running hd004b leg
(pid 381142) must remain compatible with its frozen tree — it is not migrated.

## 4. History & preservation layout (lead integrates; history agent prepares)

- Fresh git bundle per repo into `/home/maoqh/projects/ordessa-preservation/20260925/bundles/` (verify each).
- Dirty-tree workspace backups (files tarball + MANIFEST.tsv + changes.patch + status + META) under `workspace-backups/<label>/`.
- Git-level checkpoint commits for dirty trees made in **clones** under `checkpoints/` — never stage inside a source repo.
- Archive ref map for the candidate repo: `refs/archive/<repo-key>/heads/<branch>`, `refs/archive/<repo-key>/tags/<tag>`, `refs/archive/<repo-key>/checkpoint/<label>`; curated `refs/reference/hermes-desktop|backend-legacy|studio-legacy`.
- repo-key values: `agent-box`, `agent-box-desktop-next`, `agent-box-studio`, `control`, `acp-adapter`, `harness-profile`, `harness-provider`, `harness-workboard`.

## 5. Hard boundaries for all agents

1. `/home/maoqh/projects/ordessa/**` and all source repos/worktrees are **read-only**. No commits, branches, staging, deletes, chmod, moves in sources. Writes only in your own assigned directory.
2. Never kill/restart services. Live now: qoder pids 36036/66577 (bc-native), 66935 (fc-functional), 273506 (desktop-ui-codex); server leg pid 381142 + access-entry 394938 + acp-adapter 394946; data under `/home/maoqh/ordessa-acceptance/`. Their paths are read-only.
3. Never read/copy credential contents: `.c1-001-secrets/`, any `*secret*`, key files, tokens. Record path + mode only. Same for user data roots.
4. No `git push`, no remote mutation of any kind. `git ls-remote` (read) is allowed.
5. No real model API calls; no tests that spend tokens. Controlled/fake tests only; anything needing a real model is listed as untested.
6. Don't park long-lived listeners on protected ports; scratch servers bind 127.0.0.1 high ports only, and shut down before you finish.
7. Report failures with evidence; no assertion deletion, no skip-to-green, no reviving legacy compat chains to make suites pass.
8. `node_modules/`, `.venv/`, build output, `__pycache__` never enter any archive or candidate tree.

## 6. Deliverables per agent (write to your dir, lead integrates)

- history agent → `ordessa-preservation/20260925/` + `REPORT.md` (inventory tables, ref map, restore evidence, open questions incl. "what is Hermes Desktop").
- backend agent → `ordessa-migration/backend/` : `tree/` (final-layout tree, no git), `MIGRATION-TABLE.md` (old path→new path→rename→reason per §3), `BUILD-TEST.md` (commands, env, results, inherited-red list), notes.
- desktop agent → `ordessa-migration/desktop/` : same shape.
