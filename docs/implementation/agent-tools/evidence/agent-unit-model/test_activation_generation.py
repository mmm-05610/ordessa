"""Controlled C-layer evidence for durable activation-generation allocation.

Controlled C-layer evidence: real temporary SQLite (``SqliteStorePort``) plus
controlled ports and duck-typed fixtures; this is NOT a native process,
production database, provider or model run. Only generation allocation
identity is exercised here, not authorization semantics.

Scope: ``pacthold.core.activation_generation`` as reached through the durable
``Environment`` mode. Every case asserts both the positive and the refusal
side; no test is skipped and no assertion is relaxed to fit implementation
behaviour.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import sqlite3
from threading import Barrier

import pytest

from ordessa_environment_api import GuaranteeUnavailableError
from ordessa_persistence_sqlite import ProtectedFingerprintHmac, SqliteStorePort
from pacthold.agents.runtime import (
    RUNTIME_METHODS,
    RUNTIME_PROVIDER_VERSION,
    AgentContributionSet,
    RuntimeProviderDescriptor,
)
from pacthold.core.activation_generation import (
    ACTIVATION_GENERATION_NAMESPACE,
    ACTIVATION_GENERATION_SCHEMA,
    ACTIVATION_SEED_NAMESPACE,
    ActivationGenerationRefused,
    ActivationGenerationUnknown,
    seed_fresh_environment,
)
from pacthold.core.registration import (
    BatchAlreadyUsedError,
    CoreContributionSet,
    CoreRegistrySnapshot,
    RegistrationConflictError,
)
from pacthold.public import Environment, InstallationRecord

ENVIRONMENT_ID = "environment-testfixed1"
OWNER = "generation.plugin"
_RUNTIME_DIGEST = "sha256:" + "a" * 64


@dataclass(frozen=True)
class _Contract:
    contract_id = "generation.fixture@1"


def _fingerprint_port() -> ProtectedFingerprintHmac:
    return ProtectedFingerprintHmac({"fixture": b"isolated-key"}, active_key_id="fixture")


def _seed_fresh(store: SqliteStorePort) -> None:
    """Write the fresh-environment basis exactly like the deployment birth txn."""
    with store.transaction() as connection:
        seed_fresh_environment(connection, ENVIRONMENT_ID)


def _make_environment(store: SqliteStorePort, owner: str = OWNER) -> Environment:
    env = Environment(
        ENVIRONMENT_ID,
        store=store,
        policy=_AllowPolicy(),
        fingerprint_port=_fingerprint_port(),
        activation_generation="durable",
    )
    env.install(InstallationRecord(owner, "a" * 64))
    env.enable(owner)
    return env


def _generation_record(store: SqliteStorePort, owner: str = OWNER):
    return store.read_domain(ENVIRONMENT_ID, ACTIVATION_GENERATION_NAMESPACE, owner)


def _raw_generation_row(path, owner: str = OWNER):
    connection = sqlite3.connect(str(path))
    try:
        return connection.execute(
            "SELECT revision, payload FROM env_domain_records "
            "WHERE environment=? AND namespace=? AND record_id=?",
            (ENVIRONMENT_ID, ACTIVATION_GENERATION_NAMESPACE, owner),
        ).fetchone()
    finally:
        connection.close()


def _descriptor(provider_id: str) -> RuntimeProviderDescriptor:
    return RuntimeProviderDescriptor(
        provider_id,
        RUNTIME_PROVIDER_VERSION,
        {"environmentNamespace": ENVIRONMENT_ID, "definitionId": "fixture", "revision": "1"},
        _RUNTIME_DIGEST,
    )


class _Provider:
    """Controlled runtime provider fixture; never a native process."""

    def __init__(self, provider_id: str = "prov.testx") -> None:
        self.descriptor = _descriptor(provider_id)


for _name in RUNTIME_METHODS:
    setattr(_Provider, _name, lambda *args, **kwargs: None)


class _AllowPolicy:
    """Controlled policy port: this file tests generation allocation, not policy."""

    environment_id = ENVIRONMENT_ID

    def admit_invoke(self, *args, **kwargs) -> bool:
        return True

    def admit_object_access(self, *args, **kwargs) -> bool:
        return True


# 1 ---------------------------------------------------------------------------
def test_durable_generations_continue_across_cold_reopen(tmp_path):
    path = tmp_path / "cold-reopen.sqlite3"
    store = SqliteStorePort(path)
    try:
        _seed_fresh(store)
        env = _make_environment(store)
        first = env.activate(OWNER, CoreContributionSet())
        assert first.activation.generation == 1
        env.close()
    finally:
        store.close()

    # Cold reopen of the SAME fixed environment id on the same path.
    reopened = SqliteStorePort(path)
    try:
        env = _make_environment(reopened)
        second = env.activate(OWNER, CoreContributionSet())
        assert second.activation.generation == 2
        assert second.activation.generation != first.activation.generation
        record = _generation_record(reopened)
        assert record is not None
        assert record["value"] == {
            "environment": ENVIRONMENT_ID,
            "owner": OWNER,
            "schema": ACTIVATION_GENERATION_SCHEMA,
            "highWater": 2,
        }
        env.close()
    finally:
        reopened.close()


# 2 ---------------------------------------------------------------------------
def test_concurrent_instances_claim_each_generation_once(tmp_path):
    store = SqliteStorePort(tmp_path / "concurrent.sqlite3")
    try:
        _seed_fresh(store)
        # Two Environment instances over the SAME store object and environment id;
        # each owns its own activation indices but shares the domain CAS face.
        env_a = _make_environment(store)
        env_b = _make_environment(store)
        barrier = Barrier(2)

        def claim(env: Environment):
            barrier.wait(timeout=10)
            return env.activate(OWNER, CoreContributionSet())

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(claim, env) for env in (env_a, env_b)]
            receipts = [future.result(timeout=30) for future in futures]

        generations = sorted(receipt.activation.generation for receipt in receipts)
        # Neither instance may reuse the other's generation: exactly {1, 2}.
        assert generations == [1, 2]
        assert receipts[0].activation.generation != receipts[1].activation.generation
        assert all(receipt.activation.environment == ENVIRONMENT_ID for receipt in receipts)
        record = _generation_record(store)
        assert record is not None and record["value"]["highWater"] == 2
        env_a.close()
        env_b.close()
    finally:
        store.close()


# 3 ---------------------------------------------------------------------------
def test_publication_failure_consumes_generation_without_residue(tmp_path, monkeypatch):
    store = SqliteStorePort(tmp_path / "publication.sqlite3")
    try:
        _seed_fresh(store)
        env = _make_environment(store)
        provider = _Provider("prov.rollbackx")
        contributions = AgentContributionSet(agent_runtime_providers=(provider,))
        stage = env.stage_activation(OWNER, contributions)

        def failing_commit(batch):
            raise RuntimeError("publication exploded")

        monkeypatch.setattr(env._registry, "commit", failing_commit)
        with pytest.raises(RuntimeError, match="publication exploded"):
            stage.commit()
        # Staged batch has no residue: rolled back, and no contribution visible.
        assert stage.state == "rolled_back"
        assert env.registry_snapshot.agent_runtime_provider_ids == ()
        assert env.registry_snapshot.contract_ids == ()
        # The failed publication already consumed generation 1: high-water = 1.
        record = _generation_record(store)
        assert record is not None and record["value"]["highWater"] == 1

        monkeypatch.undo()
        # A rolled-back batch can never be re-committed by the real registry.
        with pytest.raises(BatchAlreadyUsedError):
            env._registry.commit(stage._batch)
        receipt = env.activate(OWNER, contributions)
        assert receipt.activation.generation == 2
        assert env.registry_snapshot.agent_runtime_provider_ids == ("prov.rollbackx",)
        record = _generation_record(store)
        assert record is not None and record["value"]["highWater"] == 2
        env.close()
    finally:
        store.close()


# 4 ---------------------------------------------------------------------------
def test_lost_reservation_receipt_is_not_published_or_resent(tmp_path, monkeypatch):
    store = SqliteStorePort(tmp_path / "lost-receipt.sqlite3")
    try:
        _seed_fresh(store)
        env = _make_environment(store)
        provider = _Provider("prov.receiptlost")
        contributions = AgentContributionSet(agent_runtime_providers=(provider,))

        real_commit = store.commit_domain_change
        calls = []

        def lost_receipt(request, digest, writes, result):
            calls.append(request)
            real_commit(request, digest, writes, result)
            raise OSError("receipt lost")

        monkeypatch.setattr(store, "commit_domain_change", lost_receipt)
        with pytest.raises(GuaranteeUnavailableError) as excinfo:
            env.activate(OWNER, contributions)
        assert isinstance(excinfo.value, ActivationGenerationUnknown)
        # Unknown outcome: never resent, never published.
        assert len(calls) == 1
        assert env.registry_snapshot.agent_runtime_provider_ids == ()
        # The real commit did persist before the receipt was lost: the
        # high-water record is still there and was not deleted to "roll back".
        record = _generation_record(store)
        assert record is not None and record["value"]["highWater"] == 1

        monkeypatch.undo()
        receipt = env.activate(OWNER, contributions)
        assert receipt.activation.generation == 2  # the lost receipt's write persisted
        record = _generation_record(store)
        assert record is not None and record["value"]["highWater"] == 2
        env.close()
    finally:
        store.close()


# 5 ---------------------------------------------------------------------------
def _damaged_value(kind: str) -> dict:
    value = {
        "environment": ENVIRONMENT_ID,
        "owner": OWNER,
        "schema": ACTIVATION_GENERATION_SCHEMA,
        "highWater": 1,
    }
    if kind == "high-water-bool":
        value["highWater"] = True
    elif kind == "high-water-float":
        value["highWater"] = 2.0
    elif kind == "schema":
        value["schema"] = "activation-generation/2"
    elif kind == "owner":
        value["owner"] = "generation.plugin.other"
    elif kind == "environment":
        value["environment"] = "environment-otherenv1"
    elif kind == "extra":
        value["extra"] = "unexpected"
    else:  # pragma: no cover - the parametrization below is exhaustive
        raise AssertionError(f"unknown damage kind {kind!r}")
    return value


@pytest.mark.parametrize(
    "kind",
    ["high-water-bool", "high-water-float", "schema", "owner", "environment", "extra"],
)
def test_damaged_generation_record_is_refused(tmp_path, kind):
    path = tmp_path / f"damaged-{kind}.sqlite3"
    store = SqliteStorePort(path)
    try:
        _seed_fresh(store)
        env = _make_environment(store)
        first = env.activate(OWNER, CoreContributionSet(contracts=(_Contract,)))
        assert first.activation.generation == 1
        before = env.registry_snapshot
        assert before.contract_ids == ("generation.fixture@1",)

        damaged = _damaged_value(kind)
        damaged_payload = json.dumps(damaged, sort_keys=True, allow_nan=False)
        connection = sqlite3.connect(str(path))
        try:
            connection.execute(
                "UPDATE env_domain_records SET payload=? "
                "WHERE environment=? AND namespace=? AND record_id=?",
                (damaged_payload, ENVIRONMENT_ID, ACTIVATION_GENERATION_NAMESPACE, OWNER),
            )
            connection.commit()
        finally:
            connection.close()
        broken = _generation_record(store)
        assert broken is not None and broken["value"] == damaged

        with pytest.raises(GuaranteeUnavailableError) as excinfo:
            env.activate(OWNER, CoreContributionSet())
        assert isinstance(excinfo.value, ActivationGenerationRefused)

        # Damaged evidence is never rewritten into something usable, and no
        # activation contribution is published from the refused attempt.
        assert env.registry_snapshot == before
        assert env.registry_snapshot.contract_ids == ("generation.fixture@1",)
        still_broken = _generation_record(store)
        assert still_broken is not None and still_broken["value"] == damaged
        assert still_broken["revision"] == 1
        revision, payload = _raw_generation_row(path)
        assert revision == 1 and payload == damaged_payload
        env.close()
    finally:
        store.close()


def test_valid_generation_record_reactivates_next_generation(tmp_path):
    """Intact control for the damaged-record refusals above."""
    store = SqliteStorePort(tmp_path / "intact.sqlite3")
    try:
        _seed_fresh(store)
        env = _make_environment(store)
        first = env.activate(OWNER, CoreContributionSet(contracts=(_Contract,)))
        assert first.activation.generation == 1
        second = env.activate(OWNER, CoreContributionSet())
        assert second.activation.generation == 2
        assert second.activation.generation != first.activation.generation
        record = _generation_record(store)
        assert record is not None and record["value"]["highWater"] == 2
        assert env.registry_snapshot.contract_ids == ("generation.fixture@1",)
        env.close()
    finally:
        store.close()


# 6 ---------------------------------------------------------------------------
def test_historical_database_without_basis_is_refused(tmp_path):
    # A store with no fresh-environment basis at all: a historical database.
    store = SqliteStorePort(tmp_path / "historical.sqlite3")
    try:
        env = _make_environment(store)
        with pytest.raises(GuaranteeUnavailableError) as excinfo:
            env.activate(OWNER, CoreContributionSet())
        assert isinstance(excinfo.value, ActivationGenerationRefused)

        assert _generation_record(store) is None
        assert store.list_domain(ENVIRONMENT_ID, ACTIVATION_GENERATION_NAMESPACE) == ()
        assert store.list_domain(ENVIRONMENT_ID, ACTIVATION_SEED_NAMESPACE) == ()
        assert env.registry_snapshot == CoreRegistrySnapshot()
        env.close()
    finally:
        store.close()


# 8 ---------------------------------------------------------------------------
def test_contribution_conflict_still_judged_by_registry(tmp_path):
    store = SqliteStorePort(tmp_path / "registry-conflict.sqlite3")
    try:
        _seed_fresh(store)
        env = _make_environment(store)
        provider = _Provider("prov.testx")
        first = env.activate(OWNER, AgentContributionSet(agent_runtime_providers=(provider,)))
        assert first.activation.generation == 1
        assert env.registry_snapshot.agent_runtime_provider_ids == ("prov.testx",)

        # Same owner, same provider id, second activation: the CoreRegistry is
        # still the sole contribution authority and refuses the duplicate at
        # staging time, before any generation reservation.
        second_provider = _Provider("prov.testx")
        with pytest.raises(RegistrationConflictError):
            env.activate(OWNER, AgentContributionSet(agent_runtime_providers=(second_provider,)))

        # Exactly one provider and one activation: no successful re-registration.
        assert env.registry_snapshot.agent_runtime_provider_ids == ("prov.testx",)
        admitted = env.agent_runtime_contribution(provider.descriptor.definition_ref)
        assert admitted.owner_activation == first.activation
        assert admitted.provider_ref["generation"] == 1
        # Actual behaviour: the conflict is raised while staging, so no
        # generation was consumed for the refused second activation.
        record = _generation_record(store)
        assert record is not None and record["value"]["highWater"] == 1
        env.close()
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Run evidence (recorded after the actual run; controlled C-layer evidence,
# real tmp_path SQLite + controlled ports, no native process/model):
#
# $ PYTHONPATH=products/agent-tools/deployment:packages/backend/harness-transport/src \
#       /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python \
#       -m pytest -c products/agent-tools/pyproject.toml \
#       docs/implementation/agent-tools/evidence/agent-unit-model/test_activation_generation.py \
#       -q --tb=short
# .............                                                            [100%]
# 13 passed in 0.19s
# exit code: 0
#
# Test 7 is intentionally absent here; it is covered by a separate file.
# No implementation/test conflict was found. No assertion was weakened, no
# test skipped, no mock used to fake green.
