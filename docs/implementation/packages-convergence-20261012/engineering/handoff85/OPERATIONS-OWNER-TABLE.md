# Candidate 2.6 operation-owner wiring audit

Read-only source audit of the 14 `kind: operation` entries in
`methods/incremental-engineering/candidates/2.6.0/method.yaml` (`requires`).
This records source presence and conditional composition paths, not a fresh
runtime/catalog call, publication, capability grant, or test qualification.

## Registration path and status interpretation

The method lists 14 operation descriptors: `engineering.artifacts.create`,
`engineering.artifacts.append_revision`, `engineering.proposals.create`,
`engineering.reviews.request`, `engineering.reviews.record`,
`engineering.notices.publish`, `engineering.approvals.prepare_intent`,
`engineering.approvals.request`, `engineering.approvals.record_conversation`,
`engineering.changes.apply`, `engineering.acceptance.adopt`,
`engineering.packages.freeze`, `engineering.executions.dispatch`, and
`engineering.submissions.record_report`.

`EngineeringService.operation_capabilities()` exposes detached descriptions.
`EngineeringService.bound_operation_capabilities()` selects descriptions only
when the corresponding original owner is attached and has the expected
factory/access/source guards. `EngineeringWireBinding.methods()` creates
callable methods from the wire command set; `RegisteredEngineeringCommandCatalog`
intersects those callables with the Service's bound descriptions. Finally,
`RegisteredMethodPublication.publish()` compiles against
`RegisteredHostCapabilityCatalog.read_current()`. A declaration in method
YAML cannot register its own descriptor. Calls still pass the current
`EngineeringCommandAccess` requirement and the relevant owner guards; a
catalog descriptor is not a grant.

Sources: `packages/engineering/src/ordessa_engineering/application/api/service.py`
(`operation_capabilities`, `bound_operation_capabilities`, handler map and
input schemas); `packages/interfaces/system-access/bindings/src/ordessa_system_access_bindings/engineering_wire.py`
(`EngineeringApplicationPorts`, `EngineeringWireBinding`);
`apps/server/src/ordessa_server/composition/engineering_capability_catalog.py`;
`apps/server/src/ordessa_server/composition/engineering_method_management.py`.

## Operation owners

“Default binding” below means the Service owner graph constructed without a
custom `application_ports_factory`; it does not mean a command was invoked or
authorized. “Composition available” means a source builder exists, but this
audit found no first-party product configuration selecting the complete
2.6.0 graph by default. Test-only wiring is not counted as a production
selection.

