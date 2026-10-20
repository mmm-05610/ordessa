"""Explicit production owner wiring counterexamples (controlled C evidence).

Real temporary SQLite store/journal and the real deployment composition with
controlled authority/evidence ports. No native process, no model, no user
data. Every case here must stay a strict refusal or strict cleanup semantic:
none of them may be softened to make the suite green.
"""
from __future__ import annotations
from ordessa_server.composition.agent_tools.owner_ports import OwnerAssemblyRefused

import importlib
import importlib.util
import json
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from ordessa_units.public import unit_services
from pacthold.core.registration import CoreContributionSet
from pacthold.environment import InstallationRecord

def deployment_module():
    from ordessa_server.composition import agent_tools
    return agent_tools


def owner_ports_module(deployment):
    return importlib.import_module(deployment.__name__ + ".owner_ports")


def fingerprint():
    from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
    return ProtectedFingerprintHmac({"fixture": b"isolated-owner-wiring"}, active_key_id="fixture")


class Authority:
    issuer_ref = {"environmentNamespace": "env", "issuerId": "controlled-owner-authority"}
    revision = "rev-1"
    expiry = 100

    def authorize(self, request, actions, target_ref, delegation_ref):
        from ordessa_units.admission.invocation import InvocationGrant
        return InvocationGrant(principal_scope=request.principal_scope, actions=actions,
                               target_ref=target_ref, delegation_ref=delegation_ref,
                               authority_revision=self.revision, expires_at=self.expiry,
                               issuer_ref=self.issuer_ref)

    def revalidate(self, grant, request, actions, target_ref):
        return self.authorize(request, actions, target_ref, grant.delegation_ref)


class CurrentState:
    def inspect(self, request, pinned_provider_ref, context_ref, target_ref, action):
        return None


class ScopeAuthority:
    def issue_scope(self, provider_ref, node_ref, private_root_facts):
        raise AssertionError("not used in these counterexamples")

    def verify_scope(self, scope_ref, private_root_facts):
        return True

    def map_legacy_scope(self, legacy_target):
        return None


class SessionEvidence:
    def verify_binding(self, unit, creation_correlation, evidence):
        raise AssertionError("not used in these counterexamples")


class Epoch:
    def current_epoch(self, node_ref):
        return 0


class NodeEvidence:
    def inspect(self, operation, steps):
        return None


class ContextPort:
    def resolve(self, request, manifest, admitted_provider, node_ref, context, options):
        raise AssertionError("not used in these counterexamples")


class ObservationPort:
    def observe(self, operation, step, reply):
        raise AssertionError("not used in these counterexamples")


class Policy:
    def __init__(self, environment_id):
        self.environment_id = environment_id

    def admit_invoke(self, principal, surface, guarantee):
        return True

    def admit_object_access(self, principal, object_ref, mode):
        return True


def owner_ports(owner_mod, **overrides):
    fields = dict(authority=Authority(), current_state=CurrentState(),
                  scope_authority=ScopeAuthority(),
                  native_session_evidence=SessionEvidence(),
                  management_epoch=Epoch(),
                  node_evidence_port=NodeEvidence(),
                  preparation_context_port=ContextPort(),
                  preparation_observation_port=ObservationPort())
    fields.update(overrides)
    return owner_mod.OwnerPorts(**fields)


def make_deployment(deployment, owner_mod, tmp_path, *, ports_factory=True, **port_overrides):
    def owner_factory(environment):
        return owner_ports(owner_mod, **port_overrides)

    kwargs = {}
    if ports_factory:
        kwargs["policy_factory"] = lambda env_id: Policy(env_id.value)
        kwargs["owner_ports_factory"] = owner_factory
    return deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        **kwargs)


def core_path(tmp_path):
    (tmp_path / "state").mkdir(parents=True, exist_ok=True)
    return tmp_path / "state" / "core.sqlite"


@pytest.fixture
def root_ownership_port():
    """Acquire real host ownership for each temporary root used by a test."""
    from ordessa_server.bootstrap.data_root import write_owner_marker
    from ordessa_server.composition.runtime import DataRootOwner

    owners = {}

    def acquire(root_path):
        root = Path(root_path).absolute()
        if root in owners:
            return owners[root]
        root.mkdir(parents=True, exist_ok=True)
        # pytest created this isolated test root; use the host's normal marker
        # writer before acquiring its real exclusive lease.
        write_owner_marker(root)
        owner = DataRootOwner(root)
        owner.acquire()
        owners[root] = owner
        return owner

    try:
        yield acquire
    finally:
        for owner in reversed(tuple(owners.values())):
            owner.release()


