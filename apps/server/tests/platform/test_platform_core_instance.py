"""Host topology and Agent Unit contracts on one Product Environment.

Controlled public providers exercise the real Agent Tools deployment, Server
Host and SQLite authority. The retained shared-file CoreStore witness records
why two connections to one legacy database were rejected; it is not a runtime
registration path. No model or native process is invoked.
"""
from __future__ import annotations
from ordessa_units.errors import UnitAdmissionRefused
from ordessa_server.composition.runtime import RuntimeCompositionUnavailable
from ordessa_agents.harness.providers.registry.errors import CatalogIdentityConflict
from pacthold.core.registration import RegistrationConflictError

import json
import sqlite3
import threading
from pathlib import Path

import pytest
from pacthold.public import CoreStore, Environment
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.definitions.operations import UsageMutation, node_holder, operation_holder
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.public import (
    AgentContributionSet, DirectoryBindingRef, InvocationCurrentState,
    InvocationGrant, unit_services,
)
from ordessa_agents.harness.providers.registry.contributions import (
    RUNTIME_METHODS, RUNTIME_PROVIDER_VERSION, RuntimeProviderDescriptor,
)
from ordessa_units.bindings.assembly import PreparationContext, PreparationObservation
from ordessa_units.bindings.publication import NodePublicationEvidence, decode_node_ref
from ordessa_units.lifecycle.service import LifecycleObservation
from ordessa_server_plugin_api import (
    Contribution, ContributionBatch, PACTHOLD_CONTRIBUTIONS_API_VERSION,
    PACTHOLD_CONTRIBUTIONS_POINT_ID, ServerPluginDescriptor, ServerPluginRegistration,
)
from ordessa_server.composition.agent_tools import AgentServiceConfiguration, AgentToolsDeployment
from ordessa_server.composition.agent_tools.owner_ports import OwnerPorts
from ordessa_server.composition.plugin_host.host import OwnerLifecycleError
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac

def test_the_seam_names_no_core_internals_import():
    """Binding rule (1), checkable form: core_binding.py imports from
    pacthold.public and nowhere else inside the kernel."""
    from ordessa_server.composition import core_binding as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("from pacthold.") or stripped.startswith("import pacthold."):
            assert ".public" in stripped, line


def test_core_binding_is_per_composition_and_crosses_the_host_wall(tmp_path):
    """Two Agent Tools products expose their own Environment at the Host wall."""
    a, _ = _runtime(tmp_path / "wall-a", plugin=_Plugin("wall.a"))
    b, _ = _runtime(tmp_path / "wall-b", plugin=_Plugin("wall.b"))
    try:
        assert a.core_binding is not b.core_binding
        assert a.core_binding.environment is not b.core_binding.environment
        assert a.plugin_host.host_ports["core.binding"] is a.core_binding
        assert b.plugin_host.host_ports["core.binding"] is b.core_binding
        point = a.plugin_host.contribution_points.point(PACTHOLD_CONTRIBUTIONS_POINT_ID)
        assert point is not None and point.handler is a.core_binding
        assert point.api_version == PACTHOLD_CONTRIBUTIONS_API_VERSION
    finally:
        a.stop()
        b.stop()


def test_a_refused_contribution_round_leaves_the_composition_rebindable(tmp_path):
    """A rejected Agent contribution releases the root; valid retry binds there."""
    root = tmp_path / "joint-abort"
    with pytest.raises(TypeError):
        _deployment(root, plugin=_Plugin("joint.bad", bad_payload=True))
    good = _Plugin("joint.good")
    retry, _ = _runtime(root, plugin=good)
    try:
        env = retry.core_binding.environment
        admitted = env.agent_runtime_contribution(_Provider.definition_ref(env.environment_id))
        assert admitted.provider is good.provider
        assert retry.plugin_host.is_active(good.owner)
        run = _prepare(retry, _profile(retry), "joint-retry")
        assert run.status == "published"
        _release(retry, run, "joint-retry-release")
    finally:
        retry.stop()


