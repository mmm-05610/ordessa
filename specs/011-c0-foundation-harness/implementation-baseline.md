# C0 implementation baseline

Status: in progress. This measured input ledger is supplemented by the fixed `foundation` publication `8844c475bc02a185ab194c69eed873122aa48349`; it does not claim Harness v2 completion.

## Frozen repository state (2026-09-28)

| Input | Full commit | Observation |
| --- | --- | --- |
| C0 start | `96fef2db47f485091ccaadda96f5321400b249f2` | `codex/011-c0-foundation-harness`; clean at first inspection (`git status --short --branch`) |
| Common parent | `cd7d31f3cfba6a0e1ec65f9a13014c6b9751540b` | `git merge-base HEAD codex/010-platform-server`, `...-pacthold`, `...-frontend`, `codex/workbench-sidebar` all returned this commit |
| A published implementation | `b47b6d78038a7ecabda551b43c18735d32bed012` | Already an ancestor of B's committed branch (B report states merge `4a43f0b304`); A final report tip is `9e33a4df5120645de0bb8c492a8b7610adf5a9bb` |
| B final handoff | `888d69f853a38427e8131bec462ca4327821b835` | `IMPLEMENTATION_REVIEW_READY`; last code-bearing `7248db4f025d328f84f4255174c266450be32796`; merged here at `26be37359dbfbf342fe8a5994ed1e291d8f42098` |
| C7/C8 | `82b7ef1fc3fc79037b7a6d4749b612d4f54865fd` | merged here at `3660bacc7e26cfa0b4648c382925181345b2ea96`; composite UI gates in `report.md` |
| Workbench sidebar | `2b22e1608f934d1810f4a09f626f46e9e36b2d1e` | merged here at `4929437e57381d72ae01bef1bee3455d89dc83aa`; real-browser follow-up at `eabc77c96f` |

The published B report records the server suite at 67 reds after one named retirement from its 68-red T002 baseline; harness 2 reds and ACP orchestration 18 reds remain. C0's first four-suite rerun and later Server host-wiring rerun are recorded with JUnit digests and per-ID comparison in `report.md`. B's missing-history-migration-provider and bare-host import gaps were repaired in C0. Foundation's clean-clone wheel installation and selected-product startup proof are also in that report. No uncommitted B files are input.

## Environment observed in C0 tree

- `python3.12 --version` → `Python 3.12.14` (exit 0).
- `node --version` → `v22.22.1` (exit 0); `npm --version` → `9.2.0` (exit 0).
- `go version` → exit 127 (`go` absent from PATH). The pinned toolchain is documented at `docs/baseline.md`; the Go bridge gate has not run here.
- No `.venv` or root `node_modules` existed at initial inspection. The current C0 environment was installed after B integration; results are in `report.md` and must not be confused with the initial observation.
- C0 created `.venv` and installed `apps/server/lockfiles/server-linux-py312.txt` successfully (exit 0). The first editable install before B merge exited 1 because `packages/server-plugin-api` was absent. After B merge, `pip install -e 'packages/pacthold[dev]' -e packages/server-plugin-api -e 'apps/server[dev]' -e 'plugins/harness[dev]' -e plugins/workspace -e plugins/server-compat -e plugins/runtime-compat -e products/server` exited 0. The later Harness API source was supplied by `PYTHONPATH=plugins/harness/api/src` for the first Harness full-suite snapshot; the API wheel is now installed in this venv, and an independent clone/venv installed all nine built wheels without editable links for the foundation gate.
- Required suites: `packages/pacthold`, `plugins/harness`, `apps/server`, `tests/acp_orchestration`, with full JUnit and per-ID reason diff; independent `plugins/harness/api` wheel and changed frontend workspaces after integration. Evidence output stays under `/tmp` or another external evidence root, not in git.

## Scope and ownership

The C0 write boundary and the cross-line overrides are in `specs/011-plugin-rollout/plan.md`. T10/T11 business adapters belong to Z3/Q1, Profile glue to Z1, and Permissions policy to Q5. C0 owns Harness runtime and ACP control/submit seams, public product composition, root lock, compat retirement, integration tests, and the final evidence ledger. This mapping is a responsibility assignment; it is not evidence that the dependent line has delivered.

## B2 ACP owner symbol map (read-only production inspection)

`plugins/connectors/acp` owns the desktop ACP connector as `ordessa.agent-acp` (`manifest.json`, `entry.ts`), and the default desktop product enables it once. Its production path acquires native orchestration in `entry.ts`, opens `acp.channel.open` in `native.ts`, initializes the ACP SDK in `client.ts`, and currently reaches `session/new` and `session/prompt` directly from `createAndSend`/`sendMessage`. `createAndSend` ignores its `requestId`; `native.ts` relays arbitrary frames; `requestPermission` maps a frontend choice directly to SDK resolution. The package's 10 tests pass, but their HTTP Server and HarnessPeer are fakes. These are exact T13/G18/G19 missing production seams: no backend-held one-use permit bound to request/channel/session/generation/config digest, no unknown-after-restart refusal, and no execution-time permission authorization. A frontend-only guard would be bypassable through the native relay. This map is an implementation input, not a passing gate.

`plugins/connectors/ordessa` has a useful first-send pattern: `OrdessaClient.createAndSend` preserves the caller `requestId`, native `sessions.createAndSend` revalidates the project/profile, and an uncertain outcome queries `sendOutcome.query` with that same ID. `approvals.decide` uses expected version and once scope. Its package tests pass 41/41 against mocked wire/bridge. Both first and follow-up send still hardcode `attachments: []` and `overrides: []`; no attachment prepare/reference/cleanup, safe picker, native command catalog, configuration generation/digest, or backend permit exists. Follow-up send creates a new request ID and has no unknown-outcome query. These are candidate reuse points for the C0 implementation, not evidence of G18/G19 completion.
