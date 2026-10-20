"""Regression coverage for the Unit-owned Profile catalog seam.

These checks exercise the public ProfileService through the original Unit
admission context and SqliteUnitStore. They do not recreate the retired
CoreRegistry or Environment service assembly.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, RLock

import pytest

from ordessa_execution_agents.harness.providers.registry import HarnessCatalog
from ordessa_execution_agents.profiles import (
    Profile,
    ProfileAccessRefused,
    ProfileChangeUnknown,
    ProfileRevisionConflict,
    ProfileService,
    ProfileValidationError,
)
from ordessa_execution_agents.profiles.management.compatibility import (
    PROFILE_RECORDS,
)
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.admission.context import UnitAdmissionContext
from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
from ordessa_units.admission.material_registration import MaterialCatalog
from ordessa_units.errors import UnitOperationUnknown
from ordessa_units.bindings.profile_admission import UnitProfileAdmission
from ordessa_units.persistence.sqlite.store import SqliteUnitStore


class _Policy:
    def __init__(self):
        self.denied_objects = set()
        self.denied_invocations = set()

    def admit_object_access(self, *_args):
        principal, resource, mode = _args
        return (principal, resource, mode) not in self.denied_objects

    def admit_invoke(self, *_args):
        principal, operation, reliability = _args
        return (principal, operation, reliability) not in self.denied_invocations


def _open_owner(database, *, principal="profile-owner"):
    store = SqliteUnitStore(database)
    lock = RLock()
    policy = _Policy()
    harnesses = HarnessCatalog("profile-regression", policy=policy, admission_lock=lock)
    materials = MaterialCatalog("profile-regression", admission_lock=lock)
    context = UnitAdmissionContext(
        "profile-regression",
        store=store,
        policy=policy,
        fingerprint_port=ProtectedFingerprintHmac(
            {"test": b"unit-profile-catalog-regression"}, active_key_id="test"
        ),
        harness_catalog=harnesses,
        material_catalog=materials,
        principal_scope=principal,
        admission_lock=lock,
    )
    return ProfileService(UnitProfileAdmission(context)), context, store, harnesses, materials


def _close_owner(owner):
    _service, context, store, harnesses, materials = owner
    try:
        context.close()
    finally:
        harnesses.close()
        materials.close()
        store.close()


def _content(*, marker="initial"):
    return {
        "schemaVersion": "1",
        "harnessDefinitionRef": {
            "environmentNamespace": "profile-regression",
            "definitionId": "fixture",
            "revision": "1",
        },
        "declarations": [],
        "metadata": {"marker": marker},
    }


def test_profile_revision_axes_history_and_replay_survive_cold_reopen(tmp_path):
    database = tmp_path / "unit-profile-catalog.sqlite"
    owner = _open_owner(database)
    service = owner[0]
    try:
        first = service.create(
            profile_id="profile",
            name="Profile",
            content=_content(),
            request=service.request_key("create-profile"),
        )
        assert service.create(
            profile_id="profile",
            name="Profile",
            content=_content(),
            request=service.request_key("create-profile"),
        ) == first

        second = service.revise(
            "profile",
            content=_content(marker="second"),
            expected_version=1,
            base_revision=first.current_revision,
            request=service.request_key("revise-profile"),
        )
        assert second.version == 2
        assert second.current_revision.revision == 2
        assert service.get_revision(first.current_revision).content.metadata["marker"] == "initial"
        assert service.get_revision(second.current_revision).content.metadata["marker"] == "second"

        # The catalog CAS axis and the immutable content-base axis are both
        # independently required to match the current Profile.
        with pytest.raises(ProfileRevisionConflict):
            service.revise(
                "profile",
                content=_content(marker="stale-base"),
                expected_version=2,
                base_revision=first.current_revision,
                request=service.request_key("stale-base"),
            )
        with pytest.raises(ProfileRevisionConflict):
            service.revise(
                "profile",
                content=_content(marker="stale-catalog"),
                expected_version=1,
                base_revision=second.current_revision,
                request=service.request_key("stale-catalog"),
            )

        with pytest.raises(ProfileValidationError):
            service.create(
                profile_id="profile",
                name="Different replay payload",
                content=_content(marker="different"),
                request=service.request_key("create-profile"),
            )
        assert service.get("profile") == second
    finally:
        _close_owner(owner)

    reopened = _open_owner(database)
    replay_service = reopened[0]
    try:
        assert replay_service.get("profile").version == 2
        assert replay_service.get_revision(first.current_revision).content.metadata["marker"] == "initial"
        assert replay_service.create(
            profile_id="profile",
            name="Profile",
            content=_content(),
            request=replay_service.request_key("create-profile"),
        ) == first
    finally:
        _close_owner(reopened)


def test_profile_service_concurrent_revisions_compare_both_expected_axes(tmp_path):
    owner = _open_owner(tmp_path / "unit-profile-concurrent.sqlite")
    service = owner[0]
    try:
        first = service.create(
            profile_id="profile",
            name="Profile",
            content=_content(),
            request=service.request_key("create"),
        )
        start = Barrier(2)

        def revise(request_id, marker):
            start.wait()
            try:
                return service.revise(
                    "profile",
                    content=_content(marker=marker),
                    expected_version=1,
                    base_revision=first.current_revision,
                    request=service.request_key(request_id),
                )
            except ProfileRevisionConflict as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = tuple(executor.map(
                lambda args: revise(*args),
                (("revise-a", "a"), ("revise-b", "b")),
            ))

        assert sum(isinstance(value, Profile) for value in outcomes) == 1
        assert sum(isinstance(value, ProfileRevisionConflict) for value in outcomes) == 1
        current = service.get("profile")
        assert current.version == 2
        assert service.get_revision(first.current_revision).ref == first.current_revision
        assert len(service.list()) == 1
    finally:
        _close_owner(owner)


def test_profile_unknown_spends_request_key_and_cannot_be_replayed(tmp_path):
    owner = _open_owner(tmp_path / "unit-profile-unknown.sqlite")
    service, _context, store, _harnesses, _materials = owner
    request = service.request_key("unknown-create")
    commit = store.commit_domain_change

    def spend_then_lose_result(key, digest, *_args, **_kwargs):
        assert store.reserve_request(key, digest)
        raise UnitOperationUnknown("commit result cannot be established")

    store.commit_domain_change = spend_then_lose_result
    try:
        for _attempt in range(2):
            with pytest.raises(ProfileChangeUnknown):
                service.create(
                    profile_id="unknown-profile",
                    name="Unknown",
                    content=_content(),
                    request=request,
                )
        # UNKNOWN is not a refusal: the original key remains spent and no
        # replay may turn uncertainty into a second write attempt.
        assert store.read_domain("profile-regression", PROFILE_RECORDS, "unknown-profile") is None
        assert store.read_request(request) is not None
    finally:
        store.commit_domain_change = commit
        # This deliberately leaves an UNKNOWN/spent request in the fixture;
        # UnitAdmissionContext.close() must refuse while that evidence remains.
        owner[3].close()
        owner[4].close()
        store.close()


def test_target_object_denial_does_not_spend_request_key_and_can_be_retried(tmp_path):
    owner = _open_owner(tmp_path / "unit-profile-target-denial.sqlite")
    service, _context, store, _harnesses, _materials = owner
    policy = _context.policy
    request = service.request_key("target-denied")
    target = "profile-regression:agents.profile:target"
    policy.denied_objects.add(("profile-owner", target, "write"))
    try:
        with pytest.raises(ProfileAccessRefused):
            service.create(
                profile_id="target",
                name="Target",
                content=_content(),
                request=request,
            )
        assert store.read_request(request) is None

        # The surface invocation remains admitted; only the target object
        # decision changes. Reusing the exact RequestKey is therefore safe.
        policy.denied_objects.remove(("profile-owner", target, "write"))
        created = service.create(
            profile_id="target",
            name="Target",
            content=_content(),
            request=request,
        )
        assert created.profile_id == "target"
        assert store.read_request(request) is not None
    finally:
        _close_owner(owner)


def test_principal_and_policy_refusals_do_not_spend_authorized_request_key(tmp_path):
    owner = _open_owner(tmp_path / "unit-profile-principal-denial.sqlite")
    service, _context, store, _harnesses, _materials = owner
    policy = _context.policy
    request_id = "denied-before-authorization"
    authorized_request = service.request_key(request_id)
    wrong_principal = RequestKey("profile-regression", "other-principal", request_id)
    try:
        with pytest.raises(ProfileAccessRefused):
            service.create(
                profile_id="principal",
                name="Principal",
                content=_content(),
                request=wrong_principal,
            )
        assert store.read_request(authorized_request) is None

        target = "profile-regression:agents.profile:principal"
        policy.denied_objects.add(("profile-owner", target, "write"))
        with pytest.raises(ProfileAccessRefused):
            service.create(
                profile_id="principal",
                name="Principal",
                content=_content(),
                request=authorized_request,
            )
        assert store.read_request(authorized_request) is None

        policy.denied_objects.remove(("profile-owner", target, "write"))
        assert service.create(
            profile_id="principal",
            name="Principal",
            content=_content(),
            request=authorized_request,
        ).profile_id == "principal"
    finally:
        _close_owner(owner)


def test_same_request_id_is_independent_for_two_authorized_principals(tmp_path):
    store = SqliteUnitStore(tmp_path / "unit-profile-principals.sqlite")
    lock = RLock()
    policy = _Policy()
    harnesses = HarnessCatalog("profile-regression", policy=policy, admission_lock=lock)
    materials = MaterialCatalog("profile-regression", admission_lock=lock)

    def make_service(principal):
        context = UnitAdmissionContext(
            "profile-regression",
            store=store,
            policy=policy,
            fingerprint_port=ProtectedFingerprintHmac(
                {"test": b"unit-profile-catalog-regression"}, active_key_id="test"
            ),
            harness_catalog=harnesses,
            material_catalog=materials,
            principal_scope=principal,
            admission_lock=lock,
        )
        return ProfileService(UnitProfileAdmission(context)), context

    first, first_context = make_service("principal-a")
    second, second_context = make_service("principal-b")
    try:
        first_result = first.create(
            profile_id="profile-a",
            name="A",
            content=_content(),
            request=first.request_key("shared-request-id"),
        )
        second_result = second.create(
            profile_id="profile-b",
            name="B",
            content=_content(),
            request=second.request_key("shared-request-id"),
        )
        assert first_result.profile_id == "profile-a"
        assert second_result.profile_id == "profile-b"
        assert store.read_request(first.request_key("shared-request-id")) is not None
        assert store.read_request(second.request_key("shared-request-id")) is not None
    finally:
        first_context.close()
        second_context.close()
        harnesses.close()
        materials.close()
        store.close()


def test_closed_unit_context_refuses_profile_reads_and_writes_without_records(tmp_path):
    owner = _open_owner(tmp_path / "unit-profile-closed.sqlite")
    service, context, store, _harnesses, _materials = owner
    existing = service.create(
        profile_id="existing",
        name="Existing",
        content=_content(),
        request=service.request_key("create-existing"),
    )
    denied_request = service.request_key("write-after-close")
    original_record = store.read_domain("profile-regression", PROFILE_RECORDS, "existing")
    context.close()
    try:
        with pytest.raises(ProfileAccessRefused):
            service.get("existing")
        with pytest.raises(ProfileAccessRefused):
            service.list()
        with pytest.raises(ProfileAccessRefused):
            service.create(
                profile_id="later",
                name="Later",
                content=_content(),
                request=denied_request,
            )
        assert store.read_request(denied_request) is None
        assert service.environment_namespace == existing.current_revision.environment_namespace
        assert store.read_domain("profile-regression", PROFILE_RECORDS, "later") is None
        assert store.read_domain("profile-regression", PROFILE_RECORDS, "existing") == original_record
    finally:
        # Already-closed context is safe to close again; the temporary SQLite
        # store remains solely a test fixture and is closed by owner cleanup.
        _close_owner(owner)
