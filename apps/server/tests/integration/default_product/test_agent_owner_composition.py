"""Default product does not manufacture or select an Agent owner."""

from __future__ import annotations

from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot
from ordessa_server.composition.configuration.product_selection import (
    bind_product_harness_effects,
    create_host_product_composition,
)

from pathlib import Path
import sqlite3
import pytest

from ordessa_units.definitions.admission_identity import AdmissionNamespace
from ordessa_units.public import AgentOwnerInputs
from ordessa_units.public import (
    AgentOwnerUnavailable, validate_agent_owner_selection,
)
from ordessa_server.composition.agent_owner import assemble_agent_owner
from ordessa_server_product.composition import ServerProductComposition
from ordessa_server.composition.configuration.product_selection import create_host_product_composition as create_composition
from ordessa_units.public import unit_services
from pacthold.public import Environment
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from ordessa_server.composition.runtime import DataRootOwner
from server_plugin_api import OwnedRootBinding


class _Policy:
    def admit_invoke(self, principal, surface, guarantee):
        return True

    def admit_object_access(self, principal, object_ref, mode):
        return True


class _Authority:
    issuer_ref = {"environmentNamespace": "owner-test", "issuerId": "controlled"}

    def authorize(self, request, actions, target_ref, delegation_ref):
        return None

    def revalidate(self, grant, request, actions, target_ref):
        return None


class _CurrentState:
    def inspect(self, request, pinned_provider_ref, context_ref, target_ref, action):
        return None


class _Port:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class _ProductEnvironment(Environment):
    def __init__(self, store, store_path, journal_path):
        super().__init__("owner-test", policy=_Policy(), store=store,
            fingerprint_port=ProtectedFingerprintHmac(
                {"controlled": b"owner-composition-test-key"}, active_key_id="controlled"), resource_extension_snapshot=_test_resource_snapshot)
        self._product_store = store
        self.store_path = store_path
        self.agent_journal_path = journal_path

    @property
    def store_port(self):
        return self._product_store


def _owner_inputs(*, close=None, managed_capture_content_port=None,
                  workspace_execution_port=None):
    from ordessa_harness_codex import CodexRuntimeProvider

    def provider_factory(environment_id, provider_view):
        return CodexRuntimeProvider(
            definition_ref={"environmentNamespace": environment_id.value,
                "definitionId": "controlled-codex", "revision": "1"},
            implementation_digest="sha256:" + "a" * 64,
            unit_records=provider_view.records, verifier=provider_view.verifier)

    return AgentOwnerInputs(
        authority=_Authority(), current_state=_CurrentState(),
        scope_authority=_Port(), native_session_evidence=_Port(),
        management_epoch=_Port(), node_evidence_port=_Port(),
        preparation_context_port=_Port(), preparation_observation_port=_Port(),
        provider_factory=provider_factory, managed_capture_content_port=managed_capture_content_port,
        workspace_execution_port=workspace_execution_port, close=close)


def test_default_product_has_no_owner_and_does_not_select_codex():
    product = create_composition()
    assert product._agent_owner_inputs is None
    assert all(plugin.descriptor().id != "codex" for plugin in product.default_plugins())


def test_incomplete_explicit_owner_is_refused_before_runtime_composition():
    with pytest.raises(AgentOwnerUnavailable):
        bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, fingerprint_port=object(), agent_owner_inputs=object()))


def test_explicit_owner_uses_one_environment_store_records_verifier_and_service_cache(tmp_path):
    data_root = tmp_path / "data"
    root_owner = DataRootOwner(data_root)
    root_owner.acquire()
    store_path = data_root / "state" / "core.sqlite"
    store = SqliteStorePort(store_path)
    journal_path = data_root / "state" / "agent-owner" / "operations.sqlite"
    binding = root_owner.bind_owned_root(root_path=data_root, store_path=store_path,
                                         child_path=journal_path)
    environment = _ProductEnvironment(store, store_path, journal_path)
    capture_content, workspace_execution = _Port(), _Port()
    owner = assemble_agent_owner(environment, _owner_inputs(
        managed_capture_content_port=capture_content,
        workspace_execution_port=workspace_execution), binding, root_port=root_owner)
    environment.owner_ports = owner.ports
    try:
        assert owner.issuer._store is store is environment._store
        assert owner.records.journal is owner.journal
        assert owner.records.verifier is owner.verifier
        assert owner.ports.provider_view.records is owner.records
        assert owner.ports.provider_view.verifier is owner.verifier
        assert owner.ports.managed_capture_content_port is capture_content
        assert owner.ports.workspace_execution_port is workspace_execution

        services = unit_services(environment, owner_ports=owner.ports)
        assert unit_services(environment) is services
        with pytest.raises(ValueError, match="overridden"):
            unit_services(environment, invocation_issuer=owner.issuer)

        product = create_host_product_composition(
            fingerprint_port=environment._fingerprint_port,
            agent_owner_inputs=_owner_inputs())
        assert any(plugin.descriptor().id == "codex" for plugin in product.default_plugins())
        provider = product._codex_provider_factory(
            AdmissionNamespace(environment.environment_id), owner.ports.provider_view)
        assert provider.records is owner.records
        assert provider.verifier is owner.verifier
        assert "start" not in provider.descriptor.supported_methods
        assert "apply_configuration" not in provider.descriptor.supported_methods
    finally:
        owner.revoke()
        environment.close()
        store.close()
        root_owner.release()


