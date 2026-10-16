# Original-owner bootstrap and first Work receiving

This is a source-level receiving recipe for the first case, not evidence that
the full candidate is production-ready. It uses one original Engineering
library, one `SQLiteUoWFactory`, one selected access authority, and the same
method/review/work owner objects throughout. It introduces no work database,
proposal identifier, method identifier, synthetic capability, reviewer role,
Grant, execution result, or unit.

The executable sequencing helpers are in
[`BOOTSTRAP-RECIPE.py`](BOOTSTRAP-RECIPE.py). They accept owner-returned
objects only. Current `SQLiteReviewBindings` supports the unbound constructor
and one-shot `bind_selection`; this is a source audit, not a qualification of
the complete product flow. No source, frozen84 artifact, or test file was
changed for this recipe.

## Corrected bootstrap conclusion

The existence of a future Proposal is not an inherent precondition for
publishing a method that requires `engineering.reviews.request`. The actual
requirement is a real bound operation owner in the host catalog. An unbound
`SQLiteReviewBindings` can be composed with the original `EngineeringReviewAdmission`
before any Proposal exists, provided the actual selected Unit and source
callbacks are supplied. Its exact object is available as
`ports.review_admission.bindings` and is shared with the Work source. The
original Service can then advertise `engineering.reviews.request` only when
the installed handler and this actual bound source satisfy its catalog checks.
After the original Proposal is created, the same object receives the actual
refs through `bind_selection`.

That corrects the earlier claim that publication itself must refuse until a
Proposal exists. Publication must refuse when the actual registered catalog
lacks required operation/check owners. The unbound reader creates no catalog
descriptor by itself: it only lets the actual Service pass its bound-source
check when that reader is installed. A request or Work start must refuse
when its subject/material facts are not yet present. Neither refusal may be
avoided by inserting a placeholder Proposal or fixture descriptor.

## Source-before-subject composition

Trusted product composition first uses the same `factory`, `access`,
`WireScope`, `SQLiteMethodControl`, and `SQLiteBlobStore` to construct
an unbound review binding. `method_unit_application_ports_factory` in
`engineering_method_unit_assembly.py` is the existing Server owner builder. It
constructs `build_engineering_review_ports`,
which creates the real `EngineeringReviewAdmission`, original
`SQLiteUnitReviewBindings`, reviewer authority and review response-trust
source; the Work source receives that exact `review_admission.bindings`
object. The actual reviewer/response source ports must be supplied from the
selected `LocalUnitOwner` and its original records/query owners. They cannot
be replaced with a fake or an `ActorRef` conversion.

`SQLitePersistedMethodWorkSource` and
`build_method_run_bindings(factory, method_control=..., work_condition_source=...,
registry_loader=load_registry)` are then constructed before subject selection.
The same `MethodRunBindings` is returned as
`EngineeringApplicationPorts.current_wait_bindings` and used by the original
review/report consumers. The actual packaged `load_registry` is the runtime
loader; callers pass the callable, not a preloaded dictionary. The Product root
retains the exact `review_bindings` object in its trusted in-process
composition closure so it can later bind the actual subject. This retains an
owner object, not a second Work state or a permission.

The current source-facing APIs are:

```python
SQLiteReviewBindings(factory, method_control, *, scope,
                     proposal_ref=None, phases=None)  # approved unbound form
review_bindings.bind_selection(context, *, proposal_ref=actual_ref,
                               phases=actual_nonempty_phase_tuple)
build_method_run_bindings(factory, *, method_control,
                          work_condition_source, registry_loader)
```

The unbound constructor and binding method exist in current Engineering
source. Server `product_runtime._method_unit_configuration` still requires
`proposal_ref` and nonempty `phases`, so the ordinary Product route cannot
select the unbound form yet. It also requires a selected `pi_selection` and
`pi_ports`. User JSON remains data-only; the source callbacks and selected
Unit owner must come from trusted runtime composition. Thus this helper is
not a current CLI feature.

## Publication and original selection

