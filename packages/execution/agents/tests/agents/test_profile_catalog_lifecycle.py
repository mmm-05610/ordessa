"""Current public ProfileCatalog behavior on an isolated real Environment."""

from __future__ import annotations
from ordessa_agents.profiles import encode_content

import pytest

from pacthold.public import Environment
from ordessa_units.public import (
    ProfileRevisionConflict,
    unit_services,
    wire_contract,
    wire_schema_digest,
)
from ordessa_agents.profiles import ProfileAccessRefused, ProfileStoreUnavailable
from pacthold.adapters.sqlite.environment.store import KeyConflictError, SqliteStorePort
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

MANIFEST = {
    "schemaVersion": "profile/1",
    "harnessDefinitionRef": {
        "environmentNamespace": "catalog-test",
        "definitionId": "controlled.definition",
        "revision": "1",
    },
    "declarations": [],
}


class ProfilePolicy:
    def __init__(self):
        self.allow_invoke = True
        self.allow_object = True
        self.invocations = []

    def admit_invoke(self, principal, surface, guarantee):
        self.invocations.append((principal, surface, guarantee))
        return self.allow_invoke

    def admit_object_access(self, principal, target, access):
        return self.allow_object


@pytest.fixture
def catalog_env(tmp_path):
    store = SqliteStorePort(tmp_path / "agent-core.sqlite")
    policy = ProfilePolicy()
    fingerprint = ProtectedFingerprintHmac(
        {"controlled-test": b"profile-catalog-controlled-test-key"},
        active_key_id="controlled-test",
    )
    environment = Environment(
        "catalog-test", policy=policy, principal_scope="test-principal",
        store=store, fingerprint_port=fingerprint,
    resource_extension_snapshot=_test_resource_snapshot)
    services = unit_services(environment)
    yield environment, store, policy, services.profiles
    environment.close()
    store.close()


def request(catalog, request_id):
    return catalog.request_key(request_id)


def create(catalog, profile_id="main", display_name="Main", manifest=MANIFEST,
           request_id="create-main"):
    return catalog.create(
        profile_id=profile_id,
        name=display_name,
        content=manifest,
        request=request(catalog, request_id),
    )


def test_profile_catalog_create_read_history_and_wire_identity(catalog_env):
    environment, _store, policy, catalog = catalog_env
    first = create(catalog)
    revised_manifest = {**MANIFEST, "declarations": [{
        "declarationId": "ratio", "configurationKind": "controlled.ratio",
        "schemaVersion": "1", "action": "value", "requirement": "required",
        "payload": 0.5,
    }]}
    second = catalog.revise(
        "main", content=revised_manifest,
        expected_version=1, base_revision=first.current_revision,
        request=request(catalog, "edit-main"),
    )

    assert encode_content(catalog.get_revision(first.current_revision).content) == MANIFEST
    assert encode_content(catalog.get_revision(second.current_revision).content) == revised_manifest
    assert second.version == 2
    assert second.current_revision.revision == 2
    assert first.current_revision.environment_namespace == environment.environment_id
    assert first.current_revision.digest.startswith("sha256:")
    assert len(first.current_revision.digest.removeprefix("sha256:")) == 64
    assert first.current_revision != second.current_revision
    assert catalog.get("main") == second
    assert catalog.capabilities()["profileCatalog"] is True
    assert catalog.capabilities()["nodes"] is False
    assert catalog.capabilities()["managedInput"] is False
    assert wire_contract()["contractVersion"]
    assert wire_schema_digest().startswith("sha256:")
    assert len(wire_schema_digest().removeprefix("sha256:")) == 64
    assert set(policy.invocations) >= {
        ("test-principal", "pacthold.agents.profiles.create", "reliable"),
        ("test-principal", "pacthold.agents.profiles.edit", "reliable"),
    }


