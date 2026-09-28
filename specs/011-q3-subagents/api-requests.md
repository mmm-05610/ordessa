# Q3 seam requests (`api-requests.md`)

Real symbol-level gaps found while freezing `implementation-baseline.md`. Format
per `specs/011-plugin-rollout/contracts/checkpoints.md` §"依赖不构成整线停机":
caller → target operation → DTO → failing counter-example → request owner.

Nothing below is a placeholder Q3 invents locally; where Q3 can proceed without
the seam, it does, and the seam only gates the *production wiring* claim.

## SR-1 → C0 (`harness-api`) — configuration adapter registration

> **Superseded by measurement — see SR-1b below.** Written when the seam had zero
> code hits; C0 has since landed it on its feature branch.

## SR-1b → C0 — the seam now EXISTS in code (read-only observation of `9e4d69e1f7`)

At 2026-09-28 02:37 +08 this line observed C0's committed branch
`codex/011-c0-foundation-harness` (tip `9e4d69e1f7 test(harness): exercise
external adapter through product carrier`, on top of `6f86799615` and
`e61fef1269`) and found a real standalone contract package
`plugins/harness/api/src/ordessa_harness_api/`:

| Group | Actual exported symbols (from `__init__.py`) |
| --- | --- |
| Adapter contract (answers SR-1/SR-3) | `ConfigurationAdapter`, `ConfigurationAdapterDescriptor`, `AdapterContext`, `AdapterRefusal`, `Assessment`, `FieldClaim`, `Verification`, `VerificationUnknown`, `TargetDescriptor`, `VersionRange`, `Installation`, `ActionDescriptor` |
| Intent vocabulary (the CA2 collision) | `Intent`, `IntentSet`, `IntentSource`, `MountContent`, `RemoveOwnedContent`, `SetField`, `ResetField`, `InvokeAction`, `TargetHandle`, `FieldPath`, `ContentRef`, `BindSecret` |
| Apply / plan / permit machinery (answers SR-2) | `ConfigurationService`, `Plan`, `PlanResult`, `Confirmed`, `Refused`, `Unknown`, `NotFound`, `OperationRecord`, `DesiredFragment`, `ApplicationTarget`, `ConfigurationCapabilities`, `ConfigurationCapability` |
| Runtime / lifecycle | `RuntimeAdapter`, `RuntimeAdapterDescriptor`, `ReconfigurationDecision`, `LaunchPlan`, `LaunchRequest`, `ResumeRequest`, `Match`, `Mismatch`, `RuntimeConfirmed/Refused/Result/Unknown` |
| Errors / schema | `ContractError`, `ErrorCode`, `JsonValue`, `ValueSchema`, `closed_object`, `validate_json` |

Observed design properties that Q3 must conform to, read from
`ordessa_harness_api/intents.py`:

- Every intent carries an injected **`IntentSource(facet_id, item_id,
  contribution_version)`** — ownership comes from the registration context, which
  matches `contracts.md` §C3's "注册 owner 由宿主授予，不接受定义/贡献者自行声明".
- The target is an **opaque server-issued `TargetHandle(handle_id, generation)`**,
  not a slot enum: the *generation* concept SR-2 asked for is already modelled, and
  it is the Harness's, not the contributor's.