`RegisteredMethodPublication` in
`apps/server/src/ordessa_server/composition/engineering_method_management.py`
must use the `RegisteredHostCapabilityCatalog` built from the actual registered
host plugins on the same factory. Its `publish(MethodSource, compiler_version=...)`
loads, compiles against `catalog.read_current()`, then freezes the snapshot.
The candidate `methods/incremental-engineering/candidates/2.6.0/method.yaml`
requires these 19 exact descriptors:

- Operations: `engineering.artifacts.create`,
  `engineering.artifacts.append_revision`, `engineering.proposals.create`,
  `engineering.reviews.request`, `engineering.reviews.record`,
  `engineering.notices.publish`, `engineering.approvals.prepare_intent`,
  `engineering.approvals.request`, `engineering.approvals.record_conversation`,
  `engineering.changes.apply`, `engineering.acceptance.adopt`,
  `engineering.packages.freeze`, `engineering.executions.dispatch`, and
  `engineering.submissions.record_report`.
- Checks: `ordessa.claims.coverage`, `ordessa.sources.integrity`,
  `ordessa.schema.validate`, `ordessa.submission.binding`, and
  `ordessa.decision.evaluate`.

These must come from the actual current owners, with exact versions and
contract digests. No static fixture or hand-written catalog entries can fill a
gap. The first-case checkpoint observed the real catalog reject
`engineering.reviews.request`; the unbound review owner is the narrow way to
make that descriptor available before a subject exists. It does not establish
the other 18 descriptors. If any real owner is still absent, keep the
publication diagnostic and do not select or start Work. Candidate metadata
also remains `unsupported-owner-binding-candidate` with production activation
forbidden pending owner contracts; a successful compiler call by itself is
not product activation authorization.

On successful publication, retain the exact returned snapshot `MethodRef`.
Convert it only at the existing composition boundary to the domain
`ordessa_engineering.domain.artifacts.method_binding.MethodRef`, preserving
method id, release version, schema version and SHA-256 snapshot digest. Select
that exact ref through `RegisteredMethodPublication.select(...,
expected_version=actual_method_selection_version)`; obtain the current
selection version from the original Methods repository/CAS, never guess it.
The original `SQLiteMethodControl.guard_selected` must then resolve this exact
adopted snapshot.

## Create and bind the actual subject

After selection, persist the actual material and Proposal through the existing
Engineering Service:

1. Create/append typed MethodPayload artifact revisions through the original
   `engineering.artifacts.create` and `engineering.artifacts.append_revision`
   operations. Keep the actual returned immutable `ArtifactRevisionRef`s and
   command outcomes.
2. Create the Proposal through original `engineering.proposals.create`, with
   the selected domain MethodRef, actual same-artifact base/proposed revision
   refs, complete claims/change/baseline material, and the exact method
   requirement template data. Keep the actual `ProposalRef` returned in the
   command result. Resolve/read it through the original Proposal repository to
   confirm the exact persisted closure; do not calculate a digest locally.
3. Derive the nonempty `ConfiguredReviewPhase` tuple from the selected frozen
   method's declared review nodes and the actual persisted Proposal/material
   records. Pass only exact owner-produced ArtifactRevisionRefs and targets.
   Call `review_bindings.bind_selection(context, proposal_ref=proposal_ref,
   phases=phases)` on the exact binding object already retained by the live
   ReviewAdmission and Work source. The call validates method, phase, target,
   scope and Proposal closure through the original repositories.

The lower `method_unit_application_ports_factory` accepts the unbound values,
but `product_runtime` rejects them before that builder runs. The minimum
receiving change is to allow an explicit trusted unbound mode and retain the
original binding object for step 3. The user JSON must remain data-only; it
must not carry callbacks, synthetic refs, catalog entries or permission
objects. The trusted product root needs a normal typed handoff from Proposal
creation to the retained owner object.

## Create the method input and start on the same Service

Create a real MethodPayload artifact revision for the selected method's
`document.work_inputs.schema`. Its document has exact fields:
`document_type`, `schema_version=1`, `run_id`, `proposal_ref`, and `events`.
Its proposal ref must equal the persisted Proposal selected above; its events
must contain only method-declared wait inputs and must not claim readiness,
review, authorization, acceptance, or completion. Retain the actual immutable
`ArtifactRevisionRef` returned by the artifact owner.