# -- factory pairing / typing / version gates ---------------------------------

def test_factories_must_be_paired_callable_and_v2(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    path = core_path(tmp_path)
    assert path.parent.is_dir()  # refusals below create no deployment
    with pytest.raises(OwnerAssemblyRefused, match="supplied together"):
        deployment.AgentToolsDeployment(
            fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
            policy_factory=lambda env_id: Policy(env_id.value))
    with pytest.raises(OwnerAssemblyRefused, match="supplied together"):
        deployment.AgentToolsDeployment(
            fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
            owner_ports_factory=lambda environment: owner_ports(owner_mod))
    with pytest.raises(TypeError):
        deployment.AgentToolsDeployment(
            fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
            policy_factory=5, owner_ports_factory=lambda environment: owner_ports(owner_mod))
    with pytest.raises(TypeError):
        deployment.AgentToolsDeployment(
            fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
            policy_factory=lambda env_id: Policy(env_id.value), owner_ports_factory=5)
    with pytest.raises(OwnerAssemblyRefused, match="agent-assembly/3"):
        deployment.AgentToolsDeployment(
            fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/1",
            policy_factory=lambda env_id: Policy(env_id.value),
            owner_ports_factory=lambda environment: owner_ports(owner_mod))
    assert not path.exists()  # constructor refusals create no core database


def test_lifecycle_observation_is_injected_into_the_same_owner_services(tmp_path, root_ownership_port):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)

    class LifecycleObservation:
        def observe(self, operation, step, reply):
            return None

    evidence = LifecycleObservation()
    wired = make_deployment(deployment, owner_mod, tmp_path,
                            lifecycle_observation_port=evidence)
    env = wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    try:
        assert env._agent_services.lifecycle._observation_port is evidence
        assert env._agent_services.lifecycle._issuer is env.owner_ports.issuer
        assert env._agent_services.lifecycle._issuer._store is env.store_port
    finally:
        env.close()


def test_wired_v2_deployment_assembles_single_owner(tmp_path, root_ownership_port):
    deployment = deployment_module()
    wired = make_deployment(deployment, owner_ports_module(deployment), tmp_path)
    env = wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    try:
        owner = env.owner_ports
        assert owner is not None
        # One issuer on the environment's original store, one verifier shared
        # by the records owner and providers, one canonical journal.
        assert owner.issuer._store is env.store_port
        assert owner.records.verifier is owner.verifier
        assert owner.records.journal is owner.journal
        assert env._agent_services is not None
        assert env._agent_services.configuration._issuer is owner.issuer
        journal_path = tmp_path / "plugins" / "profile" / "native-configuration.sqlite"
        assert journal_path.is_file()
    finally:
        env.close()


def test_foreign_bound_policy_is_refused(tmp_path, root_ownership_port):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)

    def owner_factory(environment):
        return owner_ports(owner_mod)

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy("foreign-environment"),
        owner_ports_factory=owner_factory)
    with pytest.raises(OwnerAssemblyRefused, match="foreign"):
        wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))


# -- port shape refusals ------------------------------------------------------

def test_required_and_optional_ports_need_callable_methods(tmp_path, root_ownership_port):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    cases = [
        dict(management_epoch=None),
        dict(scope_authority=type("BadScope", (), {"issue_scope": None,
                                                   "verify_scope": None,
                                                   "map_legacy_scope": None})()),
        dict(native_session_evidence=type("BadSession", (), {"verify_binding": None})()),
        dict(node_evidence_port=type("BadNode", (), {"inspect": 5})()),
        dict(preparation_context_port=type("BadCtx", (), {"resolve": "nope"})()),
        dict(configuration_evidence=type("BadConfig", (), {})()),
        dict(native_unit_evidence=type("BadUnit", (), {"verify_unit_binding": None})()),
        dict(input_association_evidence=type("BadInput", (), {})()),
        dict(termination_evidence=type("BadTerm", (), {})()),
        dict(termination_evidence=type("BadTermMethod", (), {"verify_termination": 5})()),
        dict(close=5),
    ]
    for overrides in cases:
        wired = make_deployment(deployment, owner_mod, tmp_path, **overrides)
        with pytest.raises(OwnerAssemblyRefused):
            wired.owned_environment_factory(
                core_path(tmp_path / "r"), root_ownership_port(tmp_path / "r"))


