"""Cold-context Profile bootstrap; no native Unit or Pi process is started."""
from copy import copy
from dataclasses import dataclass, replace
from pathlib import Path
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
import time

import pytest

from ordessa_agents.harness.providers.registry import (
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
)
from ordessa_environments import (
    EnvironmentManager, EnvironmentRefused, SQLiteEnvironmentStore,
)
from ordessa_environments_local import LocalEnvironmentResourceProvider
from ordessa_agents.profiles import ProfileService
from ordessa_interfaces.system_access.access_control import AccessError, AccessGrant
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_units.public import UnitAdmissionContext
from ordessa_server.composition.configuration.product_selection import create_host_product_composition
from ordessa_server.composition.product_native_provider import (
    NativeProviderInputsUnavailable,
    construct_product_native_provider_inputs,
)


_ACTIONS = frozenset({"prepare", "start", "interaction", "stop", "release"})
_CAPABILITIES = frozenset("execution.units." + action for action in _ACTIONS)


def _fingerprint():
    return ProtectedFingerprintHmac({"controlled": b"k" * 32}, active_key_id="controlled")


@dataclass
class _Case:
    runtime: object
    fingerprint: object
    principal: object
    scope: Scope
    arguments: dict


def _case(tmp_path, *, with_fingerprint=True, grant_capabilities=True, foreign_principal=False):
    root = (tmp_path / "server").resolve()
    fingerprint = _fingerprint() if with_fingerprint else None
    runtime = create_host_product_composition(
        fingerprint_port=fingerprint,
    ).default_runtime(root)
    context = runtime.unit_runtime.context
    assert isinstance(context, UnitAdmissionContext)
    authority = runtime.wire.identity_authority
    scope = Scope(context.environment_namespace, "first-case")
    grants = (AccessGrant(scope, tuple(sorted(_CAPABILITIES))),) if grant_capabilities else ()
    authority.replace_grants(grants)
    principal = authority.authenticate("Bearer " + runtime.token)
    if foreign_principal:
        other = InstanceAccessAuthority(lambda: runtime.token, grants=())
        principal = other.authenticate("Bearer " + runtime.token)

    definition = {
        "environmentNamespace": context.environment_namespace,
        "definitionId": "pi",
        "revision": "1",
    }
    declaration = HarnessDefinitionDeclaration(
        HarnessDefinitionDescriptor(
            "pi", definition, "sha256:" + "b" * 64, "acp/v1", "controlled", "controlled",
            ("prepare", "start", "stop", "release"),
        ),
        lambda expected: None,
    )
    environment_root = (tmp_path / "environment-root").resolve()
    environment_root.mkdir()
    unit_root = (tmp_path / "unit-root").resolve()
    unit_root.mkdir()
    environment_store = (tmp_path / "environment.sqlite").resolve()
    profile_content = {
        "schemaVersion": "1",
        "harnessDefinitionRef": definition,
        "declarations": [{
            "declarationId": "selected-model",
            "configurationKind": "assets.model-provider",
            "schemaVersion": "1",
            "action": "value",
            "requirement": "required",
            "payload": {
                "provider": "opencode",
                "model": "step-5-preview-free",
                "protocol": "openai-chat",
                "endpoint": "https://opencode.ai/zen/v1",
            },
        }],
    }
    arguments = {
        "project_id": "first-case",
        "principal": principal,
        "profile_id": "first-case-profile",
        "profile_name": "First case profile",
        "profile_content": profile_content,
        "profile_request_id": "create-first-case-profile",
        "environment_store_path": str(environment_store),
        "environment_root": str(environment_root),
        "unit_root_directory": str(unit_root),
        "unit_actions": _ACTIONS,
        "joint_capabilities": _CAPABILITIES,
        "permission_expires_at": time.time() + 60,
        "agent_id": "first-case-agent",
        "sharing": True,
        "model_declaration_id": "selected-model",
        "provider": "opencode",
        "model": "step-5-preview-free",
        "model_catalogue": ("step-5-preview-free",),
        "native_model_definition": {
            "provider": "opencode",
            "id": "step-5-preview-free",
        },
        "declaration": declaration,
        "fingerprint": fingerprint,
        "bridge_executable": "/controlled/pi-acp-bridge",
        "bridge_sha256": "a" * 64,
        "pi_executable": "/controlled/pi",
        "credential_source": "/controlled/credential-reference",
    }
    return _Case(runtime, fingerprint, principal, scope, arguments)


