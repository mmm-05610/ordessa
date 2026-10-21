"""Profile admission borrows the original Unit lock and SQLite store."""
from threading import RLock

import pytest

from ordessa_agents.harness.providers.registry import HarnessCatalog
from ordessa_agents.profiles import (
    ProfileAccessRefused,
    ProfileChangeUnknown,
    ProfileService,
    ProfileStoreUnavailable,
)
from ordessa_agents.profiles.management.compatibility import PROFILE_RECORDS
from ordessa_infrastructure.database.records import DomainStorePort
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.errors import UnitOperationUnknown
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
from ordessa_units.persistence.sqlite.store import SqliteUnitStore


class Policy:
    def admit_object_access(self, *_args):
        return True

    def admit_invoke(self, *_args):
        return True


def owner(tmp_path):
    store = SqliteUnitStore(tmp_path / "original-unit.sqlite")
    lock = RLock()
    policy = Policy()
    harnesses = HarnessCatalog("profile-env", policy=policy, admission_lock=lock)
    materials = MaterialCatalog("profile-env", admission_lock=lock)
    context = UnitAdmissionContext(
        "profile-env",
        store=store,
        policy=policy,
        fingerprint_port=ProtectedFingerprintHmac(
            {"test": b"unit-profile-admission"}, active_key_id="test"
        ),
        harness_catalog=harnesses,
        material_catalog=materials,
        principal_scope="profile-test",
        admission_lock=lock,
    )
    adapter = UnitProfileAdmission(context)
    return context, adapter, ProfileService(adapter), store, lock, harnesses, materials


def sample_content():
    return {
        "schemaVersion": "1",
        "harnessDefinitionRef": {
            "environmentNamespace": "profile-env",
            "definitionId": "fixture",
            "revision": "1",
        },
        "declarations": [],
    }


def close_owner(context, store, harnesses, materials):
    context.close()
    harnesses.close()
    materials.close()
    store.close()


def test_profiles_use_same_unit_lock_and_atomic_sqlite_authority(tmp_path):
    context, adapter, profiles, store, lock, harnesses, materials = owner(tmp_path)
    try:
        assert adapter.unit_context is context
        assert adapter.admission_lock is lock
        assert context.store_port is store
        assert isinstance(adapter.store_port, DomainStorePort)

        created = profiles.create(
            profile_id="profile",
            name="Original Unit profile",
            content=sample_content(),
            request=profiles.request_key("create-profile"),
        )

        assert profiles.get("profile") == created
        row = store.read_domain("profile-env", PROFILE_RECORDS, "profile")
        assert row is not None and row["record_id"] == "profile"

        context.close()
        with pytest.raises(ProfileAccessRefused):
            profiles.get("profile")
    finally:
        close_owner(context, store, harnesses, materials)


def test_unknown_unit_store_commit_becomes_profile_change_unknown(tmp_path):
    context, _adapter, profiles, store, _lock, harnesses, materials = owner(tmp_path)
    try:
        def unknown_commit(*_args, **_kwargs):
            raise UnitOperationUnknown("original operation result is unknown")

        store.commit_domain_change = unknown_commit
        with pytest.raises(ProfileChangeUnknown):
            profiles.create(
                profile_id="uncertain",
                name="Unknown result",
                content=sample_content(),
                request=profiles.request_key("unknown-profile"),
            )
        assert store.read_domain("profile-env", PROFILE_RECORDS, "uncertain") is None
    finally:
        close_owner(context, store, harnesses, materials)


def test_existing_profile_service_observes_current_capability_withdrawals(tmp_path):
    context, _adapter, profiles, store, _lock, harnesses, materials = owner(tmp_path)
    original_policy = context._policy
    original_fingerprint = context._fingerprint_port
    try:
        context._policy = None
        with pytest.raises(ProfileAccessRefused):
            profiles.get("profile")

        context._policy = original_policy
        context._fingerprint_port = None
        with pytest.raises(ProfileStoreUnavailable):
            profiles.create(
                profile_id="no-fingerprint",
                name="Withdrawn fingerprint",
                content=sample_content(),
                request=profiles.request_key("withdrawn-fingerprint"),
            )

        context._fingerprint_port = original_fingerprint
        context._store = None
        with pytest.raises(ProfileStoreUnavailable):
            profiles.get("profile")
    finally:
        context._policy = original_policy
        context._fingerprint_port = original_fingerprint
        context._store = store
        close_owner(context, store, harnesses, materials)