| Required operation | Actual owner and input/evidence source | Access and bound-source condition | Current wiring finding |
| --- | --- | --- | --- |
| `engineering.artifacts.create` | `ArtifactUseCases.create`; owner schema accepts artifact kind and optional initial material payload/provenance. Material validation resolves through original Engineering repositories/blob/source owners. | Current caller must hold this operation through the selected `EngineeringCommandAccess`; bound descriptor requires the Service's same-factory `ArtifactUseCases`. | Present in default Service and callable wire set. Basic owner path is already attachable; it creates no method, Grant, or source authority by itself. |
| `engineering.artifacts.append_revision` | `ArtifactUseCases.append_revision`; artifact id/version, parent refs and payload are validated against the original artifact/material repositories. | Same `ArtifactUseCases` instance as create, original access and UoW. | Present in default Service and callable wire set. No extra product owner required for descriptor binding. |
| `engineering.proposals.create` | `ProposalUseCases.create`; decoded draft, expected version, exact method ref, artifacts and requirement templates are validated against original repositories/closure. | Same-factory/access `ProposalUseCases`; each command still needs its own current access grant. | Present in default Service and callable wire set. Existing source owner is available; proposal writes that require an implementation baseline remain subject to the original baseline refusal. |
| `engineering.reviews.request` | `ReviewUseCases.request` -> `EngineeringReviewAdmission`; exact plan/phase/Proposal inputs come through configured `SQLiteReviewBindings`; reviewer/check source is an original Unit, human, or JEV owner. | `bound_operation_capabilities` requires an actual `ReviewUseCases` with same factory/access, real `EngineeringReviewAdmission`, method-control and binding owners, and plan/response/trust methods. | Conditional composition exists in `engineering_review_assembly.py` and `engineering_method_unit_assembly.py`. `product_runtime.py` only takes this path when trusted PI selection and `method_unit_options` are supplied. The current builder expects explicit `proposal_ref` and `phases`; the new unbound lifecycle is not yet called by that product assembler. No default selected production review source was found. |
| `engineering.reviews.record` | `ReviewUseCases.record_command`; exact review id/request version/fence and raw response bytes, with `EngineeringReviewAdmission` validating the full original plan and reviewer evidence. | Requires the review request owner plus the same-authority original BlobStore and response/trust source; current operation permission is checked on every call. | Same conditional review assembly as `reviews.request`; no default reviewer/response source selected. A response DTO or completed request alone is not sufficient. |
| `engineering.notices.publish` | `ApprovalUseCases.publish_notice`; original Notice and exact target/artifact refs. | Bound only with the same original `ApprovalUseCases` plus `ConversationAdmission` (`guard_intent`, `guard_evidence`) and the same live review admission/source gates. | Handler exists in default Service, but descriptor is conditional. `assemble_engineering_admission` can create the original intent router/attestor; product method-unit assembly supplies it only through explicit `confirmation_options`. No default conversation confirmation source/configuration was found. |
| `engineering.approvals.prepare_intent` | `ApprovalUseCases.prepare_intent`; typed AuthorizationIntent and original targets/Notice/required review requirements. | Same approval and review owner conditions as notice publication; current operation access and full intent/evidence/review guards remain required. | Handler exists; no default selected conversation/review gate. The owner can be composed through the explicit confirmation path, but no production selection of it was found. |
| `engineering.approvals.request` | `ApprovalUseCases.request`; exact persisted intent id/digest and original challenge/control state. | Same original ApprovalUseCases/ConversationAdmission and review gates. | Handler exists; conditional source composition only. No configured production conversation source was found. |
| `engineering.approvals.record_conversation` | `ApprovalUseCases.record_conversation`; challenge id, nonce, expected version and evidence decoded/verified by the selected conversation attestor. | Same source/gates; caller still needs the actual operation capability. | Handler exists; `MainAgentChatConfirmation` is an available original owner wrapper, but no default conversation locator/attestor binding was found. |
| `engineering.changes.apply` | `ChangeApplyUseCases.apply`; original ChangeSet/plan, exact Proposal/material refs, notice/intent/grant, current review set and target versions. | Bound only when ChangeApplyUseCases shares the ApprovalUseCases' exact conversation/review admission and same factory/access. | Handler exists; it is conditionally bound by the same explicit confirmation + review source composition. No default full action/review graph found. |
| `engineering.acceptance.adopt` | `AcceptanceUseCases.adopt`; exact SubmissionRef, ApprovalRef, control version and target/version expectations. Original `SubmissionSourcePort.guard_submission` validates stored report/Submission/package/MethodRun/dispatch facts; acceptance admission validates the original intent, Grant and review gates. | Requires same approval/review owners, original `guard_intent`, and actual selected `submission_source.guard_submission`. | Conditional source exists through `attach_method_unit_submission_ports()` when `report_phase_key` is provided. That path requires same MethodRunBindings, original UnitRecords/query factory, BlobStore, and report source. `method_unit_options` makes `report_phase_key` optional, so the operation is not automatically bound. It must not be advertised without this closure. |
| `engineering.packages.freeze` | `ImplementationUseCases.freeze_package`; exact package record, original implementation grant/intent/evidence, baselines, file/blob manifest and current review gates. | Bound when the Service's package owner shares the same ApprovalUseCases with valid conversation and review guards. | Handler exists; its source mechanism is present but conditional on the complete approval/review composition. It refuses when ImplementationGrant authority is unavailable; a Package record itself is not a Grant. |
| `engineering.executions.dispatch` | Canonical `ImplementationDispatch` through `bind_execution_dispatch`; original package/run resolver, approval/review/control/source guards, selected LocalUnitOwner, UnitRecords/query identity and effect-write handoff. | The Service advertises it only with a same-factory/access dispatch owner and callable `execute`; the wire invokes a separately supplied `execution_dispatch_binder`. Caller also needs the canonical dispatch permission and effect lease. | Original binder exists in `engineering_native_dispatch_assembly.py`, but `method_unit_application_ports_factory` does not install it itself. A trusted `base_ports_factory` can return `EngineeringApplicationPorts.execution_dispatch_binder`; no first-party default caller doing so was found. `engineering_dispatch.py`'s reconcile/read routes are not the canonical dispatch owner. |
| `engineering.submissions.record_report` | `SubmissionUseCases.record_report`; original execution capture/query, raw bytes from same-authority BlobStore, frozen method report schema/content, current package Grant/review gates and original Submission UoW. | Requires method-bound `report_source.guard_report`, same MethodRunBindings, same BlobStore/records, and query factory; Service only adds this descriptor after all source checks. | `attach_method_unit_submission_ports()` creates the source when trusted product composition sets `report_phase_key`; the report adapter and original Unit query/read mechanisms exist. The product option is optional and no default 2.6 report binding was found. Report submission is pending review, not acceptance. |

## Classification and concrete receiver requests

1. **Already usable operation owners:** artifact create/append and Proposal
   create are constructed by the default Service and have original command
   schemas, UoW and access checks. Their descriptors can be present without
   the higher-level method graph.
2. **Original mechanism exists; selected production owner graph is still
   conditional:** review request/record, notice/approval, change application,
   package freeze, adoption and report. The relevant public builders and
   original guards exist. A production composition must select the same actual
   Proposal/phase, reviewer/Unit or human source, confirmation/evidence source,
   MethodRun bindings, report capture/query and submission source. Existing
   tests and builder APIs do not establish that a default product runtime has
   those selections.
3. **Dispatch needs a distinct production glue step:** the canonical owner and
   Engineering binder exist, and the wire has the `execution_dispatch_binder`
   seam. The current method-unit factory can accept a `base_ports_factory`, but
   does not itself produce or select this binder. A trusted product owner must
   bind the same live Unit/Records/access/effect-handoff source and feed the
   binder through that seam; the old reconcile route is not a substitute.
4. **No publication permission follows from any row:** command descriptors
   describe operations; `EngineeringCommandAccess` still checks each caller's
   current grants. `RegisteredMethodPublication` also requires all exact
   descriptor digests to be in the current catalog. This report did not call
   that catalog or publish the candidate.

Receiver request for Server/Interfaces composition: select and pass the
explicit unbound `SQLiteReviewBindings`, then call its one-time
`bind_selection(context, proposal_ref=..., phases=...)` from the trusted
selection lifecycle before review/work invocation. Preserve same factory,
MethodControl, Scope, UnitRecords, access and review/approval owners throughout.
Complete the actual reviewer, conversation, submission/report and canonical
dispatch factories in the selected product graph; pass dispatch through the
existing `execution_dispatch_binder` field. Do not advertise descriptors from
method requirements, test catalogs, or DTO fields alone.

No tests, build, install, publication, capability query, or live product run was
performed for this audit. The classifications above are source findings, not
runtime receipts.
