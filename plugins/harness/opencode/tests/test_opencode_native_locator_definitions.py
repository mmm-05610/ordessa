import pytest
from ordessa_agents.harness.definitions import NativeProfileRef, NativeCredentialRef
from ordessa_harness_opencode.profiles import OpenCodeProfileRef, OpenCodeContinuationResourceProvider


def test_profile_locator_keeps_historical_identity_fields():
    ref = OpenCodeProfileRef("profile", 2, "digest").as_ref()
    assert type(ref) is NativeProfileRef
    assert ref.provider == "harness-profile" and ref.native_id == "profile" and ref.uri is None
    assert ref.metadata == {"harness_type": "opencode", "revision": "2", "digest": "digest"}


def test_continuation_rejects_other_native_locator_kinds():
    provider = OpenCodeContinuationResourceProvider()
    for kind in (NativeProfileRef, NativeCredentialRef):
        with pytest.raises(ValueError, match="CONTINUATION_REF_MISMATCH"):
            provider.resolve("agent-box.opencode-continuation@1", kind(provider.provider_id, "session"))


def test_continuation_resolves_original_contract_from_actual_brand_owner():
    from ordessa_agents.harness.definitions import NativeContinuationRef
    from ordessa_harness_opencode import OpenCodeContinuationV1
    provider = OpenCodeContinuationResourceProvider()
    resolved = provider.resolve(OpenCodeContinuationV1.contract_id,
                                NativeContinuationRef(provider.provider_id, "session-original"))
    assert type(resolved) is OpenCodeContinuationV1
    assert resolved.session_id == "session-original"
