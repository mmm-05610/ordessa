"""Original assembly and selected-port regression at the Units owner."""
from dataclasses import fields
from types import SimpleNamespace

import pytest

from ordessa_units.assembly.runtime.assembler import assemble_runtime_composition
from ordessa_units.assembly.runtime.coordinator import ResolvedComposition
from ordessa_execution_agents.harness.definitions.command_projection import HarnessCommandSpec
from ordessa_environments.composition import RuntimePreparationRejected
from ordessa_environments.definitions.runtime_resources import (
    RuntimeHostRef,
    RuntimeHostV1,
    SandboxRef,
    SandboxV1,
)


def _request(*values):
    return SimpleNamespace(
        resolved_inputs=tuple(SimpleNamespace(contract_id=x.contract_id, value=x) for x in values)
    )


def _source(tmp_path):
    from ordessa_execution_agents.harness.providers.resolution.source_declaration import declare_source
    source = tmp_path / "source"
    source.write_bytes(b"controlled source")
    return source, declare_source("workspace", source, "/workspace", access="rw")


@pytest.mark.parametrize("kind", ["cwd", "overlap", "drift"])
def test_actual_assembler_checks_entire_plan_before_registration(tmp_path, kind):
    from dataclasses import replace
    from ordessa_execution_agents.harness.providers.resolution.source_declaration import declare_source
    affinity = "controlled:linux:amd64"
    host = RuntimeHostRef("controlled", "h", "hd", affinity)
    sandbox = SandboxRef("controlled", "s", "sd", affinity)
    registered = []
    provider = SimpleNamespace(register_prepared_source=lambda *args, **kwargs: registered.append((args, kwargs)))
    source = tmp_path / "source"
    source.write_bytes(b"controlled source")
    first = declare_source("workspace", source, "/workspace", access="rw")
    second = declare_source("profile", source, "/profile")
    if kind == "overlap": second = replace(second, guest_target="/workspace/child")
    if kind == "drift": second = replace(second, expected_digest="different")
    command = HarnessCommandSpec(("controlled",), "/outside" if kind == "cwd" else "/workspace", runtime_sources=(first, second))
    request = _request(
        RuntimeHostV1(host, SimpleNamespace()),
        SandboxV1(sandbox, SimpleNamespace(provider=provider)),
    )
    with pytest.raises(ValueError, match="cwd|overlapping|digest drift") as rejected:
        assemble_runtime_composition(request, command)
    assert isinstance(rejected.value, RuntimePreparationRejected)
    assert registered == []
    assert source.read_bytes() == b"controlled source"


def test_assembler_binds_host_and_sandbox_and_resolves_their_ports(tmp_path):
    affinity = "controlled:linux:amd64"
    host = RuntimeHostRef("controlled", "h", "hd", affinity)
    sandbox = SandboxRef("controlled", "s", "sd", affinity)
    host_port, sandbox_port = SimpleNamespace(), SimpleNamespace()
    provider = SimpleNamespace(register_prepared_source=lambda *args, **kwargs: None)
    sandbox_port.provider = provider
    _, source = _source(tmp_path)
    command = HarnessCommandSpec(("controlled",), "/workspace", runtime_sources=(source,))
    request = _request(RuntimeHostV1(host, host_port), SandboxV1(sandbox, sandbox_port))

    binding, coordinator = assemble_runtime_composition(request, command)
    # The v1 binding names exactly the host and the sandbox; no terminal ref.
    assert tuple(field.name for field in fields(binding)) == ("runtime_host_ref", "sandbox_ref")
    assert binding.runtime_host_ref == host and binding.sandbox_ref == sandbox
    assert coordinator._resolver(binding) == ResolvedComposition(host_port, sandbox_port)


def test_assembler_requires_exactly_the_v1_host_and_sandbox_ports(tmp_path):
    affinity = "controlled:linux:amd64"
    host = RuntimeHostRef("controlled", "h", "hd", affinity)
    sandbox = SandboxRef("controlled", "s", "sd", affinity)
    provider = SimpleNamespace(register_prepared_source=lambda *args, **kwargs: None)
    _, source = _source(tmp_path)
    command = HarnessCommandSpec(("controlled",), "/workspace", runtime_sources=(source,))
    for request in (
        _request(RuntimeHostV1(host, SimpleNamespace())),
        _request(SandboxV1(sandbox, SimpleNamespace(provider=provider))),
    ):
        with pytest.raises(RuntimePreparationRejected, match="exact RuntimeHost and Sandbox inputs are required"):
            assemble_runtime_composition(request, command)