def test_fresh_owner_without_capture_and_workspace_ports_keeps_turn_schema_off(tmp_path):
    data_root = tmp_path / "data"
    root_owner = DataRootOwner(data_root)
    root_owner.acquire()
    store_path = data_root / "state" / "core.sqlite"
    store = SqliteStorePort(store_path)
    journal_path = data_root / "state" / "agent-owner" / "operations.sqlite"
    binding = root_owner.bind_owned_root(root_path=data_root, store_path=store_path,
                                         child_path=journal_path)
    environment = _ProductEnvironment(store, store_path, journal_path)
    owner = assemble_agent_owner(environment, _owner_inputs(), binding, root_port=root_owner)
    try:
        assert not owner.records.managed_turn_available
        with sqlite3.connect(journal_path) as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "harness_managed_turn_attempts" not in tables
    finally:
        owner.revoke()
        environment.close()
        store.close()
        root_owner.release()


def test_agent_product_direct_factory_without_root_proof_has_no_filesystem_effects(tmp_path):
    root = tmp_path / "unowned"
    product = bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, 
        fingerprint_port=ProtectedFingerprintHmac(
            {"controlled": b"direct-factory-test-key"}, active_key_id="controlled"),
        agent_owner_inputs=_owner_inputs()))
    with pytest.raises(AgentOwnerUnavailable, match="root ownership proof"):
        product.environment_factory(root / "state" / "core.sqlite")
    assert not root.exists()


def test_boolean_owner_probe_is_not_an_agent_storage_proof(tmp_path):
    root = tmp_path / "bool-only"
    product = bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, 
        fingerprint_port=ProtectedFingerprintHmac(
            {"controlled": b"bool-only-test-key"}, active_key_id="controlled"),
        agent_owner_inputs=_owner_inputs()))
    with pytest.raises(AgentOwnerUnavailable, match="host root ownership proof"):
        product.owned_environment_factory(root / "state" / "core.sqlite", lambda: True)
    assert not root.exists()


def test_v29_caller_forged_binding_refuses_before_filesystem_effects(tmp_path):
    root = tmp_path / "forged"
    store_path = root / "state" / "core.sqlite"
    child_path = root / "state" / "agent-owner" / "operations.sqlite"

    class ForgedRootPort:
        def bind_owned_root(self, *, root_path, store_path, child_path):
            # Exact V29 attack: public DTO plus caller-controlled always-true validator.
            return OwnedRootBinding(root_path, store_path, child_path, lambda: True)

    product = bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, 
        fingerprint_port=ProtectedFingerprintHmac(
            {"controlled": b"forged-binding-test-key"}, active_key_id="controlled"),
        agent_owner_inputs=_owner_inputs()))
    with pytest.raises(AgentOwnerUnavailable, match="host root ownership proof"):
        product.owned_environment_factory(store_path, ForgedRootPort())
    assert not root.exists()
    assert not store_path.exists()
    assert not child_path.exists()


def test_structural_binding_lookalike_refuses_before_filesystem_effects(tmp_path):
    root = tmp_path / "lookalike"
    store_path = root / "state" / "core.sqlite"
    child_path = root / "state" / "agent-owner" / "operations.sqlite"

    class ForgedBinding:
        def validate_for(self, **_kwargs):
            return None

    class ForgedRootPort:
        def bind_owned_root(self, **_kwargs):
            return ForgedBinding()

    product = bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, 
        fingerprint_port=ProtectedFingerprintHmac(
            {"controlled": b"lookalike-binding-test-key"}, active_key_id="controlled"),
        agent_owner_inputs=_owner_inputs()))
    with pytest.raises(AgentOwnerUnavailable, match="root ownership proof"):
        product.owned_environment_factory(store_path, ForgedRootPort())
    assert not root.exists()
    assert not store_path.exists()
    assert not child_path.exists()