def test_shared_file_topology_counterexample_double_applies_a_write(tmp_path):
    """The rejected S1c option, demonstrated rather than asserted away.

    If Core shared the legacy database file, the host's in-process
    ``db.write_lock`` would no longer serialise Core's second OS-level
    connection (``CoreStore``: ``sqlite3.connect(path, timeout=10.0)``,
    default journal, no injection seam). This witness scripts the
    multi-statement read-check-write the legacy chain runs under that lock,
    against a second connection on the SAME file, with a forced interleave:
    both sides count zero, both apply — a DOUBLE-APPLIED WRITE. Under the
    chosen topology (Core at its own ``state/core.sqlite``) the same script
    cannot land two writes on one logical target, because there is no second
    connection to the legacy tables at all.

    If a future edit re-points the composition's CoreBinding at
    ``runtime.database.path``, this witness plus
    ``test_stage_a_server.py::test_core_uses_the_server_owned_database_file``
    is what goes red.
    """
    from pacthold.work_core import db as legacy_db_module

    shared_file = tmp_path / "shared.sqlite"

    def shared_script() -> int:
        """Both writers guard 'apply once' under the host's process lock.
        Forced interleave: legacy counts, core counts, core commits, legacy
        re-applies from its stale zero — one logical application, two rows."""
        legacy = sqlite3.connect(str(shared_file), timeout=10.0,
                                 check_same_thread=False)
        legacy.execute("CREATE TABLE IF NOT EXISTS applied_once (who TEXT PRIMARY KEY, "
                       "n INTEGER NOT NULL CHECK (n = 1))")
        legacy.commit()
        store = CoreStore(shared_file)  # THE REJECTED CHOICE: same file, second connection
        legacy_counted = threading.Event()
        core_counted = threading.Event()
        outcome = {"rows": None}

        def legacy_side():
            with legacy_db_module.write_lock:
                n = legacy.execute("SELECT COUNT(*) FROM applied_once").fetchone()[0]
                legacy_counted.set()
                core_counted.wait(10)
                if n == 0:
                    legacy.execute("INSERT INTO applied_once VALUES ('legacy', 1)")
                    legacy.commit()

        def core_side():
            legacy_counted.wait(10)
            with store.transaction() as conn:
                n = conn.execute("SELECT COUNT(*) FROM applied_once").fetchone()[0]
                if n == 0:
                    conn.execute("INSERT INTO applied_once VALUES ('core', 1)")
            core_counted.set()

        threads = [threading.Thread(target=legacy_side),
                   threading.Thread(target=core_side)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        outcome["rows"] = legacy.execute(
            "SELECT COUNT(*) FROM applied_once").fetchone()[0]
        store.close()
        legacy.close()
        return outcome["rows"]

    # The counterexample: one logical application double-applied across the
    # two OS-level connections — exactly the hazard the write_lock was
    # supposed to prevent and cannot, once the second connection exists.
    assert shared_script() == 2, (
        "the shared-file counterexample did NOT double-apply: either the "
        "interleave was lost (fix the witness; do NOT approve option (b) on "
        "this run) or sqlite serialised the guarded window on this machine")

    # Chosen topology: the same guarded script, but Core's file is NOT the
    # legacy file — a core write can never interleave a legacy read-check-
    # write because they touch different databases.
    legacy_file = tmp_path / "chosen" / "state" / "agentbox.sqlite"
    core_file = tmp_path / "chosen" / "state" / "core.sqlite"
    legacy_file.parent.mkdir(parents=True)
    assert core_file != legacy_file
    legacy = sqlite3.connect(str(legacy_file), timeout=10.0, check_same_thread=False)
    legacy.execute("CREATE TABLE IF NOT EXISTS applied_once (who TEXT PRIMARY KEY, n INTEGER)")
    legacy.commit()
    store = CoreStore(core_file)
    with store.transaction() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS core_marker (t TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO core_marker VALUES ('applied')")
    with legacy_db_module.write_lock:
        n = legacy.execute("SELECT COUNT(*) FROM applied_once").fetchone()[0]
        if n == 0:
            legacy.execute("INSERT INTO applied_once VALUES ('legacy', 1)")
            legacy.commit()
    assert legacy.execute("SELECT COUNT(*) FROM applied_once").fetchone()[0] == 1
    core_tables = [r[0] for r in store.query_all(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    assert "applied_once" not in core_tables  # the legacy table is not even there
    store.close()
    legacy.close()


def _source(provider, identity):
    return {"environmentNamespace": provider["environmentNamespace"],
            "ownerProviderRef": json.loads(safe_json(provider)),
            "sourceRevision": "native-1", "ref": identity}


class _Authority:
    revision = "rev-1"
    expiry = 4102444800

    def __init__(self, environment_id):
        self.issuer_ref = {"environmentNamespace": environment_id,
                           "issuerId": "controlled-host-authority"}

    def authorize(self, request, actions, target_ref, delegation_ref):
        return InvocationGrant(principal_scope=request.principal_scope, actions=actions,
                               target_ref=target_ref, delegation_ref=delegation_ref,
                               authority_revision=self.revision, expires_at=self.expiry,
                               issuer_ref=self.issuer_ref)

    def revalidate(self, grant, request, actions, target_ref):
        return self.authorize(request, actions, target_ref, grant.delegation_ref)


class _State:
    def __init__(self, environment_id):
        self.environment_id = environment_id
        self.directory = DirectoryBindingRef(environment_id, "directory", 1,
                                             "sha256:" + "d" * 64)
        self.provider_ref = None

    def inspect(self, request, pinned_provider_ref, context_ref, target_ref, action):
        acquired = None
        acquisition_evidence = None
        if action in {"stop", "release", "query"} and "instanceId" in target_ref:
            node = decode_node_ref(target_ref)
            # The controlled current-state port reads the same published Node
            # and its original durable holds; it never echoes an unacquired target.
            published = unit_services(self.environment).nodes.read(node)
            usages = self.environment.store_port.read_usages(
                self.environment_id,
                node_holder(node.environment, node.instance_id, node.generation))
            retained = {row["usageId"] for row in usages
                        if row["state"] in {"active", "unknown"}}
            original_refs = [] if published is None else [
                ref for ref in published["resourceUsageRefs"]
                if ref["environmentNamespace"] == self.environment_id
                and ref["usageId"] in retained]
            if original_refs:
                acquired = target_ref
                acquisition_evidence = original_refs[0]
        return InvocationCurrentState(self.provider_ref, True, 0, self.directory,
                                      True, acquired, acquisition_evidence)

    def resolve(self, request, manifest, admitted, node, context, options):
        return PreparationContext(self.directory,
            {"installationRef": {"environmentNamespace": self.environment_id,
                                  "installationId": "controlled", "sourceRevision": "rev-1"}},
            {"nodeRef": node, "privateRootFacts": {"cwd": "/controlled/fixture"}})

    def observe(self, operation, step, reply):
        provider = step.pinned_provider_ref
        if operation.intent.kind == "agent-preparation":
            unit = _source(provider, "actual-unit")
            holds = () if step.step_id == "start" else (
                UsageMutation(operation.intent.operation_ref + ".unit", 0, None,
                              operation_holder(operation.request, operation.intent.operation_ref),
                              unit, ("use",), "active"),)
            return PreparationObservation(
                step.step_id, provider, step.input_digest, step.recovery_correlation,
                _source(provider, step.step_id + "-receipt"), {"unitRef": unit}, holds)
        action = operation.intent.context_ref["lifecycleRequest"]["action"]
        if action in {"stop", "release"}:
            termination = {"version": "harness-unit-termination/1", "action": action,
                           "state": "confirmed",
                           "identity": {"unitRef": reply["argument"],
                                        "inputDigest": step.input_digest},
                           "outcome": {"controlled": "confirmed"}}
            return LifecycleObservation(step.step_id, provider, step.input_digest,
                                        step.recovery_correlation,
                                        _source(provider, action + "-receipt"),
                                        termination=termination)
        return LifecycleObservation(step.step_id, provider, step.input_digest,
                                    step.recovery_correlation,
                                    _source(provider, "recover-receipt"),
                                    recovered_binding=reply["argument"])

    def node_evidence(self, operation, steps):
        provider = operation.intent.steps[0].pinned_provider_ref
        unit = steps[0].evidence["preparedUnit"]["unitRef"]
        return NodePublicationEvidence(
            provider,
            {"nodeRef": operation.intent.node_ref,
             "operationRef": operation.intent.operation_ref,
             "profileSnapshotRef": operation.intent.profile_snapshot_ref,
             "preparationContextRef": operation.intent.context_ref,
             "harnessProviderRef": provider,
             "harnessDefinitionRef": _Provider.definition_ref(self.environment_id),
             "harnessUnitRef": unit,
             "configurationTargetRef": _source(provider, "target"),
             "nativeSessionRefs": []},
            tuple({"stepId": row.intent.step_id,
                   "providerRef": row.intent.pinned_provider_ref,
                   "inputDigest": row.intent.input_digest,
                   "recoveryCorrelation": row.intent.recovery_correlation,
                   "evidenceRef": row.evidence["evidenceRef"]} for row in steps),
            (_source(provider, "access"),))

    def issue_scope(self, provider_ref, node_ref, private_root_facts):
        raise AssertionError("native scope is not used")

    def verify_scope(self, scope_ref, private_root_facts):
        return True

    def map_legacy_scope(self, legacy_target):
        return None

    def verify_binding(self, unit, creation_correlation, evidence):
        raise AssertionError("native binding is not used")

    def current_epoch(self, node_ref):
        return 0


class _NodeEvidence:
    def __init__(self, state): self.state = state
    def inspect(self, operation, steps): return self.state.node_evidence(operation, steps)


class _Policy:
    def __init__(self, environment_id): self.environment_id = environment_id
    def admit_invoke(self, principal, surface, guarantee):
        return principal == "local" and guarantee == "reliable"
    def admit_object_access(self, principal, object_ref, mode):
        return principal == "local" and object_ref.startswith(self.environment_id + ":")


class _Provider:
    provider_id = "controlled.unit"

    @staticmethod
    def definition_ref(environment_id):
        return {"environmentNamespace": environment_id, "definitionId": "controlled",
                "revision": "1"}

    def __init__(self, environment_id, owner_view, *, provider_id=None,
                 definition_environment=None):
        self.descriptor = RuntimeProviderDescriptor(
            provider_id or self.provider_id, RUNTIME_PROVIDER_VERSION,
            self.definition_ref(definition_environment or environment_id), "sha256:" + "a" * 64,
            ("plan_preparation", "prepare", "start", "query_step",
             "stop", "release", "recover"))
        self.verifier = owner_view.verifier
        self.records = owner_view.records
        self.calls = []
        self.fail = None

    def plan_preparation(self, snapshot, context, correlation):
        self.calls.append("plan")
        return {"snapshot": snapshot, "context": context, "correlation": correlation}

    def _invoke(self, action, argument, invocation):
        self.calls.append(action)
        facts = invocation.facts
        self.verifier.verify_and_consume(invocation, action, facts["providerRef"],
                                         facts["targetRef"], facts["inputDigest"])
        if self.fail == action:
            raise ConnectionError("controlled lost native reply")
        return {"argument": argument}

    def prepare(self, plan, invocation): return self._invoke("prepare", plan, invocation)
    def start(self, prepared, invocation): return self._invoke("start", prepared, invocation)
    def stop(self, unit, invocation): return self._invoke("stop", unit, invocation)
    def release(self, unit, invocation): return self._invoke("release", unit, invocation)
    def recover(self, binding, invocation): return self._invoke("recover", binding, invocation)
    def query_step(self, correlation, invocation):
        self.calls.append("query")
        raise LookupError("original evidence intentionally absent")


for _name in RUNTIME_METHODS:
    if not hasattr(_Provider, _name):
        setattr(_Provider, _name, lambda *args: None)


class _Plugin:
    def __init__(self, owner="controlled.owner", *, bad_payload=False,
                 provider_id=None, definition_environment=None):
        self.owner = owner
        self.bad_payload = bad_payload
        self.provider_id = provider_id
        self.definition_environment = definition_environment
        self.provider = None

    def descriptor(self):
        return ServerPluginDescriptor(self.owner, self.owner, "1")

    def build(self, context):
        environment = context.ports["core.binding"].environment
        owner = environment.owner_ports
        self.provider = _Provider(
            environment.environment_id, owner.provider_view,
            provider_id=self.provider_id,
            definition_environment=self.definition_environment)
        payload = ({"not": "a contribution"} if self.bad_payload else
                   AgentContributionSet(agent_runtime_providers=(self.provider,)))
        return ServerPluginRegistration(contributions=ContributionBatch((Contribution(
            PACTHOLD_CONTRIBUTIONS_POINT_ID, PACTHOLD_CONTRIBUTIONS_API_VERSION,
            payload, required=True),)))


def _deployment(root, *, plugin=None):
    states = {}

    def state(environment):
        return states.setdefault(environment.environment_id, _State(environment.environment_id))

    def owner_ports(environment):
        owned = state(environment)
        owned.environment = environment
        return OwnerPorts(authority=_Authority(environment.environment_id),
                          current_state=owned, scope_authority=owned,
                          native_session_evidence=owned, management_epoch=owned,
                          node_evidence_port=_NodeEvidence(owned),
                          preparation_context_port=owned,
                          preparation_observation_port=owned,
                          lifecycle_observation_port=owned)

    selected = AgentToolsDeployment(
        fingerprint_port=ProtectedFingerprintHmac({"fixture": b"host-agent-unit"},
                                                  active_key_id="fixture"),
        agent_contract_version="agent-assembly/3",
        provider_plugins=() if plugin is None else (plugin,),
        policy_factory=lambda identity: _Policy(identity.value),
        owner_ports_factory=owner_ports)
    runtime = selected.build_runtime(AgentServiceConfiguration(root, agent_contract_version="agent-assembly/3"))
    return runtime, states


def _runtime(root, *, plugin=None):
    runtime, states = _deployment(root, plugin=plugin)
    runtime.start()
    env = runtime.core_binding.environment
    if plugin is not None:
        states[env.environment_id].provider_ref = env.agent_runtime_contribution(
            _Provider.definition_ref(env.environment_id)).provider_ref
    return runtime, states[env.environment_id]


def _profile(runtime):
    env = runtime.core_binding.environment
    return unit_services(env).profiles.create(
        profile_id="controlled-profile", name="Controlled Profile",
        content={"harnessDefinitionRef": _Provider.definition_ref(env.environment_id),
                 "schemaVersion": "1", "declarations": []},
        request=RequestKey(env.environment_id, "local", "create-profile"))


def _prepare(runtime, profile, request_id):
    env = runtime.core_binding.environment
    return unit_services(env).assembly.prepare(
        RequestKey(env.environment_id, "local", request_id),
        profile.current_revision, {}, {})


def _release(runtime, operation, request_id):
    env = runtime.core_binding.environment
    return unit_services(env).lifecycle.release(
        RequestKey(env.environment_id, "local", request_id),
        decode_node_ref(operation.result["nodeRef"]), {})


def test_unselected_owner_refuses_before_provider_dispatch_then_selected_owner_runs(tmp_path):
    runtime, state = _runtime(tmp_path / "one")
    plugin = _Plugin()
    try:
        profile = _profile(runtime)
        env = runtime.core_binding.environment
        before = env.registry_snapshot
        with pytest.raises(UnitAdmissionRefused, match="RuntimeProvider unavailable"):
            _prepare(runtime, profile, "unselected")
        assert env.registry_snapshot == before
        assert plugin.provider is None
        runtime.plugin_host.activate(plugin)
        state.provider_ref = env.agent_runtime_contribution(_Provider.definition_ref(env.environment_id)).provider_ref
        run = _prepare(runtime, profile, "selected")
        assert run.status == "published"
        assert plugin.provider.calls.count("prepare") == 1
        assert plugin.provider.calls.count("start") == 1
        replay = _prepare(runtime, profile, "selected")
        assert replay == run and plugin.provider.calls.count("start") == 1
        _release(runtime, run, "release-selected")
    finally:
        runtime.stop()


def test_selected_provider_identity_and_busy_retirement_are_exact(tmp_path):
    plugin = _Plugin()
    runtime, _ = _runtime(tmp_path / "identity", plugin=plugin)
    try:
        env = runtime.core_binding.environment
        admitted = env.agent_runtime_contribution(_Provider.definition_ref(env.environment_id))
        assert admitted.provider is plugin.provider
        run = _prepare(runtime, _profile(runtime), "identity-run")
        with pytest.raises(OwnerLifecycleError):
            runtime.plugin_host.deactivate(plugin.owner)
        assert runtime.plugin_host.is_active(plugin.owner)
        _release(runtime, run, "identity-release")
        runtime.plugin_host.deactivate(plugin.owner)
        assert not runtime.plugin_host.is_active(plugin.owner)
    finally:
        runtime.stop()


def test_raising_host_stage_has_zero_leak_and_same_root_retries(tmp_path):
    root = tmp_path / "stage"
    runtime, _ = _runtime(root)
    try:
        before = runtime.core_binding.environment.registry_snapshot
        with pytest.raises(TypeError):
            runtime.plugin_host.activate(_Plugin("bad.owner", bad_payload=True))
        assert runtime.core_binding.environment.registry_snapshot == before
        assert not runtime.plugin_host.is_active("bad.owner")
        assert "bad.owner" not in runtime.core_binding.environment.enabled
        good = _Plugin("good.owner")
        runtime.plugin_host.activate(good)
        assert good.provider is runtime.core_binding.environment.agent_runtime_contribution(
            _Provider.definition_ref(runtime.core_binding.environment.environment_id)).provider
        runtime.plugin_host.deactivate("good.owner")
    finally:
        runtime.stop()


def test_joint_registration_conflict_preserves_registry_host_and_retry(tmp_path):
    runtime, _ = _runtime(tmp_path / "joint-conflict")
    winner = _Plugin("owner.winner")
    loser = _Plugin("owner.loser")
    try:
        env = runtime.core_binding.environment
        runtime.plugin_host.activate(winner)
        before = env.registry_snapshot
        assert runtime.plugin_host.is_active(winner.owner)
        with pytest.raises(RegistrationConflictError):
            runtime.plugin_host.activate(loser)
        assert env.registry_snapshot == before
        assert runtime.plugin_host.is_active(winner.owner)
        assert not runtime.plugin_host.is_active(loser.owner)
        assert loser.owner not in env.enabled
        # Retire the actual owner of the collision, then retry the same plugin
        # and root. A rejected C2/Environment registration must leave no stale
        # reservation or host lifecycle token behind.
        runtime.plugin_host.deactivate(winner.owner)
        runtime.plugin_host.activate(loser)
        admitted = env.agent_runtime_contribution(_Provider.definition_ref(env.environment_id))
        assert admitted.provider is loser.provider
        assert runtime.plugin_host.is_active(loser.owner)
        runtime.plugin_host.deactivate(loser.owner)
    finally:
        runtime.stop()


def test_joint_registration_bad_environment_reference_rolls_back_and_retries(tmp_path):
    runtime, _ = _runtime(tmp_path / "joint-bad-reference")
    plugin = _Plugin("owner.bad-reference", definition_environment="foreign-environment")
    try:
        env = runtime.core_binding.environment
        before = env.registry_snapshot
        with pytest.raises(CatalogIdentityConflict):
            runtime.plugin_host.activate(plugin)
        assert env.registry_snapshot == before
        assert not runtime.plugin_host.is_active(plugin.owner)
        assert plugin.owner not in env.enabled
        # Correct only the malformed public provider definition and retry on
        # the same host and Environment; no old C1 bind_owner route is used.
        plugin.definition_environment = None
        runtime.plugin_host.activate(plugin)
        admitted = env.agent_runtime_contribution(_Provider.definition_ref(env.environment_id))
        assert admitted.provider is plugin.provider
        assert runtime.plugin_host.is_active(plugin.owner)
        runtime.plugin_host.deactivate(plugin.owner)
    finally:
        runtime.stop()


def test_two_live_compositions_a_close_does_not_steal_b_unit_requests(tmp_path):
    a, _ = _runtime(tmp_path / "a", plugin=_Plugin("owner.a"))
    b, _ = _runtime(tmp_path / "b", plugin=_Plugin("owner.b"))
    try:
        assert a.core_binding.environment is not b.core_binding.environment
        a_path = Path(a.core_binding.store_path).resolve()
        b_path = Path(b.core_binding.store_path).resolve()
        assert a_path != b_path
        assert a_path == (a.data_root / "state" / "core.sqlite").resolve()
        assert b_path == (b.data_root / "state" / "core.sqlite").resolve()
        profile = _profile(b)
        first = _prepare(b, profile, "b-first")
        _release(b, first, "b-release-first")
        a.stop()
        second = _prepare(b, profile, "b-second")
        assert second.status == "published"
        original = unit_services(b.core_binding.environment).assembly.query(
            RequestKey(b.core_binding.environment.environment_id, "local", "b-first"))
        assert original is not None and original.intent.operation_ref == first.intent.operation_ref
        _release(b, second, "b-release-second")
    finally:
        b.stop()


def test_stop_and_recover_use_original_unit_and_evidence(tmp_path):
    plugin = _Plugin()
    runtime, _ = _runtime(tmp_path / "lifecycle", plugin=plugin)
    try:
        run = _prepare(runtime, _profile(runtime), "life-run")
        env = runtime.core_binding.environment
        node = decode_node_ref(run.result["nodeRef"])
        services = unit_services(env)
        stop = services.lifecycle.stop(RequestKey(env.environment_id, "local", "life-stop"), node, {})
        assert stop["operationRef"] and plugin.provider.calls.count("stop") == 1
        assert services.lifecycle.stop(RequestKey(env.environment_id, "local", "life-stop"), node, {}) == stop
        assert plugin.provider.calls.count("stop") == 1
        recover = services.lifecycle.recover(RequestKey(env.environment_id, "local", "life-recover"), node, {})
        assert recover["operationRef"] and plugin.provider.calls.count("recover") == 1
        # A lost native reply has no invented reconciliation proof. Its exact
        # request is durably unknown and replay cannot call the provider twice.
        plugin.provider.fail = "recover"
        unknown_key = RequestKey(env.environment_id, "local", "life-recover-unknown")
        unknown = services.lifecycle.recover(unknown_key, node, {})
        assert unknown["status"] == "unknown"
        assert services.lifecycle.recover(unknown_key, node, {}) == unknown
        assert plugin.provider.calls.count("recover") == 2
        plugin.provider.fail = None
        _release(runtime, run, "life-release")
    finally:
        runtime.stop()


def test_product_core_file_contains_unit_facts_and_no_legacy_c1_tables(tmp_path):
    plugin = _Plugin()
    runtime, _ = _runtime(tmp_path / "topology", plugin=plugin)
    try:
        run = _prepare(runtime, _profile(runtime), "topology-run")
        core = Path(runtime.core_binding.store_path)
        assert core == runtime.data_root / "state" / "core.sqlite"
        assert core != runtime.database.path
        with sqlite3.connect(core) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert {"env_requests", "env_request_steps", "env_domain_records"} <= tables
            assert {"core_execution", "core_operation"}.isdisjoint(tables)
        with sqlite3.connect(runtime.database.path) as connection:
            legacy_tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert "env_requests" not in legacy_tables
        assert run.status == "published"
        _release(runtime, run, "topology-release")
    finally:
        runtime.stop()


def test_joint_host_round_reaches_original_unit_dispatch_and_query(tmp_path):
    plugin = _Plugin()
    runtime, _ = _runtime(tmp_path / "joint", plugin=plugin)
    try:
        env = runtime.core_binding.environment
        assert runtime.plugin_host.is_active(plugin.owner)
        assert env.agent_runtime_contribution(_Provider.definition_ref(env.environment_id)).provider is plugin.provider
        request = RequestKey(env.environment_id, "local", "joint-run")
        run = _prepare(runtime, _profile(runtime), request.request_id)
        assert run.status == "published" and run.intent.operation_ref
        assert plugin.provider.calls.count("prepare") == 1
        assert plugin.provider.calls.count("start") == 1
        observed = unit_services(env).assembly.query(request)
        assert observed == run and plugin.provider.calls.count("start") == 1
        _release(runtime, run, "joint-release")
    finally:
        runtime.stop()


def test_successful_close_reports_same_ledger_and_reopen_reads_original_fact(tmp_path):
    plugin = _Plugin()
    runtime, _ = _runtime(tmp_path / "restart", plugin=plugin)
    try:
        env = runtime.core_binding.environment
        original_id = env.environment_id
        request = RequestKey(original_id, "local", "close-run")
        run = _prepare(runtime, _profile(runtime), request.request_id)
        before = unit_services(env).operations.unresolved_snapshot()
        assert before.active_usage_ids  # the published Unit still holds exact Usages
        with pytest.raises(RuntimeCompositionUnavailable, match="owner lifecycle retirement"):
            runtime.stop()
        assert runtime.owner.acquired and runtime.plugin_host.is_active(plugin.owner)
        assert not env._closed
        assert unit_services(env).operations.unresolved_snapshot() == before
        _release(runtime, run, "close-release")
        runtime.stop()
        report = runtime.core_shutdown_report
        assert report is runtime.core_binding.shutdown_report
        assert runtime.core_binding.close() is report
        assert runtime.core_binding.close() is report
        assert report.unresolved_operation_refs == ()
        assert report.active_usage_ids == ()
        assert env._closed
        with pytest.raises(RuntimeCompositionUnavailable):
            runtime.core_binding.snapshot()  # read cannot silently reopen
        runtime.start()
        reopened = runtime.core_binding.environment
        assert reopened is not env and reopened.environment_id == original_id
        assert unit_services(reopened).assembly.query(request).intent.operation_ref == run.intent.operation_ref
    finally:
        runtime.stop()
