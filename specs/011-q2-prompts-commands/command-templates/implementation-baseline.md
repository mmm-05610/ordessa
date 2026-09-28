# command-templates — T00/T01/T02 implementation baseline

Phase-0 freeze for the Q2 command-templates single package. Recorded 2026-09-28
against the live tree. Nothing here is copied from a prior ledger: every SHA,
version and symbol was re-checked in this session. Commands and evidence live
outside the worktree at `/home/maoqh/.local/share/qe2-evidence/command-templates/`.

## 1. Frozen SHAs (git read-only, verified)

| Role | SHA | Consumable here? |
| --- | --- | --- |
| `main` root-switch anchor | `cd7d31f3cfba6a0e1ec65f9a13014c6b9751540b` | yes (ancestor of HEAD) |
| Lane branch start (task brief) | `96fef2db47f485091ccaadda96f5321400b249f2` | yes — HEAD's ancestor |
| Current lane HEAD | `07dceb395c9ae6b7d9af89c2ab8af3982a8fe7c6` | this tree (orchestrator snapshot-commits in-flight work; main agent owns git) |
| desktop-workbench | `36fefc50d348ec924f840a0118cf78093f51dba7` (`feature/desktop-workbench-registration`) | **NO — not an ancestor of `main`**; read-only reference only |
| plugin-assets-skills-impl | `752f148b1b01f58c0d090e79728948127173f9fb` (`feature/plugin-assets-skills-impl`) | **NO — not an ancestor of `main`** |
| platform-frontend | `82b7ef1fc3fc79037b7a6d4749b612d4f54865fd` (`codex/010-platform-frontend`, `codex/011-c0-foundation-harness`) | **NO — not an ancestor of `main`** |

`git merge-base --is-ancestor <sha> main` returned non-zero for all three read-only
sources, so none may be imported. They inform design only.

### Checkpoint consumption (G00)
`specs/011-plugin-rollout/checkpoints/` did not exist at lane start. Ref state,
polled at lane start and again at final run:

```
codex/011-foundation-ready        ABSENT
codex/011-harness-api-ready       ABSENT
codex/011-profile-api-ready       ABSENT
codex/011-chat-api-ready          ABSENT at start -> PUBLISHED 54ad26c15d8480823374d85590919ba6bcca60d2
codex/011-permissions-api-ready   ABSENT
                                          (producer z2, status READY, implementationSha a3ec20c046…)
```

The `chat-api` ref was published mid-session. `git merge-base --is-ancestor
54ad26c1 main` is **false**, so per the consumption protocol it must be merged at
its fixed publication SHA before it can be imported — that merge is the main
agent's git responsibility and its consumers (T10/T11 Chat glue) are outside this
round's scope (T00–T07). **Nothing was consumed this round**; all work stayed in
the pure domain, and the Chat/Harness/Profile-dependent items remain blocked and
are filed in `api-requests.md`, not faked. `addInputSource` presence is therefore
recorded twice: absent in the merged tree this package compiles against (below),
published on the not-yet-merged `chat-api` ref (see api-requests REQ-CT-01).

## 2. Real importable public symbols (verified by `import`, venv `/tmp/q2-ct-venv`)

The pure domain deliberately imports **none** of these at runtime (stdlib only);
they are the seam vocabulary a future Server-plugin host would consume, and their
existence was proven by actually importing them:

- `server_plugin_api` — `SERVER_PLUGIN_API_VERSION`, `ServerMethodDescriptor`,
  `ServerPluginDescriptor`, `ServerPluginContext`, `ServerPluginRegistration`,
  `StreamRouteDescriptor`, `HttpRouteDescriptor`, `ServerPlugin`, and typed errors
  `ServerPluginError`, `InvalidDeclarationError`, `DuplicateMethodError`, … (the
  full list in `packages/server-plugin-api/src/server_plugin_api/__init__.py`).
- `pacthold.storage` — `Database`, `FutureSchemaError`, `ObjectStore`,
  `ObjectRecord`, `SecretStore` (+ `MemorySecretStore`, `WindowsDpapiSecretStore`).

`pip install -e` of `packages/pacthold` and `packages/server-plugin-api` into the
isolated venv succeeded (exit 0); `import pacthold, server_plugin_api` succeeded.

## 3. Toolchain (this environment)

| Tool | Value | Source |
| --- | --- | --- |
| Python (venv) | **3.14.4** (`/tmp/q2-ct-venv/bin/python`) | `python --version` |
| pytest | 9.1.1 | installed into venv via system `pip 25.1.1 --python` (venv `ensurepip` is unavailable on this Debian image, so venv was built `--without-pip` and system pip targeted it) |
| Node / npm | v22.22.1 / 9.2.0 | `node --version`, `npm --version` |
| Baseline-documented Python | 3.12.14 (`docs/baseline.md`) | **diverges from this environment's default `python3`=3.14.4**; recorded honestly, no package floor violated (`requires-python>=3.9`) |

## 4. `addInputSource` and the draft-insert action — publication status (G00)

In the **merged tree this package compiles against** (`main`..HEAD), searched
across `plugins/**`, `packages/desktop-platform/**`, `apps/**` (plain `grep`,
which covers untracked files): `addInputSource` appears nowhere as a real symbol
— the only hit is a comment in this package's own `contracts/index.ts`. So in this
working tree it is **design-only and not consumable**.

