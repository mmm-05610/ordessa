# T019 plan — desktop business test migration (source → target)

Baseline source of truth: `desktop.ids.txt` from the T003 freeze — 146 IDs over 13 files in
`apps/desktop/renderer`. FR-010/FR-012: business code and unit tests must not live in the app/host
shell; only startup / window / IPC / host tests may stay there. Cross-package integration may stay
in the product (`products/desktop/tests`).

Split by the freeze counts (10 files / 110 IDs migrate, 3 files / 36 IDs stay):

| IDs | source (`apps/desktop/renderer/…`) | disposition | target |
| --- | --- | --- | --- |
| 11 | `agent-connections.test.ts` | migrate | `plugins/agent/connections/tests/` (the facade under test lives there since T028) |
| 1 | `agent-connections-status.test.tsx` | migrate | `plugins/agent/connections/tests/` |
| 18 | `agent-conversation.test.tsx` | migrate | `plugins/agent/conversation/tests/` |
| 16 | `agent-sessions-draft.test.ts` | migrate | `plugins/agent/sessions/tests/` |
| 3 | `agent-sessions.test.ts` | migrate | `plugins/agent/sessions/tests/` |
| 7 | `agent-sessions.test.tsx` | migrate | `plugins/agent/sessions/tests/` |
| 10 | `agent-acp-wiring.test.ts` | migrate | `plugins/connectors/acp/tests/` (bridge/transport/host wiring of that connector) |
| 18 | `agent-ordessa-connector.test.ts` | migrate | `plugins/connectors/ordessa/tests/` |
| 23 | `agent-ordessa.test.ts` | migrate | `plugins/connectors/ordessa/tests/` — all 23 IDs are that connector's own origin/token-file/send semantics, none of them host startup |
| 3 | `agent-ui-probe.test.tsx` | migrate | `products/desktop/tests/` — it exercises the example probe extension through the assembled host, so it is product-level integration, not a plugin unit test |
| 6 | `foundation.test.tsx` | stays | host contract/carrier suite of the desktop app |
| 11 | `host.test.tsx` | stays | Lumino host startup |
| 19 | `loader.test.ts` | stays | loader/discovery confinement, module validation |

Rules for the move (same rules that made T017/T028 auditable):

1. Relocation changes file paths and import specifiers only. Zero assertion lines may be dropped
   or relaxed; prove it with `git diff -U0 | grep '^-' | grep -c 'expect('` → 0 on the moved files.
2. Every one of the 110 migrated IDs must still run, with the same test name, in the target
   package, and the per-ID source→target map must be appended to `reports/C.md` (this table is the
   file-level plan, not the receipt).
3. Each receiving plugin needs a vitest config (jsdom + the `@extensions/...` aliases). To avoid a
   6th copy of the drifting alias list, the aliases come from one shared helper
   (`tooling/vitest-extensions.mjs`), which the existing configs are also repointed at — a single
   source for `@extensions/ordessa.contracts/contract.js` and
   `@extensions/ordessa.agent-contracts/contract.js`.
4. `apps/desktop` vitest include narrows to the three host files; its count must be re-frozen from
   the actual run, not assumed.
5. Root aggregation (`T021`) picks up the new per-package runs; until then each package is run
   explicitly with `npx vitest run --maxWorkers=1 --root <pkg>`.
