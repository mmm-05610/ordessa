# Ordessa architecture

This page describes the current source boundaries and the implemented state
visible in this checkout. It is not an acceptance report. See
[`reference/baseline.md`](../reference/baseline.md) for toolchains,
[`reference/known-issues.md`](../reference/known-issues.md) for registered gaps, and
[`docs/implementation/agent-core-engineering/status.md`](../implementation/agent-core-engineering/status.md)
for historical Agent engineering acceptance. The current restructuring status is [nightly status](../implementation/nightly/status.md).

本轮上层目标与迁移见[源码映射](../implementation/nightly/source-target-map.md)。下图区分实际实现与批准预留；上层验收证据见[独立验证区](../verification/overnight-upper-structure-20261009/)。完整产品和未经细审的底层状态单列，不以结构验收代替运行验收。

## Component map

```text
apps/
  cli/              Agent Tools client application
  desktop/          Electron host, Server lifecycle bridge and product assembly
  mcp/              reserved MCP application (README only)
  status-board/     reserved status application (README only)
  server/           HTTP/WS host, transport, wire schema, plugin composition and Agent Tools composition
packages/
  engineering/      sole Engineering library and methods source
  execution/
    kernel/         Pacthold governance kernel and plugin SDK
    agents/         sole Agent/Profile services sharing original core authority
    decision/       host-neutral decision runtime
  interfaces/
    execution/c1-api  host-independent execution and Harness contracts
    server/plugin-api  Server plugin contracts
    cli/            command API/runtime structural reservation
    mcp/            contribution API/runtime structural reservation
    workbench/      extension API/runtime/host/loader, Workbench and shared UI packages
  infrastructure/   canonical encoding and SHA-256 primitives
plugins/
  agents/ui/        Agent contracts and connection/session consumers
  agents/profiles/ui/ Profile catalog API and UI consumer
  agents/resources/ Agent-owned resource families
  decision/jev/     independent Jev adapter and configuration
  decision/laya/    reserved provider (no implementation)
  harness/<brand>/  independently packaged Harness providers
  engineering/      Engineering plugin extension slot (no implementation yet)
  workbench/        Chat, commands, LSP and other Workbench feature plugins

Server product composition: apps/server/deployment/default-product/

Agent Tools client: apps/cli. Its optional Server composition is under
apps/server/src/ordessa_server/composition/agent_tools/.

Desktop product manifest: apps/desktop/packaging/product/extensions.json
```

`packages/execution/decision` is the sole `decision-runtime` distribution;
its stable `decision_runtime` imports and persisted contracts remain unchanged.
Jev is independently packaged at `plugins/decision/jev`, imported as
`ordessa_decision_jev`. The retired `decision_runtime.providers.jev` entry
has no alias or fallback. The Ordessa-specific read-only facade now lives in apps/server/src/ordessa_server/bootstrap/adapters/decision;
Pacthold assignment flows keep their Core owner and consume neutral public Decision contracts/runtime; Server owns only its product read adapter. Brand Profile plans consume public same-Environment views, with no Product reverse import or filesystem fallback. Current structural and dependency evidence is recorded in the [migration acceptance ledger](../verification/overnight-upper-structure-20261009/migration-checklist.md).
Historical extraction checkpoints `f8c3650771` and `ea7091d90b` describe the
source baseline, not the current directory map. The independent `packages/engineering` package contains
the local SQLite engineering-library and finite-method workflow. Its bounded
local mechanism slice is completed and accepted under R0029. This does not
establish a complete Agent authoring product, real DID identity, or
standard-method semantics. Do not treat either package's presence as proof of
end-to-end product readiness.

## Ownership and dependency direction

- The execution Agent package owns `ProfileCatalog` and Agent services,
  retaining original operation claims, namespaces and recovery semantics.
  Pacthold retains the unique Environment, CoreRegistry and permission gates.
  The Server routes public `/3` methods through `ordessa_execution_agents.public`;
  the reserved owner ID remains `pacthold.agents`. The Server product's current
  opt-in Agent composition is in
  [default Product composition](../../apps/server/deployment/default-product/src/ordessa_server_product/composition.py),
  with pure input validation owned once by
  [Agents admission](../../packages/execution/agents/src/ordessa_execution_agents/units/admission/owner_selection.py)
  and Host ports bound by `apps/server/src/ordessa_server/composition/configuration/product_selection.py`;
  ordinary default composition supplies no Agent owner
  ports, so managed Agent execution remains unavailable by default. C08 source
  has V30's bounded independent acceptance for the Host-owned root-proof and
  pre-effect refusal boundary. This is a trusted-code composition guarantee,
  not a same-process Python sandbox or complete Agent integration.