def test_owner_factory_must_not_pre_cache_agent_services(tmp_path, root_ownership_port):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)

    def owner_factory(environment):
        unit_services(environment)  # poisons the one-shot cache without issuer
        return owner_ports(owner_mod)

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy(env_id.value),
        owner_ports_factory=owner_factory)
    with pytest.raises(OwnerAssemblyRefused, match="cached agent services"):
        wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    journal_path = tmp_path / "plugins" / "profile" / "native-configuration.sqlite"
    assert not journal_path.exists()


# -- journal ownership evidence ----------------------------------------------

def test_existing_journal_without_trusted_evidence_is_refused_and_never_deleted(
    tmp_path, root_ownership_port
):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    wired = make_deployment(deployment, owner_mod, tmp_path)
    journal_path = tmp_path / "plugins" / "profile" / "native-configuration.sqlite"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_bytes(b"")  # empty historical file: still unattributable
    with pytest.raises(OwnerAssemblyRefused, match="trusted ownership evidence"):
        wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    assert journal_path.exists()  # never deleted to fake a rollback


def test_evidenced_journal_loses_refusal_only_when_evidence_matches(
    tmp_path, root_ownership_port
):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    wired = make_deployment(deployment, owner_mod, tmp_path)
    env = wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    env.close()
    journal_path = tmp_path / "plugins" / "profile" / "native-configuration.sqlite"
    assert journal_path.is_file()
    # Remove the trusted ownership evidence: an existing journal with history
    # must then be refused, and its rows must survive untouched.
    from pacthold.core.activation_generation import (
        ACTIVATION_SEED_NAMESPACE, JOURNAL_BINDING_RECORD)
    with sqlite3.connect(core_path(tmp_path)) as db:
        before = db.execute("SELECT COUNT(*) FROM env_requests").fetchone()[0]
        db.execute("DELETE FROM env_domain_records WHERE namespace=? AND record_id=?",
                   (ACTIVATION_SEED_NAMESPACE, JOURNAL_BINDING_RECORD))
        db.commit()
    with pytest.raises(OwnerAssemblyRefused, match="trusted ownership evidence"):
        wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    with sqlite3.connect(core_path(tmp_path)) as db:
        after = db.execute("SELECT COUNT(*) FROM env_requests").fetchone()[0]
    assert after == before
    assert journal_path.is_file()


def test_journal_and_sidecars_must_not_traverse_symlinks(tmp_path, root_ownership_port):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target.sqlite"
    target.write_bytes(b"")

    # case A: the journal file itself is a symlink
    root_a = tmp_path / "s1"
    journal_a = root_a / "plugins" / "profile" / "native-configuration.sqlite"
    journal_a.parent.mkdir(parents=True)
    journal_a.symlink_to(target)
    with pytest.raises(OwnerAssemblyRefused, match="symlink"):
        make_deployment(deployment, owner_mod, root_a).owned_environment_factory(
            core_path(root_a), root_ownership_port(root_a))

    # case B: the journal is real but its WAL sidecar is a symlink
    root_b = tmp_path / "s2"
    journal_b = root_b / "plugins" / "profile" / "native-configuration.sqlite"
    journal_b.parent.mkdir(parents=True)
    journal_b.write_bytes(b"")
    journal_b.with_name(journal_b.name + "-wal").symlink_to(target)
    with pytest.raises(OwnerAssemblyRefused, match="symlink"):
        make_deployment(deployment, owner_mod, root_b).owned_environment_factory(
            core_path(root_b), root_ownership_port(root_b))

    # case C: the journal's parent directory is a symlink
    root_c = tmp_path / "s3"
    (root_c / "plugins").mkdir(parents=True)
    (root_c / "plugins" / "profile").symlink_to(outside)
    with pytest.raises(OwnerAssemblyRefused, match="symlink"):
        make_deployment(deployment, owner_mod, root_c).owned_environment_factory(
            core_path(root_c), root_ownership_port(root_c))


# -- mixing refusals ---------------------------------------------------------

def test_second_store_on_same_core_file_is_refused(tmp_path, root_ownership_port):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    wired = make_deployment(deployment, owner_mod, tmp_path)
    env = wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    try:
        from pacthold.adapters.sqlite.environment.store import WriterLockHeldError
        with pytest.raises(WriterLockHeldError):
            SqliteStorePort(core_path(tmp_path))
    finally:
        env.close()


