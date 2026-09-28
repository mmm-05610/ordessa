# T00 — Q3 implementation baseline (frozen facts)

Frozen 2026-09-28 by the Q3 main agent. Every SHA/version below was re-read from
this worktree in this turn, not copied from a design document.

## Git identity

| Item | Value | How measured |
| --- | --- | --- |
| Working directory | `/home/maoqh/projects/ordessa/worktrees/011-q3-subagents` | `pwd` |
| Branch | `codex/011-q3-subagents` | `git status` |
| Tree start HEAD | `96fef2db47f485091ccaadda96f5321400b249f2` | `git rev-parse HEAD` |
| `main` | `cd7d31f3cfba6a0e1ec65f9a13014c6b9751540b` | `git rev-parse main` |
| `merge-base HEAD main` | `cd7d31f3cf…` (== main) | `git merge-base` |
| `refs/heads/codex/011-plugin-plan` | `96fef2db47f485091ccaadda96f5321400b249f2` | `git rev-parse` |
| Start state | clean (`git status --short` empty) | `git status` |

The plan anchor and the tree start commit are the same object, so this line
derives from the design snapshot recorded in `specs/011-plugin-rollout/README.md`
(parent `cd7d31f3cf`) plus the Spec Kit rollout preparation commit.

## Dependency checkpoints — actual state at freeze time

`git branch -a` in this repository (worktrees share refs) contains **none** of the
five producer checkpoint branches:

| Checkpoint | Unique producer | Branch searched | Present? |
| --- | --- | --- | --- |
| `foundation` | C0 | `codex/011-foundation-ready` | **NO** |
| `harness-api` | C0 | `codex/011-harness-api-ready` | **NO** |
| `profile-api` | Z1 | `codex/011-profile-api-ready` | **NO** |
| `chat-api` | Z2 | `codex/011-chat-api-ready` | **NO at freeze time** |
| `permissions-api` | Q5 | `codex/011-permissions-api-ready` | **NO** |

