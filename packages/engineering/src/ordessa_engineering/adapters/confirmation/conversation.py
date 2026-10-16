"""Admit explicitly selected, versioned agent-attested conversation evidence.

The host supplies an original-authority guard for the registered main agent and
an exact-method intent guard. This records the product's accepted attestation;
it never reports independent human/platform authentication.
"""
from contextlib import ExitStack, contextmanager
import hashlib
import yaml

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef
from ordessa_engineering.domain.common.models.values import Digest


class ConversationAdmission:
    def __init__(self, policy_bytes, selected_policy_ref, *, attestor_guard, intent_guard):
        if type(policy_bytes) is not bytes or type(selected_policy_ref) is not ConsentPolicyRef:
            raise ApplicationError('INVALID_CONSENT_POLICY')
        policy = yaml.safe_load(policy_bytes)
        if (type(policy) is not dict or policy.get('schema_version') != 1
                or policy.get('policy_id') != selected_policy_ref.policy_id
                or policy.get('revision') != selected_policy_ref.revision
                or selected_policy_ref.digest != Digest('sha256', hashlib.sha256(policy_bytes).hexdigest())
                or policy.get('selection_authority') != 'product_composition_and_configured_engineering_admission'
                or policy.get('method_may_select_arbitrary_policy') is not False
                or policy.get('authorized_attestor_role') != 'registered_main_agent'
                or policy.get('accepted_source_trust_level') != 'agent-attested'
                or policy.get('allows_automatic_method_trust_elevation') is not False):
            raise ApplicationError('INVALID_CONSENT_POLICY')
        if attestor_guard is None or intent_guard is None:
            raise ApplicationError('CONFIRMATION_AUTHORITY_UNAVAILABLE')
        self.policy_ref = selected_policy_ref
        self._attestor_guard = attestor_guard
        self._intent_guard = intent_guard

    @contextmanager
    def guard_capture(self, context, source, policy_ref):
        if policy_ref != self.policy_ref or source.trust_grade != 'agent-attested':
            raise ApplicationError('CONSENT_POLICY_CHANGED')
        if source.attestor_id != context.principal_id:
            raise ApplicationError('UNTRUSTED_CONSENT_ATTESTOR')
        if source.captured_at > context.received_at:
            raise ApplicationError('INVALID_CONSENT_TIME')
        with self._attestor_guard(context, self.policy_ref):
            yield

    @contextmanager
    def guard_intent(self, context, intent):
        if intent.policy_ref != self.policy_ref:
            raise ApplicationError('CONSENT_POLICY_CHANGED')
        with self._intent_guard(context, intent):
            yield

    @contextmanager
    def guard_evidence(self, context, intent, evidence):
        if evidence.policy_ref != intent.policy_ref or evidence.intent_digest != intent.digest or evidence.notice_ref != intent.notice_ref:
            raise ApplicationError('CONSENT_BINDING_MISMATCH')
        with ExitStack() as guards:
            guards.enter_context(self.guard_capture(context, evidence.source, evidence.policy_ref))
            guards.enter_context(self.guard_intent(context, intent))
            yield
