# Ordessa Server plugin-host boundary — staged implementation plan

Status: **approved design direction, implementation and merge not yet performed**.
This document is written in the backend multi-Harness worktree for handoff.
Its existing uncommitted multi-Harness changes are **not** part of the first
Server-host batch. Do not stash, reset, overwrite, stage, or silently absorb
them. Before implementation, compare this plan with current `main` and record
the exact source baseline; do not assume this worktree's older HEAD is current.

## Objective and non-goals

Make `apps/server` a small, stable **host**, not the owner of every product
domain. A bare Server must start safely, authenticate, accept its core control
requests, report only actual capabilities, and shut down cleanly. Each optional
domain owns its service, data and wire methods. Adding or removing a domain
must not require a new branch in the host's method table or bootstrap function.

The first batch establishes and proves the hosting boundary while preserving
current wire/1 and on-disk behaviour. It is **not** permission to rewrite the
database, change persisted identifiers, rename wire methods, replace the
current ACP relay, or claim all business code has already moved out. The old
business assembly may be bridged temporarily, but it must be visibly marked
as transitional and must not become a second permanent plugin host.

## Target ownership

| Capability | Target owner | What the Server host retains |
| --- | --- | --- |
| Process/data-root ownership, startup/shutdown, HTTP/WS, bearer auth, request size limits, error sanitisation, health and `server.hello` | `apps/server` | All of it; no business-record CRUD |
| Plugin discovery/selection, dependency validation, activation/disposal, method/stream-route registry | `apps/server` | Generic mechanics and fail-closed checks only |
| Execution facts and storage primitives | `packages/pacthold` or a generic execution-ledger capability | Host may expose a scoped port; no mandatory Profile foreign key or Harness brand branch |
| Workspace records, local-path authority and environment providers | Workspace domain plugin | Authenticated route dispatch only; ACP consumers depend on a Workspace resolution port |
| Harness discovery, launch, ACP channel identity, run/relay ownership and release | `plugins/harness` Server facet | Generic WS admission/forwarding facility; never brand flags or adapter paths |
| Conversation session, message/history, queue, approvals, stop and send outcome | Agent-session domain plugin | No conversation-specific endpoint implementations |
| Profile CRUD, grants, permissions and profile configuration | Profile domain plugin | At most opaque execution provenance supplied by the caller |
| Provider/model configuration and probes | Model-provider domain plugin | No provider-specific record or endpoint |
| Skills/MCP/code assets, catalogues and bindings | Asset domain plugin(s), split by actual independent lifecycle | Common storage/transaction port if needed |
| Provider subscription accounts and account assets | Account domain plugin | Server bearer auth stays in the host; it is a different responsibility |
| Hooks/automation and usage reports | Their domain plugins | Generic event publication only if used by multiple domains |

This is an **ownership map**, not an instruction to create one package per
existing directory. Keep related records and methods together until a real
independent activation/test boundary is proven. For example,
`workspaces.gitStatus` may become an optional Git contribution to Workspace;
it need not force the Workspace record service into the host. Conversely,
`acp.channel.*` must not be called a generic host capability merely because
its WebSocket crosses the host transport.

## Small plugin contract

Define one pure Python Server-plugin contract consumable by both Server and
plugins without importing `ordessa_server` internals or adding Server-specific
wire types to Pacthold's work-core API. Preferred placement is a small stable
`packages/server-plugin-api` package; confirm its naming and package build
before creating it. It should carry only:

- Static identity/API version and **required** dependencies; optional
  contributions are discovered separately so optional absence never prevents
  unrelated activation. Dependencies form a directed acyclic graph.
- Scoped activation context with explicit ports (storage/transactions,
  workspace resolution, execution facts, event publication, authorised stream
  registration as applicable). No raw database, credential contents, mutable
  host registry, or unrestricted FastAPI app object.
- Registration of a method as one atomic descriptor: stable wire ID, exact
  required/optional parameter shape (or a versioned validator), handler,
  availability predicate, and owning plugin. A method cannot be advertised
  unless its handler is installed and available. Duplicate IDs and unknown
  schema forms fail startup, not first request.
- A narrow stream-endpoint descriptor for protocols such as ACP. Host-owned
  origin/bearer checks and close semantics cannot be bypassed by a plugin.
- Owned resources/disposal and, where necessary, explicit storage migrations.
  Activation failure rolls back only that plugin's contributions; shutdown
  releases each successfully activated plugin exactly once.

The product/deployment manifest explicitly selects enabled Server plugins.
Installing a Python distribution must not silently enable it. Discovery may
reuse Pacthold's existing entry-point mechanics, but its work-core
`PluginRegistration` must not be redefined as a Server RPC table. Do not add a
second scheduler or dynamic code-loading path.

`server.hello` is generated from the active registry. During wire/1 migration,
preserve the existing `{id, supported, reason?}` shape and previously agreed
availability semantics; do not quietly redefine `supported` to mean
"installed". Unknown methods remain typed refusals, not 500s.

