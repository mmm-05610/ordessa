# First-case method capability audit

Read-only source audit after the 2026-10-13 11:00 Shanghai checkpoint. No
candidate, capability declaration, application source, or permission was
changed. The 84 publication manifest remains unchanged at SHA-256
`2718f2cbde827697b25c3cf01de43dc107ad31b70327adb422861a8c2896edb5`.

## Observed failure

The real registered publication attempt rejected candidate 2.6.0 with
`UNKNOWN_CAPABILITY` at `method.yaml#/requires/3` for
`engineering.reviews.request`; the checkpoint says no method, proposal, or
Work was created, with zero model calls. This is the first missing descriptor
encountered by validation, not evidence that the declaration is wrong.

The candidate pins the real operation descriptor as kind `operation`, version
`1`, digest
`a7395f23914f088ae9a578f3c4d8430752c8ac16dfe4a32ef8aa21c85ba97e61` at
[`method.yaml`](../../../../../methods/incremental-engineering/candidates/2.6.0/method.yaml:421).
The underlying operation is present in the original Engineering registry
resource as version `1`, with a single `plan` input and `completed`/`rejected`
results: [`operation_registry.v1.json`](../../../../../packages/engineering/src/ordessa_engineering/adapters/registry/resources/operation_registry.v1.json:2181).
`command_capabilities()` derives the host descriptor from the actual
`EngineeringService` input schema and operation contract; it labels completion
as “review request persisted, not review pass”:
[`method_bridge.py`](../../../../../packages/engineering/src/ordessa_engineering/application/orchestration/method_bridge.py:20).

## Where the descriptor is lost

The production path is:

1. `RegisteredMethodPublication.publish()` calls `compile_method()` with the
   `RegisteredHostCapabilityCatalog`, then `freeze_method()` re-reads that
   catalog and runs compatibility validation before any snapshot write:
   [`engineering_method_management.py`](../../../../../apps/server/src/ordessa_server/composition/engineering_method_management.py:48),
   [`publish_snapshot.py`](../../../../../packages/engineering/src/ordessa_engineering/application/usecases/publish_snapshot.py:80).
2. `RegisteredEngineeringCommandCatalog.read_current()` intersects callable
   registered Server methods with `binding.service.bound_operation_capabilities()`;
   it does not build descriptors from candidate `requires`:
   [`engineering_capability_catalog.py`](../../../../../apps/server/src/ordessa_server/composition/engineering_capability_catalog.py:20).
3. The service adds `engineering.reviews.request` only when the selected
   handler is the original `ReviewUseCases` on the same factory/access and its
   admission is exactly an `EngineeringReviewAdmission` tied to that factory
   and method-control owner, with `guard_plan`, `verify_response`, and
   `guard_trust` callable:
   [`service.py`](../../../../../packages/engineering/src/ordessa_engineering/application/api/service.py:132).
   `engineering.reviews.record` has a further same-authority BlobStore
   requirement. Both commands are in the registered callable map, but callable
   registration alone is insufficient.
4. `EngineeringWireBinding` constructs `EngineeringService` from trusted
   `EngineeringApplicationPorts`; when no application-port factory is
   selected, it constructs ports with only `proposal_control_admission`, so
   `ReviewUseCases` receives `review_admission=None`:
   [`engineering_wire.py`](../../../../../packages/interfaces/system-access/bindings/src/ordessa_system_access_bindings/engineering_wire.py:141),
   [`service.py`](../../../../../packages/engineering/src/ordessa_engineering/application/api/service.py:334).
   In that configuration the handler exists, but `request()` reaches
   `_admission()` and refuses with `REVIEW_AUTHORITY_UNAVAILABLE` rather than
   creating a plan request:
   [`reviews/service.py`](../../../../../packages/engineering/src/ordessa_engineering/application/usecases/reviews/service.py:196).

The checkpoint records the actual case as using the default Product startup,
with Pi selection and the production method-bound reviewer sources still
absent. This is consistent with the missing `review_admission` input above.
`engineering.reviews.request` is in `SUPPORTED_METHODS`; that only establishes
the wire callable is registered. It does not establish an original review
admission or make the command usable.

## Required original-owner binding

The smallest receiver-side fix is to initialize the Server plugin with a
trusted `application_ports_factory` that returns an actual same-library
`EngineeringApplicationPorts` containing the original review admission and
its phase/subject binding. For the candidate's subsequent review recording,
the same ports must retain the original same-authority BlobStore and a real
response/trust source; otherwise `engineering.reviews.record` remains absent
or execution refuses. Then the actual catalog should return the exact
`engineering.reviews.request` and `engineering.reviews.record` descriptors
from `EngineeringService.bound_operation_capabilities()` intersected with
registered Server callables. Only after that should the existing public
`RegisteredMethodPublication.publish(MethodSource, compiler_version=...)`
path be retried.

Existing product factories are not a drop-in bootstrap for the recorded
first-case state: `method_unit_application_ports_factory` requires a selected
Pi/Unit owner, exact proposal/phase bindings, and actual Unit query sources;
`proposal_application_ports_factory` requires an already selected Proposal
and JEV provider. The checkpoint explicitly says those production inputs are
not yet configured. `SQLiteReviewBindings` also resolves an explicitly
configured Proposal before it produces bindings. No current receipt proves a
same-library initial reviewer source and binding for this case. Engineering
must supply that original source/binding before publication; adding a test
descriptor, deleting the method requirement, or treating `trust_class="host"`
as a permission would conceal the missing owner.

There is one additional shape to account for if a human-review port is chosen:
`EngineeringHumanReviewAdmission` wraps an `EngineeringReviewAdmission` in
`.base`, but `bound_operation_capabilities()` currently accepts only the exact
base type. That wrapper is not the observed cause in the default case (there
was no review admission at all); if selected in production, the owner must
either expose the actual base admission through a narrowly reviewed source
projection or the current catalog will continue to omit the descriptor.

The immediate first error is therefore missing selected review-source
initialization. The next declared capability, `engineering.reviews.record`,
also needs its BlobStore/source binding. The later `WORK_WAIT_AUTHORITY_UNAVAILABLE`
is a separate Work-start owner gap, not a publication workaround.

No tests, builds, installs, permission changes, or candidate edits were made
for this audit. The 84 frozen manifest and capture were left untouched.