- `FieldPath(segments)` rejects `""`, `"."`, `".."`, `/` and `\` — same no-path
  rule Q3 imposed on itself, but expressed as a structured path rather than Q3's
  closed enum of private generation slots.
- `SetField` refuses secret-bearing field names and directs them to `BindSecret`;
  values pass `validate_json`. Q3's "no credential in an intent" rule therefore has
  an official channel (`BindSecret`) instead of only refusal.

**This creates a duplicate-contract risk that is now concrete (CA2 was a
prediction, this is the fact):** Q3's `adapters/intents.py` defines its own
`MountContent`/`RemoveOwnedContent`/`SetRebuildClassOption`/`InvokeSubagent`/
`TargetSlot` with different shapes. Two sealed intent vocabularies cannot both
survive integration.

**Q3's position and the request to C0:**
1. Q3's types are **internal only**; they are never presented as the cross-tree
   contract, and the adapters will be refactored so their `compile()` output is
   *mapped* onto `ordessa_harness_api` intents (Q3 keeps no parallel public shape).
   A test asserting that boundary is part of that refactor.
2. Please state, in the `harness-api` checkpoint record, the canonical mapping for
   a *directory-shaped* managed mount: Q3 needs "mount the complete managed set
   into the private generation of target T" — is that `MountContent` +
   `ContentRef`, or `SetField` on a `FieldPath` per item? The distinction decides
   whether §C3's "一次性编译完整目标集合，不逐项拼补丁" is expressible at all.
3. `ResetField.baseline_rule` offers `remove-key | native-default |
   restore-owned-baseline`. For facet-owned generated content FR09 needs
   "remove only what this facet owns and nothing the user already had" — confirm
   `restore-owned-baseline` is that rule and how ownership is scoped
   (`IntentSource.facet_id`?).
4. Confirm whether `Assessment`/`Verification` require the per-brand evidence
   strings Q3 records (pin + probe ref), so `supported` cannot be asserted without
   evidence (G01/G03).
5. **Consumption is still blocked:** this is a feature branch, not the
   `codex/011-harness-api-ready` checkpoint (`git branch --list '*ready*'` returns
   only `codex/011-chat-api-ready`). Per `contracts/checkpoints.md` Q3 does not
   merge an un-published branch or read its working files; the alignment above is
   from committed history only, and the adapters refactor happens when the
   checkpoint is published. C0 may treat SR-1/SR-2/SR-3/SR-3b as **answered in
   code, pending publication**.

- **Caller:** `ordessa_assets_subagents.adapters.{claude,codex,pi}` — the pure
  `assess / compile / verify` triads Q3 implements.
- **Target operation:** registration of a `harness.configuration-adapters/v1`
  contribution with facet `assets.native-subagents`, per
  `docs/design/harness-v2/contracts.md` §C2 and
  `docs/design/native-subagents/contracts.md` §C3.
- **Missing today:** no code symbol for `harness.configuration-adapters`,
  `IntentSet`, `MountContent`, `RemoveOwnedContent`, `SetField`, `InvokeAction`.
  Verified by grep across `plugins/ apps/ packages/ products/` → zero hits; the
  design page itself states `这些接口尚未实现。`
- **DTO Q3 needs:** (1) the intent variant set with *typed* targets — a mounted
  content item must carry `{native_name, content_digest, owned_generation_token}`
  and must not accept an absolute path or a shell string; (2) an
  `assess(target_descriptor) -> supported | extension-backed | unsupported |
  unknown` result shape with a mandatory evidence field; (3) the registry call
  that grants the owner (Q3 must not self-declare ownership, §C3).
- **Counter-example that must be caught:** an adapter that reports `loaded`
  because its materialised file exists (G11/G12: "文件生成即记 loaded" is the
  failure mode). Registration seam must make `projected → loaded` require a
  separate observed fact.
- **What Q3 does meanwhile:** implements compile/verify as pure functions over a
  Q3-owned intent type and unit-tests them at L1; leaves the registry hook as an
  explicitly-absent seam, and does **not** tick the "adapter wired" gates.

## SR-2 → C0 (`harness-api`) — instance-private generation, reset, reload

- **Caller:** T12 (apply the complete managed set under one submit permit) and
  T10 (next-submission effective set).
- **Target operation:** `plan / apply / verify` on a per-instance private
  generation, plus full `reset` on removal, plus a *proved* reload or
  restart-and-resame-native-session path.
- **Missing today:** no `runtime_generation` / `submission_permit` / config
  `reset` symbol exists. The nearest existing analogues are the whole-document
  renderers (`plugins/harness/src/ordessa_harness/{claude,codex,pi}/production.py`,
  `native_materialization.py:239 materialize_family`) and artifact identity
  `{"token","target","treeDigest"}` (`claude/production.py:194`,
  `codex/production.py:295`, `pi/production.py:226`). These render an entire
  document — they are not an owned-subset mount/remove.
- **Blocking consequence:** G16 (mid-output isolation), G18 (send exactly once
  after Confirmed), G19 (reset/restart resumes the *same* native session), G20
  (busy refusal while reset/reconcile is still needed) cannot be claimed by Q3
  at L3. Q3 supplies the domain-side input and the counter-examples, and marks
  the cells unknown.

## SR-3 → C0 (`harness-api`) — target/field authorization

- **Caller:** T02 field matrix and every adapter's `assess`.
- **Target operation:** Harness C1 `describe_targets/actions` — the authority
  that says which native fields, directories and invocation actions a given
  pinned target honours (`contracts.md` §C3: "目标字段必须由 Harness C1
  describe_targets/actions 授权").
- **Exists partially:** `ordessa_harness.registry` (`HarnessRegistry`,
  `HarnessDefinition`, `ProfileSpec` with `native_home`, `config_format`,
  `payload_schema`, `skill_target`, `mcp_target`, `hooks_target`),
  `registry/capability_claims.py:14 capability_claims(harness_type)`, and
  `packages/pacthold/src/pacthold/resource_contracts/harness_capabilities.py`
  `CANONICAL_CAPABILITY_IDS` = `start, observe, finish, attach, steer, stream,
  permissions, native_continuation`.
- **Gap:** `ProfileSpec` has *no* `agents_target` / subagent directory slot (it
  has skill/mcp/hooks targets), and `CANONICAL_CAPABILITY_IDS` has no
  subagent-definition capability. Q3 cannot invent either — adding a field to the
  Harness registry is C0's write surface.
- **Request:** add a typed per-brand agents-directory slot + a capability id
  (or an explicit `unsupported`), each backed by version-matched probe evidence.

## SR-3b → C0 (`harness-api`) — the concrete Claude channel that already exists at the pin

`capability-matrix.md` §Claude proves the pinned adapter
`@agentclientprotocol/claude-agent-acp@0.81.2` already exposes everything Q3's
Claude column needs, while **Ordessa passes none of it**. This is now a precise,
small ask rather than a vague dependency:

1. **Client-side capability declaration.** The adapter gates its native subagent
   runtime behind `clientSupportsSubagents(clientCapabilities)` and advertises
   session capability `subagents: {}` (`acp-agent.js:1086-1094`, `:2055`). Q3
   needs C0 to declare the client capability / negotiate
   `nativeSubagentSessions` so the runtime actually turns on, and to expose the
   negotiated result as a **target fact** Q3 can read.
   *Counter-example to catch:* reporting `invokable` when the capability was
   never negotiated (G11's "文件生成即记 loaded" failure mode in capability form).
2. **An options pass-through for rebuild-class keys.** `_meta.claudeCode.options`
   is how a caller sets SDK `Options`; `agents` and `settingSources` are both
   classified `OPTION_REBUILDS_SESSION: true` (`acp-agent.js:286-300`), and the
   query is built as `{ settingSources: ["user","project","local"],
   ...userProvidedOptions }` (`:6376-6385`). Q3 needs either (a) a typed
   "set rebuild-class option for the next session start" intent, or (b) an
   owned-file mount into a root that `settingSources` actually reads. Q3 must not
   hand-write an absolute path or a `_meta` blob itself (§C3 forbids arbitrary
   paths).
   *Counter-example to catch:* mutating the option set of a **live** session and
   claiming US4 holds — at this pin that key forces a Query rebuild, so an
   in-place "apply" must be refused, not attempted.
3. **Event → state facts.** `subagent_spawned` / `subagent_state_update` /
   `subagent-transcript` and `subagentSessionId` / `subagentParentToolUseId`
   exist at the pin. Q3 needs the observed fact surfaced so `used` can be set
   from an event only (FR15, data-model §状态和迁移).
   *Counter-example to catch:* `used` inferred from a menu click or from the
   model's own narration.
4. **Verified absences in this repo today** (plain grep, this turn): no
   `_meta`+options pass-through, no `claudeCode.options`, no `settingSources`,
   no `agents` key in `plugins/harness/src/ordessa_harness/claude/*.py` nor in
   `plugins/harness/adapters/acp-adapter/internal/`.

## SR-4 → Z1 (`profile-api`) — facet + editor contribution

- **Caller:** T10 — Profile facet `assets.native-subagents` and its editor.
- **Target:** the published `FacetDescriptor` shape and `.addEditor` from
  `docs/design/profile-v2/contracts.md`, plus unload/hide-but-keep-data
  semantics.
- **Missing today:** `codex/011-profile-api-ready` branch absent; `plugins/profile/`
  does not exist in this worktree.
- **Q3 supplies:** the facet payload DTO (candidate definition references,
  tri-state decision, pinned revision, read-only capability diagnostics) and the
  resolution service that must be the *single* source of the effective set, so
  Profile cannot re-implement the override algorithm
  (`contracts.md` §C1: "不能让前端重写覆盖算法").
- **Counter-example:** a Profile-side copy of the resolution that silently
  differs from the server on the `disable` tri-state (G07/G08).

## SR-5 → Z2 (`chat-api`) — invoke-action contribution — **CONSUMED**

- **Consumed publication SHA:** `54ad26c15d8480823374d85590919ba6bcca60d2`
  (branch `codex/011-chat-api-ready`, producer `z2`, `status: READY`,
  `implementationSha: a3ec20c04653c7b9a267023751c23d7499f14d4a`).
  Verified before consuming, per `contracts/checkpoints.md`: implementation SHA
  **is** an ancestor of the publication SHA; the publication descends from this
  line's base `96fef2db47`; `planAnchorRef` is
  `refs/heads/codex/011-plugin-plan` = `96fef2db47` (this line's own start).
  Merged by **fixed SHA** as commit `c0686a2407` (no rebase, no floating branch
  tracking); the 13 incoming paths are disjoint from `plugins/assets/subagents/**`.
- **Re-verified in this tree after merging** (not taken from Z2's record):
  `cd plugins/chat/api && npx vitest run` → `Test Files 1 passed (1)`,
  `Tests 15 passed (15)`, exit 0; `npx tsc --noEmit` → exit 0.
- **What this unblocks:** T11. The contract already carries
  `ChatInputEntryAction = insert-command | add-content | invoke{execute}` plus
  `availability: ready | disabled{reason}` and
  `ChatActionResult = accepted | refused | unavailable`, with
  `ChatInputQuery.signal` and registry-level "abort keeps previous entries".
  That is exactly the shape G17 needs — **no new seam request to Z2**: Q3 can
  express "only proved-invokable gets a live action" and "everything else is
  detail-only with a reason" without a pseudo-call.
- **Remaining gap (still open, unchanged by this checkpoint):** the *invoke*
  action can be wired only to a gateway that can prove a target Harness control
  entry exists. That is SR-2/SR-3b (C0), not Z2. Until then every Q3 entry is
  `disabled` with a named reason, which is the honest state given
  `capability-matrix.md`.
- **Z2's own registered limitation this line must respect:** the checkpoint is
  built on design snapshot `96fef2db47` and is **before** foundation C7/C8; its
  component keys come from `defineChatComponentKey` rather than the platform
  factory, and `ChatActionResult`/`ChatScopedAction` only *align* with platform
  `UiAction`. So Q3 must not treat these as the final platform types — after
  foundation, Z2 issues a `chat-api` revision and Q3 re-consumes by a new fixed
  SHA (do not auto-follow the branch).
- **Not provided here:** `ChatSessionGateway` / `ChatAttachmentService` /
  `ChatCommandCatalog` implementations are Z2's *expected consumer* interfaces
  awaiting C0 — Q3 must not implement them either.

## SR-6 → Q5 (`permissions-api`) — ceiling adjudication

- **Caller:** T04 resource-reference resolution and FR06 ceiling enforcement.
- **Target:** an authority that answers "may this principal, in this
  project/session, have tool/model/MCP X" so a definition's declaration can be
  refused before side effects.
- **Missing today:** `codex/011-permissions-api-ready` absent.
- **Q3 does meanwhile:** models declarations as non-executable refs, requires an
  injected ceiling authority in the resolution API (an absent authority yields a
  typed `PERMISSION_EXCEEDS_CEILING`/`REFERENCE_UNRESOLVED` refusal, never a
  permissive default), and records refusal diagnostics. R07 of the rollout spec
  is honoured: managed invocation is refused while no pre-execution authority
  exists.

## SR-7 → C0 (`foundation`) — server plugin composition + wire methods

- **Caller:** T13 product enablement.
- **Target:** `server_plugin_api.ServerPluginDescriptor` /
  `ServerMethodDescriptor` / `ServerPluginContext` registration and
  `products/server/src/ordessa_server_product/composition.py:40-55
  default_plugins()` insertion.
- **Reference implementation that exists today:**
  `plugins/workspace/src/ordessa_workspace/plugin.py:48-206`
  (`WorkspaceServerPlugin`, ports `database`/`idempotency`, returns a
  `ServerPluginRegistration`).
- **Ownership:** `products/**` and the root lock are C0-only (rollout plan §"每线
  所有者"). Q3 writes its own `plugin.py` inside its package and lists the
  composition insertion in `integration-request.md` instead of editing
  `products/`.

## SR-8 → C0 — shared `IdempotentRecords` / DB port decision

- **Caller:** T04/T05 persistence of definitions, assignments and operation keys.
- **Question for C0:** Q3 deliberately keeps a domain-owned file-backed store
  (pattern reused from `assets/skills.py` / `assets/catalog.py`) instead of
  adding tables to `packages/pacthold/src/pacthold/storage/database.py`
  (`PRODUCT_SCHEMA_VERSION = 21`), because (a) `research-and-reuse.md` forbids
  folding this domain into Pacthold/Server, and (b) shared schema/migration
  work is C0's surface. If C0 wants Q3 rows in the product DB instead, say so
  before the integration step and Q3 will move the store behind the same
  service API.


## SR-9 → self (Q3) + note to Z2 — chat-api r1→r3 invoke signature drift

- **Consumer:** `plugins/assets/subagents/ui` (T11 Chat input source).
- **Fact:** `ChatInputEntryAction.invoke.execute` became `(location: ChatLocation) => Promise<ChatActionResult>`
  (`plugins/chat/api/src/contract.ts:222`), replacing `ChatScopedAction<void>`; our face still
  passes a zero-arg closure → `TS2322` at `subagent-input-source.ts:160`.
- **Resolution owned by this line:** make `execute` revalidate the **passed** location and return
  `unavailable` on staleness with zero business calls — the contract change improves G17, so Q3
  adopts it rather than adapting around it. No request to Z2.
- **Note for Z2 (documentation, not a blocker):** the signature change is source-breaking for
  consumers that captured the query location; worth a line in the next `chat-api` revision record,
  since Q3's own r1-based tests encoded the old shape.

## SR-10 → C0 — post-consumption gates this line still cannot close

- `permissions-api` states plainly: **no pre-effect execution gate exists** (their Request G1,
  owner C0), so Q3's ceiling can consult the real authorizer for *adjudication* but must keep
  G18/G19 (apply-Confirmed-then-send-exactly-once, enforced pre-side-effect) **open**.
- `harness-api` states: the default product's ACP admission port reports `ready=False`
  (Q5 authorizer, one-use execution permit, native runtime generation and the production
  pre-effect path are not wired), and instance generation / operation-bound native receipt are
  absent so restart reconcile must remain `Unknown`. Therefore Q3's `loaded`/`invokable`/`used`
  cells and G19/G20 cannot be claimed from these checkpoints alone, and Q3 will not infer them.


## SR-11 → C0 + Z1 — `AgentBoxProfileV1`: **RESOLVED by consumption, no patch needed**

- **Symbol:** `pacthold.resource_contracts.AgentBoxProfileV1`, imported by
  `plugins/profile/src/ordessa_profile/plugin.py:17`.
- **Resolution (2026-09-28 00:2x):** no owner decision is required. Z1 already moved off
  the removed marker in `40cb6cc4ed` (import from
  `pacthold_runtime_compat.resource_contracts`, provided by `plugins/runtime-compat`), and
  `foundation` legitimately dropped `pacthold.resource_contracts.AgentBoxProfileV1`
  (present on `main`, absent on `codex/011-foundation-ready` — verified per ref).
- **What was actually wrong on our side:** my own merge deleted Z1's lane, and the first
  repair restored their *older* publication, which is why the import still failed. Taking
  Z1's lane tip fixed it; `pytest plugins/profile` now passes 140/140.
- **Consequence for Q3:** T10 is unblocked — `ProfilePluginServices.register_v2_facet` is
  present and importable, so the facet/editor slice can be implemented against the real
  seam. Intermediate notes claiming it blocked remain in the ledger as an audit trail.


## SR-1b answered from C0's published source (main agent, independent of the writer)

Read directly from `plugins/harness/api/src/ordessa_harness_api/` at
`codex/011-harness-api-ready` (`d3f026904e`):

**(a) How a complete managed set is expressed** — `IntentSet(intents: tuple[Intent, …])`
(`intents.py:200-208`) accepts many intents and rejects any kind outside
`{SetField, ResetField, MountContent, RemoveOwnedContent, BindSecret, InvokeAction}`.
Each item is a `MountContent(source, target, relative_name,
immutable_content_ref: ContentRef, mode)` (`intents.py:123-138`), and content is
content-addressed: `ContentRef(reference, sha256, size)` with a 64-hex digest and a
non-negative int size, both validated (`intents.py:109-120`). So "compile the whole
target set at once" is expressed as **one `IntentSet` carrying N `MountContent`**, not
a per-item patch series — §C3's requirement is satisfiable.

**(b) Which reset rule means "remove only what this facet owns"** — 
`ResetField.baseline_rule` is the closed set
`{"remove-key", "native-default", "restore-owned-baseline"}` and ownership is carried by
`IntentSource(facet_id, item_id, contribution_version)` (`intents.py:34-45`,
`ResetField` at `:154` region). FR09's "delete only our generation's content, never the
user's pre-existing native items" maps to **`restore-owned-baseline`**, scoped by
`facet_id`. Still to confirm from the *apply* side (not the type): that the restore is
computed from the facet's own baseline and cannot reach a user file — requested below.

**(c) Can `Assessment`/`Verification` carry proof** — `contracts.py:192-205`:
```
status: Literal["supported","unsupported","unknown"]
evidence_ref: str | None = None
reason: str | None = None
  → unsupported/unknown assessment needs reason   (enforced)
  → evidence_ref is optional, and only checked non-empty when present
```
So a `supported` verdict is constructible **with no evidence reference at all**. That is
the G01/G03 failure mode ("把官网最新版功能误宣告为仓内 pin 已支持") left open by the
contract itself.

**New request to C0 (SR-12):** make `evidence_ref` mandatory when
`status == "supported"` (and for `ConfigurationCapability`/`Verification` the same way),
mirroring the rule they already enforce for `reason` on the negative statuses. It is a
one-field validation change in `contracts.py:197-205`; until then Q3 enforces the rule
locally — our adapters refuse to emit `supported` without a pin-scoped evidence string —
and this asymmetry is recorded rather than silently relied upon.

**Policy consequence Q3 adopts regardless:** `MountContent.mode` includes
`"executable"`. A subagent definition is content, never code (FR14/G05), so every Q3
mount must use `mode="read-only"` and a test must prove the executable mode is
unreachable from this domain's compile path.


## SR-3c → C0 — the pre-effect gate is *derivable*, not absent: three ports to inject

I previously recorded G18/G19 as blocked because `harness-api`'s record says the default
product's ACP admission port answers `ready=False`. Reading the providing code changes
what that blocker actually is — and it is smaller and concrete:

- `plugins/permissions/backend/src/ordessa_permissions_backend/plugin.py:206` already
  **provides** `ACP_ADMISSION_PORT` (and `AUTHORIZER_PORT`) — so Q5's authorizer is a
  real composed port, not a proposal.
- `plugins/harness/src/ordessa_harness/server_acp/plugin.py:98` **consumes** it
  (`ports.get(ACP_ADMISSION_PORT)`), so the call path exists on both ends.
- The adapter's readiness is *derived, never assumed* (that module's own docstring,
  lines 6-11): with no injected authority sources it honestly answers `ready=False`.

The missing piece is therefore **composition**, expressed as exactly three optional port
keys (`plugin.py:56-60`):

| Port key | Provides | Who must wire it |
| --- | --- | --- |
| `acp.admission.native_evidence` | authoritative native-session / runtime-generation evidence | C0 (Harness owns native session identity) |
| `acp.admission.principal` | the server-side principal for the admission call | C0 (host-side identity, never client-reported — G07) |
| `server.instance_id` | the instance the generation belongs to | C0 |

**Request:** once those three are injected in the default composition, the gate becomes
live and Q3's T12 can claim G18/G19 at L2/L3. Until then Q3's `apply.py` must keep
refusing with the missing keys named — and this line will not substitute a fixture for
that wiring and report it as a passed production gate.

**Also corrected here:** my earlier wording said the authorizer/admission authority was
"absent in this tree". It is present and provided; what is absent is the injection of
those three sources. Q3's refusal behaviour is unchanged either way (fail closed), but
the blocker text now matches the code.


## SR-1b FINAL answers, verified against C0's implementation (was: my prediction)

The adapters face now emits only real `ordessa_harness_api` types and its own vocabulary
is **deleted**, so the earlier guesses are replaced by what the code actually does:

- **(a) complete managed set** — one real `MountContent` per definition, and set
  completeness is enforced host-side by **whole-generation rebuild**:
  `materialize_generation` publishes one complete directory and states there is no hot
  apply (`plugins/harness/src/ordessa_harness/materialization/private_generation.py:447-495`),
  with overlapping claims refused (`intent_merge.py:235-239`). `ContentRef` is
  content-**addressed**: no bytes travel in the intent; the host resolves
  `reference` from `RuntimeSnapshot.content` and re-verifies `size`+`sha256`
  (`private_generation.py:268-277`). Q3's grant is one
  `FieldClaim("directory", handle_id, ("agents",))`.
- **(b) FR09 removal** — **`RemoveOwnedContent`, not `ResetField`**: ownership is the host
  snapshot keyed `(target handle, resource, relative_name)` and compared against the
  **carrier-granted owner**, not `IntentSource.facet_id`
  (`intent_merge.py:218-220`, `private_generation.py:278-287`). My earlier guess that
  `restore-owned-baseline` was the FR09 rule is **wrong and retracted**: the materializer
  implements only `remove-key` and raises "unsupported reset baseline rule" for the rest
  (`private_generation.py:259-263`), so nothing may route through it.
- **(c) evidence** — asymmetric, and it matters: `Match` **requires** a non-empty
  `evidence_ref` (`contracts.py:208-214`) and only `Match` can confirm
  (`configuration_service.py:303-305`), so verification cannot be claimed without proof;
  but `Assessment` allows `status="supported"` with **no** `evidence_ref`
  (`contracts.py:197-205`). Q3 keeps its stricter internal constructor and always fills
  `evidence_ref`.

## SR-12 expanded → six symbol-level gaps for C0 (G-1…G-6)

| # | Gap | Request |
| --- | --- | --- |
| G-1 | `compile` returns only an `IntentSet`, yet `MountContent.immutable_content_ref.reference` must **already exist** in `RuntimeSnapshot.content`; nothing in the contract lets a contributor deposit bytes | add a `ContentStaging` protocol (`stage(reference, data)`) to `ordessa_harness_api`, or state who mints references. Q3 interim: a host-injected `stage_content` sink; storage never expressed inside an intent |
| G-2 | no intent expresses "set a **rebuild-class** option, never in place" (Claude pin: `agents`/`settingSources` force a Query rebuild, matrix C-6). A `SetField` on a file codec would falsely imply hot applicability | typed `SetRebuildClassOption`, or a `SetField` carrying `reconfiguration="restart-resume"`, or commit to the alternative: mount into a root that `settingSources` reads and expose negotiation as a target fact. Q3 interim: the builder exists and **always refuses**, with a test |
| G-3 | `Assessment.supported` constructible with no evidence | require `evidence_ref` for `supported`, mirroring `Match` |
| G-4 | `ResetField.baseline_rule` offers three values, one implemented | implement `restore-owned-baseline`/`native-default` or drop them from the Literal |
| G-5 | `IntentSet` cannot carry compile diagnostics (e.g. native-discovery `unknown`) | add a `diagnostics: tuple[str, …]` companion |
| G-6 | no way to say "extension-backed absent" in an `Assessment` | either document the convention (`unsupported` + empty `FieldClaim` tuple, which Q3 now uses for Pi) or add an `origin` field |

## SR-13 → self-owned follow-up, recorded because it is a policy collision, not a bug

The published contracts (`ordessa_harness_api`, `ordessa_permissions_api`) are separate
installable packages, so emitting real intents necessarily makes this plugin import a
non-stdlib module. Q3's own `test_boundaries_t03b.py` assert list carries the earlier
**stdlib-only** promise from `integration-request.md` I-1, so the two cannot both hold.
Decision (main agent): the boundary that must survive is *no host-private and no
sibling-plugin private* imports — that guard stays green. The stdlib-only line is
replaced by an explicit allow-list of published API packages, mirroring the existing
precedent in Q5's
`plugins/assets/sandbox/adapters/tests/test_purity_no_fake_apply.py:37`.
Consequence for C0: I-1's "runtime dependencies: stdlib only" is superseded — this
package now requires `ordessa-harness-api` and `ordessa-permissions-api` (plus
`ordessa-profile-api` if the facet slice consumes it), so the composition step must add
those editable-install lines.

## SR-13b — measured offender list, and one import that should NOT be allowed

The stdlib-only collision is now concrete (from the boundary guard's own output):

| Imported third-party module | Importers in this package | Ruling |
| --- | --- | --- |
| `ordessa_harness_api` | `adapters/{__init__,base,claude,codex,intents,pi}.py`, `apply.py` | **allow** — published contract package of C0 (55 exports, standalone wheel) |
| `ordessa_permissions_api` | `permissions_seam.py` | **allow** — published contract package of Q5 |
| `server_plugin_api` | `plugin.py`, `wire.py` | **allow** — the platform's server-plugin API, the same one `plugins/workspace` registers through |
| `ordessa_permissions_backend` | `permissions_seam.py` | **do not allow** — that is Q5's *provider* package, not its published contract. Importing a sibling plugin's backend is the exact plugin→plugin private edge `AGENTS.md` rule 3 and the boundary tests exist to prevent, and it is not needed: the seam should receive the authorizer object and its port name **by host injection**, or take constants from `ordessa_permissions_api` only |

So the guard migration must widen the allow-list to the first three rows and keep the
fourth red as a defect. Declared runtime dependencies for I-1/C0 become
`ordessa-harness-api`, `ordessa-permissions-api`, `ordessa-server-plugin-api` —
never `ordessa-permissions-backend`.


## SR-14 — wire/registration findings that are *not* faked, recorded as open seams

From the in-package server-plugin registration (`plugin.py`/`wire.py`, 54 tests,
8 mutations each killing ≥1 test). The point of this section is that every unwired
capability is **registered as refusing** rather than answered with an invented result:

| Item | Reality measured | Current honest behaviour |
| --- | --- | --- |
| Identity authority | `permissions.authorizer@1` answers `evaluate/reconcile` only — it **cannot attest a principal** (`service.py:59-66` needs `verify_principal` + `permission_ceiling`) | `assets.subagents.context@1` port with a fail-closed `DeploymentAttestation`: exactly one operator principal, empty ceiling, **no verified project**. Needs an owner (host authentication) to provide it |
| `resolvePreview` | real resolver needs an **assignment store** (`DefinitionStore` holds definitions/revisions/receipts only), an `ApprovalAuthority` and a `Ceiling` | registered with `availability=(False, "RESOLVE_PREVIEW_UNWIRED")` and a handler that refuses, naming `assets.subagents.assignments@1` + `permissions.authorizer@1` |
| `approveAssignmentUpdate`, `inspectNative` | `service.py:658/661/664` raise `NotImplementedError` | **not registered at all** — advertising an unbacked method is the fake-interface pattern R2 forbids |
| apply / invoke / run / reset / mount verbs | no `assets.subagents.*` dispatch path may exist (FR12, SR-2) | not registered; `apply.py` self-documents its four missing production collaborators |
| §C1 ownership-filtered reads | `service.get_definition/list_definitions` take **no viewer**, so per-scope filtering (`scopes.visible_definition_ids`) is not enforceable at the wire | reads answer over the attested server scope's whole library — recorded as a **real gap in this package's own service face**, not hidden |
| "Unknown must be queryable" (§C5) | the idempotency scope string is service-internal (`service.py:604`) | projected as `OUTCOME_UNKNOWN` + `retryable`, but there is no receipt re-read surface. Requested symbol: `DefinitionService.operation_status(principal, action, target, operation_key)` |
| `NOT_FOUND` | §C5 has no such code and `errors.py:26-41` neither | mapped to `DEFINITION_INVALID → INVALID_REQUEST` rather than inventing a code |

**Consequence for C0's composition step:** when `NativeSubagentsServerPlugin()` is added
to `default_plugins()`, the existing guard
`test_boundaries_t03b.py:459 test_no_composition_or_server_source_references_this_package_yet`
**must be retired in that same commit** — it asserts today's absence, and leaving it
would make a correct integration look like a regression.

**Follow-up owed by this line (not by C0):** the two service-face gaps above
(viewer-scoped reads, `operation_status`) are inside `plugins/assets/subagents/**` and
will be closed here, not handed out.


## SR-15 → Q5 — three symbols Q3 needs are only in your *provider* package

Measured against the installed packages of the consumed `permissions-api` checkpoint:

```
import ordessa_permissions_api as a
AUTHORIZER_PORT      -> NOT in API      ApprovalScope  -> in API
CorrelationConflict  -> NOT in API      ApprovalState  -> in API
VersionConflict      -> NOT in API
import ordessa_permissions_backend as b
b.AUTHORIZER_PORT    -> 'permissions.authorizer@1'
```

So `permissions_seam.py:78` has no API-level source for the port name or for the two
conflict outcomes, which is how a sibling plugin's backend ended up imported at all.
That import is the plugin→plugin private edge `AGENTS.md` rule 3 forbids, so widening a
guard to bless it would be the wrong fix.

**Request (symbol level, either form is enough):**
1. re-export `AUTHORIZER_PORT`, `CorrelationConflict`, `VersionConflict` from
   `ordessa_permissions_api` (they are contract facts, not storage internals), or
2. publish them as a tiny shared module the API depends on, or
3. state in the checkpoint record that consumers must receive the port **name** and the
   conflict **types** by host injection, in which case the composition (C0) supplies them
   and Q3 removes the import.

**What Q3 does meanwhile** (this line's own change, not waiting): take the port name from
the injected context instead of a constant, and handle conflicts through an injected
tuple of exception types with a **fail-closed** default — an unrecognised exception must
become `OPERATION_UNKNOWN`, never "the authority did not object". The backend import
disappears, the boundary guard keeps it forbidden, and SR-13b's fourth row is resolved
without an allow-list hack.
