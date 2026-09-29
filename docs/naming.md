# Naming map — old → new

One-time list produced by the migration contract
(`docs/migration/shared-contract.md` §3). Mechanical renames were applied to
active code only; the exceptions column lists every place an old name
legitimately survives.

## Distribution / import names

| Old (source tree) | New (this repo) | Kind |
| --- | --- | --- |
| `pacthold` 2.0.0a1 (declared) but modules under `agent_box` | `pacthold` — `packages/pacthold`, import `pacthold` | dist + import |
| `agent_box.server` (inside core package) | `ordessa_server` — `apps/server`, import `ordessa_server` | dist + import |
| `plugins/agent-box-harness` / `agent_box_harness` | `plugins/harness`, dist `ordessa-harness`, import `ordessa_harness` | path + dist + import |
| entry points `agent-box`, `agent-box-server`, `agent-box-server-credential` (aliases in source pyproject) | dropped in this baseline; entry points are `pacthold…` / `ordessa-server…` (see `docs/baseline.md`) | CLI |
| desktop root package `ordessa-desktop` | repo root `ordessa` (private) | npm |
| `products/agent-desktop` | `products/desktop` | path |
| acp-adapter (Go) | `plugins/harness/adapters/acp-adapter` — **module path unchanged** (upstream-derived) | path |

## Where old names intentionally remain

| Old name | Where | Why |
| --- | --- | --- |
| `agent-box` / `agent_box` | archive refs `refs/archive/agent-box*`, commit history, bundle filenames | history is immutable |
| `https://github.com/mmm-05610/agent-box.git` | historical URL; renamed 2026-09-29 to `https://github.com/mmm-05610/ordessa.git` (redirect kept) | old URL remains a history identifier |
| `beyond5959/acp-adapter` go module path | `plugins/harness/adapters/acp-adapter/go.mod` | upstream identifier |
| `NousResearch/hermes-agent` | upstream remote of the desktop lineage; LICENSE copyright lines | upstream attribution |
| `agentbox-*` data roots (`~/.agentbox-trial-chat`, `~/.agentbox-qa-2nd`, `~/.agentbox-all-harnesses`) | live user data locations | user data, unchanged |
| deployment JSON schema keys, extension ids (`ordessa.*`), DB migration numbering, `--plugin-root` tree ids | on-disk data | data compatibility (see `docs/architecture.md`) |
| dated migration/review documents under `docs/` that quote old paths | kept verbatim | historical evidence, marked |

## Active-code rename verification

The rename gate for this baseline is recorded in `docs/baseline.md`
(grep scope, allowed exceptions, results). `agent_box`/`agent-box` must not
appear in active Python imports, entry points or build scripts; occurrences
in the exceptions table above are the complete allowance.
