"""EnvironmentManager validates issued views against its original resource."""
import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ordessa_environments import (
    BackendNotFound,
    BackendObservation,
    CapabilityReport,
    EnvironmentManager,
    EnvironmentOperationUnknown,
    EnvironmentRefused,
    EnvironmentSnapshot,
    EnvironmentInstance,
    SQLiteEnvironmentStore,
)


class ControlledProvider:
    identity = "controlled"
    binding_id = "controlled-resource-scope"
    operations = frozenset({"start", "stop", "delete"})

    def __init__(self):
        self.state = "running"
        self.exists = True
        self.creates = 0
        self.fail_stop = False

    def inspect(self, backend_id):
        if not self.exists:
            raise BackendNotFound("controlled resource is absent")
        return BackendObservation(
            backend_id,
            self.state,
            CapabilityReport({}, "none", "provider_self_report"),
            datetime.now(timezone.utc).isoformat(),
            runtime_identity="runtime-1",
        )

    def create(self, reference, *, operation_id):
        self.creates += 1
        return self.inspect("immutable-backend")

    def open_use(self, backend_id, **kwargs):
        return SimpleNamespace(
            files=SimpleNamespace(root=lambda: "/controlled-backend"),
            execution=SimpleNamespace(start=lambda request: None),
            release=lambda: {"resourcePreserved": True},
        )

    def start(self, backend_id):
        self.state = "running"
        return self.inspect(backend_id)

    def stop(self, backend_id):
        if self.fail_stop:
            raise TimeoutError("controlled stop has no receipt")
        self.state = "stopped"
        return self.inspect(backend_id)

    def delete(self, backend_id):
        self.exists = False


@pytest.fixture
def resource(tmp_path):
    store = SQLiteEnvironmentStore(tmp_path / "environments.sqlite")
    provider = ControlledProvider()
    manager = EnvironmentManager(store=store, providers={provider.identity: provider})
    instance = manager.create(provider.identity, {})
    expected_snapshot = instance.inspect()
    assert isinstance(expected_snapshot, EnvironmentSnapshot)
    return SimpleNamespace(
        store=store,
        provider=provider,
        manager=manager,
        instance=instance,
        expected_snapshot=expected_snapshot,
    )


def _corrupt_snapshot(resource, field, value):
    with resource.store.transaction() as connection:
        row = resource.store.resource(connection, resource.instance.identity)
        if field in {"provider_id", "backend_id"}:
            connection.execute(
                f"UPDATE environment_resources SET {field}=? WHERE identity=?",
                (value, resource.instance.identity),
            )
            return
        observation = json.loads(row["observation"])
        observation[field] = value
        connection.execute(
            "UPDATE environment_resources SET observation=? WHERE identity=?",
            (json.dumps(observation, sort_keys=True), resource.instance.identity),
        )


def test_same_manager_fresh_get_view_validates_without_creating_resource(resource):
    fresh = resource.manager.get(resource.instance.identity)
    assert fresh is not resource.instance

    current = resource.manager.validate_instance(
        fresh, expected_snapshot=resource.expected_snapshot
    )

    assert isinstance(current, EnvironmentSnapshot)
    assert current.identity == resource.expected_snapshot.identity
    assert current.provider_id == resource.expected_snapshot.provider_id
    assert current.backend_id == resource.expected_snapshot.backend_id
    assert current.generation == resource.expected_snapshot.generation
    assert resource.provider.creates == 1


def test_view_from_another_manager_sharing_store_and_provider_is_refused(resource):
    other_manager = EnvironmentManager(
        store=resource.store,
        providers={resource.provider.identity: resource.provider},
    )
    foreign_view = other_manager.get(resource.instance.identity)

    with pytest.raises(EnvironmentRefused):
        resource.manager.validate_instance(
            foreign_view, expected_snapshot=resource.expected_snapshot
        )
    assert resource.provider.creates == 1


