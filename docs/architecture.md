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
    native-bridge/      restricted native IPC (Electron main)
    server-bridge/      host's seam onto the Server it starts (data root,
                        wire port, lifecycle)
    ui/                 base controls (Card/Panel/forms) + styles.css
    ui-components/      generic component provision/consumption (contract C7)
    connections/        generic Connections platform API (contract C6); the
                        platform ships no concrete protocol kind
    contracts/          platform-owned carriers only: commands source + the
                        `ordessa.contracts` foundation carrier. Domain contract
                        carriers belong to their owning domain (Agent:
                        plugins/agent/contracts) — FR-009, guarded by the
                        platform-purity and no-reverse-re-export tests.
                        Note: contracts/foundation/src/product/harness-availability.ts
                        still carries a Harness-domain contract on the platform
                        side (registered 2026-10-02, spec 021 N4-R1 B-03;
                        currently zero product consumers).
  workbench/            Workbench public API + implementation (contract C4),
                        extension id `ordessa.workbench` kept across the move
plugins/
  harness/        ordessa_harness: harness lifecycle & ACP adaptation.
    adapters/acp-adapter/   Go ACP bridge source + tests (upstream-derived;
                            module path preserved). Harness-internal.
    packaging/     bridge build & dependency prep
    tests/
  commands/       ordessa.commands
  agent/          contracts/ connections/ sessions/  (ordessa.agent-contracts /
                  ordessa.agent-connections / ordessa.agent-sessions)
  chat/           api/ frontend/  (ordessa.chat-api / ordessa.chat)
  connectors/     ordessa/ acp/  (ordessa.agent-server / ordessa.agent-acp)
  profile/        api/ frontend/ integrations/chat/
  permissions/    frontend/
  assets/         skills, mcp, model-provider, prompts, sandbox, subagents,
                  memory, lsp, extensions, command-templates,
                  runtime-preferences
  workspace/  runtime-compat/ (pacthold_runtime_compat)  server-compat/
products/
  desktop/        enabled-extension manifest (extensions.json + lock) for the
                  default product build. Extension ids are data, not paths.
  server/         ordessa_server_product: `create_composition()` — the thin
                  product assembly root the Server resolves; it registers
                  plugins, it does not own business rules.
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
  `apps/server` → `pacthold` is **normal use, not an ownership breach**
  (`core_binding.py` imports `pacthold.public`; `bootstrap/runtime.py` imports
  `pacthold.storage`); the load-bearing rule is the reverse direction.
- Two cross-layer edges inside `desktop-platform` are deliberate and are
  listed as accepted exceptions in the core inventory
  (`specs/021-nightly-product-closeout/core-inventory-20261002.md`, B-01/B-04):
  the `ordessa.contracts` carrier re-exports the Workbench and Connections
  public APIs so the product has one shared copy of each Token, and
  `server-bridge/src/data-root.ts` imports the Server-owned
  `data_root_layout.json` (data, not API). The "contracts only" arrow above
  describes the intent, not these two documented carriers.
- The Workbench (`packages/workbench`) is an application UI framework, not a
  business plugin: it owns navigation, regions/views/pages, overlays, the
  settings page container and UI-contribution registration — not model/Profile
  state, configuration storage or business components.
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
- The archived independent plugin repositories `harness-profile`,
  `harness-provider` and `harness-workboard` continue **outside** this
  monorepo; their history is kept here as `refs/archive/*`
  (`docs/reference-index.md`, `docs/migration/source-destination.md`). Those
  three archived repos are **not** the current product's Profile and
  model-provider plugin families: those live in-tree at `plugins/profile/` and
  `plugins/assets/model-provider/` and are enabled in
  `products/desktop/extensions.json` (`ordessa.profile-api`,
  `ordessa.profile-frontend`, `ordessa.profile-chat`, `ordessa.model-provider`,
  `ordessa.model-provider-chat`). No in-tree Workboard code exists.
  *(Corrected 2026-10-02 under spec 021 N4-R1. `AGENTS.md` §"What this repo
  is" still uses the old shorthand "Profile / Provider / Workboard" for the
  archived repos; flagged for Lead/user confirmation.)*