def test_profile_catalog_rejects_stale_catalog_and_base_refs_without_mutation(catalog_env):
    _environment, _store, _policy, catalog = catalog_env
    first = create(catalog)
    changed = {**MANIFEST, "declarations": [{
        "declarationId": "fresh", "configurationKind": "controlled.fresh",
        "schemaVersion": "1", "action": "value", "requirement": "required",
        "payload": 2,
    }]}
    edited = catalog.revise(
        "main", content=changed, expected_version=1,
        base_revision=first.current_revision,
        request=request(catalog, "edit-main-before-stale-cas"),
    )
    current = catalog.rename(
        "main", name="Renamed", expected_version=2,
        request=request(catalog, "rename-main"),
    )

    with pytest.raises(ProfileRevisionConflict):
        catalog.revise(
            "main", content=changed, expected_version=1,
            base_revision=first.current_revision,
            request=request(catalog, "stale-catalog"),
        )
    with pytest.raises(ProfileRevisionConflict):
        catalog.revise(
            "main", content=MANIFEST, expected_version=3,
            base_revision=first.current_revision,
            request=request(catalog, "stale-base"),
        )

    assert catalog.get("main") == current
    assert encode_content(catalog.get_revision(first.current_revision).content) == MANIFEST
    assert encode_content(catalog.get_revision(edited.current_revision).content) == changed
    assert catalog.list() == (current,)


def test_profile_catalog_metadata_lifecycle_clone_and_immutable_history(catalog_env):
    _environment, _store, policy, catalog = catalog_env
    original = create(catalog)
    renamed = catalog.rename(
        "main", name="Renamed", expected_version=1,
        request=request(catalog, "rename"),
    )
    archived = catalog.archive(
        "main", expected_version=2, request=request(catalog, "archive"),
    )
    assert archived.archived_at
    assert catalog.list() == ()
    assert catalog.list(include_archived=True) == (archived,)

    restored = catalog.restore(
        "main", expected_version=3, request=request(catalog, "restore"),
    )
    clone = catalog.clone(
        original.current_revision, profile_id="clone", name="Clone",
        request=request(catalog, "clone"),
    )
    assert restored.archived_at is None
    assert restored.current_revision == original.current_revision
    assert clone.current_revision.profile_id == "clone"
    assert clone.current_revision.digest == original.current_revision.digest
    assert encode_content(catalog.get_revision(original.current_revision).content) == MANIFEST
    assert catalog.get("main").name == "Renamed"
    assert renamed.current_revision == original.current_revision
    assert {
        surface for _principal, surface, _guarantee in policy.invocations
    } >= {
        "pacthold.agents.profiles.create",
        "pacthold.agents.profiles.rename",
        "pacthold.agents.profiles.archive",
        "pacthold.agents.profiles.restore",
        "pacthold.agents.profiles.clone",
    }


def test_profile_catalog_request_replay_is_idempotent_and_key_conflicts_on_new_facts(catalog_env):
    _environment, _store, _policy, catalog = catalog_env
    key = request(catalog, "same-create")
    first = catalog.create(
        profile_id="repeat", name="Repeat", content=MANIFEST, request=key,
    )
    replay = catalog.create(
        profile_id="repeat", name="Repeat", content=MANIFEST, request=key,
    )
    assert replay == first
    assert catalog.list() == (first,)

    with pytest.raises(KeyConflictError):
        catalog.create(
            profile_id="repeat", name="Different", content=MANIFEST, request=key,
        )
    assert catalog.get("repeat") == first


@pytest.mark.parametrize("denial", ["invoke", "object"])
def test_profile_catalog_permission_denial_leaves_catalog_unchanged(catalog_env, denial):
    _environment, store, policy, catalog = catalog_env
    if denial == "invoke":
        policy.allow_invoke = False
    else:
        policy.allow_object = False

    with pytest.raises(ProfileAccessRefused):
        create(catalog, profile_id="denied", request_id=f"denied-{denial}")
    # Read back the owner store directly: in the object-denial variant the
    # policy also denies listing, so that API cannot serve as a no-write probe.
    assert store.list_domain("catalog-test", "agents.profile-catalog") == ()
    assert store.list_domain("catalog-test", "agents.profile-manifests") == ()


def test_profile_catalog_without_fingerprint_refuses_writes(catalog_env, tmp_path):
    _environment, _store, _policy, _catalog = catalog_env
    store = SqliteStorePort(tmp_path / "without-key.sqlite")
    environment = Environment(
        "catalog-test", policy=ProfilePolicy(), principal_scope="test-principal", store=store,
    resource_extension_snapshot=_test_resource_snapshot)
    try:
        catalog = unit_services(environment).profiles
        assert catalog.capabilities()["profileCatalog"] is False
        with pytest.raises(ProfileStoreUnavailable, match="fingerprint"):
            create(catalog, profile_id="no-key", request_id="no-key-create")
        assert catalog.list() == ()
    finally:
        environment.close()
        store.close()
