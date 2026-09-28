# Development baseline

Baseline identity: `main` at the root-switch commit (SHA recorded in
`docs/migration/README.md` assembly table; tag `baseline/cp-monorepo-0` at
switch). Sources: HD-002 candidates backend `a0b343e0` / desktop `450944bd` /
ACP bridge `41d9d94`, ancestor = former `agent-box` remote main `6c14ea8d`.

Known issues are registered, not blocking: `docs/known-issues.md`.

## Toolchain (pinned, verified 2026-09-25)

| Tool | Version |
| --- | --- |
| Python | 3.12.14 (suite-verified; Server/Pacthold floor 3.9, Harness API/default product floor 3.10) |
| Go | 1.24.13 linux-amd64 (`/home/maoqh/ordessa-builds/go1.24.13`, tarball sha256 `1fc94b57…` — build record in `plugins/harness/adapters/` docs) |
| Node / npm | 22.22.1 / 9.2.0 (frozen `package-lock.json`; npm-free-resolution has a known arborist crash — always install from the lock) |
| Bridge build | `CGO_ENABLED=0 go build -buildvcs=false -trimpath -ldflags "-buildid=" ./cmd/acp` — reproduces sha256 `5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea` byte-for-byte |

## Desktop

```sh
npm ci                       # 277 packages, from lockfile
npm run typecheck
npm test                     # root JS aggregate (tooling/test-all.mjs, T021): typecheck +
                             # real builds + every workspace suite (the Agent/connector plugin
                             # suites live in each package's tests/ since T019) + product
                             # guards + ACP rig + Electron gates; C0 composite run = 25 suites
                             # (~110 s), each suite keeps its own exit code;
                             # `npm test -- --list` prints them
npm run build                # 10 enabled extensions + electron app
npm run --workspace apps/desktop test              # host shell only: 3 files / 36 tests (FR-010)
(cd tests/acp-connector && npm ci && npx vitest run)   # 79 tests
npm run test:agent-shell && npm run test:electron      # headless smokes (xvfb)
```

## Backend

```sh
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r apps/server/lockfiles/server-linux-py312.txt   # verified closure (starlette pinned 1.7.0)
pip install -e 'packages/pacthold[dev]' -e packages/server-plugin-api -e plugins/harness/api \
  -e 'apps/server[dev]' -e 'plugins/harness[dev]' -e plugins/workspace \
  -e plugins/server-compat -e plugins/runtime-compat -e products/server
python -c "import pacthold, server_plugin_api, ordessa_harness_api, ordessa_server, ordessa_harness, ordessa_server_product"
python -m pytest packages/pacthold              # 238 passed (run from repo root: cwd must be on sys.path)
python -m pytest plugins/harness                # 308 passed / 3 skipped / 2 failed (inherited)
python -m pytest apps/server                    # inherited-red ledger: docs/migration/backend-build-test.md
bash scripts/start-server.sh 8931             # loopback smoke, throwaway data root
bash plugins/harness/packaging/acp-adapter/build-acp-adapter-round-h.sh  # reproducible bridge (never committed)
```

Suite expectations (verified by two separate evidence kinds — see
`docs/migration/README.md` §verification gates: run6 count gate + per-ID
ledger diff): pacthold green; harness carries 2 inherited npm-closure
failures; the server suite carries the classified inherited-red ledger from
the bc-native baseline (the frozen baseline itself was 97 failed + 25 errors /
1755 passed; migrated: 783P/43F/10S/25E = 59 inherited same-id + 6 ruled
scope-reds, per-item rulings in `docs/known-issues.md`).
`tests/acp_orchestration` reds are the worker-entry retirement ruling — do
not revive compat chains to green them.

The commands above include the post-010 public Server and Harness API packages
and the default product. The counts beside individual `pytest` commands are
the frozen switch baseline, not current C0 acceptance. C0's measured four-suite
per-ID comparison and current frontend aggregate are in
`specs/011-c0-foundation-harness/report.md`; inherited reds remain visible.

## Untested scope (honest boundary)

- Real-model end-to-end chain: not exercised in this migration (no API calls
  authorized). Version-matched controlled evidence: Round H acceptance
  2026-09-25, 11/11 gates — details in `docs/known-issues.md`.
- Full GUI acceptance incl. the two registered UI debts.
- Windows-side flows (the WSL/Windows split legs of old rounds).

## Deriving work from this baseline

Branch from the switch-commit SHA; per-stream trees and business lanes follow
the layout in `docs/architecture.md`. Profile/Provider/Workboard work happens
in their independent repositories, not here.