However the mid-session `chat-api` checkpoint (ref `54ad26c1…`, producer z2, status
READY) **does publish** it: `git grep addInputSource 54ad26c1 -- plugins/chat/api`
resolves to `plugins/chat/api/src/contract.ts:387` (`addInputSource(source:
ChatInputSource): IDisposable`), with a real in-memory registry (`registry.ts`), a
vitest suite (15/15) and a typecheck suite. The published action union is
`ChatInputEntryAction = insert-command{text} | add-content{prepare} |
invoke{execute}`, plus `ChatContentReference` (branded), `ChatDraftState`,
`ChatSubmissionSnapshot`, and `ChatSubmissionResult = accepted | refused | unknown`.
Because that ref is not an ancestor of `main`, this package cannot import it until
it is merged at the fixed SHA (main-agent git step). Consuming it and building the
"parameter-form → preview → insert editable draft, literal leading-`/`, never
auto-send" glue is **T10/T11, out of this round's scope**, and is tracked in
`api-requests.md` REQ-CT-01.

`plugins/commands` is confirmed to be a thin contribution container with an
`execute(id)` callback dispatch (`shared/registry.ts`, `src/entry.ts`): it is not
a body store, parameter engine, or session-send port. Consumed only as a possible
"open panel" action, never for template query/render.

## 5. Brand native capability matrix (G15 / G16)

Pins read from `plugins/harness/src/ordessa_harness/*/production.py`. Native
command-template loading / discovery / reload / priority / current ACP message
role have **no** controlled probe in this batch (L3/L4 not authorized). Cells are
`supported` only with first-hand evidence, `unsupported` for an explicit design
refusal, otherwise `unknown`.

| Brand | Adapter pin | Native CLI pin | Native command dir wired in harness? | Native template projection | Reload / same-session resume | Bare `/name` priority vs builtin/Skill | Current ACP message role |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pi | 0.5.0 | — | no `prompt-template`/`command` slot in `harnesses.toml` (only `instruction`,`mcp`,`skill`) | **unsupported** (design: never write user/project dir) | **unknown** (no probe) | **unknown** | **unknown** (Chat path design-only) |
| Codex | 1.1.14 | codex CLI 0.147.0 | `skill_target=/runtime/home/skills`; no custom-prompt slot | **unsupported** (custom prompts deprecated — refused as a core dependency) | **unknown** | **unknown** | **unknown** |
| Claude | 0.81.2 | — | `skill_target=/runtime/home/.claude/skills`; commands merged into Skills | **unsupported by default** (double-load with Skills must be avoided) | **unknown** | **unknown** (cannot claim exclusive bare command) | **unknown** |

No native projection was implemented; the mandatory cross-brand path (Ordessa
Chat preview → draft → existing submit) is Chat/Harness-owned and blocked pending
`chat-api`/`harness-api`.

## 6. Compat asset kinds / template-command consumers / user data (G01 / G21)

- Compat vocabularies: `ordessa_server_compat/assets/records.py` `KINDS = ("skill",
  "mcp", "command", "plugin")`; `catalog.py` `KINDS = ("skill", "mcp")`. The
  `"command"` kind is a legacy compat asset label stored in `server_assets`.
- Consumers: `grep` for a `kind='command'` asset or a template body in
  `apps/server/src` and `plugins/server-compat/src` returned **nothing** that
  reads command templates. `plugins/commands` holds no persistent template data.
- **Migration / retention / deletion ledger:** this domain is a brand-new **private
  schema** (`ct_template`, `ct_revision`, `ct_assignment`, `ct_idempotency` in a
  private `command-templates.sqlite`). No existing data is migrated into it; the
  legacy compat `command` asset kind stays owned by `plugins/server-compat` and was
  **not** touched (baseline read-only — this package only adds new files). There is
  no user-data id to preserve or rename, so no compatibility note is required under
  `docs/migration/`. Importing native Pi/Claude/Codex files is opt-in and read-only
  (T07), creating new revisions, never editing sources.

## 7. Affected-suite red ledger (pre-change, same turn)

This change is **purely additive**: all files are new under
`plugins/assets/command-templates/` (and this `specs/...` directory). `git diff`
against the committed tree for the package is empty after the mutation harness
restored every file, confirming no existing suite was modified and no stray edit
was left behind. Consequently no pre-existing test id is affected, and the
dependency packages (`pacthold`, `server_plugin_api`) were consumed as installed
deps, not edited.

The only suite in scope is the new package's own, run clean this turn:

- command: `/tmp/q2-ct-venv/bin/python -m pytest tests/ -p no:cacheprovider --junit-xml=...`
- exit code: **0**
- collected **83** / passed **83** / failed **0** / errors **0** / skipped **0**
- full log: `pytest-full.log`; JUnit: `junit-full.xml`
- no `skip`/`xfail`/tautology in any test (grep-audited)
- 11 mutation checks (`mutation-checks.log`, harness exit **0**): each removes a
  guard and the targeted counterexample goes RED (exit 1, FAILED), then is GREEN
  (exit 0) after byte-exact restore — proving the negatives are load-bearing, not
  decorative.

Pre-change "before" numbers: none to inherit — the package did not exist at the
lane start, so there is no prior command-template red ledger to diff.
