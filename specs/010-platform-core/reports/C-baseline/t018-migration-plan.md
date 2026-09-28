# T018 plan — contract ownership migration (business types out of the platform umbrella)

FR-009: public contracts belong to their owner; the platform must not reverse re-export a domain
API; a Token/kind must still exist exactly once; an implemented-but-not-enabled extension must still
be able to import its API. The C6 amendment (plan.md §修订 C6) exempts the generic Connections
platform from this migration — `packages/desktop-platform/connections` stays platform-owned.

## What actually violates FR-009 today

`packages/desktop-platform/contracts/` is the platform umbrella, and it hosts Agent-domain
declarations:

- `agent/src/agent.ts` (207 L) — 100% Agent domain: `Availability`, `RunStatus`, `AgentCapabilities`,
  `Agent{Connection,Workspace,Session}Info`, `AgentToolCall`, `AgentMessage`, `AgentInteraction`,
  `AgentOption`, `AgentSnapshot`, `InteractionAnswer`, `AgentRelease{Status,State}`, `AgentClient`,
  `AgentConnector`, `AgentWorkspaceSnapshot`, `AgentSessions` + `AgentSessionsToken`.
- `connections/src/connections.ts` (61 L) — Agent-domain connection facade: `AgentConnections(+Token)`,
  `AgentConnectionWorkspace`, `AgentClientConnectionKind`, `hasOpenRun`, `hasAwaitingInteraction`.
- `agent-ui/` — the carrier package (`ordessa.agent-contracts`) that bundles those two files as
  `contract.js`; it also sits under the platform umbrella.

Platform-owned and staying: `commands/src/commands.ts`, `foundation/` (carrier of
commands + `packages/workbench/api` + `packages/desktop-platform/connections/api`).

There is no `plugins/chat`: the chat surface is `plugins/agent/conversation`
(`ordessa.agent-conversation`), which consumes `AgentMessage` / `AgentInteraction` /
`InteractionAnswer` from the domain carrier. Chat therefore migrates with the Agent domain owner;
no chat type is re-exported by a platform carrier today, and the post-move guard must keep it so.

## Target shape

Move the whole domain carrier under its owning domain, keeping every persistent identity:

- new package `plugins/agent/contracts/` with `ordessa.id` = `ordessa.agent-contracts` (unchanged),
  `src/{agent.ts,connections.ts,contract.ts,entry.ts}`, `build.mjs` (entries `entry` + `contract`),
  `manifest.json` unchanged, package name → `@ordessa/agent-contracts`.
- `plugins/**` is already an npm workspace pattern and `plugins` is already a
  `tooling/build-all.mjs` discovery root, so the move needs no root additions.
- Consumers keep importing `@extensions/ordessa.agent-contracts/contract.js` — the shared module
  channel, not a path — so the 26 consumer files do NOT change; only the mapping sites below do.

## Shared mapping sites to repoint (the whole blast radius)

1. `apps/desktop/tsconfig.json:14`
2. `apps/desktop/vitest.config.ts:6`
3. `packages/workbench/vitest.config.ts:6`
4. `tests/acp-connector/vitest.config.ts:9`
5. `tests/acp-connector/acp-ts-hooks.mjs` — `ALIASES` (L21) and `TS_DIRS` (L30: it whitelists
   `packages/desktop-platform/contracts/`; after the move the domain dir must be added or the seam
   dies on `Unknown file extension ".ts"`)
6. `tooling/build-all.mjs:34` discovery roots (no change needed — `plugins` already scanned)
7. `packages/workbench/tests/token-scan.mjs` — `TOKEN_SOURCE_DISCOVERY_ROOTS` must gain the new
   source dir or the source↔watchlist sync test fails for `ordessa.agent.*` tokens
   (coordinate with T029, which edits this same file)
8. `apps/desktop/renderer` + `tests/acp-connector/ui` deep relative imports of
   `packages/desktop-platform/contracts/agent-ui/src/contract` (7 test files) — these are the files
   T019 moves anyway; T018 repoints them and T019 relocates them
9. Docs that name the old path: `docs/migration/desktop-migration-table.md`, `docs/migration/*`,
   `specs/010-platform-core/reports/C.md` (append a migration receipt, do not rewrite history)

## Guards to add/extend (so the wall cannot silently fall back)

- A platform-purity scan: no Agent/Chat domain declaration (name list from `agent.ts`) may be
  declared anywhere under `packages/desktop-platform/**` except the platform API packages
  (`connections/api`, `contracts/commands`, `contracts/foundation` re-export lines) — the CN-01 wall
  in `packages/desktop-platform/connections/tests/connections.test.ts` is the pattern to copy.
- No reverse re-export: `packages/desktop-platform/**` must not import or re-export
  `@extensions/ordessa.agent-contracts/...` or a `plugins/**` path.
- CN-08 already proves single-instance Token/kind in the real build (T029); after this move the same
  guard must still report exactly one construction per literal, now owned by the moved carrier.
