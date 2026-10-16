"""Declared `incremental.prepare-packages` steps, organised as business code.

Step semantics come from the released declaration, not from this module:

    admission: same_scope · exact_inputs · method_pin · review_complete ·
               review_passed · baseline_available
    check-package-admission (invoke)      -> no command: a guard over the formal
                                             review record and the Work's pins
    prepare-spec-kit-package (invoke)     -> the existing dispatch capability
                                             (Unit generation), never a review run

The first step consumes the *already reviewed change* (the review contract named
by the declaration), never a `package_ref`: the package does not exist yet. The
package ref is produced here and only then consumed by `implement-package`.
"""

from dataclasses import asdict

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.provenance_codec import decode_source
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
from ordessa_engineering.domain.artifacts.method_codec import decode_method_ref
from ordessa_engineering.domain.changes.models import SourceChange
from ordessa_engineering.domain.reviews.targets import SourceTargetRef
from ordessa_engineering.domain.common.mechanisms.codec import decode_scope

ADMISSION_KINDS = ("same_scope", "exact_inputs", "method_pin", "review_complete",
                   "review_passed", "baseline_available")


def verify_reviewed_change(uow, context, *, proposal_ref, review_ref, method_ref,
                           baseline, candidate):
    """Read and strictly bind the exact current proposal, sources and review."""
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from ordessa_engineering.domain.changes.models import SourceChange
    from ordessa_engineering.domain.reviews.targets import SourceTargetRef
    try:
        proposal = uow.proposals.get_proposal(proposal_ref,
                                             budget=uow.proposals.validated_budget())
        control = uow.proposals.get_control(proposal_ref)
        current = uow.proposals.get_change(proposal.change_id)
        controlled = uow.reviews.get_review(review_ref)
    except ApplicationError:
        raise ApplicationError("WORK_ACTION_ADMISSION_EXACT_INPUTS_FAILED") from None
    record = getattr(controlled, "record", None)
    review_control = getattr(controlled, "control", None)
    source = getattr(proposal, "source_change", None)
    if baseline is None and candidate is None and type(source) is SourceChange:
        baseline, candidate = source.baseline, source.candidate
    if (proposal.ref != proposal_ref or proposal.scope != context.scope
            or proposal.schema_version != 2 or type(source) is not SourceChange
            or control.disposition != "available"
            or proposal_ref.change_id != current.change_id
            or proposal_ref.proposal_id not in current.proposal_ids
            or proposal.method_ref != method_ref
            or source.baseline != baseline or source.candidate != candidate
            or review_ref not in source.review_refs
            or record is None
            or getattr(record, "ref", None) != review_ref
            or getattr(review_control, "state", None) != "active"
            or getattr(record, "complete", None) is not True
            or getattr(record, "verdict", None) != "pass"):
        raise ApplicationError("WORK_ACTION_ADMISSION_EXACT_INPUTS_FAILED")
    requirement = getattr(getattr(record, "plan", None), "requirement", None)
    if (getattr(requirement, "schema_version", None) != 2
            or getattr(requirement, "scope", None) != context.scope
            or getattr(requirement, "method_ref", None) != method_ref
            or getattr(requirement, "method_resource_refs", None) != source.method_resource_refs):
        raise ApplicationError("WORK_ACTION_ADMISSION_METHOD_PIN_FAILED")
    targets = getattr(getattr(requirement, "expected_targets", None), "targets", ())
    source_targets = tuple(item.ref for item in targets
                           if type(getattr(item, "ref", None)) is SourceTargetRef)
    expected = (source.baseline.content_identity, source.candidate.content_identity)
    actual = tuple(item.source_ref.content_identity for item in source_targets)
    if (len(source_targets) != len(targets) or len(actual) != 2
            or set(actual) != set(expected)):
        raise ApplicationError("WORK_ACTION_ADMISSION_EXACT_INPUTS_FAILED")
    return proposal, controlled, record


