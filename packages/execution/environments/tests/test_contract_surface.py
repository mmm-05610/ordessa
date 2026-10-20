"""The environment contract must stay free of concrete execution mechanics.

This is a source/AST gate, not a prose check: the contract's own docstrings name
the forbidden mechanics in order to forbid them, so a text scan would flag the
rule itself. We therefore inspect imports and identifier usage.

If this test fails, the contract has started binding one concrete environment
implementation and can no longer be implemented by a different provider.
"""
from __future__ import annotations

import ast
import pathlib

import ordessa_environments.definitions as definitions

#: Import roots the pure contract may use. Anything else means the contract has
#: picked up a concrete mechanic or a foreign dependency.
ALLOWED_IMPORT_ROOTS = frozenset({"__future__", "os", "dataclasses", "typing", "math"})
ALLOWED_CONTENT_DIGEST_IMPORT = "ordessa_infrastructure.encoding.content_identity"

#: Concrete mechanics that must never be named in the contract. Matched against
#: AST identifiers/attributes, never against raw source text.
FORBIDDEN_IDENTIFIERS = frozenset(
    {
        "Popen",
        "asyncio",
        "boto3",
        "botocore",
        "docker",
        "fork",
        "kubernetes",
        "lxc",
        "paramiko",
        "podman",
        "pty",
        "socket",
        "ssh",
    }
)

#: Concrete-mechanic module roots that must never be imported.
FORBIDDEN_IMPORT_ROOTS = FORBIDDEN_IDENTIFIERS | {"subprocess"}


def _contract_sources() -> list[pathlib.Path]:
    package = pathlib.Path(definitions.__file__).resolve().parent
    return sorted(package.rglob("*.py"))


def test_contract_package_is_present() -> None:
    sources = _contract_sources()
    assert sources, "the contract package has no source files"


def test_contract_imports_only_neutral_stdlib() -> None:
    offenders: list[str] = []
    for path in _contract_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                if node.level:  # relative import inside the contract package
                    continue
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            if (path.name in {"runtime_resources.py", "capabilities.py", "composition_values.py"}
                    and isinstance(node, ast.ImportFrom)
                    and node.module == ALLOWED_CONTENT_DIGEST_IMPORT
                    and tuple(alias.name for alias in node.names) == ("digest",)):
                continue
            for root in roots:
                if root in FORBIDDEN_IMPORT_ROOTS:
                    offenders.append(f"{path.name}: imports concrete mechanic {root!r}")
                elif root not in ALLOWED_IMPORT_ROOTS and not (
                        path.name == "runtime_resources.py" and root in {"enum", "re", "pathlib"}) and not (
                        path.name == "capabilities.py" and root == "enum") and not (
                        path.name == "composition_values.py" and root == "enum"):
                    offenders.append(f"{path.name}: imports non-neutral module {root!r}")
    assert not offenders, offenders


def test_contract_never_names_a_concrete_mechanic() -> None:
    offenders: list[str] = []
    for path in _contract_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_IDENTIFIERS:
                offenders.append(f"{path.name}:{node.lineno}: name {node.id!r}")
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_IDENTIFIERS:
                offenders.append(f"{path.name}:{node.lineno}: attribute {node.attr!r}")
    assert not offenders, offenders


def test_contract_exposes_the_agreed_surface() -> None:
    """The managed capability surface plus the request/handle/area protocols."""
    for name in (
        "ProcessHandle",
        "ProcessRequest",
        "FileArea",
        "ExecutionSpace",
        "CapabilityReport",
        "CapabilityStatus",
        "require_capabilities",
        "CAPABILITY_KEYS",
        "OUTBOUND_NETWORK_CAPABILITY",
        "PROCESS_CAPABILITY",
        "BYTE_CHANNEL_CAPABILITY",
        "FILE_AREA_CAPABILITY",
        "TERMINAL_CAPABILITY",
        "STREAMING_STDERR_CAPABILITY",
        "KNOWN_CAPABILITIES",
        "ProcessObservation",
        "ProcessCancellation",
        "ProviderFacts",
    ):
        assert hasattr(definitions, name), f"contract surface is missing {name}"
    for retired in ("EnvironmentHandle", "EnvironmentProvider", "Capabilities", "require_guarantees",
                    "ProviderDescriptor"):
        assert not hasattr(definitions, retired), f"retired contract surface {retired} is still exported"


#: Retired identifiers that must not appear anywhere in the contract sources.
#: ``TerminalSession``/``TerminalSessionRef`` and friends are the v1-absent
#: terminal surface; ``ProviderDescriptor`` is the renamed provider-facts type.
RETIRED_CONTRACT_IDENTIFIERS = frozenset(
    {
        "TERMINAL_SESSION_CONTRACT_ID",
        "TerminalSession",
        "TerminalSessionProvider",
        "TerminalSessionRef",
        "TerminalSessionV1",
        "TerminalAllocation",
        "AttachDescriptor",
        "TerminalRunHandle",
        "ProviderDescriptor",
    }
)


def test_contract_never_names_a_retired_identifier() -> None:
    """The retired terminal/provider-descriptor names are gone, not aliased."""
    offenders: list[str] = []
    for path in _contract_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in RETIRED_CONTRACT_IDENTIFIERS:
                offenders.append(f"{path.name}:{node.lineno}: name {node.id!r}")
            elif isinstance(node, ast.Attribute) and node.attr in RETIRED_CONTRACT_IDENTIFIERS:
                offenders.append(f"{path.name}:{node.lineno}: attribute {node.attr!r}")
    assert not offenders, offenders


def test_process_identity_is_opaque_not_a_pid() -> None:
    """``identity`` is declared as a string, never an integer PID.

    The contract must not promise OS-level process identity: that is a local
    provider detail. A future remote provider reports its own opaque token.

    ``from __future__ import annotations`` makes these annotations strings, so
    both the resolved and the raw form are accepted.
    """
    annotations = getattr(definitions.ProcessHandle, "__annotations__", {})
    assert "identity" in annotations, "ProcessHandle must declare an identity"
    assert annotations["identity"] in (str, "str")


def test_byte_io_belongs_directly_to_one_neutral_process_protocol() -> None:
    """Approved direct async owner replaces the old stream protocol atomically."""
    import inspect
    assert not hasattr(definitions,'ByteStream')
    assert getattr(definitions.ProcessHandle, "_is_protocol", False) is True
    for retired in ("EnvironmentHandle", "EnvironmentProvider", "Capabilities", "require_guarantees"):
        assert not hasattr(definitions, retired), retired
    for name in ('read_stdout','read_stderr','write_stdin','close_stdin','wait_exit','cancel'):
        assert inspect.iscoroutinefunction(getattr(definitions.ProcessHandle,name)),name
    for retired in ('stdin','stdout','stderr','fileno','poll','wait','terminate','kill','send_signal'):
        assert not hasattr(definitions.ProcessHandle,retired),retired
