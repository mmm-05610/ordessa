import pytest
from ordessa_agents.harness.definitions import NativeProfileRef, NativeContinuationRef, NativeCredentialRef
from ordessa_harness_hermes.profile import ProfileRef
from ordessa_harness_hermes.projection import HermesProjection


def test_profile_locator_keeps_historical_identity_fields():
    ref = ProfileRef("profile", 2, "digest").as_ref()
    assert type(ref) is NativeProfileRef
    assert ref.provider == "harness-profile" and ref.native_id == "profile" and ref.uri is None
    assert ref.metadata == {"harness_type": "hermes", "revision": "2", "digest": "digest"}


def test_projection_rejects_other_native_locator_kinds_before_render(tmp_path):
    projection = HermesProjection(tmp_path)
    for kind in (NativeContinuationRef, NativeCredentialRef):
        with pytest.raises(ValueError, match="PROFILE_REF_MISMATCH"):
            projection.materialize("execution", kind("harness-profile", "profile"), historical_view=None)
