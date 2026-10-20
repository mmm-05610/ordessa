"""Registered chat attestation under an explicitly selected Product policy.

This source verifies the full displayed checklist and faithful bounded answer
expansion. It authenticates the registered machine attestor; human attribution
is agent-attested, not independent platform/person authentication. No Grant,
permission, conversation store or automatic model quality is created here.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import base64
from threading import RLock, local

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.manual_reviews import VerifiedHumanDisposition
from ordessa_engineering.application.orchestration.human_review import (
    human_review_observations, human_review_presentation_digest,
)
from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.evidence import VerifiedReviewerEvidence
from ordessa_engineering.domain.reviews.models import observations_digest
from .conversation_attestor import RegisteredMainAgentAttestor, MAIN_AGENT_ATTESTATION_CAPABILITY

QUESTION = '请审核以下完整清单及冻结依据。审核答复不授权实施；机械事实不能覆盖。可逐项给出清单中的JSON答复，或明确回答“完整审核清单全部满足”；其余整体答复必须明确限定全部人工语义检查。'
SOURCE_LIMITATION = ('agent-attested chat source; registered instance bearer holders share attestor identity; '
                    'human attribution is not independently authenticated by the platform')
WHOLE_ANSWERS = {'完整审核清单全部满足':'satisfied', '完整审核清单中的全部人工语义检查不满足':'violated',
                 '完整审核清单中的全部人工语义检查依据不足':'insufficient',
                 '完整审核清单中的全部人工语义检查无法确定':'unknown'}


class SelectedHumanReviewPolicy:
    """Deployment configuration, with current selection locked through COMMIT.

    No wire mutation. Trusted root can replace selection or disable it; raw
    bytes/ref are selected outside method declarations and compared exactly.
    """
    def __init__(self, raw, ref):
        self._lock = RLock()
        self._guards = local()
        self.select(raw, ref)

    def select(self, raw, ref):
        if (type(raw) is not bytes or type(ref) is not ConsentPolicyRef
                or ref.digest != Digest('sha256', hashlib.sha256(raw).hexdigest())):
            raise ApplicationError('HUMAN_REVIEW_POLICY_INVALID')
        # Validate the actual versioned policy, without selecting from a method.
        import yaml
        policy = yaml.safe_load(raw)
        if (not isinstance(policy, dict) or policy.get('policy_id') != ref.policy_id
                or policy.get('revision') != ref.revision):
            raise ApplicationError('HUMAN_REVIEW_POLICY_INVALID')
        with self._lock:
            if getattr(self._guards,'depth',0):
                raise ApplicationError('HUMAN_REVIEW_POLICY_BUSY')
            self._raw, self._ref, self._enabled = raw, ref, True

    def disable(self):
        with self._lock:
            if getattr(self._guards,'depth',0):
                raise ApplicationError('HUMAN_REVIEW_POLICY_BUSY')
            self._enabled = False

    @contextmanager
    def guard(self, expected):
        with self._lock:
            if not self._enabled or self._ref != expected:
                raise ApplicationError('HUMAN_REVIEW_POLICY_CHANGED')
            self._guards.depth=getattr(self._guards,'depth',0)+1
            try:
                yield self._raw
            finally:
                self._guards.depth-=1


def captured_source_inputs(factory,context,revisions):
    """Selected immutable source bytes from original same-authority budget."""
    from ordessa_engineering.domain.artifacts.provenance import ExcerptCapture
    rows=[]
    with factory.begin(context.scope,'read') as uow:
        budget=uow.engineering.validated_budget()
        for revision in revisions:
            for source in revision.sources:
                if type(source.capture) is not ExcerptCapture:
                    raise ApplicationError('HUMAN_REVIEW_SOURCE_UNAVAILABLE')
                raw=budget.read(source.capture.blob_ref)
                selected=budget.selectors.check(raw,source.capture.selector,source.capture.excerpt_digest)
                try:
                    body={'encoding':'utf-8','text':selected.decode('utf-8')}
                except UnicodeError:
                    body={'encoding':'base64','text':base64.b64encode(selected).decode('ascii')}
                rows.append({'target_ref':asdict(revision.ref),'source':asdict(source),
                    'selected_bytes_digest':hashlib.sha256(selected).hexdigest(),'selected_content':body})
    return rows


def human_review_checklist(plan, frozen_request, standard, revisions, mechanical_answers, source_inputs=()):
    """A bounded, exact presentation of original full Plan/material facts."""
    if (frozen_request.plan_digest != plan.plan_digest
            or tuple(r.ref for r in revisions) != tuple(t.ref for t in plan.requirement.expected_targets.targets)):
        raise ApplicationError('HUMAN_REVIEW_PRESENTATION_CHANGED')
    criteria = {c.criterion_id:c for c in standard.criteria}
    mechanical = {a.check_key:a.status for a in mechanical_answers}
    result = {'contract':'ordessa.product-human-checklist/1',
        'review_id':plan.review_id, 'plan_digest':asdict(plan.plan_digest),
        'request_version':frozen_request.request_version, 'fence':frozen_request.fence,
        'method_ref':asdict(plan.requirement.method_ref),
        'criterion_set_ref':asdict(plan.requirement.criterion_set_ref),
        'checks':[{'check_key':asdict(k), 'statement':criteria[k.criterion_id].statement,
                   'mechanical_status':mechanical.get(k),
                   'answer_origin':'mechanical_required' if criteria[k.criterion_id].checks[0].capability_id == 'ordessa.sources.integrity' else 'human_semantic'}
                  for k in plan.check_keys],
        'materials':[r.projection() for r in revisions], 'captured_sources':list(source_inputs),
        'source_limitation':SOURCE_LIMITATION, 'review_is_implementation_grant':False,
        'whole_plan_answers':list(WHOLE_ANSWERS),
        'per_check_answer_format':'JSON array of {check_key: <displayed exact key>, status: satisfied|violated|insufficient|unknown}; every displayed key once'}
    raw = canonical_bytes(result)
    if len(raw) > 262144:
        raise ApplicationError('HUMAN_REVIEW_PRESENTATION_TOO_LARGE')
    return result


def expand_explicit_answer(plan, standard, user_answer, mechanical_answers):
    """Faithful parsing only; no free-text semantic guesses or fake consent."""
    words = user_answer.strip().rstrip('。.!！') if type(user_answer) is str else ''
    if not words:
        raise ApplicationError('HUMAN_REVIEW_ANSWER_PENDING')
    criteria = {c.criterion_id:c for c in standard.criteria}
    mechanical = {a.check_key:a.status for a in mechanical_answers}
    if words in WHOLE_ANSWERS:
        if words=='完整审核清单全部满足' and any(
                mechanical.get(k)!='satisfied' for k in plan.check_keys
                if criteria[k.criterion_id].checks[0].capability_id=='ordessa.sources.integrity'):
            raise ApplicationError('HUMAN_REVIEW_MECHANICAL_CONFLICT')
        return {k:(mechanical[k] if criteria[k.criterion_id].checks[0].capability_id == 'ordessa.sources.integrity'
                    else WHOLE_ANSWERS[words]) for k in plan.check_keys}
    try:
        rows = decode_json(user_answer.encode('utf-8'))
        if type(rows) is not list or len(rows) != len(plan.check_keys):
            raise ValueError()
        by_bytes = {canonical_bytes(asdict(k)):k for k in plan.check_keys}
        parsed = {}
        for row in rows:
            if (type(row) is not dict or set(row) != {'check_key','status'}
                    or row['status'] not in {'satisfied','violated','insufficient','unknown'}):
                raise ValueError()
            key = by_bytes[canonical_bytes(row['check_key'])]
            if key in parsed: raise ValueError()
            parsed[key] = row['status']
        if set(parsed) != set(plan.check_keys): raise ValueError()
        return parsed
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ApplicationError('HUMAN_REVIEW_ANSWER_PENDING') from None


class RegisteredChatHumanReviewAuthority:
    """Explicitly configured main Agent attestation, not bearer-as-human.

    Trusted composition chooses actual conversation locator and attributed
    human ID. Wire cannot select these identities or the Product policy. The
    agent must capture real Q&A; synthetic test sources are labelled fixtures.
    """
    def __init__(self, factory, access, *, scope, principal_id, policy_selection,
                 selected_policy_ref, conversation_locator, human_subject_id):
        if (type(policy_selection) is not SelectedHumanReviewPolicy or not conversation_locator
                or not human_subject_id):
            raise ApplicationError('HUMAN_REVIEW_AUTHORITY_UNAVAILABLE')
        self.factory, self.access, self.scope = factory, access, scope
        self.selection, self.policy_ref = policy_selection, selected_policy_ref
        self.locator = conversation_locator
        self.human = ActorRef(human_subject_id, 'human', 'agent-attested-chat')
        self.attestor = RegisteredMainAgentAttestor(access, scope=scope, principal_id=principal_id,
                                                  selected_policy_ref=selected_policy_ref)

    @contextmanager
    def guard_disposition(self, context, plan, frozen, raw_ref, reply, *, standard,
                          mechanical_answers, expected=None):
        if (context.scope != plan.scope or frozen.plan_digest != plan.plan_digest
                or (context.scope.realm_id,context.scope.project_id) != (self.scope.realm_id,self.scope.project_id)
                or plan.reviewer_requirements != ('reviewer',)
                or 'reviewer' not in plan.requirement.eligible_reviewer_roles
                or reply.source.locator != self.locator or reply.source.attestor_id != context.principal_id
                or reply.source.trust_grade != 'agent-attested' or reply.source.captured_at > context.received_at
                or SOURCE_LIMITATION not in reply.source.limitations):
            raise ApplicationError('UNTRUSTED_REVIEWER')
        if not reply.source.message_refs and 'message references unavailable' not in reply.source.limitations:
            raise ApplicationError('HUMAN_REVIEW_SOURCE_UNAVAILABLE')
        with self.selection.guard(self.policy_ref) as raw_policy, self.access.guard_current_capability(
                context,self.scope,MAIN_AGENT_ATTESTATION_CAPABILITY) as caller, self.attestor.guard(context,self.policy_ref):
            with self.factory.begin(context.scope,'read') as uow:
                revisions = tuple(uow.engineering.resolve_revision(t.ref) for t in plan.requirement.expected_targets.targets)
            checklist = human_review_checklist(plan,frozen,standard,revisions,mechanical_answers,
                captured_source_inputs(self.factory,context,revisions))
            if (reply.question != QUESTION or reply.necessary_context != canonical_bytes(checklist).decode('utf-8')):
                raise ApplicationError('HUMAN_REVIEW_PRESENTATION_CHANGED')
            parsed = expand_explicit_answer(plan,standard,reply.user_answer,mechanical_answers)
            if ({a.check_key:a.status for a in reply.check_answers} != parsed
                    or len(reply.check_answers) != len(plan.check_keys)
                    or any(a.evidence_refs not in ((),(a.check_key.target.ref,))
                        or a.rationale!='chat-attested explicit answer: '+reply.user_answer
                        for a in reply.check_answers)):
                raise ApplicationError('HUMAN_REVIEW_REPLY_CHANGED')
            observations = human_review_observations(plan,standard,reply,raw_policy,mechanical_answers)
            presentation = human_review_presentation_digest(plan,reply,raw_policy)
            trust = record_digest('registered-chat-human-review-source',{
                'principal_id':context.principal_id, 'policy_ref':asdict(self.policy_ref),
                'human_attribution':asdict(self.human), 'locator':self.locator,
                'presentation_digest':asdict(presentation), 'source':asdict(reply.source)})
            evidence = VerifiedReviewerEvidence(context.scope,self.human,('reviewer',),
                'ordessa.registered-main-agent.chat-human-review','1',caller.credential_epoch,
                plan.request_digest,raw_ref.digest,observations_digest(observations),trust)
            if expected is not None and evidence != expected:
                raise ApplicationError('UNTRUSTED_REVIEWER')
            yield VerifiedHumanDisposition(raw_policy,evidence,True,presentation)