def test_issued_view_with_replaced_manager_owner_is_refused(resource):
    other_manager = EnvironmentManager(
        store=resource.store,
        providers={resource.provider.identity: resource.provider},
    )
    issued_view = resource.manager.get(resource.instance.identity)
    issued_view._manager = other_manager

    with pytest.raises(EnvironmentRefused):
        resource.manager.validate_instance(
            issued_view, expected_snapshot=resource.expected_snapshot
        )


def test_forged_copied_and_subclass_views_are_refused(resource):
    class DerivedEnvironmentInstance(EnvironmentInstance):
        pass

    views = (
        EnvironmentInstance(resource.manager, resource.instance.identity),
        copy.copy(resource.instance),
        DerivedEnvironmentInstance(resource.manager, resource.instance.identity),
    )
    for view in views:
        with pytest.raises(EnvironmentRefused):
            resource.manager.validate_instance(
                view, expected_snapshot=resource.expected_snapshot
            )
    assert resource.provider.creates == 1


def test_same_provider_different_resource_is_refused(resource):
    other = resource.manager.register(resource.provider.identity, "another-backend")

    with pytest.raises(EnvironmentRefused):
        resource.manager.validate_instance(
            other, expected_snapshot=resource.expected_snapshot
        )
    assert resource.provider.creates == 1


def test_old_generation_is_refused_after_original_stop_and_start(resource):
    assert resource.instance.stop().confirmed
    assert resource.instance.start().confirmed
    assert resource.instance.snapshot.generation != resource.expected_snapshot.generation
    fresh = resource.manager.get(resource.instance.identity)

    with pytest.raises(EnvironmentRefused):
        resource.manager.validate_instance(fresh, expected_snapshot=resource.expected_snapshot)


@pytest.mark.parametrize("generation", [False, -1], ids=["bool-is-not-int-generation", "negative-generation"])
def test_expected_snapshot_requires_nonnegative_exact_integer_generation(resource, generation):
    malformed = replace(resource.expected_snapshot, generation=generation)
    fresh = resource.manager.get(resource.instance.identity)

    with pytest.raises(EnvironmentRefused):
        resource.manager.validate_instance(fresh, expected_snapshot=malformed)


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_id", "foreign-provider"),
        ("backend_id", "forged-backend"),
        ("runtime_identity", "runtime-2"),
        ("isolation", "container"),
        ("state", "stopped"),
    ],
    ids=["provider", "backend", "runtime-identity", "isolation", "state"],
)
def test_changed_resource_facts_are_refused(resource, field, value):
    _corrupt_snapshot(resource, field, value)
    fresh = resource.manager.get(resource.instance.identity)

    with pytest.raises(EnvironmentRefused):
        resource.manager.validate_instance(fresh, expected_snapshot=resource.expected_snapshot)


def test_observation_time_and_shared_active_use_do_not_change_resource_identity(resource):
    use = resource.instance.acquire("shared-owner", sharing=True)
    _corrupt_snapshot(resource, "observed_at", "2030-01-01T00:00:00+00:00")
    fresh = resource.manager.get(resource.instance.identity)

    current = resource.manager.validate_instance(
        fresh, expected_snapshot=resource.expected_snapshot
    )

    assert current.active_uses == 1
    assert current.observation.observed_at == "2030-01-01T00:00:00+00:00"
    assert resource.provider.creates == 1
    assert use.release()["resourcePreserved"] is True


def test_unknown_and_deleted_resources_are_refused(resource):
    resource.provider.fail_stop = True
    with pytest.raises(EnvironmentOperationUnknown):
        resource.instance.stop()
    fresh_unknown = resource.manager.get(resource.instance.identity)
    with pytest.raises(EnvironmentRefused):
        resource.manager.validate_instance(
            fresh_unknown, expected_snapshot=resource.expected_snapshot
        )

    # The unknown stop remains fenced; do not retry it. Exercise deletion on a
    # separate original resource so the UNKNOWN operation is never replayed.
    second = resource.manager.register(resource.provider.identity, "second-backend")
    second_snapshot = second.inspect()
    assert second.delete().confirmed
    fresh_deleted = resource.manager.get(second.identity)
    with pytest.raises(EnvironmentRefused):
        resource.manager.validate_instance(fresh_deleted, expected_snapshot=second_snapshot)