## First mergeable batch: hosting boundary, not multi-Harness expansion

Implement from a **clean worktree based on then-current `main`**, separate
from the dirty `feature/backend-multi-harness-acp` tree. One writer owns the
host API/registry and shared test harness; dependent slices run serially.

1. Freeze baseline: full method inventory (`method -> record owner -> handler
   -> capability condition -> plugin candidate`), exact tests and known-red
   IDs, clean source SHA, data schema/migration identifiers. Any unclassified
   method blocks removal from the host.
2. Implement the minimal registration and activation seam. Keep the existing
   product running through a clearly named compatibility adapter while methods
   are migrated. The adapter is a bridge for wire/1 stability, not evidence
   that business ownership has moved. No duplicate dispatch tables: registry
   owns shape, handler and capability together.
3. Prove bare-host and plugin boundaries with a test plugin **not shipped in
   the product**: zero plugins, one plugin, duplicate method, missing/cyclic
   dependency, bad validator, activation rollback, disposal, absent stream
   route, and authenticated versus unauthenticated call. Missing fixtures or
   zero collected tests fail the gate.
4. Move one bounded real domain behind the new interface only after the
   register/activate/teardown contract is stable. Workspace is a preferred
   candidate because its resolution port is a useful dependency for ACP;
   first verify its local/WSL/SSH and on-disk behaviours can be preserved.
   If that dependency surface is too coupled, report the blocker and choose a
   smaller domain with an independently checkable absent/present pair. Do not
   silently weaken Workspace behaviour to hit the milestone.
5. Audit the diff: no Pi/Codex/Claude brand branch in Server, no new Profile
   record dependency in generic execution facts, no frontend changes and no
   inclusion of the existing multi-Harness worktree's uncommitted changes.

This first batch may be merged to `main` **only as the tested host boundary**.
Its report must say exactly which business domains still sit behind the
compatibility adapter. Do not describe it as the final small-core extraction
until those domains are actually moved.

## Later batches and the multi-Harness branch

After the host batch is reviewed, committed, and independently rerun on an
integration branch, the user may approve its merge into `main`. Then rebase
or port the saved multi-Harness work against that new baseline **without
discarding its dirty files**. Place binding validation and brand launch in
Harness, use the new Server registration/admission ports, and delete any
temporary parallel admission source. Run its controlled pi/codex/claude
checks and the existing single-Harness compatibility checks again before a
separate merge decision. The Go bridge and real-model gate remain separate.

Remaining Profile, Provider, Session, Asset, Account, Hook and Usage migrations
should be ordered by dependency and data ownership; each must show the
plugin-present/plugin-absent contrast. Do not create empty plugin directories
or move code solely to make the tree look symmetric. A business-domain plugin
may later contain both Server and Desktop facets, but neither facet must
import the other's runtime.

## Acceptance and anti-false-green gates

| Gate | Required evidence | Counterexample | Missing/unknown evidence |
| --- | --- | --- | --- |
| Bare host | Start without business plugins; health/auth/hello and clean shutdown work; no business methods advertised as available | Removed Workspace or Harness still appears supported or crashes startup | Fail |
| Registry truth | Exact shape, duplicate rejection and handler/capability consistency | Method in hello has no reachable handler; extra `instanceId` passes an ACP shape | Fail |
| Lifecycle isolation | Failed plugin rolls back its methods/resources; unrelated plugin remains active; disposal once | One plugin's activation failure removes another's route or leaks a stream | Fail |
| Security | Plugin methods/streams pass through host auth, origin and error-sanitisation policy | A registered stream bypasses bearer/origin checks or leaks exception text | Fail |
| Compatibility | Existing wire/1 replies, persisted IDs and ACP path/release semantics compare against baseline by case ID | Runtime test count looks green while an old method disappears from discovery | Fail |
| Data | Old data root loads without migration-number/identifier changes; plugin absent never deletes its tables or records | Removing Profile makes old execution records unreadable | Fail |
| Separation | First-batch diff excludes multi-Harness files and frontend implementation; later port has its own diff/review | Dirty Stage A changes ride along in the host merge | Fail |
| Full regression | pacthold, Server, Harness, ACP orchestration suites with exit codes, counts and per-ID red diff; no hidden collection errors | A known-red total masks a new failing test ID | Fail |

Do not claim real-Harness or real-model integration from a controlled fake.
Do not start/stop user services, read credentials, push, or merge merely to
make a gate pass. A test environment that lacks a dependency is **not run** or
failed, never green by omission. Existing known reds are not permission for
new unexplained reds.

## Decision and handoff format

Before asking for the host merge, report: source/main SHAs; exact changed
paths; which domains remain transitional; method/owner inventory; baseline
and final test commands, counts, exit codes and failing-ID diff; data-root
compatibility evidence; controlled versus real coverage; rollback target;
and whether the multi-Harness worktree is byte-for-byte untouched. Request
one explicit merge approval for the host batch. Ask separately before porting
or merging the multi-Harness batch.
