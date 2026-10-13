# Candidate 2.6 checks and Work owner receiving table

Read-only source audit, 2026-10-13. The audit covers the current candidate,
Engineering source, Server composition and System Access wire. It changes no
source, tests, candidate, or frozen84 paths. No tests, build, install, model,
or Git commands were run.

## Candidate facts

`methods/incremental-engineering/candidates/2.6.0/method.yaml` is release
`2.6.0`, declares 19 required capability descriptors, sets
`candidate_binding_status.publication_allowed: false` and
`execution_allowed: false`, and labels `unit_submission_review` unsupported
pending host role/source binding. Its `work_source` declares
`ordessa.persisted-work-source/1`, input slot `work_inputs`, input document
type `work-inputs`, and 21 wait IDs. The input document is a method-owned
schema-validated artifact; its event values are data, never readiness,
acceptance, Grant, or execution truth.

The 19 required descriptors are not evidence that the catalog currently
provides them. The registered catalog reads exact installed handler/source
descriptors and refuses missing or digest-mismatched requirements.

## Five required check owners

All five checks are pinned by the candidate at interface `1.0.0`. The
candidate contract digests are listed so the registered catalog can be
compared without substituting names or versions.

| Candidate check | Pinned digest | Current Engineering source | Facts and boundary | Actual receiving status |
| --- | --- | --- | --- | --- |
| `ordessa.claims.coverage` | `5e16a304e5fcd714501efe6701129b83353e5b7d9496f54662c70ad5f12222aa` | `MechanicalReviewCheckSource` via `MechanicalCheckCapabilityAdapter` | Reads exact original artifact/source/claim links. A complete chain remains `unknown`; missing/empty links are `insufficient`. It does not assert semantic claim support or completeness. | Mechanism and descriptor exist. It is included only when original review admission is assembled and the actual bound catalog verifies it. |
| `ordessa.sources.integrity` | `4b7fff2a8bccfd721f681fd80f5539baf4c3ab2e5c50c742d9cf802a9cdc1354` | Same mechanical source/adapter | Verifies exact source bytes, digest, selectors and original BlobStore/material closure. It does not establish source authenticity, completeness or claim truth. | Same composition dependency; no standalone descriptor padding. |
| `ordessa.schema.validate` | `b120bf7b0ddac3c63792233edf5aaee32195f6307300a2f95446f6094c76df03` | `DeclaredInvariantReviewCheckSource` via `InvariantCheckCapabilityAdapter` | Resolves exact frozen method schema/resource identity and validates the actual `MethodContent` body. Unknown/missing/wrong schema bindings refuse or return non-pass; it is not a JSON Schema declaration-only check. | Mechanism and descriptor exist. Requires original admission and exact method resources. |
| `ordessa.submission.binding` | `57a385824dd93162fbad5356fadd8419f14b56230f17036b9e4e731b9fd512fd` | Same invariant source/adapter | Correlates the original Submission/package/Grant/baseline/output graph with the exact MethodRun dispatch binding and captured result references. It does not scan source trees, tests or Git, and does not itself mean accepted. | Mechanism exists. Requires a real same-library closure, dispatch binding, and source admission; no missing facts are invented. |
| `ordessa.decision.evaluate` | `73034144196330fe4dcc0f28359b0a2d64b90c58d0f36160cb132a8991eb71bf` | `GenericDecisionCheckSource` over `UnitReviewCheckSource` | Reads exact frozen question/input bindings and the original captured Unit response; verifies response bytes/schema and reviewer authority. Disposition mapping is the selected method's policy. This is not a generic JEV/semantic-evaluation replacement and does not certify model quality. | Source composition exists, but real Unit invocation, UnitRecords query, response/trust and reviewer-role producers must be passed by actual owners. Current default Server runtime does not provide them. |

Public composition is `ordessa_engineering.application.assembly.build_review_check_admission(...)`.
It requires the same original factory, method control, blob owner, review
bindings, UnitRecords, UnitReviewBindingResolver, UnitReviewerAuthority,
composite reviewer authority, selected access and scope. It constructs the
three original sources (`mechanical`, `invariants`, `decision`), maps the five
descriptors to those exact sources, and returns `EngineeringReviewAdmission`.
The public bound-source reader validates expected factory/access/scope before
the registered capability catalog consumes the descriptors. The builder is
assembly; it does not manufacture any source authority.

## Work owner and exact inputs

Engineering's public builder
`ordessa_engineering.application.assembly.build_method_run_bindings(factory,
*, method_control, work_condition_source, registry_loader)` validates and
returns the existing `MethodRunBindings`. Server's
`build_engineering_work_bindings(...)` creates the concrete
`SQLitePersistedMethodWorkSource`, supplies the packaged `load_registry`
callable, and shares the exact `SQLiteReviewBindings` with review admission.
The wire forwards `EngineeringApplicationPorts.current_wait_bindings` into
the original `EngineeringService`; it does not create another runner or run
store.

The start path requires:

