"""Fixed local-state checks over real Environment and scoped owner facts."""
from types import SimpleNamespace

import pytest

from ordessa_environments import EnvironmentRefused
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.admission.local_state import FixedUnitCurrentState, _same
from ordessa_units.records.unit_records import CanonicalConfigurationScopeRef, UnitRecordsRefused
from test_public_unit_api import public_units


class Catalog:
    def describe(self, definition_ref):
        raise AssertionError("this test does not resolve a provider")


class ReadStore:
    def read_operation(self, request):
        return None

    def pending_operations(self, environment_namespace):
        return ()


class ScopeCatalog:
    def __init__(self, provider_ref):
        self.provider_ref = provider_ref

    def describe(self, definition_ref):
        return SimpleNamespace(provider_ref=self.provider_ref)


class ScopeStore(ReadStore):
    def __init__(self, operation):
        self.operation = operation

    def read_operation(self, request):
        if self.operation is not None and self.operation.request == request:
            return self.operation
        return None

    def pending_operations(self, environment_namespace):
        return (self.operation,) if self.operation is not None else ()


def test_exact_comparison_supports_json_scalars_without_type_coercion():
    assert _same("owner", "owner") is True
    assert _same("owner", "other-owner") is False
    assert _same(1, True) is False


def state_for(tmp_path, public_units):
    return FixedUnitCurrentState(
        store=ReadStore(),
        harness_catalog=Catalog(),
        environment_instance=public_units.environments.instance,
        environment_namespace="env",
        root_directory=str(tmp_path / "fixed-root"),
        owner_id="unit-owner-test",
        profile_revision=public_units.revision,
        agent_id="agent",
        permission_id="permission-test",
    )


def test_fixed_private_roots_and_scope_are_exact_and_not_legacy_mapped(tmp_path, public_units):
    state = state_for(tmp_path, public_units)
    node = {"environmentNamespace": "env", "nodeId": "node-a", "generation": 1}
    roots = {key: str(tmp_path / "fixed-root" / "node-a" / key)
             for key in ("home", "cwd", "profile", "tmp")}
    directory = state.directory_ref(node, roots)
    assert directory.to_dict()["environmentNamespace"] == "env"
    assert directory.binding_id.startswith("unit-")

    provider = {"environmentNamespace": "env", "providerId": "provider-a",
                "generation": 1, "implementationDigest": "sha256:" + "a" * 64}
    scope = CanonicalConfigurationScopeRef("env", "unit-scope-test", "sha256:" + "b" * 64)
    assert state.verify_scope(scope, roots) is False
    with pytest.raises(UnitRecordsRefused, match="pending original prepare"):
        state.issue_scope(provider, node, roots)
    assert state.map_legacy_scope(object()) is None


def test_scope_verification_rechecks_the_original_operation_source(tmp_path, public_units):
    node = {"environmentNamespace": "env", "nodeId": "node-source", "generation": 1}
    roots = {key: str(tmp_path / "fixed-root" / "node-source" / key)
             for key in ("home", "cwd", "profile", "tmp")}
    provider = {"environmentNamespace": "env", "providerId": "provider-a",
                "generation": 1, "implementationDigest": "sha256:" + "a" * 64}
    request = RequestKey("env", "test-principal", "scope-source-1")
    context = {
        "nodeRef": node,
        "privateRootFacts": roots,
        "localUnitRun": {"ownerId": "unit-owner-test"},
        "harnessDefinitionRef": {"environmentNamespace": "env", "definitionId": "fixed"},
    }
    operation = SimpleNamespace(
        request=request,
        intent=SimpleNamespace(
            context_ref=context,
            steps=(SimpleNamespace(pinned_provider_ref=provider),),
        ),
    )
    store = ScopeStore(operation)
    state = FixedUnitCurrentState(
        store=store,
        harness_catalog=ScopeCatalog(provider),
        environment_instance=public_units.environments.instance,
        environment_namespace="env",
        root_directory=str(tmp_path / "fixed-root"),
        owner_id="unit-owner-test",
        profile_revision=public_units.revision,
        agent_id="agent",
        permission_id="permission-test",
    )

    scope = state.issue_scope(provider, node, roots)
    assert state.verify_scope(scope, roots) is True

    store.operation = None
    assert state.verify_scope(scope, roots) is False

    changed_context = {**context, "privateRootFacts": {**roots, "cwd": str(tmp_path / "elsewhere")}}
    store.operation = SimpleNamespace(
        request=request,
        intent=SimpleNamespace(
            context_ref=changed_context,
            steps=(SimpleNamespace(pinned_provider_ref=provider),),
        ),
    )
    assert state.verify_scope(scope, roots) is False


def test_private_root_symlink_escape_and_unknown_epoch_are_refused(tmp_path, public_units):
    state = state_for(tmp_path, public_units)
    node = {"environmentNamespace": "env", "nodeId": "node-link", "generation": 1}
    base = tmp_path / "fixed-root" / "node-link"
    base.parent.mkdir(parents=True)
    base.symlink_to(tmp_path, target_is_directory=True)
    roots = {key: str(base / key) for key in ("home", "cwd", "profile", "tmp")}
    with pytest.raises(UnitRecordsRefused):
        state.directory_ref(node, roots)
    with pytest.raises(UnitRecordsRefused):
        state.directory_ref({"environmentNamespace": "env", "nodeId": "../outside",
                             "generation": 1}, roots)
    with pytest.raises(UnitRecordsRefused, match="original operation"):
        state.current_epoch(node)


def test_environment_use_check_binds_live_handle_identity_and_generation(public_units):
    environment = public_units.environments.instance
    use = environment.acquire("local-state-test", sharing=True)
    public_units.extra_uses.append(use)
    snapshot = environment.snapshot
    assert use.check(environment.identity, snapshot.generation) is True
    with pytest.raises(EnvironmentRefused):
        use.check("environment/foreign", snapshot.generation)
    with pytest.raises(EnvironmentRefused):
        use.check(environment.identity, snapshot.generation + 1)
