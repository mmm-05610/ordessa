# Ordessa architecture

Baseline structure (see `docs/baseline.md` for exact versions and
`docs/naming.md` for the old→new name map):

```text
apps/
  desktop/        Electron shell: lifecycle, security bridge, extension host boot.
                  No business logic; assembly comes from products/desktop.
  server/         Ordessa Server (ordessa_server): HTTP/WS transport, wire
                  schema, session/workspace/approval/asset endpoints, plugin
                  composition. Depends on pacthold, never embeds it.
packages/
  pacthold/       Governance kernel (src/pacthold): work_core execution
                  semantics, storage + migrations, execution composition,
                  extensions (plugin interfaces), service layer,
                  resource_contracts, CLI. Zero product dependencies.
  desktop-platform/
    extension-api/      registration/services/release contracts
    extension-loader/   discovery + loading
    extension-host/     activation, dependency & lifecycle
    native-bridge/      restricted native IPC
    connections/        generic Connections platform API (contract C6); the
                        platform ships no concrete protocol kind
    contracts/          platform-owned carriers only: commands source + the
                        `ordessa.contracts` foundation carrier. Domain contract
                        carriers belong to their owning domain (Agent:
                        plugins/agent/contracts) — FR-009, guarded by the
                        platform-purity and no-reverse-re-export tests.
  workbench/            Workbench public API + implementation (contract C4),
                        extension id `ordessa.workbench` kept across the move
plugins/
  harness/        ordessa_harness: harness lifecycle & ACP adaptation.
    adapters/acp-adapter/   Go ACP bridge source + tests (upstream-derived;
                            module path preserved). Harness-internal.
    packaging/     bridge build & dependency prep
    tests/
  commands/ agent/contracts/ agent/connections/ agent/sessions/ agent/conversation/
  connectors/ordessa/ connectors/acp/
products/
  desktop/        enabled-extension manifest (extensions.json + lock) for the
                  default product build. Extension ids are data, not paths.
scripts/          build / start / verify entry points
tests/            cross-component tests (acp-connector seam rig)
docs/
```

## Dependency direction (load-bearing)

```text
apps/desktop ──▶ packages/desktop-platform ──▶ (contracts only)
   │                                    ▲
   └── plugins/* ───────────────────────┘ (plugins never import host internals)

apps/server ──▶ packages/pacthold ◀── plugins/harness (loaded via plugin root)
                     │
                     └── imports nothing above it (no app, no plugin, no product)

product (products/desktop) ── enables plugins by id; never imports internals
```

- `pacthold` is the bottom of the backend stack: it defines the plugin
  contract that `ordessa_harness` implements and `ordessa_server` composes.
- The desktop product consumes the harness only through the server connector
  (`plugins/connectors/ordessa`) and ACP connector (`plugins/connectors/acp`).
  Bridge binary paths, Pi CLI flags and tool locations are harness-internal
  configuration; diagnostic override hooks are allowed, hard-wired paths in
  product scripts are not.
- The Go ACP bridge is built from `plugins/harness/adapters/acp-adapter`
  with a pinned toolchain and reproducible flags; the artifact is generated,
  never committed.

## Data compatibility

On-disk identifiers are intentionally **unchanged** from the hd002 baseline:
data-root layout, database migration numbering, deployment JSON schema,
extension ids (`ordessa.*`), credential locators. Renaming a persisted
identifier requires a migration entry in `docs/migration/` and user
confirmation.

## What is deliberately NOT here

- The other nine backend plugins of the source tree (artifacts, git,
  runtime-local, runtime-wsl, sandbox-bwrap, sandbox-windows, skills,
  terminal-session, web): archived, not part of this baseline; any real
  dependency on them is registered in `docs/known-issues.md`, not hidden.
- Legacy Studio, the retired scheduling trees, the old trial-server stacks —
  archive refs only (`docs/reference-index.md`).
- Profile / Provider / Workboard: independent repos outside the monorepo.
