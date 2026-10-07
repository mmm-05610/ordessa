"""Explicit production owner wiring counterexamples (controlled C evidence).

Real temporary SQLite store/journal and the real deployment composition with
controlled authority/evidence ports. No native process, no model, no user
data. Every case here must stay a strict refusal or strict cleanup semantic:
none of them may be softened to make the suite green.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

from ordessa_environment_api import GuaranteeUnavailableError
from ordessa_persistence_sqlite import SqliteStorePort
from pacthold.agents.public import agent_services
from pacthold.core.registration import CoreContributionSet
from pacthold.environment import InstallationRecord, ObservationReleasePendingError

DEPLOYMENT_ROOT = Path(__file__).resolve().parents[5] / "products" / "agent-tools"


def deployment_module():
    path = DEPLOYMENT_ROOT / "deployment" / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "agent_tools_owner_wiring_deployment", path,
        submodule_search_locations=[str(path.parent)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def owner_ports_module(deployment):
    return importlib.import_module(deployment.__name__ + ".owner_ports")


def fingerprint():
    from ordessa_persistence_sqlite import ProtectedFingerprintHmac
    return ProtectedFingerprintHmac({"fixture": b"isolated-owner-wiring"}, active_key_id="fixture")


class Authority:
    issuer_ref = {"environmentNamespace": "env", "issuerId": "controlled-owner-authority"}
    revision = "rev-1"
    expiry = 100

    def authorize(self, request, actions, target_ref, delegation_ref):
        from pacthold.agents.access.invocation import InvocationGrant
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


# -- factory pairing / typing / version gates ---------------------------------

def test_factories_must_be_paired_callable_and_v2(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    path = core_path(tmp_path)
    assert path.parent.is_dir()  # refusals below create no deployment
    with pytest.raises(GuaranteeUnavailableError, match="supplied together"):
        deployment.AgentToolsDeployment(
            fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
            policy_factory=lambda env_id: Policy(env_id.value))
    with pytest.raises(GuaranteeUnavailableError, match="supplied together"):
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
    with pytest.raises(GuaranteeUnavailableError, match="agent-assembly/3"):
        deployment.AgentToolsDeployment(
            fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/1",
            policy_factory=lambda env_id: Policy(env_id.value),
            owner_ports_factory=lambda environment: owner_ports(owner_mod))
    assert not path.exists()  # constructor refusals create no core database


def test_wired_v2_deployment_assembles_single_owner(tmp_path):
    deployment = deployment_module()
    wired = make_deployment(deployment, owner_ports_module(deployment), tmp_path)
    env = wired.owned_environment_factory(core_path(tmp_path), lambda: True)
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


def test_foreign_bound_policy_is_refused(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)

    def owner_factory(environment):
        return owner_ports(owner_mod)

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy("foreign-environment"),
        owner_ports_factory=owner_factory)
    with pytest.raises(GuaranteeUnavailableError, match="foreign"):
        wired.owned_environment_factory(core_path(tmp_path), lambda: True)


# -- port shape refusals ------------------------------------------------------

def test_required_and_optional_ports_need_callable_methods(tmp_path):
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
        with pytest.raises(GuaranteeUnavailableError):
            wired.owned_environment_factory(core_path(tmp_path / "r"), lambda: True)


def test_owner_factory_must_not_pre_cache_agent_services(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)

    def owner_factory(environment):
        agent_services(environment)  # poisons the one-shot cache without issuer
        return owner_ports(owner_mod)

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy(env_id.value),
        owner_ports_factory=owner_factory)
    with pytest.raises(GuaranteeUnavailableError, match="cached agent services"):
        wired.owned_environment_factory(core_path(tmp_path), lambda: True)
    journal_path = tmp_path / "plugins" / "profile" / "native-configuration.sqlite"
    assert not journal_path.exists()


# -- journal ownership evidence ----------------------------------------------

def test_existing_journal_without_trusted_evidence_is_refused_and_never_deleted(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    wired = make_deployment(deployment, owner_mod, tmp_path)
    journal_path = tmp_path / "plugins" / "profile" / "native-configuration.sqlite"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_path.write_bytes(b"")  # empty historical file: still unattributable
    with pytest.raises(GuaranteeUnavailableError, match="trusted ownership evidence"):
        wired.owned_environment_factory(core_path(tmp_path), lambda: True)
    assert journal_path.exists()  # never deleted to fake a rollback


def test_evidenced_journal_loses_refusal_only_when_evidence_matches(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    wired = make_deployment(deployment, owner_mod, tmp_path)
    env = wired.owned_environment_factory(core_path(tmp_path), lambda: True)
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
    with pytest.raises(GuaranteeUnavailableError, match="trusted ownership evidence"):
        wired.owned_environment_factory(core_path(tmp_path), lambda: True)
    with sqlite3.connect(core_path(tmp_path)) as db:
        after = db.execute("SELECT COUNT(*) FROM env_requests").fetchone()[0]
    assert after == before
    assert journal_path.is_file()


def test_journal_and_sidecars_must_not_traverse_symlinks(tmp_path):
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
    with pytest.raises(GuaranteeUnavailableError, match="symlink"):
        make_deployment(deployment, owner_mod, root_a).owned_environment_factory(
            core_path(root_a), lambda: True)

    # case B: the journal is real but its WAL sidecar is a symlink
    root_b = tmp_path / "s2"
    journal_b = root_b / "plugins" / "profile" / "native-configuration.sqlite"
    journal_b.parent.mkdir(parents=True)
    journal_b.write_bytes(b"")
    journal_b.with_name(journal_b.name + "-wal").symlink_to(target)
    with pytest.raises(GuaranteeUnavailableError, match="symlink"):
        make_deployment(deployment, owner_mod, root_b).owned_environment_factory(
            core_path(root_b), lambda: True)

    # case C: the journal's parent directory is a symlink
    root_c = tmp_path / "s3"
    (root_c / "plugins").mkdir(parents=True)
    (root_c / "plugins" / "profile").symlink_to(outside)
    with pytest.raises(GuaranteeUnavailableError, match="symlink"):
        make_deployment(deployment, owner_mod, root_c).owned_environment_factory(
            core_path(root_c), lambda: True)


# -- mixing refusals ---------------------------------------------------------

def test_second_store_on_same_core_file_is_refused(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    wired = make_deployment(deployment, owner_mod, tmp_path)
    env = wired.owned_environment_factory(core_path(tmp_path), lambda: True)
    try:
        from ordessa_persistence_sqlite.store import WriterLockHeldError
        with pytest.raises(WriterLockHeldError):
            SqliteStorePort(core_path(tmp_path))
    finally:
        env.close()


def test_second_scope_authority_on_same_journal_is_refused(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    wired = make_deployment(deployment, owner_mod, tmp_path)
    env = wired.owned_environment_factory(core_path(tmp_path), lambda: True)
    try:
        from ordessa_harness_records import UnitRecordsRefused
        # A different scope authority on the same journal object is refused by
        # the original single-owner pin; a second full assembly is refused by
        # the deployment itself.
        with pytest.raises(UnitRecordsRefused):
            owner_mod.assemble_owner(
                env, owner_ports(owner_mod, scope_authority=ScopeAuthority()),
                env.owner_ports.journal)
        with pytest.raises(GuaranteeUnavailableError, match="already assembled"):
            wired._wire_owner(env, env.store_port, env.environment_id, core_path(tmp_path))
    finally:
        env.close()


# -- owner close chain semantics ---------------------------------------------

def _wired_env(tmp_path, owner_mod, deployment, **port_overrides):
    wired = make_deployment(deployment, owner_mod, tmp_path, **port_overrides)
    return wired.owned_environment_factory(core_path(tmp_path), lambda: True)


def test_owner_callback_reentering_close_is_contained_and_error_preserved(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    holder = {}

    def owner_factory(environment):
        holder["env"] = environment
        return owner_ports(owner_mod, close=lambda: holder["env"].close())

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy(env_id.value),
        owner_ports_factory=owner_factory)
    env = wired.owned_environment_factory(core_path(tmp_path), lambda: True)
    with pytest.raises(GuaranteeUnavailableError, match="already in progress"):
        env.close()
    assert env._closed is True
    assert env.owner_ports.issuer._closed is True  # permission still revoked
    # the store was released by the outer chain despite the callback error
    reopened = SqliteStorePort(core_path(tmp_path))
    reopened.close()


def test_two_threads_closing_release_the_store_exactly_once(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    env = _wired_env(tmp_path, owner_mod, deployment)
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


def test_cleanup_failure_still_revokes_permission_and_preserves_error(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)

    def owner_factory(environment):
        def failing_close():
            raise RuntimeError("fence-failed-do-not-leak")
        return owner_ports(owner_mod, close=failing_close)

    wired = deployment.AgentToolsDeployment(
        fingerprint_port=fingerprint(), agent_contract_version="agent-assembly/3",
        policy_factory=lambda env_id: Policy(env_id.value),
        owner_ports_factory=owner_factory)
    env = wired.owned_environment_factory(core_path(tmp_path), lambda: True)
    with pytest.raises(RuntimeError, match="fence-failed-do-not-leak"):
        env.close()
    assert env.owner_ports.issuer._closed is True  # revocation happened anyway
    assert env._closed is True
    reopened = SqliteStorePort(core_path(tmp_path))  # necessary cleanup ran
    reopened.close()


class _FailingOnceSource:
    def __init__(self):
        self.detaches = 0
        self.sink = None

    def attach(self, sink, *, cursor=None):
        self.sink = sink
        sink.snapshot("r1", {"name": "one"})

        def detach():
            self.detaches += 1
            if self.detaches == 1:
                raise RuntimeError("external-detach-pending")

        return detach


def test_pending_observation_detach_keeps_writer_lock_and_is_retried(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    env = _wired_env(tmp_path, owner_mod, deployment)
    # Build a live observation with a detach that fails once, then recovers.
    from pacthold.environment import Environment
    from ordessa_environment_api import AuthorityKey, AuthorityRegistration, CanonicalFactTarget
    from dataclasses import dataclass as _dataclass

    @_dataclass(frozen=True)
    class _Contract:
        contract_id = "owner.wiring@1"

    env.install(InstallationRecord("owner.wiring.plugin", "b" * 64))
    env.enable("owner.wiring.plugin")
    activation = env.activate("owner.wiring.plugin",
                              CoreContributionSet(contracts=(_Contract,))).activation
    target = CanonicalFactTarget("workspace", "ordessa.workspace", "workspace:one")
    env.register_authority(AuthorityRegistration(
        key=AuthorityKey("configuration", target),
        declaring_owner_domain="owner.wiring.plugin",
        target_schema_id="ordessa.workspace.configuration@1",
        schema_major=1), activation)
    binding = env.bind("owner.wiring")
    source = _FailingOnceSource()
    env.read_and_subscribe(binding, target, None, 1, source=source)

    from ordessa_persistence_sqlite.store import WriterLockHeldError
    with pytest.raises(ObservationReleasePendingError):
        env.close()
    assert source.detaches == 1
    assert env._closed is True  # closed flag is set, yet cleanup did not swallow
    with pytest.raises(WriterLockHeldError):
        SqliteStorePort(core_path(tmp_path))  # writer lock kept while pending
    # Re-entry retries the pending detach instead of skipping it silently.
    env.close()
    assert source.detaches == 2
    reopened = SqliteStorePort(core_path(tmp_path))
    reopened.close()


def test_provider_view_and_owner_reads_never_issue_invocations(tmp_path):
    deployment = deployment_module()
    owner_mod = owner_ports_module(deployment)
    env = _wired_env(tmp_path, owner_mod, deployment)
    try:
        owner = env.owner_ports
        view = owner.provider_view
        assert view.records is owner.records
        assert view.verifier is owner.verifier
        # The provider view never carries issuance capability.
        assert not hasattr(view, "issuer")
        assert getattr(view, "issuer", None) is None
        # Owner projection reads require no invocation context at all.
        from ordessa_harness_records import UnitRecordsRefused
        with pytest.raises(UnitRecordsRefused):
            owner.records.owner_read_unit("unit-that-does-not-exist")
        with pytest.raises(UnitRecordsRefused):
            owner.records.owner_read_session("unit-that-does-not-exist")
        # The authorized read surface still demands its invocation context.
        with pytest.raises(TypeError):
            owner.records.read_unit("unit-that-does-not-exist")
    finally:
        env.close()