def test_second_scope_authority_on_same_journal_is_refused(tmp_path, root_ownership_port):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    wired = make_deployment(deployment, owner_mod, tmp_path)
    env = wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    try:
        from ordessa_units.records import UnitRecordsRefused
        # A different scope authority on the same journal object is refused by
        # the original single-owner pin; a second full assembly is refused by
        # the deployment itself.
        with pytest.raises(UnitRecordsRefused):
            owner_mod.assemble_owner(
                env, owner_ports(owner_mod, scope_authority=ScopeAuthority()),
                env.owner_ports.journal)
        path = core_path(tmp_path)
        child = tmp_path / "plugins" / "profile" / "native-configuration.sqlite"
        binding = root_ownership_port(tmp_path).bind_owned_root(
            root_path=tmp_path, store_path=path, child_path=child)
        def current_owner():
            binding.validate_for(root_path=tmp_path, store_path=path, child_path=child)
        with pytest.raises(OwnerAssemblyRefused, match="already assembled"):
            wired._wire_owner(env, env.store_port, env.environment_id, path, current_owner)
    finally:
        env.close()


# -- owner close chain semantics ---------------------------------------------

def _wired_env(tmp_path, owner_mod, deployment, root_ownership_port, **port_overrides):
    wired = make_deployment(deployment, owner_mod, tmp_path, **port_overrides)
    return wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))


def test_owner_callback_reentering_close_is_contained_and_error_preserved(
    tmp_path, root_ownership_port
):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    holder = {"attempts": 0}

    def reenter_once():
        holder["attempts"] += 1
        if holder["attempts"] == 1:
            holder["env"].close()

    def owner_factory(environment):
        holder["env"] = environment
        return owner_ports(owner_mod, close=reenter_once)

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy(env_id.value),
        owner_ports_factory=owner_factory)
    env = wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    from pacthold.adapters.sqlite.environment.store import WriterLockHeldError
    with pytest.raises(OwnerAssemblyRefused, match="already in progress"):
        env.close()
    assert env._closed is False  # callback failure cannot silently finish close
    assert env.owner_ports.issuer._closed is True  # permission still revoked
    with pytest.raises(WriterLockHeldError):
        SqliteStorePort(core_path(tmp_path))
    env.close()  # same original Environment retries, no second owner
    assert holder["attempts"] == 2 and env._closed is True
    reopened = SqliteStorePort(core_path(tmp_path))
    reopened.close()


def test_two_threads_closing_release_the_store_exactly_once(tmp_path, root_ownership_port):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    env = _wired_env(tmp_path, owner_mod, deployment, root_ownership_port)
    store = env.store_port
    closed = []
    original_close = store.close

    def counting_close():
        closed.append(1)
        original_close()

    store.close = counting_close
    barrier = threading.Barrier(2)
    results = []

    def run():
        barrier.wait()
        try:
            env.close()
            results.append(None)
        except BaseException as exc:  # noqa: BLE001
            results.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [None, None]
    assert len(closed) == 1
    assert env._closed is True


def test_cleanup_failure_still_revokes_permission_and_preserves_error(
    tmp_path, root_ownership_port
):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    attempts = []

    def owner_factory(environment):
        def failing_once():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("fence-failed-do-not-leak")
        return owner_ports(owner_mod, close=failing_once)

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy(env_id.value),
        owner_ports_factory=owner_factory)
    env = wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    from pacthold.adapters.sqlite.environment.store import WriterLockHeldError
    with pytest.raises(RuntimeError, match="fence-failed-do-not-leak"):
        env.close()
    assert env.owner_ports.issuer._closed is True  # live grants revoked anyway
    assert env._closed is False  # failed fence does not release the writer
    with pytest.raises(WriterLockHeldError):
        SqliteStorePort(core_path(tmp_path))
    env.close()
    assert len(attempts) == 2 and env._closed is True
    reopened = SqliteStorePort(core_path(tmp_path))
    reopened.close()






