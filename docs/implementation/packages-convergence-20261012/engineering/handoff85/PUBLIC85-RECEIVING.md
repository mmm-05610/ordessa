# Engineering85 receiving and complete 2.6 owner map

This checkpoint supersedes the live Engineering84 package for the review-input
initialization seam. Original84 capture and wheel remain immutable. The
coordinator approved only the registry fact update in that old fourteen-path
freeze; the other thirteen paths are unchanged. The earlier entry85 audit and
its pending-resource receipts remain historical, unchanged.

## Exact fresh package

Engineering wheel SHA-256:
`ef7141a30cc186f31e343bd5a2a73b71edc0a9b42c2ac9349ec9ec54e337e89a`.
Its 266 Python/JSON payload files match current source, captured source, build
stage and private noneditable installation byte for byte. Source fingerprint:
`9be7ad2b882c2901bffd5076e076d5220d94c1c364dd6bbd3c3b152f2bb55ace`.
The original packaged registry is revision84, digest
`sha256:781474a34112becb8a8b871cfb5c9e54c1c758d8a6acaccfa6f76b6d3c9fd26f`.
Only two owner source hashes and the registry revision/digests changed;
operation definitions and foreign dependency facts did not.

Use this new artifact for the unbound API; the old wheel84 does not implement
it. Local artifact locations and detailed qualification receipts are provided
separately to the receiver and are excluded from publication.

## Original owner construction and lifecycle

```python
from ordessa_engineering.adapters.review_sources import SQLiteReviewBindings
from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
from ordessa_engineering.adapters.registry import load_registry
from ordessa_engineering.application.assembly import build_method_run_bindings

review_bindings = SQLiteReviewBindings(
    factory, method_control, scope=owner_scope,
    proposal_ref=None, phases=None,
)
source = SQLitePersistedMethodWorkSource(
    factory, method_control, blobs=blobs, review_bindings=review_bindings,
)
method_run_bindings = build_method_run_bindings(
    factory, method_control=method_control, work_condition_source=source,
    registry_loader=load_registry,
)
# After the actual original Proposal and phase inputs have been persisted:
review_bindings.bind_selection(
    actual_command_context, proposal_ref=actual_proposal_ref,
    phases=actual_nonempty_configured_phases,
)
```

The same factory, method control, scoped binding object and blobs must be
passed to the actual review admission and Service. Native records/query ports
are supplied to the Work source when required, using the selected original
runtime. Constructing the input reader is independent of its future subject.
Runtime reads remain unavailable until an exact subject is validated; failed
binding leaves it unbound, and competing binds cannot overwrite one another.
Selection initialization creates no permission, alternate Work state, or
latest-subject lookup. Original method, scope, closure and current admission
checks remain active.

Existing Server `method_unit_application_ports_factory(...)` directly forwards
these values to the original owners. The actual Product configuration/parser
still requires a pre-existing Proposal and phases, so Interfaces must admit
explicit trusted unbound initialization there, retain the exact
`ports.review_admission.bindings` handle and call its public `bind_selection`
after original Proposal creation. Callbacks come from trusted runtime
composition; user JSON remains data-only. The complete sequencing recipe is
the preserved `entry85/BOOTSTRAP-RECIPE.py`; it accepts original owner objects
and refs, and does not manufacture missing production sources.

## All nineteen requirements, checked together

The unchanged fixed candidate manifest SHA-256 is
`fb07a49ee56245b124c3277b2a25f0d2e387aac66009e48fa4a04882d7fdc7d6`.
Installed85 verifies all nineteen required kind/version/contract-digest values
against the exact descriptions selected by the real Service/check catalog
path. These are detached contract comparisons, not a bound production catalog,
method publication, reviewer role, execution permission or activation receipt.

Use the two complete source maps:
[fourteen operations](OPERATIONS-OWNER-TABLE.md) and
[five checks and Work](CHECKS-AND-WORK-OWNER-TABLE.md).

| Classification | Requirement group | Required next action |
| --- | --- | --- |
| Existing default owner graph | artifacts.create, artifacts.append_revision, proposals.create | Original schemas, UoW and current command access already exist. Method-bound materials and implementation baselines still require exact owner-provided facts. |
| Existing mechanism, production assembly required | reviews.request, reviews.record | Compose the original unbound reader and real same-authority admission/BlobStore. Request readiness is separate from response/trust readiness; missing sources do not advertise record. |
| Existing mechanism, production assembly required | notices.publish, approvals.prepare_intent/request/record_conversation, changes.apply, packages.freeze | Pass the original conversation/intent/evidence and review gates through `confirmation_options`/base ports. Human confirmation uses actual scoped source evidence; agent text or a Unit permission is not human consent. |
| Existing mechanism, production assembly required | submissions.record_report, acceptance.adopt | Supply the method's actual `report_phase_key`, same MethodRunBindings, original records/query, report and submission/acceptance guards. A report remains asserted data and pending review. |
| Existing canonical mechanism, distinct production binder required | executions.dispatch | Feed the existing trusted wire binder through `execution_dispatch_binder`, using the same Service and selected LocalUnitOwner/records/lease. Read/reconcile routes are not canonical dispatch. |
| Existing check mechanisms, exact source assembly required | claims.coverage, sources.integrity, schema.validate, submission.binding | Compose the original Mechanical and DeclaredInvariant sources on actual method/material/submission facts. Mechanical coverage does not prove semantic support. |
| Existing generic check mechanism, production fact producers missing in this case | decision.evaluate | Bind `GenericDecisionCheckSource(UnitReviewCheckSource(...))` to actual reviewer assignment/role, author/source evidence, native invocation, response and original query. A whole JEV source does not replace this source. |

No additional missing Engineering handler body was found among these nineteen
requirements. That statement does not mean the business fact producers exist
in the first-case production graph. Actual selected LocalUnitOwner and real
author/invocation/query/role/trust producer inputs are still absent from the
default case. The existing acceptance-author helper only resolves an exact
persisted Submission; it does not establish an initial human-authored
Proposal's Unit identity. Those missing production producers must be supplied
or explicitly designed by their original business/Execution owner, rather
than described as a lambda or filled with a test value. Method publication
also remains forbidden by the candidate's pending-binding status until the
owner contracts are actually satisfied.

## Qualification and limits

Source final focused11 passed. Fresh noneditable installed qualification passed
19 owner/Work/handoff cases plus two distinct original LocalUnit/SDK controlled
peer cases, zero skips and failures. Owner-origin checks found no source
leakage. Public object identity and original registry/source-fact verification
passed; all nineteen selected contract declarations match. Test business
authority/history/response fixtures remain explicitly synthetic and establish
no production reviewer role or human Grant. Dependencies remain the current
nightly environment and selected actual peer sources, not a full standalone
product bundle. There were no model, credential, real database, Git or service
actions in this checkpoint.

The public audit initially merged auxiliary owner descriptions and overwrote
the Service's selected package/report descriptions. Its two failing receipts
are retained. The audit was corrected to follow the actual bound Service
selection (only native dispatch adds its owner descriptor); product code,
candidate requirements and assertions were not relaxed to obtain the result.
The earlier entry85 broader-test timeout receipts also remain historical.

Actual first-case publication/adoption/Work, Pi/JEV, independent review,
acceptance and the full consumer bundle remain unqualified. This owner artifact
closes the input-reader initialization and source-integrity prerequisite; the
receiving group must verify its real registered catalog and production sources
as one complete assembly before activation.
