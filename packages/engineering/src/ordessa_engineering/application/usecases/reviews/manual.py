"""Bind a real human review reply as pending evidence in the original Artifact TX.

This entry captures no ApprovalIntent/Grant and does not auto-complete a quality
check or full ReviewRecord. Human disposition admission is independent of JEV
calibration; absent a configured actual authority this command refuses.
"""
from dataclasses import asdict
import hashlib
from ordessa_infrastructure.encoding import canonical_bytes
from ...contracts.errors import ApplicationError
from ...contracts.manual_reviews import ManualReviewReply
from ...contracts.commands import ReadSet
from ....domain.common.models.values import Digest,validate_text
from ....domain.approvals.consent import ConversationSource
from ....domain.reviews.models import ReviewRequestExpectation
from ....domain.reviews.evidence import VerifiedReviewerEvidence
from ...contracts.reviewer_admission import CriterionAnswer
from ..artifacts import ArtifactUseCases


class ManualReviewCapture:
    def __init__(self,factory,access=None,*,review_admission=None,manual_authority=None,blobs=None):
        if blobs is not None and getattr(blobs,'authority_id',None)!=factory.authority_id:
            raise ApplicationError('BLOB_AUTHORITY_MISMATCH')
        self.factory,self.access,self.admission,self.authority,self.blobs=factory,access,review_admission,manual_authority,blobs

    def capture(self,review_id,reply,context,*,expected_request_version,fence):
        if self.access is None:raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context,'engineering.reviews.capture_manual_reply')
        if self.authority is None or self.admission is None or self.blobs is None:
            raise ApplicationError('MANUAL_REVIEW_AUTHORITY_UNAVAILABLE')
        if type(reply) is not ManualReviewReply or type(reply.source) is not ConversationSource:
            raise ApplicationError('MANUAL_REVIEW_REPLY_INVALID')
        for value in (reply.question,reply.necessary_context,reply.user_answer):validate_text(value)
        with self.factory.begin(context.scope,'read') as uow:
            plan=uow.reviews.get_plan(review_id);request=uow.reviews.get_request(review_id)
        if (request.scope!=context.scope or request.state!='requested'
                or type(expected_request_version) is not int or type(fence) is not int
                or request.version!=expected_request_version or request.fence!=fence):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        if (type(reply.check_answers) is not tuple or not reply.check_answers
                or any(type(a) is not CriterionAnswer or a.status not in {'satisfied','violated','insufficient','unknown'} for a in reply.check_answers)
                or len({a.check_key for a in reply.check_answers})!=len(reply.check_answers)
                or {a.check_key for a in reply.check_answers}!=set(plan.check_keys)):
            raise ApplicationError('MANUAL_REVIEW_REPLY_INCOMPLETE')
        with self.admission.guard_plan(context,plan), self.authority.guard_reply(context,plan,request,reply) as verified:
            if (type(verified) is not VerifiedReviewerEvidence or verified.scope!=context.scope
                    or verified.reviewer.actor_kind!='human' or verified.request_digest!=plan.request_digest
                    or not set(verified.roles)&set(plan.reviewer_requirements)):
                raise ApplicationError('UNTRUSTED_REVIEWER')
            # Bind exactly what the trusted human-source port verified. DTO
            # structured answers/approved booleans alone never enter this path.
            reply_bytes=canonical_bytes(asdict(reply))
            reply_digest=Digest('sha256',hashlib.sha256(reply_bytes).hexdigest())
            if verified.raw_response_digest!=reply_digest:raise ApplicationError('MANUAL_REVIEW_REPLY_CHANGED')
            raw=canonical_bytes({'contract':'ordessa.manual-review-reply/1','plan_digest':asdict(plan.plan_digest),
                'request_version':request.version,'fence':request.fence,'reply':asdict(reply),
                'verified_source':asdict(verified),'quality_disposition':'manual','grant_created':False})
            if len(raw)>2097152:raise ApplicationError('MANUAL_REVIEW_REPLY_INVALID')
            ref=self.blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
            value={'kind':'other','initial':{'media_type':'application/json','schema_id':'urn:ordessa:manual-review-reply:1','blob_ref':asdict(ref)}}
            reads=ReadSet(context.scope,(),review_requests=(ReviewRequestExpectation(context.scope,review_id,
                plan.plan_digest,request.version,request.fence),))
            # Original Artifact journal/readset/CAS/Blob validation owns COMMIT;
            # upstream source and method guards remain held throughout it.
            return ArtifactUseCases(self.factory,self.access).create(value,context,read_set=reads)
