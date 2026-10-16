# First-use clarifications · 2026-10-13

This clarifies the receiving note frozen in `9ebfdafa`; that note, its manifest
and the original receipts remain unchanged. These are source-verified field and
authority distinctions, not newly tested product operations.

## Assignment route, schema and authority

Schema15 is an explicit Engineering library-creation choice. Opening an existing
library does not migrate it. Choosing a schema does not grant reviewer roles,
assignment powers or acceptance authority.

The current public wire binding does include the finite assignment/revocation
commands: `SUPPORTED_METHODS` incorporates Engineering's `SUPPORTED_COMMANDS`,
which includes `ASSIGN_REVIEWER` and `REVOKE_REVIEWER`; the service has their
handlers, and the application ports forward `reviewer_assignments`. Earlier
receiving prose saying there is no wire method is historical. A route's
existence does not prove its actual assignment owner, permission or authorization
producer is bound. Default machine capabilities exclude reviewer assignment,
revocation and `engineering.acceptance.adopt`.

## Work start and subsequent input binding

`engineering.work.start` takes `run_id` and `selection`, whose fields are
`proposal_ref` and `initial_slot_refs`. It does not take top-level `work_inputs`
or `method_ref` arguments. The selected MethodRef comes from the original
guarded method snapshot.

The generic schema makes selection optional, but the selected persisted Work
source requires the actual selection and its declared input-document slot.
For the current method, the initial immutable input reference belongs in
`selection.initial_slot_refs.work_inputs`. The original source validates that
reference and its method/run/proposal binding during `guard_start`; missing the
slot refuses before Work creation. Do not work around that refusal by starting
with no initial input and promising to bind it afterward.

Once the original run is waiting, later immutable input revisions use
`engineering.work.bind_inputs` with `run_id`, `input_ref`,
`expected_row_digest` and `expected_next_step_ordinal`. This is a separate CAS
operation; it does not adopt a head, advance the cursor, dispatch, grant a role
or accept the result. Resume uses its own current-condition fences.

## Remaining C1 members

The wheel has25 remaining payload members. The bounded census identifies
production consumers for several contract families; it does not say every
member has a production consumer. Empty facades, aggregate exports, package
markers, compatibility errors and frozen-vector codec members have distinct
retirement obligations. Dynamic/literal references and preserved assertions
must be checked where the census does not prove them absent.

Units records/admission, Agents/Harness provider declarations, Server host
composition and the Pi profile/prompt/workspace seams remain real cross-owner
migrations. Do not convert the25-member count into blanket deletion approval
or create a new central API to receive them.

## Evidence and limits

These statements were checked against the actual Engineering command schemas,
method-run start/input-binding implementation, persisted Work source,
Engineering wire/service binding and Server capability selection. No model,
runtime invocation, database migration, test, build or installation was performed
for this clarification. Fresh product pairing and the exact missing producers
remain necessary before claiming a real first-use result.
