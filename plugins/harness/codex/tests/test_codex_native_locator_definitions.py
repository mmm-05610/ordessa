import pytest
from ordessa_agents.harness.definitions import NativeProfileRef, NativeContinuationRef, NativeCredentialRef
from ordessa_harness_codex.continuation import CodexContinuationResourceProvider
from ordessa_harness_codex.contracts import CodexContinuationV1
from ordessa_harness_codex.launch import CodexLaunchAdapter


def test_continuation_keeps_original_source_and_rejects_other_locator_kinds():
    provider = CodexContinuationResourceProvider()
    ref = provider.make_ref("session", "codex-app-server")
    assert type(ref) is NativeContinuationRef
    assert ref.metadata == {"source_provider": "codex-app-server"}
    assert provider.resolve(CodexContinuationV1.contract_id, ref).thread_id == "session"
    for kind in (NativeProfileRef, NativeCredentialRef):
        with pytest.raises(ValueError, match="CONTINUATION_REF_MISMATCH"):
            provider.resolve(CodexContinuationV1.contract_id, kind(provider.provider_id, "session", metadata=ref.metadata))


def test_launch_rejects_wrong_profile_identity_before_materialization():
    adapter = CodexLaunchAdapter(object(), binary="/missing/codex")
    for ref in (NativeContinuationRef("harness-profile", "p"), NativeCredentialRef("harness-profile", "p"),
                NativeProfileRef("other", "p", metadata={"harness_type": "codex"}),
                NativeProfileRef("harness-profile", "p", metadata={"harness_type": "hermes"})):
        with pytest.raises(ValueError, match="PROFILE_REF_MISMATCH"):
            adapter._plan(execution_id="e", profile_ref=ref, profile=None, workspace=None, argv=())