- Agent UI consumers live under `plugins/agents/ui/{contracts,connections,sessions}`.
  Profile consumers live under `plugins/agents/profiles/ui/{api,frontend}` and consume
  the public Agent Profile Catalog wire contract; they do not own Profile state or
  persistence. The singular `plugins/agent/` and `plugins/profile/` source paths are
  retired; the current plural `plugins/agents/` tree is active.
- Agent-owned resource packages currently live under `plugins/agents/resources/`;
  the former `plugins/assets/` source tree has no active source files.
  Native ACP channel admission and access staging are Host-owned under
  `apps/server/src/ordessa_server/composition/native_channels/`. The remaining
  Profile history view uses the already composed public Agent ProfileService;
  explicit migration imports historical bytes into that same authority.
  The old filesystem Profile writer and generic provider fallback are retired.
- Workspace exposes `DirectoryBindingService` and `DirectoryAuthorityPort` under
  `plugins/agents/workspace/src/ordessa_workspace/` and through `public.py`. The default
  Agent product composition does not yet wire a Workspace execution adapter. A public
  directory-binding API therefore does not mean managed Agent turns have Workspace
  authorization or execution.
- `apps/server/deployment/default-product` composes Server plugins and bridges public Pacthold,
  Environment, Harness and Workspace ports. `apps/server` owns host transport
  and passes generic plugin/root-ownership contracts; Pacthold does not import
  Server, product or plugin internals. Plugins use public platform/domain
  contracts rather than host internals.
- Harness brands are separate leaves under `plugins/harness/<brand>/`; shared
  records are now in `packages/execution/agents/src/ordessa_execution_agents/harness/records`;
  brand launch/planning behavior stays behind public provider ports; the default
  Product injects same-Environment views and composes those ports. Retired shared
  Harness runtime and generic adapter/Profile paths are absent.
  `ordessa_execution_api.harness` from `packages/interfaces/execution/c1-api` is the public Harness contract package. The retired
  root `ordessa_harness` aggregate and `ordessa-harness-api` distribution are
  not compatibility aliases.

The Workbench is a frontend platform package, not a business authority. Its public
foundation carrier is `packages/interfaces/workbench/extension-api/contracts/foundation/src/contract.ts`;
the Workbench API and implementation live under `packages/interfaces/workbench/shell/workbench/`.
Feature plugins contribute through that public API. Desktop's private Server client is
`apps/desktop/electron/server-bridge/src/`; its `data-root.ts` reads the Server-owned
`apps/server/src/ordessa_server/bootstrap/data_root_layout.json`. These owner paths do
not make the Workbench an Agent/Profile state owner or move Server data authority into
Desktop.

The Go ACP bridge source is under `plugins/harness/pi/vendor/acp-adapter/`,
retained as an opaque upstream module sponsored by the Pi artifact recipe.
`plugins/harness/pi/tooling/build-acp-adapter-round-h.sh` builds the binary
from an explicitly supplied and validated source root plus the pinned Go
toolchain; binaries remain build outputs and are not committed. The toolchain
and recorded artifact are documented in [`reference/baseline.md`](../reference/baseline.md)
and [`plugins/harness/pi/docs/acp-build-record.md`](../../plugins/harness/pi/docs/acp-build-record.md).

## Retired paths and current residue

`ordessa-agent`, `ordessa-profile` backend authorities, the old ProfileCore,
submissions/facet/overlay execution path, and the `server-compat` runtime
authority are retired. Historical extension identifiers and on-disk data
identifiers remain unchanged. The former Agent/Profile, server-compat and runtime-compat production entrypoints are absent; retired cache-only paths have been relocated to an ignored recovery checkpoint. Archived sources and recovery caches are never runtime dependencies.

