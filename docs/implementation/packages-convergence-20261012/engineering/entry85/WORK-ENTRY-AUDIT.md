# First Work entry: current owner and Server receiving path

Read-only source audit, 2026-10-13. No production source, tests, frozen84
paths, or runtime state were changed. No tests, build, installation, model
call, or Git operation was run.

## Why the first-case Work start refused

`EngineeringService` creates `MethodRunOrchestrator` with the
`current_wait_bindings` supplied by `EngineeringApplicationPorts`. Its
`start()` checks that original binding, source, and registry loader exist
before resolving the method, Proposal, or selected inputs. When absent it
returns `WORK_WAIT_AUTHORITY_UNAVAILABLE`; this is the expected refusal when
the wire has no Work source.

The Server's `EngineeringWireBinding` invokes `application_ports_factory`
only when one is supplied. The ordinary `build_product_runtime()` path sets
that factory only for trusted Python `method_unit_options`. The first-case
data-only user configuration does not supply callbacks, and the default
product options have no method-unit factory. Thus the original Service had no
`MethodRunBindings`, and no Work row was created. This happened before
proposal/source validation.

## What the current original owners can compose

`packages/engineering/src/ordessa_engineering/adapters/persistence/sqlite/review_bindings.py`
now accepts exactly `(proposal_ref=None, phases=None)` as an unbound
`SQLiteReviewBindings`. `bind_selection(context, *, proposal_ref, phases)` is
one-shot: it validates context/scope, resolves the persisted Proposal and its
method through the original library, guards that exact frozen method, checks
the complete Proposal closure and every declared review phase, then retains
those exact refs. A failed bind leaves the object unbound. No future subject
is inferred.

The original Server composition chain is:

1. `method_unit_application_ports_factory(...)` in
   `apps/server/src/ordessa_server/composition/engineering_method_unit_assembly.py`
   receives the selected `LocalUnitOwner` plus actual author, invocation, and
   unit-query callbacks. It creates one original factory/method-control/blob
   graph, then calls `build_engineering_review_ports(...)`.
2. `build_engineering_review_ports(...)` in
   `engineering_review_assembly.py` constructs `SQLiteReviewBindings`,
   `SQLiteReviewAuthorshipSource`, the reviewer-assignment owner,
   `SQLiteUnitReviewBindings`, `SQLiteUnitReviewerAuthority`, and the
   `EngineeringReviewAdmission`. With `proposal_ref=None, phases=None`, this
   chain can now compose before a Proposal exists, provided the real Unit and
   all required source callbacks exist.
3. That exact `review_admission.bindings` object is passed to
   `build_engineering_work_bindings(...)`, which constructs
   `SQLitePersistedMethodWorkSource` and calls public Engineering assembly
   `build_method_run_bindings(factory, *, method_control,
   work_condition_source, registry_loader)`. The packaged `load_registry`
   callable is supplied by the Server helper. The same resulting
   `MethodRunBindings` becomes `EngineeringApplicationPorts.current_wait_bindings`.
4. The review binding is reachable on the returned
   `ports.review_admission.bindings`; the Server factory does not return it as
   a separate handle. The trusted root must retain that exact object if it
   will later call `bind_selection` after the original Proposal command.

The public Engineering entrypoints are
`ordessa_engineering.application.assembly.build_method_run_bindings` and
`ordessa_engineering.adapters.review_sources.SQLiteReviewBindings` (the
adapter package re-exports it). The Server composition functions are internal
product assembly, not user-config or wire APIs.

## Remaining receiving gap in the current product

The unbound source change is present, but the ordinary Server setup does not
yet expose the lifecycle needed to use it:

- `product_runtime._METHOD_UNIT_REQUIRED` still requires `proposal_ref` and
  `phases`; `_method_unit_configuration()` rejects `phases=None` and empty
  tuples. It also requires an actual `pi_selection` and `pi_ports`.