def test_provider_view_and_owner_reads_never_issue_invocations(tmp_path, root_ownership_port):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    env = _wired_env(tmp_path, owner_mod, deployment, root_ownership_port)
    try:
        owner = env.owner_ports
        view = owner.provider_view
        assert view.records is owner.records
        assert view.verifier is owner.verifier
        # The provider view never carries issuance capability.
        assert not hasattr(view, "issuer")
        assert getattr(view, "issuer", None) is None
        # Owner projection reads require no invocation context at all.
        from ordessa_units.records import UnitRecordsRefused
        with pytest.raises(UnitRecordsRefused):
            owner.records.owner_read_unit("unit-that-does-not-exist")
        with pytest.raises(UnitRecordsRefused):
            owner.records.owner_read_session("unit-that-does-not-exist")
        # The authorized read surface still demands its invocation context.
        with pytest.raises(TypeError):
            owner.records.read_unit("unit-that-does-not-exist")
    finally:
        env.close()


def _reserve_pending_unit(env, name):
    """Same SQLite Unit reservation shape, with the ordinary admission lock."""
    from ordessa_infrastructure.identifiers import RequestKey
    from ordessa_units.definitions.operations import OperationIntent, StepIntent, UsageMutation, operation_holder
    provider_ref = {"environmentNamespace": env.environment_id, "providerId": "controlled",
                    "generation": 1, "contractVersion": "1",
                    "implementationDigest": "sha256:" + "a" * 64}
    request = RequestKey(env.environment_id, "local", "close-" + name)
    step = StepIntent("prepare", provider_ref, "fixed-input", "original-correlation")
    intent = OperationIntent("pending-" + name, "agent-preparation", None,
                             {"environmentNamespace": env.environment_id}, (step,))
    usage = UsageMutation("usage-" + name, 0, None,
                          operation_holder(request, intent.operation_ref),
                          {"environmentNamespace": env.environment_id, "resourceId": name},
                          ("use",), "active")
    with env._admission_lock:
        env._check_open()
        env.store_port.reserve_operation(request, "digest-" + name, intent, usages=(usage,))


def test_failed_revoke_retry_recounts_new_same_store_unit_obligation(
    tmp_path, root_ownership_port
):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    attempts = []

    def owner_factory(environment):
        def fail_once():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("controlled-revoke-failure")
        return owner_ports(owner_mod, close=fail_once)

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy(env_id.value),
        owner_ports_factory=owner_factory)
    env = wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    from pacthold.adapters.sqlite.environment.store import WriterLockHeldError
    _reserve_pending_unit(env, "before")
    with pytest.raises(RuntimeError, match="controlled-revoke-failure"):
        env.close()
    assert env._closed is False and env._unit_shutdown_report is None
    with pytest.raises(WriterLockHeldError):
        SqliteStorePort(core_path(tmp_path))
    # The first close did not cache a pre-revoke inventory. A still-open
    # Environment can acquire another original Unit obligation before retry.
    _reserve_pending_unit(env, "after")
    report = env.close()
    assert report.unresolved_operation_refs == ("pending-after", "pending-before")
    assert report.active_usage_ids == ("usage-after", "usage-before")
    assert env.close() is report and len(attempts) == 2
    reopened = SqliteStorePort(core_path(tmp_path))
    reopened.close()


def test_concurrent_admission_before_close_cut_is_in_final_report(
    tmp_path, root_ownership_port
):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    inside_callback, allow_cut = threading.Event(), threading.Event()

    def owner_factory(environment):
        def pause_revoke():
            inside_callback.set()
            assert allow_cut.wait(10)
        return owner_ports(owner_mod, close=pause_revoke)

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy(env_id.value),
        owner_ports_factory=owner_factory)
    env = wired.owned_environment_factory(core_path(tmp_path), root_ownership_port(tmp_path))
    results = []

    def closing():
        try:
            results.append(env.close())
        except BaseException as exc:  # noqa: BLE001
            results.append(exc)

    thread = threading.Thread(target=closing)
    thread.start()
    assert inside_callback.wait(10)
    try:
        _reserve_pending_unit(env, "raced-before-cut")
    finally:
        allow_cut.set()
    thread.join(10)
    assert not thread.is_alive() and len(results) == 1
    assert not isinstance(results[0], BaseException)
    report = results[0]
    assert report.unresolved_operation_refs == ("pending-raced-before-cut",)
    assert report.active_usage_ids == ("usage-raced-before-cut",)
    assert env._closed is True
    from pacthold.environment import EnvironmentClosedError
    with pytest.raises(EnvironmentClosedError):
        _reserve_pending_unit(env, "after-cut-refused")