The old claims that Profile UI lived at `plugins/profile/api` and
`plugins/profile/frontend`, or that `plugins/agent` owned Agent contracts, are stale.
Current consumer locations are `plugins/agents/profiles/ui/` and `plugins/agents/ui/`;
Agent/Profile state authority is `packages/execution/agents` over the original Pacthold
Environment, Store, registry and owner ports. No historical directory or archived source is a
fallback runtime. Source repositories, checkpoint refs and restore procedures
remain historical material indexed in
[`reference/index.md`](../reference/index.md) and
[`docs/migration/`](../migration); those references preserve recovery history,
not active source dependencies.

## Data compatibility

Persisted identifiers stay unchanged: data-root layout, SQLite migration
history, deployment JSON, extension ids (`ordessa.*`) and credential locators.
Retiring an execution path does not authorize rewriting user data or changing
historical identifiers. Any necessary explicit migration belongs in
`docs/migration/` and requires the approval described in `AGENTS.md`.

## Current implementation limits

The neutral Decision package passed the bounded source/domain gates recorded
in the engineering work status; this does not establish Decision quality or
live-model behavior. Engineering's bounded local source/matrix/wheel slice has
limited R0029 acceptance; the complete independent Engineering Harness,
full Agent authoring, real DID identity, and standard-method semantics remain
unaccepted. V30 independently accepted the bounded C08 Host root-proof
boundary (46 tests passed, no skips, plus the public `object.__new__` forgery
probe); V29's original forged-binding failure remains historical evidence.
This does not sandbox hostile code already running in the Python process.
010's managed Codex turn mechanism is boundedly accepted by V35/R0030:
222 independent focused tests passed with no skips, including six input tests,
plus opt-out and cross-store prewrite failure probes. Controlled ports do not establish production use.
Default production Agent use, the Workspace execution adapter, full
result-content retrieval, UI send integration, interruption effects and cold
recovery remain unavailable or unaccepted. Missing ports must remain
unavailable rather than use retired execution chains.

Engineering method persistence now uses the original Library connection under explicit schema3, with immutable content and atomic release identities. Default schema2 and original data identifiers remain. This adapter is not a completed Engineering UoW or product workflow; see [migration scope](../migration/engineering-schema3-snapshots.md).

Engineering material record2 now carries closed source/claim/evidence/method fields; its single domain codec is `domain/artifacts/codec.py`. `adapters/persistence/sqlite/material_validation.py` resolves actual bytes and published method resources on the original UoW, reusing Snapshot source verification. It neither introduces a source/execution authority nor supplies authentication. See [migration](../migration/engineering-schema6-materials.md).

Schema7 now persists Change/Proposal/control and expands actual review requirements in the original EngineeringLibrary/UoW/journal. Source and installed noneditable Engineering wheel each pass488 tests without skips; scopes overlap and dependencies remain the nightly environment, not a full product distribution. Production auth/catalog/trust, baseline owner, AuthorizationIntent/Grant/outbox and Server/CLI remain incomplete. Pure ActionScope is not permission. [Proposal checkpoint](../implementation/nightly/evidence/W04/proposal-checkpoint.md) / [schema7 migration](../migration/engineering-schema7-proposals.md). Domain changes/approvals/reviews use pure exact references; actual SQLite proposal/review repositories share per-resolution material and traversal budgets, without a second byte or authorization authority.


W10 now selects one InstanceAccessAuthority in the default Server. The instance bearer is a machine identity with no default Engineering grants; original local owner ACLs remain. HTTP/wire/REST/WS share this identity mechanism; missing authority refuses, without the old token fallback. Real SQLite admission/COMMIT, revocation and copied-context negatives are verified. Full production Engineering catalog/receipt, project mapping, CLI and human confirmation remain incomplete. Server now requires Python >=3.12, matching its direct interfaces dependency. See [W10 actual evidence](../implementation/nightly/evidence/W10/README.md).

The Workbench Harness availability carrier is `packages/interfaces/workbench/extension-api/contracts/harness` (`@ordessa/harness-contracts`). It reuses the foundation opaque Token and owns only brand-neutral availability API/pure helpers, with no Agent or provider authority. Its prior `plugins/harness/contracts` source root is retired.