- the currently selected frozen MethodRef and exact published snapshot;
- an actual same-scope persisted ProposalRef whose complete closure and
  method identity resolve through the original Engineering UoW;
- `selection.initial_slot_refs.work_inputs`, an immutable
  `ArtifactRevisionRef` for a `MethodPayload` matching the frozen
  `work-inputs` document schema and exact `run_id`/ProposalRef;
- the original factory/method-control/work-source guards and runtime
  `load_registry` callable.

The current Work source reads only method-declared selectors from original
run slots and the exact persisted input-document revision. Future inputs are
new immutable artifacts explicitly bound with `engineering.work.bind_inputs`
using the row digest and step ordinal. It does not scan latest artifact heads,
files, code, tests, or registries, and it treats input fields as claims/data.
Actual wait decisions resolve refs against their original owner repositories;
review waits use the real selected plan and full required phase set.

The candidate's 21 waits are `await_proposal`, `await_source_gate`,
`await_quality_gate`, `await_acceptance_intent`, `await_intent_ref`,
`await_document_acceptance`, `await_applied_did`, `await_package_draft`,
`await_generate_package_permission`, `await_frozen_package`,
`await_package_gate`, `await_implementation_permission`,
`await_execution_capture`, `await_submission`, `await_acceptance_response`,
`await_acceptance_gate`, `await_rework_review_plan`,
`await_rework_review_response`, `await_adoption_permission`,
`await_adoption_receipt`, and `await_feedback`.
Families are declarations only: `object_exists`, `review_gate`,
`action_authorization`, and `result_exists`. Their presence is not evidence
that every external action producer is assembled.

## Current Apps path and missing production glue

The actual composition path is:

1. `apps/server/src/ordessa_server/composition/product_runtime.py`
   accepts trusted Python `method_unit_options`, then selects the Pi runtime.
   It requires actual `pi_selection` and `pi_ports`; it does not take callbacks
   from user JSON.
2. `engineering_method_unit_assembly.method_unit_application_ports_factory`
   obtains the `LocalUnitOwner` from that selected runtime, verifies its
   `UnitRunPermission` uses the same access authority and scope, and requires
   actual `author_unit_resolver`, `invocation_resolver`, and
   `unit_query_factory` callbacks. It creates same-factory method-control,
   blobs, review admission and Work bindings.
3. It returns `EngineeringApplicationPorts` with the exact review admission
   and MethodRunBindings. `engineering_capability_catalog` reads the bound
   operation capabilities from the actual Engineering Service, intersects
   them with registered plugin handlers, and obtains check descriptors from
   `bound_review_check_capabilities` on that exact admission.
4. `RegisteredMethodPublication` compiles against that live catalog. It does
   not fill absent descriptors. Selection/adoption and Work start remain
   separate original-owner operations.

Engineering source now supports `SQLiteReviewBindings(...,
proposal_ref=None, phases=None)` and one-shot `bind_selection`. This can
provide the pre-Proposal review-request owner when its actual Service and
registered handler are assembled. It does not resolve the Apps lifecycle
gap: `product_runtime._method_unit_configuration` still requires
`proposal_ref` and nonempty `phases`, and it does not retain the returned
`ports.review_admission.bindings` as a post-Proposal bootstrap handle. The
current data-only product user configuration also requires an existing
`proposalRef` and phases. No caller found in Server source constructs
`OriginalRecordedUnitReviewQueries` or
`original_submission_author_unit_resolver`; those helpers appear only in
tests. The latter is specifically for a persisted acceptance Submission,
not a Proposal's author.

The actual input fields that the trusted Server/Execution receiver must
provide are:

- same original `SQLiteUoWFactory`, `EngineeringCommandAccess`, `WireScope`,
  `SQLiteMethodControl`, and same-authority `SQLiteBlobStore`;
- selected `LocalUnitOwner`, its original `UnitRecords`, and exact
  `UnitRunPermission` scope/authority;
- `invocation_resolver(context, plan, request, prompt_binding=...)` yielding
  the original `NativeReviewInvocation` with the exact frozen review prompt;
- `unit_query_factory(context, unit_ref, plan, request, purpose=...)` yielding
  `(original query invocation, input_digest)` accepted by
  `UnitRecords.resolve_unit_reference`;
- an author resolver that can establish a real source identity for the exact
  review subject. Actor attribution is not a UnitRef. The existing
  `original_submission_author_unit_resolver` handles only an exact persisted
  Submission, so it cannot supply a pre-execution Proposal author;
- for execution-backed submission/report conditions, the same original
  execution records and query producer needed for capture. Current assembly
  has optional ports for these but no first-case production caller was found.
- original Package/Approval/Change/Acceptance/report/dispatch owners for the
  remaining required operation descriptors, each with their real
  same-scope/factory guards.

Thus the check implementations and Work source are real mechanisms, but this
is not complete 2.6 source qualification or a production receiving path. The
candidate itself forbids publication/execution until pending owner contracts
are bound. Do not promote helper construction, test peers or an incomplete
capability catalog into product readiness.

## Source fingerprint for this audit

