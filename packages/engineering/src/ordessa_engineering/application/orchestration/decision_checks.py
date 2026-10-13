"""One generic Decision evidence route over original independent Unit records.

Methods own question sets, input contracts, vocabularies and disposition policy.
This adapter verifies exact native evidence; it does not dispatch, judge code,
invent model evaluation, choose thresholds or create reviewer authorization.
"""
from contextlib import ExitStack,contextmanager
from dataclasses import asdict

from ..contracts.errors import ApplicationError
from ..contracts.mixed_reviews import FrozenCheckRequest,VerifiedCheckResponse
from ..usecases.reviews.admission import review_observations
from ...domain.common.mechanisms.hashing import record_digest
from ...domain.reviews.models import ReviewPlan,ReviewRequestState,observations_digest
from ...methods.definitions.models.compiled import thaw_value
from ...methods.definitions.models.identity import ResourceRef
from .unit_review import UnitReviewCheckSource

CAPABILITY='ordessa.decision.evaluate'
INTERFACE='1.0.0'


class GenericDecisionCheckSource:
    """Adapt a qualified native Decision/JEV reviewer to mixed check admission."""
    def __init__(self,source):
        if type(source) is not UnitReviewCheckSource or source.authority is None:
            raise ApplicationError('DECISION_SOURCE_AUTHORITY_UNAVAILABLE')
        self.source=source
        self.factory,self.methods,self.blobs=source.factory,source.methods,source.blobs

    @staticmethod
    def _request(plan,frozen):
        if (type(plan) is not ReviewPlan or type(frozen) is not FrozenCheckRequest
                or frozen.plan_digest!=plan.plan_digest):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        # A historical correlation DTO, never current request/actor authority.
        # Actual request CAS and reviewer evidence remain original owners.
        return ReviewRequestState(plan.scope,plan.review_id,'requested',frozen.fence,frozen.request_version)

    @staticmethod
    def _questions(snapshot,plan,standard,keys):
        if (type(keys) is not tuple or not keys or len(keys)>4096
                or len(set(keys))!=len(keys) or not set(keys)<=set(plan.check_keys)):
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        criteria={item.criterion_id:item for item in standard.criteria}
        expected=[]
        for key in keys:
            criterion=criteria.get(key.criterion_id)
            if (criterion is None or len(criterion.checks)!=1
                    or criterion.checks[0].capability_id!=CAPABILITY
                    or criterion.checks[0].interface_version!=INTERFACE):
                raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
            config=thaw_value(criterion.checks[0].bindings)
            binding=config.get('question_set')
            # Compilation resolves authored resource references before they
            # enter a frozen standard. Consume only that exact compiled ref;
            # never fall back to a name-only authored shape at runtime.
            if (type(binding) is not dict
                    or set(binding)!={'resource_id','sha256','kind'}
                    or type(binding.get('resource_id')) is not str
                    or type(binding.get('sha256')) is not str
                    or binding.get('kind')!='question_set'):
                raise ApplicationError('DECISION_QUESTION_BINDING_UNAVAILABLE')
            resource_ref=ResourceRef(**binding)
            definitions=[item for item in snapshot.program.decision_definitions
                         if item.resource_ref==resource_ref]
            if len(definitions)!=1:
                raise ApplicationError('DECISION_QUESTION_BINDING_UNAVAILABLE')
            definition=definitions[0]
            linked=[q.question_id for q in definition.questions
                    if any(ref.criterion_id==key.criterion_id
                           and ref.resource_ref==standard.resource_ref for ref in q.criterion_refs)]
            question_ids=config.get('question_ids',linked)
            if (type(question_ids) is not list or not question_ids
                    or len(question_ids)!=len(set(question_ids))
                    or not set(question_ids)<=set(linked)):
                raise ApplicationError('DECISION_QUESTION_BINDING_UNAVAILABLE')
            expected.append(definition.resource_ref)
        return tuple(sorted(set(expected),key=lambda ref:ref.resource_id))

    @staticmethod
    def _input_slots(snapshot,refs):
        required=[]
        for ref in refs:
            definitions=[d for d in snapshot.program.decision_definitions if d.resource_ref==ref]
            if len(definitions)!=1:
                raise ApplicationError('DECISION_INPUT_BINDING_UNAVAILABLE')
            for slot in definitions[0].required_input_slots:
                if slot not in required:
                    required.append(slot)
        return tuple(required)

    def _verify(self,context,plan,frozen,raw,standard,keys,stack):
        request=self._request(plan,frozen)
        snapshot=stack.enter_context(self.methods.guard_method(context,plan.requirement.method_ref))
        standard=self.source._standard(snapshot,plan,standard)
        expected=self._questions(snapshot,plan,standard,keys)
        binding,captured,answers=self.source._capture(context,plan,request,standard,snapshot,raw)
        if (type(binding.decision_question_refs) is not tuple
                or any(type(ref) is not ResourceRef for ref in binding.decision_question_refs)
                or tuple(sorted(binding.decision_question_refs,key=lambda ref:ref.resource_id))!=expected):
            raise ApplicationError('DECISION_QUESTION_BINDING_UNAVAILABLE')
        if (type(binding.decision_input_slots) is not tuple
                or any(type(slot) is not str for slot in binding.decision_input_slots)
                or len(set(binding.decision_input_slots))!=len(binding.decision_input_slots)
                or binding.decision_input_slots!=self._input_slots(snapshot,expected)):
            raise ApplicationError('DECISION_INPUT_BINDING_UNAVAILABLE')
        observations=review_observations(plan,standard,answers)
        evidence=stack.enter_context(self.source.authority.guard_unit_reviewer(
            context,plan,request,binding,raw,observations_digest(observations)))
        self.source._validate_evidence(context,plan,request,raw,observations_digest(observations),evidence)
        selected=tuple(answer for answer in answers if answer.check_key in keys)
        if {answer.check_key for answer in selected}!=set(keys):
            raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
        provenance=record_digest('generic-decision-review-check',{
            'plan_digest':asdict(plan.plan_digest),'request':asdict(frozen),
            'questions':[asdict(ref) for ref in expected],'raw_response_ref':asdict(raw),
            'input_slots':list(binding.decision_input_slots),
            'captured_observation_ref':asdict(captured.blob_ref),
            'prompt_digest':binding.expected_prompt_digest,'query_digest':captured.query_digest,
            'check_keys':[asdict(key) for key in keys],
            'answers':[asdict(answer) for answer in selected],'reviewer_evidence':asdict(evidence)})
        return VerifiedCheckResponse(selected,provenance)

    def verify_checks(self,context,plan,request,raw_response_ref,*,standard,check_keys):
        with ExitStack() as stack:
            return self._verify(context,plan,request,raw_response_ref,standard,check_keys,stack)

    @contextmanager
    def guard_checks(self,context,admissions):
        if type(admissions) is not tuple or not admissions:
            raise ApplicationError('REVIEW_SOURCE_INVALID')
        with ExitStack() as stack:
            for admission in admissions:
                snapshot=stack.enter_context(self.methods.guard_method(
                    context,admission.plan.requirement.method_ref))
                standard=self.source._standard(snapshot,admission.plan,None)
                current=self._verify(context,admission.plan,admission.request,
                    admission.raw_response_ref,standard,admission.check_keys,stack)
                if current!=admission.response:
                    raise ApplicationError('REVIEW_SOURCE_PROOF_CHANGED')
            yield


def generic_decision_check_capability():
    from ...methods.definitions.models.capabilities import CapabilityDescriptor
    from ...methods.definitions.models.identity import method_digest
    contract={
        'owner':'GenericDecisionCheckSource over original UnitReviewCheckSource',
        'route':'verify_checks / guard_checks; actual Decision/JEV dispatch belongs to Execution',
        'policy_owner':'external method question_set, required_input_slots, result schema, vocabulary and status/disposition rules',
        'input':'unchanged full ReviewPlan + FrozenCheckRequest + exact check-key subset + actual native response blob',
        'question_binding':'method-pinned decision resources/question_ids; fixed prompt must carry all required inputs and question refs',
        'output':'original authenticated CriterionAnswers; no synthetic evaluation/argmax/threshold/pass',
        'admission':'exact original Unit/query/prompt/delivery/schema/request identities and real independent reviewer roles/capability/current epoch held through COMMIT',
        'missing_source':'explicit refusal; descriptor is not production registration or Grant',
        'limits':{'check_keys_max':4096,'response_bytes_max':262144},
    }
    return CapabilityDescriptor(CAPABILITY,'check',INTERFACE,method_digest('capability-contract',contract),contract)
