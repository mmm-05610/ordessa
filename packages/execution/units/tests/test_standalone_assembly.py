"""Units-owned assembly binds original stores without owning host paths."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_units.definitions.admission_identity import AdmissionNamespace
from ordessa_units.admission.owner_selection import (
    AgentOwnerInputs,
    AgentOwnerUnavailable,
    FreshUnitFactory,
)
from ordessa_units.assembly import AssembledUnitOwner, assemble_unit_owner
from ordessa_units.persistence.sqlite.store import SqliteUnitStore
from ordessa_units.records import OperationJournal


class _InvocationAuthority:
    def __init__(self, store):
        self.store = store
        self.authorize_calls = 0

    @property
    def issuer_ref(self):
        return {"environmentNamespace": "env", "issuerId": "existing-fixture-owner"}

    def authorize(self, *args, **kwargs):
        self.authorize_calls += 1
        return None

    def revalidate(self, *args, **kwargs):
        return None


class _CurrentState:
    def __init__(self, store):
        self.store = store
        self.environment_namespace = "env"

    def inspect(self, *args, **kwargs):
        return None


class _Evidence:
    def __init__(self):
        self.records = None

    def verify_binding(self, *args, **kwargs):
        return {}

    def attach_owner(self, records):
        if self.records is not None and self.records is not records:
            raise RuntimeError("Cannot replace original UnitRecords owner")
        self.records = records


class _ScopeAuthority:
    def issue_scope(self, *args, **kwargs):
        return None

    def verify_scope(self, *args, **kwargs):
        return True

    def map_legacy_scope(self, *args, **kwargs):
        return None


class _Epoch:
    def current_epoch(self, *args, **kwargs):
        return 0


class _PreparationContext:
    def __init__(self, admission):
        self.admission = admission

    def resolve(self, *args, **kwargs):
        return None


def _assembly_inputs(store):
    admission = SimpleNamespace(
        _store=store,
        store_port=store,
        environment_id="env",
        environment_namespace="env",
        check_open=lambda: None,
    )
    authority = _InvocationAuthority(store)
    current_state = _CurrentState(store)
    evidence = _Evidence()
    revoked = []
    inputs = AgentOwnerInputs(
        authority=authority,
        current_state=current_state,
        scope_authority=_ScopeAuthority(),
        native_session_evidence=evidence,
        management_epoch=_Epoch(),
        preparation_context_port=_PreparationContext(admission),
        fresh_unit_factory=FreshUnitFactory(lambda *_args: None),
        close=lambda: revoked.append("owner"),
    )
    return admission, inputs, evidence, revoked


def _journal(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(mode=0o600, exist_ok=False)
    return OperationJournal(path)


def test_assembly_binds_single_original_store_records_and_manager(tmp_path):
    store = SqliteUnitStore(tmp_path / "core.sqlite")
    admission, inputs, evidence, revoked = _assembly_inputs(store)
    journal = _journal(tmp_path / "owner" / "operations.sqlite")

    owner = assemble_unit_owner(admission, inputs, journal=journal)

    assert isinstance(owner, AssembledUnitOwner)
    assert owner.issuer._store is store
    assert owner.records.journal is journal
    assert owner.records.verifier is owner.verifier
    assert owner.ports.provider_view.records is owner.records
    assert owner.ports.provider_view.verifier is owner.verifier
    assert owner.ports.unit_manager.records is owner.records
    assert owner.ports.unit_manager.verifier is owner.verifier
    assert evidence.records is owner.records
    assert owner.ports.unit_manager.list() == ()
    assert inputs.authority.authorize_calls == 0

    owner.revoke()
    owner.revoke()
    assert revoked == ["owner"]
    assert owner.issuer._closed is True
    assert journal.preopened_file_identity_valid
    assert not store._connection_closed
    store.close()


def test_assembly_refuses_selection_bound_to_another_store_without_closing_inputs(tmp_path):
    original_store = SqliteUnitStore(tmp_path / "original.sqlite")
    foreign_store = SqliteUnitStore(tmp_path / "foreign.sqlite")
    admission, inputs, evidence, _revoked = _assembly_inputs(original_store)
    foreign_admission = SimpleNamespace(
        _store=foreign_store,
        store_port=foreign_store,
        environment_id="env",
        environment_namespace="env",
        check_open=lambda: None,
    )
    journal = _journal(tmp_path / "foreign-owner" / "operations.sqlite")

    try:
        with pytest.raises(AgentOwnerUnavailable, match="another original store"):
            assemble_unit_owner(foreign_admission, inputs, journal=journal)
        assert journal.preopened_file_identity_valid
        assert evidence.records is None
        assert not original_store._connection_closed
        assert not foreign_store._connection_closed
    finally:
        original_store.close()
        foreign_store.close()


def test_failed_reassembly_revokes_only_new_issuer_and_preserves_original_owner(tmp_path, monkeypatch):
    from dataclasses import replace

    import ordessa_units.assembly.owner as owner_module

    store = SqliteUnitStore(tmp_path / "core.sqlite")
    admission, inputs, evidence, _revoked = _assembly_inputs(store)
    journal = _journal(tmp_path / "owner" / "operations.sqlite")
    original = assemble_unit_owner(admission, inputs, journal=journal)
    second_evidence = _Evidence()
    second_inputs = replace(inputs, native_session_evidence=second_evidence)
    created = []
    issuer_type = owner_module.InvocationIssuer

    def track_issuer(*args, **kwargs):
        issuer = issuer_type(*args, **kwargs)
        created.append(issuer)
        return issuer

    monkeypatch.setattr(owner_module, "InvocationIssuer", track_issuer)
    with pytest.raises(AgentOwnerUnavailable, match="already has a fresh Unit Manager binding"):
        assemble_unit_owner(admission, second_inputs, journal=journal)

    assert len(created) == 1 and created[0]._closed is True
    assert evidence.records is original.records
    assert second_evidence.records is None
    assert journal.preopened_file_identity_valid
    assert original.ports.unit_manager.records is original.records
    assert not store._connection_closed
    original.revoke()
    store.close()