- `product_runtime.build_product_runtime()` builds method-unit ports only
  from trusted Python `method_unit_options`; executable callbacks cannot be
  placed in the data-only CLI JSON. That path locates the selected
  `LocalUnitOwner` through the selected Pi runtime. In the first-case
  checkpoint there was no such selected owner.
- The builder returns `EngineeringApplicationPorts`, not the binding handle.
  The same-process owner that creates a Proposal therefore needs an explicit
  trusted handoff to `ports.review_admission.bindings`; no existing CLI/wire
  command performs that handoff. The normal configured-user reader currently
  accepts an already persisted Proposal and phase values, so it is a
  subject-bound configuration path, not a first-Proposal bootstrap path.
- The current 2.6 candidate requires 19 exact catalog descriptors. A real
  unbound review admission can satisfy EngineeringService's bound-review
  source predicate and make `engineering.reviews.request` eligible for the
  registered Engineering command catalog. It does not synthesize any
  missing descriptor or provide the other operation/check owners. The
  current registered catalog must still be read and the exact compile
  diagnostics honored.

The smallest trusted Server change is to accept explicit `proposal_ref=None,
phases=None` as a distinct unbound composition mode; keep the callbacks and
Pi owner as actual selected runtime objects; and retain the exact
`review_admission.bindings` handle in the trusted composition closure. Once
the original `engineering.proposals.create` returns its persisted ref and
the phases have been derived from the frozen method plus actual records, the
same lifecycle calls `bind_selection` with those owner-returned objects.
There must be no JSON-supplied callback, placeholder ref, fake catalog entry,
second Service, or parallel Work state.

## Work start data and exact source limits

Once the original sources are wired and the subject exists, the first
`engineering.work.start` requires an actual stable `run_id` and selection
containing the exact persisted `ProposalRef` plus the method-declared
`work_inputs` `ArtifactRevisionRef`. The original source reads the frozen
manifest's `work_source` declaration, validates the input document against
the frozen method document schema, confirms the Proposal's full original
closure and method identity, and carries the original read-set/CAS guards
through the write. The result starts at the declared wait; it does not
advance that wait.

Later external user/agent input is a normal immutable artifact revision,
explicitly selected into the existing run through `engineering.work.bind_inputs`
with the expected row digest and next-step ordinal. The source reads the
revision named in `run.slots`; it does not scan the artifact head or infer
readiness. Input fields are data only. Actual review, grant, report, package,
and execution conditions must still resolve against their original owner
repositories and evidence sources.

The selected Unit callbacks and response-trust source are independent
requirements. `author_unit_resolver`, `invocation_resolver`, and
`unit_query_factory` must resolve real original Unit records/query
invocations; `ActorRef` attribution is not a Unit identity. Native execution
report capture additionally requires the actual `UnitRecords` and query
factory. Package/approval/baseline and canonical dispatch owners are also
needed for their declared operations. A constructed Work binding is not
qualification that all 19 candidate descriptors or a full real Unit review
are available.

## Exact next receiving request

Server composition should supply, on one live original runtime:

- the selected original `SQLiteUoWFactory`, `EngineeringCommandAccess`,
  `WireScope`, `LocalUnitOwner`, `SQLiteMethodControl`, and same-authority
  `SQLiteBlobStore`;
- actual `unit_owner.records`, an author resolver, a response invocation
  resolver, and a unit-query factory bound to that owner (not test peers);
- optional original material-submission proofs and, for execution-backed
  reporting, the matching original execution records and query factory;
- an explicit unbound review setup when no Proposal yet exists, followed by
  an in-process retained binding handle and a later call to
  `bind_selection(context, proposal_ref=<actual persisted ref>, phases=<actual
  method-derived phase tuple>)`;
- the exact returned `current_wait_bindings` in the original Service, plus
  the actual method input artifact ref and Proposal ref in Work start.

Current code provides the owner builders but not the default-product
bootstrap/retained-handle lifecycle or a selected first-case Unit owner.
That is the remaining integration blocker; it must be closed by Server and
Execution owners before claiming a production first Work or end-to-end 2.6
receiving path.
