"""Main Agent attestation requires the original issued caller and capability."""
from contextvars import copy_context
from dataclasses import replace
import pytest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import ConsentPolicyRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access.access_control.authentication import AccessError, AccessGrant, InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_server.composition.conversation_attestor import MAIN_AGENT_ATTESTATION_CAPABILITY, RegisteredMainAgentAttestor

SCOPE = Scope("attestor-realm", "attestor-project")
POLICY = ConsentPolicyRef("ordessa.product.v1.chat-attested-confirmation", 1, Digest("sha256", "a" * 64))
OPERATION = "engineering.notices.publish"

def parts(attestation=True):
    capabilities = (OPERATION,) + ((MAIN_AGENT_ATTESTATION_CAPABILITY,) if attestation else ())
    authority = InstanceAccessAuthority(lambda: "test-only-temporary-token", principal_id="registered-main-agent",
        legacy_principal=None, grants=(AccessGrant(SCOPE, capabilities),))
    access = EngineeringCommandAccess(authority)
    guard = RegisteredMainAgentAttestor(access, scope=SCOPE, principal_id=authority.principal_id, selected_policy_ref=POLICY)
    return authority, access, guard, authority.authenticate("Bearer test-only-temporary-token")

def test_original_capability_lock_and_revocation():
    authority, access, guard, caller = parts()
    with access.admit(caller, SCOPE, OPERATION, request_id="notice", trace_id="notice") as context:
        with guard.guard(context, POLICY):
            with pytest.raises(AccessError, match="AUTHORIZATION_GUARD_ACTIVE"):
                authority.replace_grants(())
    authority.replace_grants(())
    with pytest.raises(AccessError):
        with access.admit(caller, SCOPE, OPERATION, request_id="old", trace_id="old"):
            pytest.fail("revoked caller admitted")

def test_same_principal_without_capability_refuses():
    _, access, guard, caller = parts(False)
    with access.admit(caller, SCOPE, OPERATION, request_id="notice", trace_id="notice") as context:
        with pytest.raises(ApplicationError, match="ACCESS_DENIED"):
            with guard.guard(context, POLICY):
                pytest.fail("identity string granted role")

def test_copied_context_and_changed_policy_refuse():
    _, access, guard, caller = parts()
    with access.admit(caller, SCOPE, OPERATION, request_id="notice", trace_id="notice") as context:
        with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
            with guard.guard(replace(context), POLICY):
                pytest.fail("constructed DTO admitted")
        with pytest.raises(ApplicationError, match="UNTRUSTED_CONSENT_ATTESTOR"):
            with guard.guard(context, replace(POLICY, revision=2)):
                pytest.fail("policy elevation admitted")
        copied = copy_context()
    def delayed():
        with guard.guard(context, POLICY):
            pytest.fail("copied context outlived admission")
    with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
        copied.run(delayed)