class DeclaredPreparePackagesSteps:
    ACTION_ID = "incremental.prepare-packages"
    STEP_ORDER = ("check-package-admission", "prepare-spec-kit-package")

    def __init__(self, factory, *, method_guard, review_admission=None):
        self.factory = factory
        self.methods = method_guard
        self.review_admission = review_admission

    def check_package_admission(self, context, binding, *, inputs):
        """Check the declared admission of this action against real records.

        Every condition is read from the formal review and the Work's own pins:
        a review that is incomplete, failed, or about a different method/scope
        refuses here. Nothing is inferred from a name, a template or a caller
        assertion.
        """
        inputs = inputs or {}
        value = inputs.get("review")
        if value is None or self.review_admission is None or self.methods is None:
            raise ApplicationError("WORK_ACTION_INPUT_MISSING")
        try:
            review_ref = decode_review_ref(value)
            baseline = decode_source(inputs.get("baseline"))
            candidate = decode_source(inputs.get("candidate"))
            method_ref = decode_method_ref(inputs.get("method"))
            input_scope = decode_scope(inputs.get("scope"))
        except Exception:
            # A malformed or forged review reference is refused as input, never
            # carried further as if it named a real review.
            raise ApplicationError("WORK_ACTION_INPUT_INVALID") from None
        if review_ref is None:
            raise ApplicationError("WORK_ACTION_INPUT_INVALID")
        if input_scope != context.scope:
            raise ApplicationError("WORK_ACTION_ADMISSION_SAME_SCOPE_FAILED")
        realm, project = getattr(review_ref, "realm_id", None), getattr(review_ref, "project_id", None)
        if (realm, project) != (context.scope.realm_id, context.scope.project_id):
            raise ApplicationError("WORK_ACTION_ADMISSION_SAME_SCOPE_FAILED")
        proposals = [item.ref for item in binding.associations
                     if getattr(item, "kind", None) == "proposal"]
        if len(proposals) != 1:
            raise ApplicationError("WORK_ACTION_ADMISSION_EXACT_INPUTS_FAILED")
        if method_ref != binding.method_ref:
            raise ApplicationError("WORK_ACTION_ADMISSION_METHOD_PIN_FAILED")
        with self.factory.begin(context.scope, "read") as uow:
            proposal, controlled, record = verify_reviewed_change(
                uow, context, proposal_ref=proposals[0], review_ref=review_ref,
                method_ref=method_ref, baseline=baseline, candidate=candidate)
        from ordessa_engineering.domain.reviews.models import CurrentReviewTrust
        with self.methods.guard(context, method_ref), \
                self.review_admission.guard_plan(context, record.plan), \
                self.review_admission.guard_trust(context, (record,)) as trusted:
            if (type(trusted) is not tuple or len(trusted) != 1
                    or type(trusted[0]) is not CurrentReviewTrust
                    or trusted[0].review_ref != review_ref
                    or trusted[0].verifier_id != record.reviewer_evidence.verifier_id
                    or trusted[0].trust_version != record.reviewer_evidence.trust_version):
                raise ApplicationError("UNTRUSTED_REVIEWER")
        verdict = record.verdict
        # The declared step output is `qualified_inputs`: exactly what this
        # guard admitted, ready for the draft step to consume.
        return {"qualified_inputs": {
                    "baseline": dict((inputs or {}).get("baseline") or {}),
                    "candidate": dict((inputs or {}).get("candidate") or {}),
                    "scope": {"realm_id": context.scope.realm_id,
                              "project_id": context.scope.project_id},
                    "review": dict((inputs or {}).get("review") or {}),
                    "method": dict((inputs or {}).get("method") or {})},
                "admitted": True,
                "admission_checked": list(ADMISSION_KINDS),
                "review_ref": {"review_id": review_ref.review_id,
                               "realm_id": review_ref.realm_id,
                               "project_id": review_ref.project_id},
                "verdict": verdict,
                "plan_digest": {"algorithm": getattr(record.plan.plan_digest, "algorithm", "sha256"),
                                "hex": record.plan.plan_digest.hex},
                "method_resource_refs": [asdict(item)
                                         for item in proposal.source_change.method_resource_refs],
                "method_ref": {"method_id": binding.method_ref.method_id,
                               "release_version": binding.method_ref.release_version,
                               "snapshot_digest": binding.method_ref.snapshot_digest.hex}}

    def validate_generated_package(self, context, binding, payload):
        """Reject generated output whose provenance differs from admitted inputs."""
        if self.review_admission is None or self.methods is None:
            raise ApplicationError("WORK_ACTION_ADMISSION_AUTHORITY_UNAVAILABLE")
        try:
            proposal_refs = [item.ref for item in binding.associations
                             if getattr(item, "kind", None) == "proposal"]
            proposal_ref = proposal_refs[0] if len(proposal_refs) == 1 else None
            from ordessa_engineering.domain.packages.models import PreparedPackagePayload
            if type(payload) is PreparedPackagePayload:
                baseline, candidate = payload.baseline, payload.candidate
                change_ref, review_refs = payload.change_ref, payload.review_refs
                method_ref, resource_refs = payload.method_ref, payload.method_resource_refs
            else:
                baseline = decode_source(payload["baseline"])
                candidate = decode_source(payload["candidate"])
                change_ref = decode_proposal_ref(payload["change_ref"])
                review_refs = tuple(decode_review_ref(item) for item in payload["review_refs"])
                method_ref = decode_method_ref(payload["method_ref"])
                from ordessa_engineering.domain.artifacts.method_codec import decode_exact_method_resource
                resource_refs = tuple(decode_exact_method_resource(item)
                                      for item in payload["method_resource_refs"])
        except Exception:
            raise ApplicationError("WORK_ACTION_GENERATION_OUTPUT_PROVENANCE_INVALID") from None
        if (proposal_ref is None or change_ref != proposal_ref or len(review_refs) != 1
                or method_ref != binding.method_ref):
            raise ApplicationError("WORK_ACTION_GENERATION_OUTPUT_PROVENANCE_INVALID")
        with self.factory.begin(context.scope, "read") as uow:
            proposal, _, record = verify_reviewed_change(
                uow, context, proposal_ref=proposal_ref, review_ref=review_refs[0],
                method_ref=method_ref, baseline=baseline, candidate=candidate)
        if (tuple(review_refs) != proposal.source_change.review_refs
                or tuple(resource_refs) != proposal.source_change.method_resource_refs):
            raise ApplicationError("WORK_ACTION_GENERATION_OUTPUT_PROVENANCE_INVALID")
        with self.methods.guard(context, method_ref), \
                self.review_admission.guard_plan(context, record.plan), \
                self.review_admission.guard_trust(context, (record,)):
            return True

    def verify_generated_registration(self, uow, context, binding, record,
                                      held_review, held_trust):
        """Re-verify every admitted fact in the transaction that registers it.

        The generation step validated the produced package, archived its exact
        document bytes and only then called back to register. This runs inside
        the *same* UoW that creates the package row (under the caller's held
        method/plan/trust guards), so it re-reads every owner here: the Work
        head revision and its complete binding, the proposal/change and its
        control, the review record and its control, the method pin and the exact
        method resource pins.

        The caller also hands over the facts those held guards were admitted on,
        in their existing types: the `ReviewRecord` and the single
        `CurrentReviewTrust` the trust guard yielded. The record and its plan
        re-read here must be exactly that record, the review must still be
        active, and its reference, verifier and trust version must still agree
        with the held trust. A review re-recorded under the same reference, a
        review withdrawn or voided, a proposal control moved, a Work revision
        advanced, or a method disabled or re-pinned between the earlier
        validation and this COMMIT refuses here instead of committing a row that
        the admission no longer supports. The archived document bytes and the
        original native receipt are content-addressed and immutable; they are
        re-read under the same held guards immediately before this TX rather
        than through a nested blob IO in the business transaction.
        """
        if self.review_admission is None or self.methods is None:
            raise ApplicationError("WORK_ACTION_ADMISSION_AUTHORITY_UNAVAILABLE")
        from ordessa_engineering.application.contracts.work_context import (
            WORK_CONTEXT_KIND, decode_work_binding)
        from ordessa_engineering.domain.packages.models import PreparedPackagePayload
        from ordessa_engineering.domain.reviews.models import (
            CurrentReviewTrust, ReviewRecord)
        # The held facts the caller's guards were admitted on, unchanged and in
        # their existing types. A caller that cannot state them cannot register.
        if (type(held_review) is not ReviewRecord or type(held_trust) is not tuple
                or len(held_trust) != 1 or type(held_trust[0]) is not CurrentReviewTrust):
            raise ApplicationError("WORK_ACTION_GENERATION_ADMISSION_UNAVAILABLE")
        held = held_trust[0]
        if (held.review_ref != held_review.ref
                or held.verifier_id != held_review.reviewer_evidence.verifier_id
                or held.trust_version != held_review.reviewer_evidence.trust_version):
            raise ApplicationError("UNTRUSTED_REVIEWER")
        payload = getattr(record, "payload", None)
        if type(payload) is not PreparedPackagePayload or len(payload.review_refs) != 1:
            raise ApplicationError("WORK_ACTION_GENERATION_OUTPUT_PROVENANCE_INVALID")
        change_ref, review_ref = payload.change_ref, payload.review_refs[0]
        if review_ref != held_review.ref:
            raise ApplicationError("WORK_ACTION_GENERATION_REVIEW_CHANGED")
        # The Work head revision and the complete binding, from the original
        # owner, read inside this registering transaction.
        head = uow.workflow.head_ref(WORK_CONTEXT_KIND, binding.stable_id)
        if (head is None or head.revision != binding.revision
                or decode_work_binding(uow.workflow.read(head)) != binding):
            raise ApplicationError("WORK_ACTION_GENERATION_WORK_CHANGED")
        # The one proposal association that names this exact reviewed change.
        proposals = [item.ref for item in binding.associations
                     if getattr(item, "kind", None) == "proposal"]
        if len(proposals) != 1 or proposals[0] != change_ref:
            raise ApplicationError("WORK_ACTION_GENERATION_CHANGE_MISMATCH")
        # Proposal/change and its control, the review record and its control,
        # the method pin and the exact method resource pins, all re-read here.
        proposal, controlled, current = verify_reviewed_change(
            uow, context, proposal_ref=change_ref, review_ref=review_ref,
            method_ref=payload.method_ref, baseline=payload.baseline,
            candidate=payload.candidate)
        # The record and its plan re-read in this transaction must be the very
        # ones the held guards admitted, the review must still be active, and
        # the held trust must still describe this record. `verify_reviewed_change`
        # already binds the reference, the scope and the active control; this
        # compares the whole record, so a record re-recorded under the same
        # reference is refused too.
        if (current != held_review or current.plan != held_review.plan
                or getattr(getattr(controlled, "control", None), "state", None) != "active"):
            raise ApplicationError("WORK_ACTION_GENERATION_REVIEW_CHANGED")
        if (held.review_ref != current.ref
                or held.verifier_id != current.reviewer_evidence.verifier_id
                or held.trust_version != current.reviewer_evidence.trust_version):
            raise ApplicationError("UNTRUSTED_REVIEWER")
        if tuple(payload.method_resource_refs) != proposal.source_change.method_resource_refs:
            raise ApplicationError("WORK_ACTION_GENERATION_METHOD_RESOURCES_INVALID")
        return True


__all__ = ["DeclaredPreparePackagesSteps", "ADMISSION_KINDS", "verify_reviewed_change"]
