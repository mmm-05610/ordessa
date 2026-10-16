"""Formal human disposition on original Review records and selected policy.

No policy, principal, reply or pass is invented by this admission. Automatic
JEV projection remains separate. Source, policy and mechanical guards share the
original record_response COMMIT, without another state store or Grant.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import asdict

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ...contracts.errors import ApplicationError
from ...contracts.manual_reviews import ManualReviewReply, VerifiedHumanDisposition
from ...contracts.mixed_reviews import FrozenCheckRequest, CheckSourceAdmission
from ...contracts.reviewer_admission import CriterionAnswer
from ...orchestration.human_review import human_review_observations, human_review_presentation_digest
from ....domain.approvals.consent import ConversationSource
from ....domain.approvals.consent_codec import decode_record
from ....domain.artifacts.ref_codec import decode_artifact_ref
from ....domain.common.mechanisms.codec import require_object, decode_digest, decode_blob_ref
from ....domain.common.models.values import validate_text
from ....domain.reviews.models import ReviewRecord, CurrentReviewTrust, observations_digest
from ....domain.reviews.evidence import VerifiedReviewerEvidence
from ....domain.reviews.identity import RecordIdentity
from ....domain.reviews.target_codec import decode_target
from ....domain.reviews.models import CheckKey
from .admission import EngineeringReviewAdmission

_CONTRACT='ordessa.human-review-disposition/1'


def encode_human_review_response(plan,request_version,fence,reply,mechanical_proof_ref,*,answer_mode='per_check'):
    return canonical_bytes({'contract':_CONTRACT,'plan_digest':asdict(plan.plan_digest),
        'request_version':request_version,'fence':fence,'answer_mode':answer_mode,
        'displayed_check_keys':[asdict(k) for k in plan.check_keys],
        'reply':asdict(reply),'mechanical_proof_ref':asdict(mechanical_proof_ref)})


def _key(value):
    require_object(value,{'target','criterion_id','claim_id'},'HUMAN_REVIEW_REPLY_INVALID')
    return CheckKey(decode_target(value['target']),value['criterion_id'],value['claim_id'])


def _answer(value):
    require_object(value,{'check_key','status','evidence_refs','rationale'},'HUMAN_REVIEW_REPLY_INVALID')
    if type(value['evidence_refs']) is not list:raise ApplicationError('HUMAN_REVIEW_REPLY_INVALID')
    return CriterionAnswer(_key(value['check_key']),value['status'],
        tuple(decode_artifact_ref(r) for r in value['evidence_refs']),value['rationale'])


class EngineeringHumanReviewAdmission:
    def __init__(self,factory,method_control,bindings,manual_authority=None,*,blobs,mechanical_source=None):
        if getattr(blobs,'authority_id',None)!=factory.authority_id:
            raise ApplicationError('BLOB_AUTHORITY_MISMATCH')
        if mechanical_source is not None and (getattr(mechanical_source,'factory',None) is not factory
                or getattr(mechanical_source,'methods',None) is not method_control):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.base=EngineeringReviewAdmission(factory,method_control,bindings)
        self.factory,self.methods,self.blobs=factory,method_control,blobs
        self.authority,self.mechanical=manual_authority,mechanical_source

    def guard_plan(self,context,plan):return self.base.guard_plan(context,plan)

    def _decode(self,plan,raw_ref):
        raw=self.blobs.read_verified(raw_ref)
        if len(raw)>2097152:raise ApplicationError('HUMAN_REVIEW_REPLY_INVALID')
        value=decode_json(raw)
        require_object(value,{'contract','plan_digest','request_version','fence','answer_mode',
            'displayed_check_keys','reply','mechanical_proof_ref'},'HUMAN_REVIEW_REPLY_INVALID')
        if (canonical_bytes(value)!=raw or value['contract']!=_CONTRACT
                or decode_digest(value['plan_digest'])!=plan.plan_digest
                or type(value['request_version']) is not int or not 0<=value['request_version']<=9007199254740991
                or type(value['fence']) is not int or not 1<=value['fence']<=9007199254740991
                or value['answer_mode'] not in ('per_check','whole_plan')
                or type(value['displayed_check_keys']) is not list
                or tuple(_key(k) for k in value['displayed_check_keys'])!=plan.check_keys):
            raise ApplicationError('HUMAN_REVIEW_REPLY_INVALID')
        row=value['reply']
        require_object(row,{'question','necessary_context','user_answer','source','check_answers'},'HUMAN_REVIEW_REPLY_INVALID')
        if type(row['check_answers']) is not list:raise ApplicationError('HUMAN_REVIEW_REPLY_INVALID')
        if type(row['user_answer']) is not str or not row['user_answer'].strip():
            raise ApplicationError('HUMAN_REVIEW_ANSWER_PENDING')
        for text in (row['question'],row['necessary_context'],row['user_answer']):validate_text(text)
        # These explicit implementation-only/ambiguous phrases were ruled out
        # by the user. Other wording still requires actual source verification;
        # absence from this list is never evidence of an explicit review answer.
        words=row['user_answer'].strip().rstrip('。.!！?？')
        if words in ('继续','可以干','继续实施','继续执行','可以','好的','开始吧'):
            raise ApplicationError('HUMAN_REVIEW_ANSWER_PENDING')
        reply=ManualReviewReply(row['question'],row['necessary_context'],row['user_answer'],
            decode_record(canonical_bytes(row['source']),ConversationSource),tuple(_answer(a) for a in row['check_answers']))
        return FrozenCheckRequest(plan.plan_digest,value['request_version'],value['fence']),reply,decode_blob_ref(value['mechanical_proof_ref'])

    @contextmanager
    def _guard(self,context,plan,raw_ref,*,expected=None):
        if self.authority is None or not callable(getattr(self.authority,'guard_disposition',None)):
            raise ApplicationError('HUMAN_REVIEW_AUTHORITY_UNAVAILABLE')
        if self.mechanical is None:raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
        with self.methods.guard_method(context,plan.requirement.method_ref) as snapshot:
            standard=self.base._expected(context,plan,snapshot)
            frozen,reply,proof_ref=self._decode(plan,raw_ref)
            criteria={c.criterion_id:c for c in standard.criteria}
            keys=tuple(k for k in plan.check_keys if len(criteria[k.criterion_id].checks)==1 and
                criteria[k.criterion_id].checks[0].capability_id in ('ordessa.sources.integrity','ordessa.claims.coverage'))
            if not keys:raise ApplicationError('HUMAN_REVIEW_NOT_ADMITTED')
            checked=self.mechanical.verify_checks(context,plan,frozen,proof_ref,standard=standard,check_keys=keys)
            admission=CheckSourceAdmission(plan,frozen,proof_ref,keys,checked)
            with self.mechanical.guard_checks(context,(admission,)), self.authority.guard_disposition(
                    context,plan,frozen,raw_ref,reply,standard=standard,
                    mechanical_answers=checked.answers,expected=expected) as verified:
                if type(verified) is not VerifiedHumanDisposition or verified.explicit_answer is not True:
                    raise ApplicationError('HUMAN_REVIEW_ANSWER_PENDING')
                observations=human_review_observations(plan,standard,reply,verified.policy_bytes,checked.answers)
                if verified.presentation_digest!=human_review_presentation_digest(plan,reply,verified.policy_bytes):
                    raise ApplicationError('HUMAN_REVIEW_PRESENTATION_CHANGED')
                evidence=verified.reviewer_evidence
                if (type(evidence) is not VerifiedReviewerEvidence or evidence.scope!=context.scope
                        or evidence.reviewer.actor_kind!='human' or evidence.request_digest!=plan.request_digest
                        or evidence.raw_response_digest!=raw_ref.digest
                        or evidence.observations_digest!=observations_digest(observations)
                        or not set(evidence.roles)&set(plan.reviewer_requirements)
                        or expected is not None and evidence!=expected):
                    raise ApplicationError('UNTRUSTED_REVIEWER')
                yield frozen,evidence,observations

    def verify_response(self,context,plan,request,raw_response_ref):
        with self._guard(context,plan,raw_response_ref) as (frozen,evidence,observations):
            if (request.scope!=context.scope or request.review_id!=plan.review_id or request.state!='requested'
                    or request.version!=frozen.request_version or request.fence!=frozen.fence):
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            return ReviewRecord(RecordIdentity(context.scope,plan.review_id,context.received_at,
                context.authenticated_actor,schema_version=2),plan,evidence,observations,raw_response_ref=raw_response_ref)

    @contextmanager
    def guard_trust(self,context,records):
        if type(records) is not tuple or any(type(r) is not ReviewRecord or r.plan.scope!=context.scope for r in records):
            raise ApplicationError('INVALID_INPUT')
        with ExitStack() as guards:
            current=[]
            for record in records:
                _,evidence,observations=guards.enter_context(self._guard(context,record.plan,record.raw_response_ref,
                    expected=record.reviewer_evidence))
                if observations!=record.observations:raise ApplicationError('REVIEW_SOURCE_INVALID')
                current.append(CurrentReviewTrust(record.ref,evidence.verifier_id,evidence.trust_version))
            yield tuple(current)