def test_cross_root_proof_refuses_before_product_database_effects(tmp_path):
    owned_root = tmp_path / "owned"
    other_root = tmp_path / "other"
    host_owner = DataRootOwner(owned_root)
    host_owner.acquire()
    product = bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, 
        fingerprint_port=ProtectedFingerprintHmac(
            {"controlled": b"cross-root-test-key"}, active_key_id="controlled"),
        agent_owner_inputs=_owner_inputs()))
    try:
        with pytest.raises(AgentOwnerUnavailable, match="root ownership proof"):
            product.owned_environment_factory(other_root / "state" / "core.sqlite", host_owner)
        assert not other_root.exists()
    finally:
        host_owner.release()


@pytest.mark.parametrize("record_kind", ["wrong-schema", "symlink"])
def test_preexisting_journal_refuses_before_core_database_effects(tmp_path, record_kind):
    root = tmp_path / record_kind
    owner = DataRootOwner(root)
    owner.acquire()
    (root / "state" / "agent-owner").mkdir(parents=True, mode=0o700)
    store_path = root / "state" / "core.sqlite"
    journal_path = root / "state" / "agent-owner" / "operations.sqlite"
    sentinel = b"sqlite sentinel bytes with wrong schema"
    if record_kind == "wrong-schema":
        with sqlite3.connect(journal_path) as connection:
            for name in (
                "plans", "operations", "native_evidence", "native_verifications",
                "harness_unit_reservations", "harness_unit_sessions",
                "harness_unit_confirmations", "harness_unit_configuration_attempts",
                "harness_unit_terminations",
            ):
                connection.execute(f"CREATE TABLE {name} (wrong_column TEXT)")
        sentinel = journal_path.read_bytes()
    else:
        target = root / "journal-sentinel"
        target.write_bytes(sentinel)
        journal_path.symlink_to(target)
    product = bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, 
        fingerprint_port=ProtectedFingerprintHmac(
            {"controlled": b"preexisting-test-key"}, active_key_id="controlled"),
        agent_owner_inputs=_owner_inputs()))
    try:
        with pytest.raises(AgentOwnerUnavailable):
            product.owned_environment_factory(store_path, owner)
        assert not store_path.exists()
        assert not Path(str(store_path) + "-wal").exists()
        assert not Path(str(store_path) + "-shm").exists()
        assert not Path(str(journal_path) + "-wal").exists()
        assert not Path(str(journal_path) + "-shm").exists()
        if record_kind == "wrong-schema":
            assert journal_path.read_bytes() == sentinel
        else:
            assert journal_path.is_symlink()
            assert journal_path.read_bytes() == sentinel
    finally:
        owner.release()


def test_product_close_revoke_is_idempotent_and_disposes_store_after_callback_error(tmp_path):
    calls = []
    def close_callback():
        calls.append("close")
        raise RuntimeError("controlled owner close failure")

    root = tmp_path / "close-owner"
    host_owner = DataRootOwner(root)
    host_owner.acquire()
    product = bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, 
        fingerprint_port=ProtectedFingerprintHmac(
            {"controlled": b"close-owner-test-key"}, active_key_id="controlled"),
        agent_owner_inputs=_owner_inputs(close=close_callback)))
    environment = None
    try:
        environment = product.owned_environment_factory(
            root / "state" / "core.sqlite", host_owner)
        assembled = environment.agent_owner
        store = environment.store_port
        with pytest.raises(RuntimeError, match="controlled owner close failure"):
            environment.close()
        assert assembled.issuer._closed is True
        assert calls == ["close"]
        environment.close()
        assert calls == ["close"]
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            with store.transaction() as connection:
                connection.execute("SELECT 1")
    finally:
        if environment is not None:
            environment.close()
        host_owner.release()


def test_owner_assembly_failure_removes_only_its_new_journal_and_closes_store(tmp_path, monkeypatch):
    import ordessa_server.composition.agent_owner as agent_owner_module

    root = tmp_path / "assembly-failure"
    host_owner = DataRootOwner(root)
    host_owner.acquire()
    product = bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, 
        fingerprint_port=ProtectedFingerprintHmac(
            {"controlled": b"assembly-failure-test-key"}, active_key_id="controlled"),
        agent_owner_inputs=_owner_inputs()))
    def fail_after_journal(*_args, **_kwargs):
        raise RuntimeError("controlled owner carrier failure")
    monkeypatch.setattr(agent_owner_module, "AgentOwnerPorts", fail_after_journal)
    store_path = root / "state" / "core.sqlite"
    journal_path = root / "state" / "agent-owner" / "operations.sqlite"
    try:
        with pytest.raises(RuntimeError, match="controlled owner carrier failure"):
            product.owned_environment_factory(store_path, host_owner)
        assert not journal_path.exists()
        assert not Path(str(journal_path) + "-wal").exists()
        assert not Path(str(journal_path) + "-shm").exists()
        reopened = SqliteStorePort(store_path, allow_takeover=False)
        reopened.close()
    finally:
        host_owner.release()