SHA-256 values identify the exact files read for this table; they are not a
registry receipt, test result, or full-source qualification:

| File | SHA-256 |
| --- | --- |
| `methods/incremental-engineering/candidates/2.6.0/method.yaml` | `fb07a49ee56245b124c3277b2a25f0d2e387aac66009e48fa4a04882d7fdc7d6` |
| `apps/server/src/ordessa_server/composition/product_runtime.py` | `88d5c111c854d8919bb34a51bca7599863d69e60eff91dc6bb2bff13807f6392` |
| `apps/server/src/ordessa_server/composition/engineering_method_unit_assembly.py` | `e7a567b5099258c5bde678410f314f552a2f74483b5996b695732a112100ee77` |
| `apps/server/src/ordessa_server/composition/engineering_review_assembly.py` | `9779f7e19732141a9b063cff0479cec86892e6c6e0e9b04972cb3777f98aa48c` |
| `apps/server/src/ordessa_server/composition/engineering_capability_catalog.py` | `a8ea6443e6bd9148a41d652629b3362cff5e97ae60cc1ebf923a1d20e4f64d19` |
| `apps/server/src/ordessa_server/composition/engineering_work_assembly.py` | `d82bb5b21fa0e2aedc51ac142bcec725d895e3aff2304f5ac9b324b1937c4e94` |
| `packages/engineering/src/ordessa_engineering/adapters/persistence/sqlite/review_bindings.py` | `a2b4cd08bd2df67f46eb361998828406a70a8ca8fd6190beac7dd2ab94be823c` |
| `packages/engineering/src/ordessa_engineering/adapters/method_work.py` | `77c5f09a62908981374408644d3a62a07943e12b6503c192ee622e9ca6576a76` |
| `packages/engineering/src/ordessa_engineering/application/assembly/review_sources.py` | `abb831aa681c43f4712de6e34b8e93c1acb98af17392d58c2cd239bc5c3a226c` |
| `packages/engineering/src/ordessa_engineering/application/orchestration/check_capabilities.py` | `a4e91f8fba4d8699d5bb3413561b5d27c6863daaa69b8beca9b9e61841397830` |
| `packages/engineering/src/ordessa_engineering/application/usecases/reviews/invariants.py` | `a30925ba7a7a6182a94d57e7321cdedef330fe5269b21d7cd1c2bcd53d5f2c55` |
| `packages/engineering/src/ordessa_engineering/application/orchestration/decision_checks.py` | `028467436842b772eca5b4d878be52ce226316ce6a2af84e894d0863a8755978` |
| `packages/engineering/src/ordessa_engineering/application/api/service.py` | `f7e25f90fdb5c56d24a81c4428dd22b3cf8579c2047cbd4a926db07fabcf6f56` |
| `packages/engineering/src/ordessa_engineering/adapters/persistence/sqlite/unit_review_bindings.py` | `56bf82a06cc537d75671fb7a7bc15b0de83a5a888b0ccc7c2b9b8c2540f9648f` |
| `packages/engineering/src/ordessa_engineering/adapters/unit_reviewer_authority.py` | `6d14b2a81191bc3e1853f0722f3f0173a69479ed0db0944af589559a43c470d4` |
| `packages/engineering/src/ordessa_engineering/application/orchestration/unit_review.py` | `162a31b7871654c400ec1f3b75b021484d6fef24a73da3a29b585436ae62fdc1` |
| `packages/engineering/src/ordessa_engineering/application/contracts/unit_review.py` | `bd2d42a3d5b4eb50b43f0bcfd27323cdf9460e330026e5373d60815fb8c0af1c` |
| `packages/engineering/src/ordessa_engineering/application/contracts/mixed_reviews.py` | `76993ed7cca9aef1485bfbc5dd1c9e72b481afcc4e71941ba22a124c2edba69b` |
| `apps/server/src/ordessa_server/composition/engineering.py` | `0e20854d41a16a0302fcba6e74d0a737fc78cfbbb140a7e9d5db082d81cbdac8` |
| `apps/server/src/ordessa_server/composition/engineering_method_unit_sources.py` | `f352f4d6812621333a9f7dab3ee913d43cfda2e59cb5c528de6f7ce302667d48` |
| `apps/server/src/ordessa_server/composition/engineering_method_management.py` | `ee6c28f6d0837c518dd137010410b98bcd5ba6cb9429eb0b443a899cd828a183` |
| `apps/server/src/ordessa_server/composition/product_user_configuration.py` | `05573f16170144a7d67b8406b0859d8612d0e03bbd08e709e2fe9140c0291dfc` |
| `apps/server/src/ordessa_server/composition/engineering_submission_assembly.py` | `eee7c70b2d2aaef0f1cb5b234a2169ad080841c041697b8ec8e240c4cad0e77b` |
| `packages/interfaces/system-access/bindings/src/ordessa_system_access_bindings/engineering_wire.py` | `59b32cc8e74a836020296dc5a4e38a125e83433b7b1a1d5b504099a1f4965699` |
