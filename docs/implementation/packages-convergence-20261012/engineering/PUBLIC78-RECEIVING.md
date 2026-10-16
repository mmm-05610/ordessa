# Source checkpoint 78 receiving contract

Status: source78 and one fresh wheel qualified for the Engineering owner scope;
see `QUALIFICATION78.json` for commands, results and limits. Wheel SHA-256:
`5d1305cdbf491efb9153e9e15d06068a69e0f5097ec7bdef2f1bdcd4a2e004d1`.
Earlier 74/75/77 artifacts cannot implement these APIs. Manifest-only freeze is
delivered separately and does not publish a method.

## Original persistence and reviewer owner

Create a **new independent acceptance library** explicitly:

```python
EngineeringLibrary.create(path, library_id=library_id, schema_version=15)
factory = SQLiteUoWFactory(library)
```

Schema2 remains the default. Existing schema14 is not migrated automatically.
All assignments, controls, immutable revoke events and command journal entries
use this original library/UoW; no role is stored in an external registry.

The public application constructor is:

```python
from ordessa_engineering.application.assembly import build_reviewer_assignment_usecases
assignments = build_reviewer_assignment_usecases(
    factory, method_control=method_control, records=records,
    expected_access=access, expected_scope=wire_scope,
    unit_query_factory=unit_query_factory,
    author_unit_resolver=author_unit_resolver,
)
```

Inject **that instance** as `EngineeringPorts.reviewer_assignments`. Service
operations are `engineering.reviews.assign_reviewer` and
`engineering.reviews.revoke_reviewer`; their schemas are obtained through
`EngineeringService.input_schema(operation)`. `ReviewerAssignmentRef` exported
from `application.api` is the original domain ref, with scope, assignment_id and
digest. Responses retain the original `CommandResult` and journal identity.

`unit_query_factory(context, unit_ref, plan, request, *, purpose)` returns the
original authorized Unit query invocation and its original input digest. The
owner invokes `records.resolve_unit_reference(..., input_digest=...)` and
compares the complete native public ref. `author_unit_resolver(context, plan)`
must obtain the actual selected author from the business source. Providing an
unrelated valid Unit as an author is refused. An attribution string does not
establish authorship.

The original EngineeringCommandAccess must hold the **dedicated current**
assign/revoke capability under the selected WireScope. Its guard yields the
verified issuer principal and credential epoch and remains active through
COMMIT. A development approval or interaction grant does not grant that role.
The first receiving seam conservatively requires the same current issuer and
epoch when rechecking a persisted assignment; it does not claim arbitrary
issuer lookup or model-quality certification.

## Review readers and authority

Public receiving path is `ordessa_engineering.adapters.review_sources`:

```python
ConfiguredReviewPhase(phase_key, eligible_reviewer_roles,
    material_inputs=(), workflow_node_id=None, targets=None,
    submission_ref=None, review_purpose=None)
SQLiteReviewBindings(factory, method_control, *, scope, proposal_ref, phases)
SQLiteUnitReviewBindings(factory, method_control, records, *,
    review_bindings, invocation_resolver, author_unit_resolver=None)
SQLiteUnitReviewerAuthority(factory, *, expected_access, expected_scope,
    assignments, method_control, unit_records, unit_query_factory,
    author_unit_resolver=None)
```

Authority receives the exact same selected objects used by assignments.
The invocation resolver `(context, plan, request, *, prompt_binding)` returns
the original `NativeReviewInvocation` exported from `application.api`:
unit_ref, operation_ref, params and query_invocation. The prompt must contain
the canonical fixed method/plan/request/schema/check/input block exactly once.
Records, native payload and authorized query retain their original identities.

`application.assembly.build_review_check_admission(...)` builds the original
mechanical, declared invariant and `GenericDecisionCheckSource(UnitReviewCheckSource(...))`
sources. It verifies the active factory/access/scope through the public
`bound_review_check_capabilities` reader. Whole-review JEV is not a substitute
for that GenericDecision source. Product composition still needs the actual
composite reviewer authority, native invocation/query producer and qualified
reviewer Unit; these are not manufactured from descriptors.

## Work and canonical dispatch

Public path is `ordessa_engineering.adapters.method_work`:

```python
SQLitePersistedMethodWorkSource(factory, method_control, *,
    phase_bindings=(), blobs=None, review_bindings=None,
    execution_records=None, execution_query_factory=None)
```

The original method-control snapshot store, blobs, Proposal, materials,
reviews and submission/dispatch records are used. Construct one
`build_method_run_bindings(factory, method_control=..., work_condition_source=...,
registry_loader=load_registry)` and reuse it for Work, waits and reports.
`engineering.work.start` takes explicit selection with ProposalRef and named
immutable input revision refs. `engineering.work.bind_inputs` takes run_id,
input_ref, expected_row_digest and expected_next_step_ordinal, binding a direct
child revision via the original CAS without moving the cursor or accepting it.

The original same-Service canonical dispatch instance is produced by
`application.assembly.bind_execution_dispatch(service, *, execution, selection,
source_snapshots, history_sources)`. Apps retain that service's `execute` and
native `OwnerOperationResult`, including unknown/accepted/engineering_completed.

## External candidate and remaining qualification

Candidate 2.6.0 uses Choice revision2 for change consistency; discrete options
map to satisfied/violated/insufficient. Unknown, incomplete, unmapped or tied
answers cannot pass. Historical 2.5.0 bytes remain immutable. Candidate metadata
continues to forbid publication/activation until actual binding qualification;
existence and controlled fixtures are not method release evidence.

Work tests use an alternate persisted review-free method; Unit reader fixtures
use synthetic native peers. Their passing receipts do not prove the complete
five-review candidate, a real Pi/JEV run, production model quality, or a human
Grant. `QUALIFICATION78.json` identifies source/installed checks and actual
provider gaps. Whole-nightly pip check is red: three old distributions still
require the retired environment API. Engineering's five direct dependencies
are satisfied; full Product dependency closure remains its owner's prerequisite.
