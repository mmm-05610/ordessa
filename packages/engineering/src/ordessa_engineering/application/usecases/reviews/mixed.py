"""Exact per-check source assembly over original raw blobs and trust guards.

One actual composite reviewer principal is required from the original configured
owner. Sources supply contributions, not actors to union into a fictitious human.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass, asdict
from ordessa_infrastructure.encoding import canonical_bytes,decode_json
from ...contracts.errors import ApplicationError
from ...contracts.mixed_reviews import FrozenCheckRequest,VerifiedCheckResponse,CheckSourceAdmission
from ...contracts.reviewer_admission import VerifiedReviewResponse
from ....domain.common.models.values import Digest
from ....domain.common.mechanisms.hashing import record_digest
from ....domain.common.mechanisms.codec import require_object,decode_digest,decode_blob_ref
from ....domain.reviews.models import CheckKey,CurrentReviewTrust,observations_digest
from ....domain.reviews.evidence import VerifiedReviewerEvidence
from ....domain.reviews.target_codec import decode_target
from .admission import review_observations,review_observations_subset

_CONTRACT='ordessa.mixed-review-response/1'


@dataclass(frozen=True)
class MixedCheckPart:
    source_id: str
    check_keys: tuple[CheckKey,...]
    raw_response_ref: object


def encode_mixed_response(plan,request_version,fence,parts):
    return canonical_bytes({'contract':_CONTRACT,'plan_digest':asdict(plan.plan_digest),
        'request_version':request_version,'fence':fence,'parts':[asdict(p) for p in parts]})


def _key(value):
    require_object(value,{'target','criterion_id','claim_id'},'REVIEW_SOURCE_INVALID')
    return CheckKey(decode_target(value['target']),value['criterion_id'],value['claim_id'])


class MixedReviewerSource:
    def __init__(self,factory,method_control,blobs,*,sources,source_for_capability,reviewer_authority=None):
        if getattr(method_control,'factory',None) is not factory or getattr(blobs,'authority_id',None)!=factory.authority_id:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.factory,self.methods,self.blobs=factory,method_control,blobs
        self.sources=dict(sources);self.mapping=dict(source_for_capability);self.authority=reviewer_authority

    def _parts(self,plan,raw_ref,standard):
        raw=self.blobs.read_verified(raw_ref)
        if len(raw)>2097152:raise ApplicationError('REVIEW_RAW_RESPONSE_INVALID')
        value=decode_json(raw)
        require_object(value,{'contract','plan_digest','request_version','fence','parts'},'REVIEW_SOURCE_INVALID')
        if (canonical_bytes(value)!=raw or value['contract']!=_CONTRACT or decode_digest(value['plan_digest'])!=plan.plan_digest
                or type(value['request_version']) is not int or not 0<=value['request_version']<=9007199254740991
                or type(value['fence']) is not int or not 1<=value['fence']<=9007199254740991
                or type(value['parts']) is not list or not 1<=len(value['parts'])<=4096):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        criteria={c.criterion_id:c for c in standard.criteria}
        parts=[];seen=set();sources=set()
        for row in value['parts']:
            require_object(row,{'source_id','check_keys','raw_response_ref'},'REVIEW_SOURCE_INVALID')
            source=row['source_id'];keys=row['check_keys']
            if type(source) is not str or source not in self.sources or source in sources or type(keys) is not list or not keys:
                raise ApplicationError('REVIEW_SOURCE_INVALID')
            sources.add(source);keys=tuple(_key(k) for k in keys)
            if len(set(keys))!=len(keys) or seen.intersection(keys) or not set(keys)<=set(plan.check_keys):
                raise ApplicationError('REVIEW_SOURCE_INVALID')
            for key in keys:
                criterion=criteria.get(key.criterion_id)
                if criterion is None or len(criterion.checks)!=1:raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                check=criterion.checks[0]
                if self.mapping.get((check.capability_id,check.interface_version))!=source:
                    raise ApplicationError('REVIEW_SOURCE_BINDING_MISMATCH')
            seen.update(keys);parts.append(MixedCheckPart(source,keys,decode_blob_ref(row['raw_response_ref'])))
        if seen!=set(plan.check_keys):raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        return FrozenCheckRequest(plan.plan_digest,value['request_version'],value['fence']),tuple(parts)

    def _verify(self,context,plan,frozen,parts,standard):
        admissions=[];answers=[]
        for part in parts:
            source=self.sources[part.source_id]
            verified=source.verify_checks(context,plan,frozen,part.raw_response_ref,standard=standard,check_keys=part.check_keys)
            if type(verified) is not VerifiedCheckResponse or type(verified.provenance_digest) is not Digest:
                raise ApplicationError('REVIEW_SOURCE_INVALID')
            review_observations_subset(plan,standard,verified.answers,part.check_keys)
            admissions.append((part.source_id,CheckSourceAdmission(plan,frozen,part.raw_response_ref,part.check_keys,verified)))
            answers.extend(verified.answers)
        answers=tuple(sorted(answers,key=lambda a:a.check_key.sort_key))
        observations=review_observations(plan,standard,answers)
        provenance=record_digest('mixed-review-provenance',{'plan_digest':asdict(plan.plan_digest),
            'request':asdict(frozen),'sources':[{'source_id':sid,'raw_response_ref':asdict(a.raw_response_ref),
              'keys':[asdict(k) for k in a.check_keys],'answers':[asdict(x) for x in a.response.answers],
              'provenance_digest':asdict(a.response.provenance_digest)} for sid,a in admissions]})
        return admissions,answers,observations,provenance

    @staticmethod
    def _evidence(context,plan,raw,obs,evidence):
        if (type(evidence) is not VerifiedReviewerEvidence or evidence.scope!=context.scope
                or evidence.request_digest!=plan.request_digest or evidence.raw_response_digest!=raw.digest
                or evidence.observations_digest!=obs or not set(evidence.roles)&set(plan.reviewer_requirements)):
            raise ApplicationError('UNTRUSTED_REVIEWER')
        return evidence

    def verify_response(self,context,plan,request,raw_response_ref,*,standard):
        if self.authority is None:raise ApplicationError('MIXED_REVIEWER_AUTHORITY_UNAVAILABLE')
        frozen,parts=self._parts(plan,raw_response_ref,standard)
        if (request.scope!=context.scope or request.review_id!=plan.review_id or request.state!='requested'
                or request.version!=frozen.request_version or request.fence!=frozen.fence):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        admissions,answers,observations,provenance=self._verify(context,plan,frozen,parts,standard)
        obs=observations_digest(observations)
        with ExitStack() as guards:
            for sid,admission in admissions:
                guards.enter_context(self.sources[sid].guard_checks(context,(admission,)))
            evidence=guards.enter_context(self.authority.guard_verification(context,plan,raw_response_ref,obs,provenance))
            return VerifiedReviewResponse(self._evidence(context,plan,raw_response_ref,obs,evidence),answers)

    @contextmanager
    def guard_trust(self,context,records):
        if self.authority is None:raise ApplicationError('MIXED_REVIEWER_AUTHORITY_UNAVAILABLE')
        with ExitStack() as guards:
            current=[]
            for record in records:
                plan=record.plan
                snapshot=guards.enter_context(self.methods.guard_method(context,plan.requirement.method_ref))
                standards=[s for s in snapshot.program.standard_definitions
                    if s.standard_id==plan.requirement.criterion_set_ref.criterion_set_id
                    and s.resource_ref.sha256==plan.requirement.criterion_set_ref.digest.hex]
                if len(standards)!=1:raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                frozen,parts=self._parts(plan,record.raw_response_ref,standards[0])
                admissions,answers,observations,provenance=self._verify(context,plan,frozen,parts,standards[0])
                if observations!=record.observations:raise ApplicationError('REVIEW_SOURCE_INVALID')
                for sid,admission in admissions:
                    guards.enter_context(self.sources[sid].guard_checks(context,(admission,)))
                obs=observations_digest(observations)
                evidence=guards.enter_context(self.authority.guard_verification(context,plan,record.raw_response_ref,obs,provenance,expected=record.reviewer_evidence))
                self._evidence(context,plan,record.raw_response_ref,obs,evidence)
                if evidence!=record.reviewer_evidence:raise ApplicationError('UNTRUSTED_REVIEWER')
                current.append(CurrentReviewTrust(record.ref,evidence.verifier_id,evidence.trust_version))
            yield tuple(current)