def test_public_binding_override_is_rejected_by_injected_actual_host_port(tmp_path):
    from types import SimpleNamespace
    root = tmp_path / "override-root"
    owner = DataRootOwner(root)
    owner.acquire()
    try:
        calls = []
        class Counterfeit(OwnedRootBinding):
            def validate_for(self, **kwargs):
                calls.append(kwargs)
        fake = object.__new__(Counterfeit)
        port = SimpleNamespace(bind_owned_root=lambda **kwargs: fake,
                               validate_owned_root=owner.validate_owned_root)
        product = bind_product_harness_effects(ServerProductComposition(agent_owner_validator=validate_agent_owner_selection, 
            fingerprint_port=ProtectedFingerprintHmac(
                {"controlled": b"counterfeit-test-key"}, active_key_id="controlled"),
            agent_owner_inputs=_owner_inputs()))
        store = root / "state" / "core.sqlite"
        with pytest.raises(AgentOwnerUnavailable, match="host root ownership proof"):
            product.owned_environment_factory(store, port)
        assert calls == []
        assert not store.exists()
        assert not (root / "state" / "agent-owner" / "operations.sqlite").exists()
    finally:
        owner.release()


@pytest.mark.parametrize("host_selected", [False, True])
def test_foreign_validator_never_runs_and_original_fingerprint_error_wins(host_selected):
    calls = []
    def foreign(*args):
        calls.append(args)
    factory = create_composition if host_selected else ServerProductComposition
    with pytest.raises(AgentOwnerUnavailable, match="protected fingerprint port") as error:
        factory(fingerprint_port=object(), agent_owner_inputs=_owner_inputs(),
                agent_owner_validator=foreign)
    assert error.value.code == "AGENT_OWNER_UNAVAILABLE"
    assert calls == []


@pytest.mark.parametrize("host_selected", [False, True])
def test_invalid_inputs_cannot_be_bypassed_with_valid_fingerprint(host_selected):
    calls = []
    factory = create_composition if host_selected else ServerProductComposition
    fingerprint = ProtectedFingerprintHmac({"controlled": b"owner-guard-key"}, active_key_id="controlled")
    with pytest.raises(AgentOwnerUnavailable, match="explicit AgentOwnerInputs"):
        factory(fingerprint_port=fingerprint, agent_owner_inputs=object(),
                agent_owner_validator=lambda *args: calls.append(args))
    assert calls == []


@pytest.mark.parametrize("field", ["authority", "current_state", "provider_factory", "scope_authority",
    "native_session_evidence", "management_epoch", "node_evidence_port", "preparation_context_port",
    "preparation_observation_port", "close", "configuration_evidence"])
def test_complete_original_owner_input_checks_cannot_be_overridden(field):
    from dataclasses import replace
    fingerprint = ProtectedFingerprintHmac({"controlled": b"owner-guard-key"}, active_key_id="controlled")
    inputs = replace(_owner_inputs(), **{field: object() if field in {"close", "configuration_evidence"} else None})
    called = []
    with pytest.raises(AgentOwnerUnavailable) as error:
        ServerProductComposition(fingerprint_port=fingerprint, agent_owner_inputs=inputs,
                                 agent_owner_validator=lambda *args: called.append(args))
    assert error.value.code == "AGENT_OWNER_UNAVAILABLE"
    assert called == []


@pytest.mark.parametrize("host_selected", [False, True])
def test_valid_owner_inputs_still_cannot_select_foreign_validator(host_selected):
    fingerprint = ProtectedFingerprintHmac({"controlled": b"owner-guard-key"}, active_key_id="controlled")
    called = []
    factory = create_composition if host_selected else ServerProductComposition
    with pytest.raises(AgentOwnerUnavailable, match="validator override"):
        factory(fingerprint_port=fingerprint, agent_owner_inputs=_owner_inputs(),
                agent_owner_validator=lambda *args: called.append(args))
    assert called == []


def test_mutated_selected_input_is_rechecked_before_any_host_store_or_root_effect(tmp_path):
    inputs = _owner_inputs()
    fingerprint = ProtectedFingerprintHmac({"controlled": b"owner-guard-key"}, active_key_id="controlled")
    product = create_composition(fingerprint_port=fingerprint, agent_owner_inputs=inputs)
    object.__setattr__(inputs, "authority", None)
    root = tmp_path / "never-created"
    with pytest.raises(AgentOwnerUnavailable, match="invocation authority"):
        product.environment_factory(root / "state" / "core.sqlite")
    with pytest.raises(AgentOwnerUnavailable, match="invocation authority"):
        product.owned_environment_factory(root / "state" / "core.sqlite", object())
    assert not root.exists()