def _profiles(case):
    return ProfileService(UnitProfileAdmission(case.runtime.unit_runtime.context))


def test_cold_product_context_creates_persisted_profile_on_its_original_store(tmp_path):
    case = _case(tmp_path)
    try:
        result = construct_product_native_provider_inputs(case.runtime, **case.arguments)
        context = case.runtime.unit_runtime.context
        assert type(result.profile_service) is ProfileService
        assert result.profile_service.environment_namespace == context.environment_namespace
        assert result.profile.current_revision == result.profile_revision.ref
        assert result.profile_revision.ref.environment_namespace == context.environment_namespace
        assert result.profile_service.get_revision(result.profile.current_revision) == result.profile_revision
        permission = result.ports.permission_factory(
            runtime=case.runtime,
            admission_context=context,
            selection=result.selection,
            environment_instance=result.environment_instance,
        )
        assert permission.access_authority is case.runtime.wire.identity_authority
        assert permission.profile_revision == result.profile_revision.ref
        assert context.owner_ports is None
        assert getattr(case.runtime, "units", None) is None
        assert getattr(case.runtime, "unit_execution_owner", None) is None
        assert _profiles(case).get("first-case-profile") == result.profile
    finally:
        case.runtime.stop()


def test_environment_manager_get_fresh_view_is_proved_against_original_snapshot(tmp_path):
    case = _case(tmp_path)
    try:
        inputs = construct_product_native_provider_inputs(case.runtime, **case.arguments)
        fresh_view = inputs.environment_manager.get(inputs.environment_instance.identity)
        assert fresh_view is not inputs.environment_instance
        assert fresh_view.identity == inputs.environment_instance.identity
        permission = inputs.ports.permission_factory(
            runtime=case.runtime,
            admission_context=case.runtime.unit_runtime.context,
            selection=inputs.selection,
            environment_instance=fresh_view,
        )
        assert permission.access_authority is case.runtime.wire.identity_authority
        assert permission.environment_identity == inputs.environment_instance.identity
    finally:
        case.runtime.stop()


@pytest.mark.parametrize("view_kind", ["foreign-manager", "copy"])
def test_environment_permission_factory_rejects_unissued_or_foreign_view(tmp_path, view_kind):
    case = _case(tmp_path)
    try:
        inputs = construct_product_native_provider_inputs(case.runtime, **case.arguments)
        if view_kind == "foreign-manager":
            # This manager shares the same SQLite store/provider, but did not
            # issue the selected original Environment view.
            foreign_manager = EnvironmentManager(
                store=inputs.environment_manager.store,
                providers=inputs.environment_manager.providers,
            )
            view = foreign_manager.get(inputs.environment_instance.identity)
        else:
            view = copy(inputs.environment_instance)
        with pytest.raises(
                NativeProviderInputsUnavailable,
                match="selected Environment view differs from its confirmed original resource"):
            inputs.ports.permission_factory(
                runtime=case.runtime,
                admission_context=case.runtime.unit_runtime.context,
                selection=inputs.selection,
                environment_instance=view,
            )
    finally:
        case.runtime.stop()


def test_environment_manager_rejects_wrong_selected_generation(tmp_path):
    case = _case(tmp_path)
    try:
        inputs = construct_product_native_provider_inputs(case.runtime, **case.arguments)
        selected = inputs.environment_instance.inspect()
        wrong_generation = replace(selected, generation=selected.generation + 1)
        with pytest.raises(EnvironmentRefused):
            inputs.environment_manager.validate_instance(
                inputs.environment_instance, expected_snapshot=wrong_generation,
            )
    finally:
        case.runtime.stop()


def test_product_native_inputs_reuse_confirmed_environment_without_create(tmp_path, monkeypatch):
    case = _case(tmp_path)
    try:
        original = construct_product_native_provider_inputs(case.runtime, **case.arguments)
        manager = original.environment_manager
        original_snapshot = original.environment_snapshot
        original_resource = manager.store.snapshot(original_snapshot.identity)

        def forbidden_create(*_args, **_kwargs):
            raise AssertionError("existing Environment selection must not create")

        monkeypatch.setattr(manager, "create", forbidden_create)
        arguments = dict(case.arguments)
        arguments.update({
            "profile_id": "first-case-profile-reuse",
            "profile_request_id": "create-first-case-profile-reuse",
            "existing_environment_manager": manager,
            "selected_environment_snapshot": original_snapshot,
        })
        selected = construct_product_native_provider_inputs(case.runtime, **arguments)
        assert selected.environment_manager is manager
        assert selected.environment_instance.identity == original.environment_instance.identity
        assert selected.environment_snapshot.generation == original_snapshot.generation
        assert manager.store.snapshot(original_snapshot.identity) == original_resource
        assert selected.selection.environment_id == original.selection.environment_id
        assert selected.profile.current_revision == selected.profile_revision.ref
    finally:
        case.runtime.stop()


