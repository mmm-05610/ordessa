"""Fixed Unit Profile resolution uses the original Profile and Harness owners."""
from contextlib import contextmanager
import json
from threading import RLock

import pytest

from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable
from ordessa_agents.harness.providers.registry import (
    HarnessCatalog,
    HarnessDefinitionDeclaration,
    HarnessDefinitionDescriptor,
)
from ordessa_agents.profiles import (
    ProfileNotFound,
    ProfileRevisionConflict,
    ProfileRevisionRef,
    ProfileService,
    ProfileValidationError,
    encode_content,
    encode_revision_ref,
)
from ordessa_units.assembly.profile_selection import resolve_unit_profile
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.persistence.sqlite.store import SqliteUnitStore
from ordessa_infrastructure.encoding.immutable_json import safe_json


class Policy:
    def admit_object_access(self, *_args):
        return True

    def admit_invoke(self, *_args):
        return True


@contextmanager
def profile_owner(tmp_path, *, namespace="unit-resolution"):
    store = SqliteUnitStore(tmp_path / "state.sqlite")
    policy = Policy()
    lock = RLock()
    owner = {}
    harness_catalog = HarnessCatalog(
        namespace,
        policy=policy,
        principal_scope="synthetic",
        admission_lock=lock,
        retirement_guard=lambda owner_id, generation: owner["context"].harness_provider_retirement_guard(
            owner_id, generation
        ),
    )
    material_catalog = MaterialCatalog(namespace, admission_lock=lock)
    context = UnitAdmissionContext(
        namespace,
        store=store,
        policy=policy,
        fingerprint_port=ProtectedFingerprintHmac(
            {"test": b"unit-profile-resolution"}, active_key_id="test"
        ),
        harness_catalog=harness_catalog,
        material_catalog=material_catalog,
        principal_scope="synthetic",
        admission_lock=lock,
    )
    owner["context"] = context
    descriptor = HarnessDefinitionDescriptor(
        "fixture-provider",
        {"environmentNamespace": namespace, "definitionId": "fixture", "revision": "r1"},
        "sha256:" + "a" * 64,
        "fixture/protocol",
        "fixture-adapter/1",
    )
    declaration = HarnessDefinitionDeclaration(descriptor, lambda _ref: None)
    harness_catalog.stage(
        "fixture-owner", 1, "fixture-installation", "b" * 64, (declaration,)
    ).commit()
    try:
        yield ProfileService(UnitProfileAdmission(context)), harness_catalog, store, descriptor
    finally:
        harness_catalog.drain("fixture-owner", 1)
        harness_catalog.retire("fixture-owner", 1)
        context.close()
        harness_catalog.close()
        material_catalog.close()
        store.close()


def content(descriptor, *, metadata=None):
    value = {
        "schemaVersion": "1",
        "harnessDefinitionRef": dict(descriptor.definition_ref),
        "declarations": [],
    }
    if metadata is not None:
        value["metadata"] = metadata
    return value


def test_resolves_requested_immutable_revision_and_current_catalog_pin(tmp_path):
    with profile_owner(tmp_path) as (service, catalog, _store, descriptor):
        first = service.create(
            profile_id="profile",
            name="Profile",
            content=content(descriptor),
            request=service.request_key("create"),
        )
        second = service.revise(
            "profile",
            content=content(descriptor, metadata={"version": "second"}),
            expected_version=1,
            base_revision=first.current_revision,
            request=service.request_key("revise"),
        )

        selected = resolve_unit_profile(service, first.current_revision, catalog)

        assert json.loads(safe_json(selected.profile_snapshot)) == {
            "ref": encode_revision_ref(first.current_revision),
            "manifest": encode_content(service.get_revision(first.current_revision).content),
        }
        assert selected.harness_descriptor == descriptor
        admitted = catalog.describe(descriptor.definition_ref)
        assert dict(selected.harness_provider_ref) == dict(admitted.provider_ref)
        assert second.current_revision != first.current_revision


def test_refuses_archived_or_missing_current_profile(tmp_path):
    with profile_owner(tmp_path) as (service, catalog, _store, descriptor):
        created = service.create(
            profile_id="profile",
            name="Profile",
            content=content(descriptor),
            request=service.request_key("create"),
        )
        service.archive(
            "profile", expected_version=1, request=service.request_key("archive")
        )
        with pytest.raises(UnitAdmissionRefused):
            resolve_unit_profile(service, created.current_revision, catalog)
        with pytest.raises(ProfileNotFound):
            resolve_unit_profile(
                service,
                ProfileRevisionRef("unit-resolution", "missing", 1, "sha256:" + "0" * 64),
                catalog,
            )


@pytest.mark.parametrize("revision_ref", [None, {"profile_id": "profile"}])
def test_requires_exact_profile_revision_reference_type(tmp_path, revision_ref):
    with profile_owner(tmp_path) as (service, catalog, _store, _descriptor):
        with pytest.raises(ProfileValidationError):
            resolve_unit_profile(service, revision_ref, catalog)


def test_rejects_foreign_or_digest_mismatched_revision(tmp_path):
    with profile_owner(tmp_path) as (service, catalog, _store, descriptor):
        created = service.create(
            profile_id="profile",
            name="Profile",
            content=content(descriptor),
            request=service.request_key("create"),
        )
        foreign = ProfileRevisionRef(
            "elsewhere", "profile", created.current_revision.revision,
            created.current_revision.digest,
        )
        with pytest.raises(ProfileValidationError):
            resolve_unit_profile(service, foreign, catalog)
        wrong_digest = ProfileRevisionRef(
            "unit-resolution", "profile", created.current_revision.revision,
            "sha256:" + "0" * 64,
        )
        with pytest.raises(ProfileRevisionConflict):
            resolve_unit_profile(service, wrong_digest, catalog)


def test_requires_real_harness_catalog_admission_for_profile_definition(tmp_path):
    with profile_owner(tmp_path) as (service, catalog, _store, descriptor):
        missing = {
            "schemaVersion": "1",
            "harnessDefinitionRef": {
                "environmentNamespace": "unit-resolution",
                "definitionId": "not-admitted",
                "revision": "r1",
            },
            "declarations": [],
        }
        created = service.create(
            profile_id="profile",
            name="Profile",
            content=missing,
            request=service.request_key("create"),
        )
        with pytest.raises(UnitAdmissionRefused):
            resolve_unit_profile(service, created.current_revision, catalog)
        with pytest.raises(UnitGuaranteeUnavailable):
            resolve_unit_profile(service, created.current_revision, object())
