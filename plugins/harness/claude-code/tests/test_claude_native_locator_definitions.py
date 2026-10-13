import pytest
from ordessa_execution_agents.harness.definitions import NativeProfileRef, NativeContinuationRef, NativeCredentialRef
from ordessa_harness_claude_code.profile import ClaudeProfileRef, ClaudeContinuationResourceProvider
from ordessa_harness_claude_code.contracts import ClaudeContinuationV1


def test_profile_locator_keeps_historical_identity_fields():
    ref = ClaudeProfileRef("profile", 2, "digest").as_ref()
    assert type(ref) is NativeProfileRef
    assert ref.provider == "harness-profile" and ref.native_id == "profile" and ref.uri is None
    assert ref.metadata == {"harness_type": "claude-code", "revision": "2", "digest": "digest"}


def test_continuation_requires_its_specific_native_locator():
    provider = ClaudeContinuationResourceProvider()
    ref = NativeContinuationRef(provider.provider_id, "session", metadata={"project_key": "project"})
    value = provider.resolve(ClaudeContinuationV1.contract_id, ref)
    assert value.session_id == "session"
    for kind in (NativeProfileRef, NativeCredentialRef):
        with pytest.raises(ValueError, match="CONTINUATION_REF_MISMATCH"):
            provider.resolve(ClaudeContinuationV1.contract_id, kind(provider.provider_id, "session"))