@pytest.mark.parametrize("missing", ["manager", "snapshot"])
def test_existing_environment_selection_requires_complete_pair_before_profile_write(
        tmp_path, missing):
    case = _case(tmp_path)
    try:
        original = construct_product_native_provider_inputs(case.runtime, **case.arguments)
        arguments = dict(case.arguments)
        arguments.update({
            "profile_id": "first-case-profile-incomplete-pair",
            "profile_request_id": "create-first-case-profile-incomplete-pair",
            "existing_environment_manager": original.environment_manager,
            "selected_environment_snapshot": original.environment_snapshot,
        })
        arguments.pop("existing_environment_manager" if missing == "manager"
                      else "selected_environment_snapshot")
        with pytest.raises(
                NativeProviderInputsUnavailable,
                match="existing Environment selection requires both its original manager and confirmed snapshot"):
            construct_product_native_provider_inputs(case.runtime, **arguments)
        profiles = _profiles(case)
        assert profiles.get("first-case-profile") == original.profile
        assert profiles.list() == (original.profile,)
    finally:
        case.runtime.stop()


@pytest.mark.parametrize("proof", ["wrong-generation", "foreign-manager-snapshot"])
def test_existing_environment_selection_rejects_invalid_snapshot_before_profile_write(
        tmp_path, proof):
    case = _case(tmp_path)
    try:
        original = construct_product_native_provider_inputs(case.runtime, **case.arguments)
        snapshot = original.environment_snapshot
        if proof == "wrong-generation":
            snapshot = replace(snapshot, generation=snapshot.generation + 1)
        else:
            foreign_store = SQLiteEnvironmentStore(str((tmp_path / "foreign.sqlite").resolve()))
            foreign_manager = EnvironmentManager(
                store=foreign_store,
                providers={"local": LocalEnvironmentResourceProvider(
                    default_root=str((tmp_path / "foreign-environment-root").resolve()),
                )},
            )
            foreign_root = tmp_path / "foreign-environment-root"
            foreign_root.mkdir()
            foreign_environment = foreign_manager.create(
                "local", {"isolation": "none", "root": str(foreign_root.resolve())},
            )
            snapshot = foreign_environment.inspect()
        arguments = dict(case.arguments)
        arguments.update({
            "profile_id": "first-case-profile-invalid-snapshot",
            "profile_request_id": "create-first-case-profile-invalid-snapshot",
            "existing_environment_manager": original.environment_manager,
            "selected_environment_snapshot": snapshot,
        })
        with pytest.raises(
                NativeProviderInputsUnavailable,
                match="selected existing Environment snapshot is not confirmed by its original manager"):
            construct_product_native_provider_inputs(case.runtime, **arguments)
        profiles = _profiles(case)
        assert profiles.get("first-case-profile") == original.profile
        assert profiles.list() == (original.profile,)
        assert original.environment_manager.store.snapshot(
            original.environment_snapshot.identity
        ).generation == original.environment_snapshot.generation
    finally:
        case.runtime.stop()


@pytest.mark.parametrize("failure", ["missing-fingerprint", "foreign-principal", "missing-capabilities"])
def test_cold_profile_bootstrap_refuses_before_environment_or_profile_write(tmp_path, failure):
    case = _case(
        tmp_path,
        with_fingerprint=failure != "missing-fingerprint",
        grant_capabilities=failure != "missing-capabilities",
        foreign_principal=failure == "foreign-principal",
    )
    try:
        if failure == "missing-capabilities":
            with pytest.raises(AccessError):
                construct_product_native_provider_inputs(case.runtime, **case.arguments)
        else:
            with pytest.raises(NativeProviderInputsUnavailable):
                construct_product_native_provider_inputs(case.runtime, **case.arguments)
        assert not Path(case.arguments["environment_store_path"]).exists()
        assert _profiles(case).list() == ()
        assert case.runtime.unit_runtime.context.owner_ports is None
        assert getattr(case.runtime, "units", None) is None
        assert getattr(case.runtime, "unit_execution_owner", None) is None
    finally:
        case.runtime.stop()
