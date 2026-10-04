"""Real isolated SQLite catalog contract tests; no native/model claims."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError, dataclass
from threading import Barrier

import pytest

from ordessa_environment_api import AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError, RequestKey, UnknownResultError
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from pacthold.public import Environment, EnvironmentClosedError
from pacthold.agents.public import agent_services, ProfileRef, ProfileRevisionConflict, ProfileValidationError


class Policy:
    def __init__(self, write=True, read=True):
        self.write, self.read = write, read
    def admit_invoke(self, principal, surface, guarantee):
        return self.write
    def admit_object_access(self, principal, object_ref, mode):
        return self.read


def key(name, environment="catalog-test", principal="user:test"):
    return RequestKey(environment, principal, name)


def manifest(value="first", environment="catalog-test"):
    return {"harnessDefinitionRef": {"environmentNamespace": environment,
            "definitionId": "absent-harness", "revision": "1"}, "schemaVersion": "1",
            "declarations": [{"declarationId": "model", "configurationKind": "absent.kind",
            "schemaVersion": "1", "action": "value", "requirement": "required",
            "payload": {"modelId": value}}]}


def fingerprint():
    return ProtectedFingerprintHmac({"fixture": b"isolated-catalog-key"}, active_key_id="fixture")


def environment(backing_store, **kwargs):
    options = {"store": backing_store, "policy": Policy(), "fingerprint_port": fingerprint(),
               "principal_scope": "user:test"}
    options.update(kwargs)
    return Environment("catalog-test", **options)


@pytest.fixture
def isolated(tmp_path):
    store = SqliteStorePort(tmp_path / "catalog.sqlite")
    env = environment(store)
    yield env, store, agent_services(env).profiles
    env.close()
    store.close()


def create(catalog, request="create-one", **kwargs):
    options = {"profile_id": "one", "display_name": "One", "manifest": manifest(),
               "request": request if isinstance(request, RequestKey) else key(request)}
    options.update(kwargs)
    return catalog.create(**options)


def test_public_singleton_and_immutable_definition(isolated):
    env, store, catalog = isolated
    assert agent_services(env) is agent_services(env)
    assert agent_services(env).profiles is catalog
    source = manifest()
    first = create(catalog, manifest=source)
    source["declarations"][0]["payload"]["modelId"] = "mutated"
    content = catalog.read(first.current_manifest_ref).content
    assert content == manifest()
    content["declarations"].clear()
    assert catalog.read(first.current_manifest_ref).content == manifest()
    with pytest.raises(FrozenInstanceError):
        first.current_manifest_ref.manifest_revision = 4
    assert env.registry_snapshot.contract_ids == ()


def test_edit_both_revision_axes_history_clone_and_metadata(isolated):
    _, _, catalog = isolated
    first = create(catalog)
    second = catalog.edit("one", manifest=manifest("second"), expected_catalog_revision=1,
                          base_manifest_ref=first.current_manifest_ref, request=key("edit-one"))
    assert (second.catalog_revision, second.current_manifest_ref.manifest_revision) == (2, 2)
    assert catalog.read(first.current_manifest_ref).content == manifest()
    assert catalog.read(second.current_manifest_ref).content == manifest("second")
    renamed = catalog.rename("one", display_name="Renamed", expected_catalog_revision=2,
                             request=key("rename-one"))
    assert renamed.catalog_revision == 3
    assert renamed.current_manifest_ref == second.current_manifest_ref
    with pytest.raises(ProfileRevisionConflict):
        catalog.edit("one", manifest=manifest("third"), expected_catalog_revision=3,
                     base_manifest_ref=first.current_manifest_ref, request=key("stale-base"))
    with pytest.raises(ProfileRevisionConflict):
        catalog.edit("one", manifest=manifest("third"), expected_catalog_revision=2,
                     base_manifest_ref=second.current_manifest_ref, request=key("stale-catalog"))
    cloned = catalog.clone(first.current_manifest_ref, profile_id="clone", display_name="Clone",
                           request=key("clone-old"))
    assert catalog.read(cloned.current_manifest_ref).content == manifest()
    assert cloned.current_manifest_ref.content_digest == first.current_manifest_ref.content_digest
    archived = catalog.archive("one", expected_catalog_revision=3, request=key("archive-one"))
    assert archived.archived_at and archived.current_manifest_ref == second.current_manifest_ref
    assert {x.profile_id for x in catalog.list()} == {"clone"}
    assert {x.profile_id for x in catalog.list(include_archived=True)} == {"one", "clone"}
    with pytest.raises(ProfileRevisionConflict):
        catalog.edit("one", manifest=manifest("third"), expected_catalog_revision=4,
                     base_manifest_ref=second.current_manifest_ref, request=key("edit-archived"))
    restored = catalog.restore("one", expected_catalog_revision=4, request=key("restore-one"))
    assert restored.catalog_revision == 5 and restored.archived_at is None
    assert restored.current_manifest_ref == second.current_manifest_ref


def test_request_replay_conflicts_and_restart(tmp_path):
    path = tmp_path / "restart.sqlite"
    store = SqliteStorePort(path)
    env = environment(store)
    catalog = agent_services(env).profiles
    first = create(catalog)
    assert create(catalog) == first
    with pytest.raises(IdentityMismatchError):
        create(catalog, manifest=manifest("changed"))
    with pytest.raises(IdentityMismatchError):
        catalog.rename("one", display_name="New", expected_catalog_revision=1,
                       request=key("create-one"))
    env.close()
    store.close()
    reopened = SqliteStorePort(path)
    restarted = environment(reopened)
    try:
        new_catalog = agent_services(restarted).profiles
        assert create(new_catalog) == first
        assert new_catalog.read(first.current_manifest_ref).content == manifest()
        assert len(new_catalog.list()) == 1
    finally:
        restarted.close()
        reopened.close()


@pytest.mark.parametrize("missing", ["policy", "fingerprint_port", "store"])
def test_missing_required_resource_refuses_write(isolated, missing):
    _, store, _ = isolated
    env = environment(store, **{missing: None})
    catalog = agent_services(env).profiles
    with pytest.raises(AdmissionRefusedError if missing == "policy" else GuaranteeUnavailableError):
        create(catalog)
    assert store.read_request(key("create-one")) is None
    env.close()


def test_policy_and_principal_denial_do_not_spend_key(isolated):
    _, store, _ = isolated
    for options, request in [(dict(policy=Policy(write=False)), key("denied-write")),
                             ({}, key("forged-principal", principal="user:other"))]:
        env = environment(store, **options)
        with pytest.raises(AdmissionRefusedError):
            create(agent_services(env).profiles, request=request)
        assert store.read_request(request) is None
        env.close()


def test_read_permission_and_cross_environment_ref(isolated):
    _, store, catalog = isolated
    first = create(catalog)
    denied = environment(store, policy=Policy(read=False))
    try:
        with pytest.raises(AdmissionRefusedError):
            agent_services(denied).profiles.read(first.current_manifest_ref)
        with pytest.raises(AdmissionRefusedError):
            agent_services(denied).profiles.list()
    finally:
        denied.close()
    foreign = ProfileRef("other-env", "one", 1, first.current_manifest_ref.content_digest)
    with pytest.raises(IdentityMismatchError):
        catalog.read(foreign)
    with pytest.raises(IdentityMismatchError):
        create(catalog, request=key("foreign-request", environment="other-env"))


def test_same_request_id_different_authorized_principal_is_separate(isolated):
    _, store, catalog = isolated
    create(catalog)
    other = environment(store, principal_scope="user:other")
    try:
        result = create(agent_services(other).profiles, profile_id="other",
                        request=key("create-one", principal="user:other"))
        assert result.profile_id == "other"
        assert store.read_request(key("create-one", principal="user:other")) is not None
    finally:
        other.close()


def test_unknown_spent_request_is_not_reused(isolated):
    _, store, catalog = isolated
    first = create(catalog)
    request = key("uncertain-rename")
    # Same protected comparison as the pending command, claimed by the existing
    # store dispatch seam; absence of a concluded domain result is not permission.
    import hashlib, json
    params = {"profileId": "one", "expectedCatalogRevision": 1, "displayName": "New"}
    content = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = fingerprint().fingerprint(request, "pacthold.agents.profiles.rename",
                                      "sha256:" + hashlib.sha256(content.encode()).hexdigest())
    assert store.claim_dispatch(request, digest)
    with pytest.raises(UnknownResultError):
        catalog.rename("one", display_name="New", expected_catalog_revision=1, request=request)
    assert catalog.read_entry("one") == first
    assert store.read_request(request)["current"]["outcome"] == "unknown"


def test_unresolved_preview_is_pure_read(isolated):
    _, store, catalog = isolated
    first = create(catalog)
    before = store.list_domain("catalog-test", "agents.profile-catalog")
    preview = catalog.preview(first.current_manifest_ref)
    assert preview["status"] == "unresolved" and preview["ready"] is False
    assert preview["referenceCoverage"] == "unknown"
    assert preview["error"]["code"] == "providerUnavailable"
    assert catalog.preview(first.current_manifest_ref) == preview
    assert store.list_domain("catalog-test", "agents.profile-catalog") == before


@pytest.mark.parametrize("bad", ["secret", "size", "depth", "nan", "duplicate", "unknown-field", "foreign-ref", "reset-value"])
def test_invalid_manifest_refused_without_request(isolated, bad):
    _, store, catalog = isolated
    value = manifest()
    payload = value["declarations"][0]["payload"]
    if bad == "secret": payload["api_key"] = "DO-NOT-EXPOSE"
    elif bad == "size": payload["text"] = "x" * 262145
    elif bad == "depth":
        leaf = payload
        for _ in range(40):
            leaf["nested"] = {}
            leaf = leaf["nested"]
    elif bad == "nan": payload["number"] = float("nan")
    elif bad == "duplicate": value["declarations"].append(deepcopy(value["declarations"][0]))
    elif bad == "unknown-field": value["unrecognized"] = True
    elif bad == "foreign-ref": value["harnessDefinitionRef"]["environmentNamespace"] = "other-env"
    elif bad == "reset-value": value["declarations"][0]["action"] = "reset"
    with pytest.raises(ProfileValidationError) as exc:
        create(catalog, manifest=value)
    assert "DO-NOT-EXPOSE" not in str(exc.value)
    assert store.read_request(key("create-one")) is None
    assert catalog.list() == ()


def test_concurrent_cas_only_one_edit_wins(isolated):
    env, _, catalog = isolated
    first = create(catalog)
    barrier = Barrier(2)
    def edit(i):
        barrier.wait(timeout=5)
        try:
            result = agent_services(env).profiles.edit("one", manifest=manifest(str(i)),
                        expected_catalog_revision=1, base_manifest_ref=first.current_manifest_ref,
                        request=key(f"race-{i}"))
            return result
        except ProfileRevisionConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, [1, 2]))
    assert sum(result is not None for result in results) == 1
    assert catalog.read_entry("one").catalog_revision == 2
    assert catalog.read(first.current_manifest_ref).content == manifest()


def test_closed_environment_refuses_catalog_reads_writes_bootstrap(isolated):
    env, _, catalog = isolated
    first = create(catalog)
    env.close()
    for call in [lambda: catalog.list(), lambda: catalog.read(first.current_manifest_ref),
                 lambda: create(catalog, request="closed"), lambda: agent_services(env)]:
        with pytest.raises(EnvironmentClosedError):
            call()


def test_domain_transaction_failure_rolls_back_catalog_manifest_and_result(isolated):
    import sqlite3
    _, store, catalog = isolated
    with store.transaction() as conn:
        conn.execute("CREATE TRIGGER fail_manifest BEFORE INSERT ON env_domain_records "
                     "WHEN NEW.namespace = 'agents.profile-manifests' "
                     "BEGIN SELECT RAISE(ABORT, 'isolated injected failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="isolated injected failure"):
        create(catalog)
    assert catalog.list() == ()
    assert store.list_domain("catalog-test", "agents.profile-manifests") == ()
    assert store.read_request(key("create-one")) is None
    with store.transaction() as conn:
        conn.execute("DROP TRIGGER fail_manifest")
    assert create(catalog).catalog_revision == 1


def test_target_write_permission_is_separate_from_surface_permission(isolated):
    _, store, _ = isolated
    class TargetDenied(Policy):
        def admit_object_access(self, principal, object_ref, mode):
            return mode == "read"
    env = environment(store, policy=TargetDenied())
    try:
        with pytest.raises(AdmissionRefusedError):
            create(agent_services(env).profiles)
        assert store.read_request(key("create-one")) is None
        assert agent_services(env).profiles.list() == ()
    finally:
        env.close()


@pytest.mark.parametrize("tamper", ["catalog-id", "manifest-id", "environment", "catalog-revision", "manifest-row-revision", "manifest-content"])
def test_corrupt_domain_identity_revision_or_digest_fails_closed(isolated, tamper):
    import json
    _, store, catalog = isolated
    first = create(catalog)
    namespace = "agents.profile-catalog"
    record_id = "one"
    if tamper.startswith("manifest-row") or tamper == "manifest-content":
        namespace, record_id = "agents.profile-manifests", "one@1"
    row = store.read_domain("catalog-test", namespace, record_id)
    value = row["value"]
    if tamper == "catalog-id": value["profileId"] = "different"
    elif tamper == "manifest-id": value["currentManifestRef"]["profileId"] = "different"
    elif tamper == "environment": value["currentManifestRef"]["environmentNamespace"] = "other-env"
    elif tamper == "catalog-revision": value["catalogRevision"] = 99
    elif tamper == "manifest-content": value["content"]["schemaVersion"] = "altered"
    with store.transaction() as conn:
        conn.execute("UPDATE env_domain_records SET payload=?, revision=? "
                     "WHERE environment=? AND namespace=? AND record_id=?",
                     (json.dumps(value), 2 if tamper == "manifest-row-revision" else row["revision"],
                      "catalog-test", namespace, record_id))
    if namespace == "agents.profile-catalog":
        for call in [catalog.list, lambda: catalog.read_entry("one")]:
            with pytest.raises(GuaranteeUnavailableError):
                call()
    else:
        with pytest.raises(GuaranteeUnavailableError):
            catalog.read(first.current_manifest_ref)


def test_secret_reference_uses_existing_contract_without_implying_applicability(isolated):
    _, _, catalog = isolated
    value = manifest()
    secret_ref = {"ref": "isolated-secret", "revision": "1", "owner_namespace": "fixture", "access_purpose": "model"}
    value["declarations"][0]["payload"]["api_key"] = {"secretRef": secret_ref}
    entry = create(catalog, manifest=value)
    assert catalog.read(entry.current_manifest_ref).content == value
    assert catalog.preview(entry.current_manifest_ref)["status"] == "unresolved"
    invalid = deepcopy(value)
    invalid["declarations"][0]["payload"]["api_key"]["secretRef"]["plaintext"] = "DO-NOT-EXPOSE"
    with pytest.raises(ProfileValidationError) as exc:
        create(catalog, request="bad-secret", profile_id="bad", manifest=invalid)
    assert "DO-NOT-EXPOSE" not in str(exc.value)


def test_plugin_cannot_claim_core_agent_surface(isolated):
    from pacthold.public import InstallationRecord, CoreContributionSet, RegistrationConflictError
    env, _, _ = isolated
    @dataclass(frozen=True)
    class ForgedCore:
        contract_id = "pacthold.agents.profiles@1"
    env.install(InstallationRecord("forged.plugin", "a" * 64))
    env.enable("forged.plugin")
    with pytest.raises(RegistrationConflictError):
        env.stage_activation("forged.plugin", CoreContributionSet(contracts=(ForgedCore,)))
    assert env.registry_snapshot.contract_ids == ()


def test_plugin_cannot_claim_builtin_core_owner(isolated):
    from pacthold.public import InstallationRecord, RegistrationConflictError
    env, _, _ = isolated
    env.install(InstallationRecord('pacthold.agents', 'a' * 64))
    env.enable('pacthold.agents')
    with pytest.raises(RegistrationConflictError):
        env.stage_activation('pacthold.agents')
    assert env.registry_snapshot.contract_ids == ()
