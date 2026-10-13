"""Formal exact Submission Artifact adoption; no DID apply alias or dispatch."""
from contextlib import ExitStack
from dataclasses import asdict
from uuid import uuid4
from ordessa_infrastructure.encoding import canonical_bytes
from ...contracts.errors import ApplicationError
from ..approvals.service import ApprovalUseCases
from .acceptance_closure import resolve_submission_acceptance
from ....domain.approvals.consent import AuthorizationIntent
from ....domain.approvals.ref_codec import decode_approval_ref
from ....domain.artifacts.ref_codec import decode_artifact_ref
from ....domain.changes.application_plan import HeadExpectation
from ....domain.changes.adoption import AcceptanceTarget, AcceptancePlan, AcceptanceReceipt
from ....domain.reviews.target_codec import decode_subject_ref
from ....domain.reviews.refs import SubmissionRef
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.common.mechanisms.codec import require_object


def resolve_acceptance_intent(uow, intent, submission_ref):
    """Whole current original closure; no client requirement/target filtering."""
    if type(intent) is not AuthorizationIntent or intent.scope != uow.scope:
        raise ApplicationError('ACTION_NOT_AUTHORIZED')
    closure=resolve_submission_acceptance(uow,submission_ref)
    if (intent.method_ref!=closure.package.payload.method_ref
            or set(intent.targets)!=set(closure.submission.output_refs)
            or len(intent.targets)!=len(closure.submission.output_refs)
            or any(r.purpose!='acceptance' for r in intent.required_review_requirements)
            or sorted(canonical_bytes(asdict(r)) for r in intent.required_review_requirements)
                !=sorted(canonical_bytes(asdict(r)) for r in closure.requirements)):
        raise ApplicationError('CONSENT_BINDING_MISMATCH')
    return closure


class AcceptanceUseCases(ApprovalUseCases):
    def __init__(self,factory,access,admission=None,review_admission=None,*,acceptance_admission=None,submission_source=None):
        super().__init__(factory,access,admission,review_admission)
        if acceptance_admission is not None and getattr(acceptance_admission,'factory',None) is not factory:
            raise ApplicationError('ACCEPTANCE_AUTHORITY_MISMATCH')
        self.acceptance_admission=acceptance_admission
        self.submission_source=submission_source

    def adopt(self,parameters,context,*,read_set=None):
        op='engineering.acceptance.adopt'
        value,reads,digest=self._input(op,parameters,context,read_set)
        try:
            approval=decode_approval_ref(value['approval_ref'])
            subject=decode_subject_ref(value['submission_ref'])
            if type(subject) is not SubmissionRef:
                raise ReferenceError('INVALID_ACCEPTANCE_PLAN')
            targets=[]
            for row in value['targets']:
                require_object(row,{'target_ref','expected'},'INVALID_ACCEPTANCE_TARGET')
                head=row['expected']
                require_object(head,{'artifact_id','version','head_ref'},'INVALID_ACCEPTANCE_TARGET')
                targets.append(AcceptanceTarget(decode_artifact_ref(row['target_ref']),
                    HeadExpectation(head['artifact_id'],head['version'],
                        None if head['head_ref'] is None else decode_artifact_ref(head['head_ref']))))
        except (ReferenceError,TypeError,ValueError,KeyError):
            raise ApplicationError('INVALID_INPUT') from None
        replay=self._replay(op,context,digest)
        if replay is not None:
            return replay  # Historical receipt read, never re-debit/re-apply.
        if self.acceptance_admission is None:
            raise ApplicationError('ACCEPTANCE_ADMISSION_UNAVAILABLE')
        if self.submission_source is None:
            raise ApplicationError('SUBMISSION_SOURCE_AUTHORITY_UNAVAILABLE')
        with self.factory.begin(context.scope,'read') as uow:
            grant=uow.authorization.get_grant(approval)
            control=uow.authorization.get_control(approval)
            intent=grant.intent
            if type(intent) is not AuthorizationIntent:
                raise ApplicationError('ACTION_NOT_AUTHORIZED')
            closure=resolve_acceptance_intent(uow,intent,subject)
            try:
                plan=AcceptancePlan(context.scope,subject,intent.acceptance_use,tuple(targets))
            except ReferenceError as exc:
                raise ApplicationError('INVALID_INPUT') from exc
        if control['state']!='granted' or control['version']!=value['expected_control_version']:
            raise ApplicationError('APPROVAL_CONTROL_CHANGED')
        if {t.target_ref for t in plan.targets}!=set(intent.targets):
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        with ExitStack() as guards:
            guards.enter_context(self.acceptance_admission.guard_intent(context,intent))
            guards.enter_context(self._admission().guard_intent(context,intent))
            guards.enter_context(self._admission().guard_evidence(context,intent,grant.evidence))
            decisions=guards.enter_context(self._gates(context,intent))
            guards.enter_context(self.submission_source.guard_submission(context,closure.submission,closure.package))
            def mutate(uow):
                if uow.authorization.get_grant(approval)!=grant or uow.authorization.get_control(approval)!=control:
                    raise ApplicationError('APPROVAL_CONTROL_CHANGED')
                current=resolve_acceptance_intent(uow,intent,subject)
                if current!=closure:
                    raise ApplicationError('SUBMISSION_BINDING_CHANGED')
                self._resolve(uow,intent)  # Exact original notice/summary/target binding.
                self._check_gates(uow,decisions)
                from ..support.clock import utc_now
                now = utc_now()
                action_id=str(uuid4())
                # All target version/head/graph checks precede every head effect.
                uow.engineering.apply_acceptance_plan(plan)
                uow.authorization.consume_action(approval,action='accept_artifact',
                    action_instance_id=action_id,target_digest=plan.digest,now=now)
                review_refs=tuple(sorted({r for d in decisions for r in d.used_review_refs},
                    key=lambda r:canonical_bytes(asdict(r))))
                receipt=AcceptanceReceipt(context.scope,str(uuid4()),action_id,approval,intent.digest,
                    plan,review_refs,control['version'],now)
                ref=uow.acceptance.create(receipt)
                return {'acceptance_receipt_ref':asdict(ref),'submission_ref':asdict(subject),
                    'acceptance_use':intent.acceptance_use,'accepted':True,
                    'target_refs':[asdict(t.target_ref) for t in plan.targets]}
            return self._run(op,context,reads,digest,mutate)
