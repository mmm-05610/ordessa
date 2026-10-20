from dataclasses import FrozenInstanceError

import pytest

from ordessa_infrastructure.encoding.content_identity import digest
from ordessa_environments.definitions import runtime_resources
from ordessa_environments.definitions.runtime_resources import (
    RUNTIME_HOST_CONTRACT_ID,
    RUNTIME_COMPOSITION_CONTRACT_ID,
    SANDBOX_CONTRACT_ID,
    CapabilitySet,
    CapabilityStatus,
    IsolatedProcessSpec,
    ProjectionRejected,
    RuntimeHostRef,
    RuntimeHostV1,
    SandboxAmbiguous,
    SandboxRef,
    SandboxRequirements,
    SandboxUnavailable,
    SandboxUnsupported,
    SandboxV1,
    guest_path,
)


def test_runtime_reference_contracts_keep_identity_fields_and_validation():
    host = RuntimeHostRef("provider", "host-1", "sha256:host", "affinity")
    sandbox = SandboxRef("provider", "sandbox-1", "sha256:policy", "affinity", network_mode="inherit")

    assert host.schema_version == sandbox.schema_version == 1
    with pytest.raises(FrozenInstanceError):
        host.provider = "changed"
    with pytest.raises(ValueError):
        RuntimeHostRef("", "host-1", "sha256:host", "affinity")
    with pytest.raises(ValueError):
        SandboxRef("provider", "sandbox-1", "sha256:policy", "affinity", network_mode="open")


def test_registry_wrappers_preserve_contract_ids_and_delegate_to_exact_port():
    class Port:
        def resolve(self):
            return "resolved"

    port = Port()
    host = RuntimeHostV1(RuntimeHostRef("provider", "host-1", "sha256:host", "affinity"), port)
    sandbox = SandboxV1(SandboxRef("provider", "sandbox-1", "sha256:policy", "affinity"), port)

    assert (host.contract_id, sandbox.contract_id) == (
        RUNTIME_HOST_CONTRACT_ID, SANDBOX_CONTRACT_ID,
    )
    assert RUNTIME_COMPOSITION_CONTRACT_ID == "agent-box.runtime-composition@1"
    assert host.resolve() == sandbox.resolve() == "resolved"


def test_capability_and_requirement_digests_use_shared_canonical_digest():
    required = SandboxRequirements(("filesystem.read@1",), "provider_self_report", "none")
    assert required.digest == digest({"required": required.required,
                                      "assurance": required.assurance,
                                      "network": required.network})

    capabilities = CapabilitySet({"filesystem.read@1": CapabilityStatus.SUPPORTED},
                                 "provider_self_report", "affinity")
    expected = {"values": {"filesystem.read@1": "supported"},
                "assurance": "provider_self_report", "affinity": "affinity"}
    assert capabilities.digest == digest(expected)
    with pytest.raises(ValueError):
        SandboxRequirements(("bad capability",))
    with pytest.raises(ValueError):
        SandboxRequirements(("filesystem.read@1", "filesystem.read@1"))
    with pytest.raises(ValueError):
        CapabilitySet({"filesystem.read@1": "supported"}, "provider_self_report", "affinity")


def test_guest_paths_fail_closed_and_sandbox_errors_keep_their_family():
    assert guest_path("/workspace/project") == "/workspace/project"
    for value in ("relative", "/workspace/../secret", "/workspace//project", "/workspace/"):
        with pytest.raises(ProjectionRejected):
            guest_path(value)
    assert issubclass(SandboxUnsupported, RuntimeError)
    assert issubclass(SandboxUnavailable, RuntimeError)
    assert issubclass(SandboxAmbiguous, RuntimeError)


def test_process_results_preserve_native_fields():
    local = IsolatedProcessSpec("spawn", "attempt", "sha256:spec", local_argv=("cmd",))
    remote = IsolatedProcessSpec("spawn", "attempt", "sha256:spec", provider_transport="remote")
    assert local.local_argv == ("cmd",) and local.provider_transport is None
    assert remote.provider_transport == "remote" and remote.local_argv is None
    with pytest.raises(ValueError):
        IsolatedProcessSpec("spawn", "attempt", "sha256:spec")
    with pytest.raises(ValueError):
        IsolatedProcessSpec("spawn", "attempt", "sha256:spec", local_argv=("cmd",),
                            provider_transport="remote")


def test_retired_terminal_session_resources_are_gone():
    """The v1-absent terminal surface must not be re-exported or aliased."""
    for retired in (
        "TERMINAL_SESSION_CONTRACT_ID",
        "TerminalSessionRef",
        "TerminalSessionV1",
        "TerminalAllocation",
        "AttachDescriptor",
        "TerminalRunHandle",
    ):
        assert retired not in vars(runtime_resources), retired
        with pytest.raises(AttributeError):
            getattr(runtime_resources, retired)
    with pytest.raises(ImportError):
        from ordessa_environments.definitions.runtime_resources import (  # noqa: F401
            TerminalSessionRef,
        )