Call the same original `EngineeringService` that was built with the retained
`MethodRunBindings`:

```python
await service.execute(
    "engineering.work.start",
    {
        "run_id": actual_stable_run_id,
        "selection": {
            "proposal_ref": asdict(actual_proposal_ref),
            "initial_slot_refs": {
                "work_inputs": asdict(actual_work_inputs_revision_ref),
            },
        },
    },
    actual_admitted_command_context,
)
```

The context must be the actual request context admitted for this scoped
operation. `guard_start` checks the selected method, exact Proposal closure,
typed input document, and original read set; the start transaction rechecks
those versions before writing its one original run/step state. The result is
`WAITING_FOR_CONDITION` at the declared entry wait. Start neither advances the
wait nor proves an event.

`engineering.work.bind_inputs` is only available after an existing run waits
at a condition. It uses the exact row digest and next-step ordinal CAS to bind
an additional method-required ArtifactRevisionRef. It cannot create the
initial Proposal, selected method, Work source, or initial `work_inputs`
reference.

## Current production blockers and handoff

The first-case Runtime had no selected Pi/LocalUnitOwner. Its current
`product_runtime.build_product_runtime` does not receive `method_unit_options`
from the data-only `--user-config`; hence its actual `EngineeringApplicationPorts`
omitted `current_wait_bindings`, and `MethodRunOrchestrator.start` correctly
returned `WORK_WAIT_AUTHORITY_UNAVAILABLE`. No Work was created.

The unbound review binding now exists, but the default product cannot claim
the complete 2.6 catalog. It still needs actual Execution/product owners for
the selected Unit/records/query producer, reviewer and authored-material
identity, current schema-15 reviewer authority, package/approval/baseline,
report source, and canonical dispatch binder. These are not encoded by the
candidate's current materials or the two persisted candidate text artifacts.
When any required owner is missing, preserve the exact publication or runtime
refusal. Do not use an `ActorRef`, a fabricated role, fixture capability,
synthetic Unit, guessed Proposal/MethodRef, or second Runtime to bridge it.

The exact callback contract is also not a caller by itself. The Server builder
requires a selected `LocalUnitOwner`, `author_unit_resolver(context, plan)`,
`invocation_resolver(context, plan, request, prompt_binding=...)`, and
`unit_query_factory(context, unit_ref, plan, request, purpose=...)`. The
unit-query callback must return the actual `(invocation, input_digest)` that
`UnitRecords.resolve_unit_reference` validates. For report capture, the
optional execution records and query factory must be the same original
UnitRecords/query owners. These callbacks are passed only by trusted Python
composition; the current `rg` of Server callers found no production runtime
construction of `OriginalRecordedUnitReviewQueries` or
`original_submission_author_unit_resolver` (their usages are tests). The
existing helper `original_submission_author_unit_resolver` only resolves the
author of an exact persisted acceptance Submission; it cannot provide the
pre-execution Proposal author. No ActorRef, profile, or proposal creator is a
substitute for an authenticated UnitRef.

The current configured-user path is subject-bound: 
`resolve_product_user_configuration(...)` requires `engineering.proposalRef`
and a nonempty list of review phases, verifies them through original owners,
then creates a bound `SQLiteReviewBindings`. It is suitable only after that
actual Proposal exists. A first Proposal flow needs trusted in-process
unbound initialization, followed by the owner-returned Proposal/phase handoff
described above. The config document itself must not carry executable
callbacks or permission objects.

The remaining product request belongs to the trusted Server/Interfaces
composition owner: permit explicit unbound `proposal_ref=None, phases=None`
only in a trusted `method_unit_options` path; retain the same review binding
across registration and later `bind_selection`; and keep CLI JSON unable to
supply executable callbacks. The first-case Product path also needs a real
selected Pi/Unit owner and actual query/response callbacks. This recipe
documents those owner handoffs; it does not perform that cross-owner change.
