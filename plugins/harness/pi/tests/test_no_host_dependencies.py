"""Pi construction seams without host imports or native effects.

Injected test objects check identity/arguments only; they do not establish Pi
native execution, configuration readback, Skills, sessions or recovery.
"""
import ast
from importlib.resources import files
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ordessa_execution_agents.harness.definitions import Installation
from ordessa_execution_agents.harness.definitions.harness_capabilities import CANONICAL_CAPABILITY_IDS
from ordessa_harness_pi import production
from ordessa_harness_pi.registration import configuration_adapters
from ordessa_harness_pi.configuration.c2 import descriptor
from ordessa_execution_agents.harness.configuration.compilation.model_choice import ModelChoiceAdapter
from ordessa_harness_pi.configuration.context import PiLiveModelContext
from ordessa_harness_pi.configuration.runtime import PiLiveModelRuntime
from ordessa_harness_pi.configuration import service


def test_all_pi_source_imports_are_independent_of_app_and_product():
    root = Path(str(files("ordessa_harness_pi")))
    sources = tuple(root.rglob("*.py"))
    assert sources
    violations = []
    for source in sources:
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                     else [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            for name in names:
                if name == "ordessa_server" or name.startswith("ordessa_server.") or (
                        name == "ordessa_server_product" or name.startswith("ordessa_server_product.")):
                    violations.append(f"{source.name}:{node.lineno}:{name}")
    assert violations == []


def test_leaf_imports_succeed_when_host_modules_are_unavailable():
    script = """
import importlib.abc, sys
class RejectHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'ordessa_server', 'ordessa_server_product'}:
            raise AssertionError('Pi attempted host import: ' + fullname)
sys.meta_path.insert(0, RejectHost())
import ordessa_harness_pi.production
import ordessa_harness_pi.registration
import ordessa_harness_pi.configuration.context
import ordessa_harness_pi.configuration.runtime
import ordessa_harness_pi.configuration.service
assert not any(k.split('.')[0] in {'ordessa_server', 'ordessa_server_product'} for k in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                            timeout=30, check=False)
    assert result.returncode == 0, result.stderr


def test_capability_claims_use_one_injected_registry_and_return_fresh_values():
    declarations = {key: key == "attach" for key in CANONICAL_CAPABILITY_IDS}
    seen = []

    def capabilities_for(brand):
        seen.append(brand)
        return declarations

    claims = production.capability_claims(capabilities_for=capabilities_for)
    assert seen == ["pi"]
    assert claims == declarations and claims is not declarations
    claims["attach"] = False
    assert declarations["attach"] is True


@pytest.mark.parametrize("kind", ["missing", "extra", "integer", "none"])
def test_invalid_registry_claims_cannot_be_emitted(kind):
    declarations = {key: False for key in CANONICAL_CAPABILITY_IDS}
    if kind == "missing":
        declarations.pop(CANONICAL_CAPABILITY_IDS[0])
    elif kind == "extra":
        declarations["invented"] = True
    elif kind == "integer":
        declarations[CANONICAL_CAPABILITY_IDS[0]] = 1
    else:
        declarations = None
    with pytest.raises(production.PiProductionTemplateError):
        production.capability_claims(capabilities_for=lambda brand: declarations)


def test_missing_capability_source_never_falls_back_to_host_registry():
    with pytest.raises(production.PiProductionTemplateError):
        production.capability_claims(capabilities_for=None)
    with pytest.raises(TypeError):
        production.capability_claims()


def test_uncomposed_production_cli_refuses_before_writing(tmp_path):
    output = tmp_path / "deployment.json"
    result = subprocess.run([sys.executable, "-m", "ordessa_harness_pi.production",
        "--artifact-token", "pi-runtime", "--tree-digest", "sha256:" + "a" * 64,
        "--out", str(output)], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode != 0
    assert "PI_CAPABILITY_SOURCE_REQUIRED" in result.stderr
    assert not output.exists()


def test_deployment_preserves_original_pi_fields_and_pin():
    claims = {key: False for key in CANONICAL_CAPABILITY_IDS}
    deployment = production.deployment_document(artifact_token="pi-runtime",
        tree_digest="sha256:" + "a" * 64, capabilities_for=lambda brand: claims)
    assert deployment["schemaVersion"] == 1
    harness, = deployment["harnesses"]
    assert harness["id"] == "pi"
    assert harness["capabilityClaims"] == claims
    assert harness["stateProjection"]["target"] == production.STATE_TARGET
    assert harness["sessionStore"] == {"kind": "sessions-subtree"}
    assert production.ADAPTER_VERSION == "0.5.0"


def test_registration_and_context_factories_return_original_objects():
    adapters = configuration_adapters()
    assert len(adapters) == 1
    assert adapters[0].descriptor == descriptor()
    assert configuration_adapters()[0] is not adapters[0]
    context = object()
    arguments = []

    def context_factory(*args, **kwargs):
        arguments.append((args, kwargs))
        return context

    snapshot = object()
    assert PiLiveModelContext(snapshot, context_factory=context_factory,
                              credential_binding=None) is context
    assert arguments == [((snapshot,), {"credential_binding": None})]


def test_model_choice_adapter_requires_explicit_brand_dependencies():
    with pytest.raises(ValueError):
        ModelChoiceAdapter(descriptor=descriptor(), local_adapter=None,
            compile_native=None, project_mount=None, target_handle_id="pi.models.json",
            minimum_native_version="0.5.0")
    with pytest.raises(ValueError):
        PiLiveModelContext(context_factory=None)


def runtime_arguments():
    return dict(target=object(), installation=Installation("pi", (0, 5, 0), (1, 0, 0),
                "fixture-installation"), private_root=Path("fixture-private-root"),
                publication_revision="publication-1", credential_binding=object())


def test_runtime_factory_keeps_pi_pin_and_original_owner_objects():
    registry, owners, original = object(), object(), object()
    arguments = runtime_arguments()
    context_factory = lambda *args, **kwargs: object()
    called = []

    def factory(*args, **kwargs):
        called.append((args, kwargs))
        return original

    assert PiLiveModelRuntime(registry, owners, **arguments, runtime_factory=factory,
                             context_factory=context_factory) is original
    assert called == [((registry, owners), {**arguments, "harness_id": "pi",
                      "native_version": (0, 5, 0), "context_factory": context_factory})]


@pytest.mark.parametrize("invalid", ["brand", "version", "publication", "context_factory", "runtime_factory"])
def test_runtime_refuses_bad_pin_or_missing_factory_before_construction(invalid):
    arguments = runtime_arguments()
    calls = []
    arguments.update(runtime_factory=lambda *args, **kwargs: calls.append(True),
                     context_factory=lambda *args, **kwargs: object())
    if invalid == "brand":
        arguments["installation"] = Installation("codex", (0, 5, 0), (1, 0, 0), "fixture")
    elif invalid == "version":
        arguments["installation"] = Installation("pi", (0, 86, 1), (1, 0, 0), "fixture")
    elif invalid == "publication":
        arguments["publication_revision"] = ""
    else:
        arguments[invalid] = None
    with pytest.raises(ValueError):
        PiLiveModelRuntime(object(), object(), **arguments)
    assert calls == []


@pytest.mark.parametrize("missing", ["runtime_factory", "context_factory", "action_grant_factory", "service_factory"])
def test_missing_service_dependency_is_rejected_before_carrier_or_journal(missing, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No carrier access, journal or runtime construction expected")

    monkeypatch.setattr(service, "OperationJournal", forbidden)
    factories = dict.fromkeys(("runtime_factory", "context_factory", "action_grant_factory", "service_factory"), forbidden)
    factories[missing] = None
    with pytest.raises(ValueError):
        service.create_model_service(registry=object(), owners=object(), target=object(),
            carrier=SimpleNamespace(contributions=forbidden), installation=object(),
            journal_path="unused.sqlite", descriptor_admission=lambda *args: None, **factories)


def test_service_preserves_publication_grant_journal_and_runtime_identity(tmp_path, monkeypatch):
    registry, owners, target, owner = object(), object(), object(), object()
    original_runtime, original_grant, original_service, original_journal = (object() for _ in range(4))
    published_descriptor = descriptor()
    view = SimpleNamespace(payload=SimpleNamespace(descriptor=published_descriptor),
        owner=owner, publication_token="publication-1")
    carrier = SimpleNamespace(contributions=lambda point: (view,) if point == "harness.configuration-adapters" else ())
    installation = Installation("pi", (0, 5, 0), (1, 0, 0), "fixture-installation")
    journal_path = tmp_path / "journal.sqlite"
    calls = {}

    def runtime_factory(*args, **kwargs):
        calls["runtime"] = (args, kwargs)
        return original_runtime

    def grant_factory(*args):
        calls["grant"] = args
        return original_grant

    def service_factory(**kwargs):
        calls["service"] = kwargs
        return original_service

    def journal_factory(path):
        calls["journal"] = path
        return original_journal

    context_factory = lambda *args, **kwargs: object()
    def descriptor_admission(payload, published_owner, point):
        assert payload is view.payload and published_owner is owner
        assert point == "harness.configuration-adapters"
        return published_descriptor

    # The injected admitted snapshot, not the mutable author payload, governs selection.
    view.payload.descriptor = SimpleNamespace(adapter_id="mutated-author-descriptor")
    monkeypatch.setattr(service, "OperationJournal", journal_factory)
    result = service.create_model_service(registry=registry, owners=owners, target=target,
        carrier=carrier, installation=installation, journal_path=journal_path,
        runtime_factory=runtime_factory, context_factory=context_factory,
        action_grant_factory=grant_factory, service_factory=service_factory,
        descriptor_admission=descriptor_admission)
    assert result == (original_service, original_runtime)
    assert calls["grant"] == (target, owner, "publication-1", "assets.model-provider",
                             "choice", "1", "acp.session.set-config-option", "1")
    assert calls["journal"] == journal_path and not journal_path.exists()
    assert calls["service"] == {"principal": "profile-owner", "target": target,
        "carrier": carrier, "runtime": original_runtime, "permits": None,
        "owner_application": True, "journal": original_journal,
        "action_executor": original_runtime, "action_grants": (original_grant,),
        "descriptor_admission": descriptor_admission}
    assert calls["runtime"][0] == (registry, owners)
    assert calls["runtime"][1]["context_factory"] is context_factory
    assert calls["runtime"][1]["private_root"] == tmp_path / "unused-live-generations"
