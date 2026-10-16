"""Declared `incremental.review-change` steps, organised as application business code.

The Engineering Service owns the ports and delegates here; the step semantics of
the released declaration live in this module, not in the Service. Each step
delegates to one existing command on the existing command journal. The native
review run is the composition-supplied ``review_run`` port (the existing
``DecisionReviewerSource`` in production), because that owner lives above the
Engineering Service; nothing here creates a Unit, a second journal or an engine.
"""

import hashlib
from contextlib import contextmanager
from dataclasses import asdict

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import (
    WORK_CONTEXT_KIND, decode_work_binding,
)
from ordessa_engineering.domain.artifacts.provenance_codec import decode_source
from ordessa_engineering.domain.reviews.codec import encode_plan
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from ordessa_engineering.domain.reviews.models import CurrentReviewTrust
from ordessa_engineering.domain.reviews.targets import SourceTargetRef
from ordessa_engineering.domain.changes.models import SourceChange
from ordessa_infrastructure.encoding import decode_json


class DeclaredReviewChangeSteps:
    """The three released steps of `incremental.review-change`.

    compare  (invoke, jev-review-explicit-change)      -> review request + native run
    record   (record, record-explicit-review-result)   -> engineering.reviews.record
    register (emit,   emit-explicitly-registered-change) -> proposals.associate_review
    """

    ACTION_ID = "incremental.review-change"
    STEP_ORDER = ("jev-review-explicit-change", "record-explicit-review-result",
                  "emit-explicitly-registered-change")

    def __init__(self, factory, *, method_guard, plan_factory, blobs,
                 dispatch, review_run=None, review_admission=None):
        self.factory = factory
        self.methods = method_guard
        self.plan_factory = plan_factory
        self.blobs = blobs
        self._dispatch = dispatch
        self.review_run = review_run
        self.review_admission = review_admission

    @property
    def runnable(self):
        """Both halves the declared steps need must be composed."""
        return self.plan_factory is not None and self.review_run is not None

    @staticmethod
    def _completed(result):
        """A delegated command that did not complete is never reported as done."""
        status = getattr(result, "status", None)
        if status != "completed":
            error = ApplicationError("WORK_ACTION_STEP_REJECTED")
            error.step_status = status
            error.business_code = (getattr(result, "result", None) or {}).get("code") \
                if isinstance(getattr(result, "result", None), dict) else None
            raise error
        return getattr(result, "result", None)

    @staticmethod
    def review_id(work_id, revision, step_id, request_id):
        """Deterministic review id for this Work revision and parent request."""
        basis = "-".join((str(work_id), DeclaredReviewChangeSteps.ACTION_ID,
                          "r%s" % revision, str(step_id), str(request_id)))
        if len(basis) <= 512:
            return basis
        return "review-" + hashlib.sha256(basis.encode()).hexdigest()

    def plan_for(self, context, binding, *, review_id, inputs):
        """Build the plan this Work pins, or refuse.

        The sources may be supplied by the caller for this request (resolved to
        exact references here, not required to be pre-bound to the Work), but the
        plan must still be the released plan for this Work's exact scope, method
        and pinned sources: a plan covering different material is refused.
        """
        if self.plan_factory is None:
            raise ApplicationError("WORK_ACTION_STEP_ASSEMBLY_MISSING")
        try:
            baseline = decode_source((inputs or {}).get("baseline"))
            candidate = decode_source((inputs or {}).get("candidate"))
        except Exception:
            raise ApplicationError("WORK_ACTION_INPUT_INVALID") from None
        if baseline is None or candidate is None:
            raise ApplicationError("WORK_ACTION_INPUT_MISSING")
        plan = self.plan_factory(context, binding, review_id=review_id,
                                 baseline=baseline, candidate=candidate)
        requirement = getattr(plan, "requirement", None)
        if (getattr(requirement, "method_ref", None) != binding.method_ref
                or getattr(requirement, "scope", None) != context.scope):
            raise ApplicationError("WORK_ACTION_PLAN_SUBJECT_MISMATCH")
        targets = getattr(getattr(requirement, "expected_targets", None), "targets", None)
        if type(targets) is not tuple or not targets:
            raise ApplicationError("WORK_ACTION_PLAN_SUBJECT_MISMATCH")
        plan_sources = {getattr(getattr(item, "ref", None), "identifier", None)
                        for item in targets}
        # Sources this Work already pins must be covered by the plan; a caller
        # reference is bound to this request by the plan itself.
        bound_sources = {association.ref.identifier for association in binding.associations
                         if association.kind == "artifact"}
        if bound_sources - plan_sources:
            raise ApplicationError("WORK_ACTION_PLAN_SOURCE_MISMATCH")
        return plan

    async def run_declared_step(self, step_name, context, binding, *, step_id,
                                parent_request_id, payload):
        """Run one declared review-change step from the chain runner's payload."""
        if step_name == "jev-review-explicit-change":
            return await self.compare(context, binding, step_id=step_id,
                                      request_id=parent_request_id, inputs=payload)
        if step_name == "record-explicit-review-result":
            return await self.record(context, payload.get("review"))
        if step_name == "emit-explicitly-registered-change":
            return await self.register(context, binding, payload.get("review"))
        raise ApplicationError("WORK_ACTION_STEP_UNIMPLEMENTED")

    async def compare(self, context, binding, *, step_id, request_id, inputs):
        """`compare`: request the review, run it, hand back its exact contract."""
        if self.review_run is None:
            raise ApplicationError("WORK_ACTION_STEP_ASSEMBLY_MISSING")
        review_id = self.review_id(binding.work_id, binding.revision, step_id, request_id)
        plan = self.plan_for(context, binding, review_id=review_id, inputs=inputs)
        self._completed(await self._dispatch("engineering.reviews.request",
                                             {"plan": decode_json(encode_plan(plan))}, context))
        with self.factory.begin(context.scope, "read") as uow:
            request = uow.reviews.get_request(review_id)
        if request is None:
            raise ApplicationError("WORK_ACTION_REQUEST_NOT_PERSISTED")
        raw_ref = await self.review_run(context, plan, request)
        raw = self.blobs.read_verified(raw_ref)
        receipt = decode_json(raw)
        if (type(receipt) is not dict
                or receipt.get("request_version") != request.version
                or receipt.get("fence") != request.fence):
            # The run must be the run of this request, never a foreign raw result.
            raise ApplicationError("WORK_ACTION_RUN_REQUEST_MISMATCH")
        return {"review_id": review_id,
                "plan_digest": {"algorithm": "sha256", "hex": plan.plan_digest.hex},
                "request_version": request.version, "fence": request.fence,
                "raw_response_utf8": raw.decode("utf-8"), "receipt": receipt}

    async def record(self, context, contract):
        """`record`: the verdict is the business result, and it is not a grant."""
        required = ("review_id", "request_version", "fence", "raw_response_utf8")
        if type(contract) is not dict or any(name not in contract for name in required):
            raise ApplicationError("WORK_ACTION_STEP_INPUT_MISSING")
        with self.factory.begin(context.scope, "read") as uow:
            request = uow.reviews.get_request(contract["review_id"])
        if request is None or (contract["request_version"] != request.version
                               or contract["fence"] != request.fence):
            raise ApplicationError("WORK_ACTION_REQUEST_STALE")
        receipt = decode_json(contract["raw_response_utf8"].encode("utf-8"))
        if (type(receipt) is not dict or receipt.get("request_version") != request.version
                or receipt.get("fence") != request.fence):
            # A caller-supplied raw result is never accepted as this run's result.
            raise ApplicationError("WORK_ACTION_RUN_REQUEST_MISMATCH")
        result = self._completed(await self._dispatch("engineering.reviews.record", {
            "review_id": contract["review_id"],
            "request_version": contract["request_version"],
            "fence": contract["fence"],
            "raw_response_utf8": contract["raw_response_utf8"]}, context))
        if type(result) is not dict:
            raise ApplicationError("WORK_ACTION_STEP_RESULT_INVALID")
        return {"verdict": result.get("verdict"), "review_ref": result.get("review_ref")}

    @contextmanager
    def guard_failed_registration(self, context, binding, record_result, *,
                                  compare_result, compare_step_id, parent_request_id):
        """Bind an explicit persisted fail to this invocation, never infer one.

        The caller retains these original plan/trust guards through parent
        completion, after the child admission has restored the parent lease.
        The returned validator rechecks the same records in the completing TX.
        No historical operation is reconciled and no successor is created.
        """
        if type(record_result) is not dict or record_result.get('verdict') != 'fail':
            yield None
            return
        if self.review_admission is None or type(compare_result) is not dict:
            raise ApplicationError('WORK_ACTION_REVIEW_RESULT_UNCONFIRMED')
        try:
            review_ref = decode_review_ref(record_result['review_ref'])
            review_id = self.review_id(binding.work_id, binding.revision,
                                       compare_step_id, parent_request_id)
            associations = tuple(item.ref for item in binding.associations
                                 if item.kind == 'proposal')
            if (len(associations) != 1 or review_ref.review_id != review_id
                    or (review_ref.realm_id, review_ref.project_id) !=
                       (context.scope.realm_id, context.scope.project_id)
                    or compare_result.get('review_id') != review_id):
                raise ValueError()
            with self.factory.begin(context.scope, 'read') as uow:
                controlled = uow.reviews.get_review(review_ref)
                proposal = uow.proposals.get_proposal(associations[0])
                change = uow.proposals.get_change(proposal.change_id)
            record = controlled.record
        except (KeyError, TypeError, ValueError):
            raise ApplicationError('WORK_ACTION_REVIEW_RESULT_UNCONFIRMED') from None

        def validate(uow):
            head = uow.workflow.head_ref(WORK_CONTEXT_KIND, binding.stable_id)
            if (head is None or head.revision != binding.revision
                    or decode_work_binding(uow.workflow.read(head)) != binding):
                raise ApplicationError('WORK_ACTION_REVIEW_RESULT_UNCONFIRMED')
            current = uow.reviews.get_review(review_ref)
            request = uow.reviews.get_request(review_id)
            parent = uow.proposals.get_proposal(associations[0])
            parent_control = uow.proposals.get_control(associations[0])
            latest = uow.proposals.get_change(parent.change_id)
            requirement = record.plan.requirement
            source = parent.source_change
            targets = tuple(t.ref for t in requirement.expected_targets.targets
                            if type(t.ref) is SourceTargetRef)
            if (current != controlled or current.control.state != 'active'
                    or record.ref != review_ref or not record.complete or record.verdict != 'fail'
                    or request is None or request.scope != context.scope
                    or request.state != 'recorded'
                    or type(compare_result.get('request_version')) is not int
                    or request.version != compare_result['request_version'] + 1
                    or request.fence != compare_result.get('fence')
                    or asdict(record.plan.plan_digest) != compare_result.get('plan_digest')
                    or parent != proposal or latest != change
                    or parent_control.disposition != 'available'
                    or parent.schema_version != 2 or type(source) is not SourceChange
                    or parent.ref.change_id != latest.change_id
                    or parent.ref.proposal_id not in latest.proposal_ids
                    or requirement.schema_version != 2 or requirement.scope != context.scope
                    or requirement.method_ref != binding.method_ref
                    or parent.method_ref != binding.method_ref
                    or requirement.method_resource_refs != source.method_resource_refs
                    or len(targets) != len(requirement.expected_targets.targets) or len(targets) != 2
                    or {t.source_ref.content_identity for t in targets} !=
                       {source.baseline.content_identity, source.candidate.content_identity}):
                raise ApplicationError('WORK_ACTION_REVIEW_RESULT_UNCONFIRMED')

        with self.review_admission.guard_plan(context, record.plan), \
                self.review_admission.guard_trust(context, (record,)) as trusted:
            if (type(trusted) is not tuple or len(trusted) != 1
                    or type(trusted[0]) is not CurrentReviewTrust
                    or trusted[0].review_ref != review_ref
                    or trusted[0].verifier_id != record.reviewer_evidence.verifier_id
                    or trusted[0].trust_version != record.reviewer_evidence.trust_version):
                raise ApplicationError('UNTRUSTED_REVIEWER')
            with self.factory.begin(context.scope, 'read') as uow:
                validate(uow)
            yield ({'code': 'WORK_ACTION_REVIEW_NOT_PASSED', 'verdict': 'fail',
                    'review_ref': asdict(review_ref), 'successor_created': False}, validate)

    async def register(self, context, binding, record_result):
        """`register`: the successor proposal for the same change and exact review."""
        review_ref = (record_result or {}).get("review_ref")
        if type(review_ref) is not dict or not review_ref:
            raise ApplicationError("WORK_ACTION_STEP_INPUT_MISSING")
        candidates = [association for association in binding.associations
                      if association.kind == "proposal"]
        if not candidates:
            raise ApplicationError("WORK_PREREQUISITE_MISSING")
        if len(candidates) != 1:
            # Never pick the first of several: the action's association is unresolved.
            raise ApplicationError("WORK_ACTION_ASSOCIATION_AMBIGUOUS")
        proposal_ref = candidates[0].ref
        with self.factory.begin(context.scope, "read") as uow:
            proposal = uow.proposals.get_proposal(proposal_ref)
            control = uow.proposals.get_control(proposal_ref)
            if proposal is None or getattr(control, "disposition", None) != "available":
                raise ApplicationError("WORK_PREREQUISITE_MISSING")
            # The association command compares the *change* version, not the
            # proposal control's version; take it from the same owner it checks.
            change = uow.proposals.get_change(proposal.change_id)
        expected_version = getattr(change, "version", None)
        if type(expected_version) is not int:
            raise ApplicationError("WORK_ACTION_PROPOSAL_VERSION_UNKNOWN")
        result = self._completed(await self._dispatch(
            "engineering.proposals.associate_review", {
                "proposal_ref": asdict(proposal_ref), "expected_version": expected_version,
                "review_ref": review_ref}, context))
        if type(result) is not dict:
            raise ApplicationError("WORK_ACTION_STEP_RESULT_INVALID")
        return {"proposal_ref": result.get("proposal_ref")}


__all__ = ["DeclaredReviewChangeSteps", "DECLARED_REVIEW_STEPS"]
DECLARED_REVIEW_STEPS = frozenset(DeclaredReviewChangeSteps.STEP_ORDER)
