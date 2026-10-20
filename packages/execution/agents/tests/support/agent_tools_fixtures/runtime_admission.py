"""Existing Environment registration authority, controlled provider contracts.

These are admission tests, not native process or product readiness evidence.
"""
from dataclasses import dataclass

import pytest

from ordessa_execution_agents.harness.providers.registry.errors import (
    CatalogAdmissionRefused, CatalogIdentityConflict,
)
from pacthold.public import Environment, InstallationRecord
from pacthold.core.registration import CoreRegistry
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.core.registration import RegistrationConflictError
from ordessa_execution_agents.harness.definitions.errors import CoreDTOError
from ordessa_execution_agents.harness.providers.registry.contributions import AgentContributionSet, RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION, RUNTIME_METHODS




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

class Policy:
    allowed = True
    def admit_object_access(self, principal, target, mode): return self.allowed
    def admit_invoke(self, *args): return self.allowed


def descriptor(provider_id="fixture.runtime", definition_id="fixture", environment="runtime-test"):
    return RuntimeProviderDescriptor(provider_id, RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": environment, "definitionId": definition_id, "revision": "1"},
        "sha256:" + "a" * 64)


class Provider:
    def __init__(self, value=None): self.descriptor = value or descriptor()


for name in RUNTIME_METHODS:
    setattr(Provider, name, lambda *args, **kwargs: None)


def installed(owner="fixture.plugin", *, store_path=None, request=None):
    policy = Policy()
    store = SqliteStorePort(store_path) if store_path is not None else None
    env = Environment("runtime-test", store=store, policy=policy, resource_extension_snapshot=_test_resource_snapshot)
    if request is not None and store is not None:
        request.addfinalizer(store.close)
        request.addfinalizer(env.close)
    env.install(InstallationRecord(owner, "a" * 64))
    env.enable(owner)
    return env, policy


