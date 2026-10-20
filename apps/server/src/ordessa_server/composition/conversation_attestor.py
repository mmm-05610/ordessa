"""Explicit main Agent selection on the existing instance capability authority.

This selection authenticates a machine attestor, never the human answer. Any
holder of that instance bearer shares its identity; evidence must disclose that
limitation. The guard neither creates credentials nor grants itself authority.
"""
from contextlib import contextmanager

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef
from ordessa_interfaces.system_access.contracts.refs import Scope


MAIN_AGENT_ATTESTATION_CAPABILITY = "engineering.conversation.attest"


class RegisteredMainAgentAttestor:
    def __init__(self, access, *, scope, principal_id, selected_policy_ref):
        if (type(scope) is not Scope or type(selected_policy_ref) is not ConsentPolicyRef
                or principal_id != access.authority.principal_id):
            raise ApplicationError("CONFIRMATION_AUTHORITY_UNAVAILABLE")
        self.access = access
        self.scope = scope
        self.principal_id = principal_id
        self.policy_ref = selected_policy_ref

    @contextmanager
    def guard(self, context, policy_ref):
        if (policy_ref != self.policy_ref or context.principal_id != self.principal_id):
            raise ApplicationError("UNTRUSTED_CONSENT_ATTESTOR")
        with self.access.guard_current_capability(context, self.scope,
                MAIN_AGENT_ATTESTATION_CAPABILITY) as caller:
            if caller.principal_id != self.principal_id or caller.kind != "machine":
                raise ApplicationError("UNTRUSTED_CONSENT_ATTESTOR")
            yield