**Amendment, measured later the same session (2026-09-28 02:22 +08):** `chat-api`
was published by Z2 while this line was working. Q3 consumed it by **fixed
publication SHA** `54ad26c15d8480823374d85590919ba6bcca60d2`
(`status: READY`, `implementationSha: a3ec20c046…` verified as an ancestor,
`planAnchorRef` = `codex/011-plugin-plan` = this line's own base `96fef2db47`),
merged as commit `c0686a2407`, and re-ran its proofs in this tree (vitest 15/15,
`tsc --noEmit` exit 0). The table above is kept as the honest freeze-time
snapshot rather than rewritten. `foundation`, `harness-api`, `profile-api`,
`permissions-api` remain unpublished. `specs/011-plugin-rollout/checkpoints/`
still did not exist at freeze time; it now exists with `chat-api.json` only,
which is why "none of the five" was true when measured.

`specs/011-plugin-rollout/checkpoints/` did not exist either. Consequence, per
`contracts/checkpoints.md` §"依赖不构成整线停机": this line executes its
independent entries (content domain, scope resolution, pure brand compilation,
migration importer, own tests) first and records precise seam requests in
`api-requests.md`. Entries whose *production wiring* needs a checkpoint stay
unchecked — they are not replaced by unit tests (spec.md §成功条件).

## Toolchain actually used by this line

| Tool | Version | Evidence |
| --- | --- | --- |
| Python (line venv) | 3.12.14 | `.venv/bin/python -V`, created locally per R01 |
| pytest | 9.1.1 → recorded also as pin `pytest>=7` | `.venv/bin/python -c "import pytest; …"` |
| Node / npm | system `node` `/usr/bin/node`, `npm` `/usr/bin/npm` (baseline pin 22.22.1 / 9.2.0, `docs/baseline.md`) | `command -v` |

This line created its **own** `.venv` (`python3.12 -m venv .venv`) and installs
nothing into any other tree, per `specs/011-plugin-rollout/spec.md` R01.

## Target-brand native entry points — pinned in code, verified by symbol

| Harness | Adapter package | Adapter pin | Native CLI pin | Source of pin (verified) |
| --- | --- | --- | --- | --- |
| Claude | `@agentclientprotocol/claude-agent-acp` | `0.81.2` | CLI `2.1.274` (comment evidence) | `plugins/harness/src/ordessa_harness/claude/production.py:66-67`; `plugins/harness/src/ordessa_harness/harnesses.toml:94`, `:111` |
| Codex | `@agentclientprotocol/codex-acp` | `1.1.14` | `@openai/codex` `0.147.0` | `plugins/harness/src/ordessa_harness/codex/production.py:85-88`; `plugins/harness/packaging/codex/package.json` overrides |
| Pi | `@automatalabs/pi-acp` | `0.5.0` | Pi packages `0.84.2` | `plugins/harness/src/ordessa_harness/pi/production.py:76-77`; `plugins/harness/packaging/builders/build-pi-runtime-artifact.mjs:69-71` |

Drift observed on this machine (registered, not hidden): the host has a `pi`
executable at `/home/maoqh/.local/bin/pi` reporting **0.86.1**, while the repo
pins Pi runtime packages at **0.84.2**. `claude` and `codex` executables are
**absent** from `PATH`. See `capability-matrix.md` for what this does and does
not prove.

## Harness contract surface that exists in code today

Read-only finding, verified by symbol grep across `plugins/`, `apps/`,
`packages/`, `products/`:

- `harness.configuration-adapters/v1`, `MountContent`, `RemoveOwnedContent`,
  `SetField`, `InvokeAction`, `IntentSet`, `runtime_generation`,
  `submission_permit` → **no code hits**. Design only
  (`docs/design/harness-v2/contracts.md`, which states verbatim
  `这些接口尚未实现。`).
- What *does* exist: `ordessa_harness.registry` (`HarnessRegistry`,
  `load_builtin_registry`, `HarnessDefinition`, `ProfileSpec`), capability
  vocabulary in `packages/pacthold/src/pacthold/resource_contracts/harness_capabilities.py`,
  `capability_claims(harness_type)`, runtime `HarnessAdapter` protocol in
  `plugins/harness/src/ordessa_harness/adapters/base.py`, `server_acp`
  channel registry (`acquire/release/stop_all`), and whole-document brand
  renderers (`{claude,codex,pi}/production.py`, `native_materialization.py`).
- No code anywhere reads or writes `.claude/agents`, `.codex/agents` or a Pi
  extension directory. So **there is no prior Q3 implementation to duplicate**
  and nothing to retire in this domain.

Therefore the brand adapters in this line are implemented as **pure**
`assess/compile/verify` functions over a typed intent that this domain owns, and
their registration/execution through the real Harness generation/reset/ACP
reload path is recorded as a seam request to C0, not simulated.

## Package position (T00 "real package path")

New, owned solely by this line: `plugins/assets/subagents/**`, Python package
`ordessa_assets_subagents`, distribution `ordessa-assets-subagents`. The root
`package.json` workspace glob `plugins/**` already discovers the directory
layout; the Python package is a separate editable install and does **not** need
a root lock change (registered in `integration-request.md` for C0's composition
step).

## Baseline test commands for this line

```sh
cd /home/maoqh/projects/ordessa/worktrees/011-q3-subagents
.venv/bin/python -m pytest plugins/assets/subagents -q       # this domain
.venv/bin/python -m pytest packages/pacthold -q              # shared kernel (unaffected)
.venv/bin/python -m pytest plugins/harness -q                # harness (unaffected)
```

Per-ID baselines and diffs are recorded in `regression-ledger.md`; expectation
sources for the inherited reds are `docs/baseline.md` and `docs/known-issues.md`
(`plugins/harness` carries 2 inherited npm-closure failures in
`tests/install/test_acp_schema_drift_target.py`).
