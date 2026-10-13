"""Original Unit ledger inventory, without C1 execution IDs or a second store."""
import pytest
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import AdmissionRefusedError, GuaranteeUnavailableError
from ordessa_execution_api.environment.operations import OperationIntent, StepIntent, UsageMutation, operation_holder
from ordessa_units.public import unit_services
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.public import Environment




from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

class _LocalPolicy:
    node_allowed = True

    def admit_invoke(self, principal, surface, guarantee):
        return principal == "local"

    def admit_object_access(self, principal, object_ref, mode):
        return principal == "local" and (self.node_allowed or ":agents.node:" not in object_ref)


def test_shutdown_inventory_reads_original_unit_requests_and_hides_foreign_principal(tmp_path):
    store = SqliteStorePort(tmp_path / "core.sqlite")
    policy = _LocalPolicy()
    env = Environment("controlled-env", store=store, policy=policy, principal_scope="local", resource_extension_snapshot=_test_resource_snapshot)
    provider_ref = {"environmentNamespace": env.environment_id, "providerId": "controlled",
                    "generation": 1, "contractVersion": "1",
                    "implementationDigest": "sha256:" + "a" * 64}
    try:
        for principal, name in (("local", "original"), ("foreign", "hidden")):
            request = RequestKey(env.environment_id, principal, "prepare-" + name)
            step = StepIntent("prepare", provider_ref, "fixed-input", "original-correlation")
            intent = OperationIntent("preparation-" + name, "agent-preparation", None,
                                     {"environmentNamespace": env.environment_id}, (step,))
            usages = ()
            if name == "original":
                usages = (UsageMutation("held-original", 0, None,
                         operation_holder(request, intent.operation_ref),
                         {"environmentNamespace": env.environment_id, "resourceId": "held"},
                         ("use",), "active"),)
            store.reserve_operation(request, "fixed-digest-" + name, intent, usages=usages)
            if name == "original":
                claim = store.claim_operation_step(request, "fixed-digest-" + name, step)
                assert claim.claimed
                store.record_operation_step(request, "fixed-digest-" + name,
                    step.step_id, step.input_digest, claim.step.revision, "unknown", {})
        report = unit_services(env).operations.unresolved_snapshot()
        assert report.unresolved_operation_refs == ("preparation-original",)
        assert report.active_usage_ids == ("held-original",)
        assert store.read_operation(RequestKey(env.environment_id, "local", "prepare-original")).status == "unknown"
        # Inventory must never dispatch, release a hold, or settle the original request.
        assert unit_services(env).operations.unresolved_snapshot() == report
        policy.node_allowed = False
        with pytest.raises(AdmissionRefusedError):
            unit_services(env).operations.unresolved_snapshot()
        policy.node_allowed = True
        with store.transaction() as connection:
            connection.execute("UPDATE env_usages SET state='fabricated' WHERE usage_id='held-original'")
        with pytest.raises(GuaranteeUnavailableError, match="Usage inventory is inconsistent"):
            unit_services(env).operations.unresolved_snapshot()
        with store.transaction() as connection:
            connection.execute("UPDATE env_usages SET state='active' WHERE usage_id='held-original'")
            connection.execute("UPDATE env_domain_records SET payload='{}' "
                "WHERE environment=? AND namespace=? AND record_id=?",
                (env.environment_id, "core.operation-identities", "preparation-original"))
        with pytest.raises(GuaranteeUnavailableError, match="inventory is inconsistent"):
            unit_services(env).operations.unresolved_snapshot()
    finally:
        env.close()
        store.close()


def test_concluded_lifecycle_row_does_not_hide_residual_usage_or_unknown(tmp_path):
    store = SqliteStorePort(tmp_path / "core.sqlite")
    env = Environment("controlled-env", store=store, policy=_LocalPolicy(), principal_scope="local", resource_extension_snapshot=_test_resource_snapshot)
    provider_ref = {"environmentNamespace": env.environment_id, "providerId": "controlled",
                    "generation": 1, "contractVersion": "1",
                    "implementationDigest": "sha256:" + "a" * 64}
    try:
        for name, outcome, hold_state in (("settled", "concluded", None),
                                          ("held", "concluded", "active"),
                                          ("ambiguous", "unknown", "unknown")):
            request = RequestKey(env.environment_id, "local", "life-" + name)
            step = StepIntent("release", provider_ref, "fixed-input", "original-correlation")
            intent = OperationIntent("life-" + name, "agent-release", None,
                                     {"environmentNamespace": env.environment_id}, (step,))
            usages = () if hold_state is None else (UsageMutation(
                "usage-" + name, 0, None,
                operation_holder(request, intent.operation_ref),
                {"environmentNamespace": env.environment_id, "resourceId": name},
                ("use",), hold_state),)
            store.reserve_operation(request, "digest-" + name, intent, usages=usages)
            claim = store.claim_operation_step(request, "digest-" + name, step)
            assert claim.claimed
            store.record_operation_step(request, "digest-" + name, step.step_id,
                step.input_digest, claim.step.revision, outcome,
                {"evidenceRef": {"environmentNamespace": env.environment_id,
                                 "ownerProviderRef": provider_ref, "ref": "receipt-" + name}}
                if outcome == "concluded" else {})
            assert store.read_operation(request).status in {"running", "unknown"}
        report = unit_services(env).operations.unresolved_snapshot()
        assert report.unresolved_operation_refs == ("life-ambiguous", "life-held")
        assert report.active_usage_ids == ("usage-ambiguous", "usage-held")
        assert unit_services(env).operations.unresolved_snapshot() == report
        assert store.read_operation(RequestKey(env.environment_id, "local", "life-settled")).status == "running"
        # Invalid current Usage on a concluded row must refuse inventory,
        # even though its generic operation status alone looks settled.
        with store.transaction() as connection:
            connection.execute("UPDATE env_usages SET state='fabricated' WHERE usage_id='usage-held'")
        with pytest.raises(GuaranteeUnavailableError, match="Usage inventory is inconsistent"):
            unit_services(env).operations.unresolved_snapshot()
    finally:
        env.close()
        store.close()


def test_closed_cut_inventory_keeps_original_acl_and_cannot_run_early(tmp_path):
    store = SqliteStorePort(tmp_path / "core.sqlite")
    policy = _LocalPolicy()
    env = Environment("controlled-env", store=store, policy=policy, principal_scope="local", resource_extension_snapshot=_test_resource_snapshot)
    services = unit_services(env)
    provider_ref = {"environmentNamespace": env.environment_id, "providerId": "controlled",
                    "generation": 1, "contractVersion": "1",
                    "implementationDigest": "sha256:" + "a" * 64}
    request = RequestKey(env.environment_id, "local", "close-original")
    step = StepIntent("prepare", provider_ref, "fixed-input", "original-correlation")
    intent = OperationIntent("close-original", "agent-preparation", None,
                             {"environmentNamespace": env.environment_id}, (step,))
    usage = UsageMutation("close-usage", 0, None,
                          operation_holder(request, intent.operation_ref),
                          {"environmentNamespace": env.environment_id, "resourceId": "held"},
                          ("use",), "active")
    try:
        store.reserve_operation(request, "fixed-digest", intent, usages=(usage,))
        with pytest.raises(GuaranteeUnavailableError, match="admission cut"):
            services.operations.closed_unresolved_snapshot()
        env.close()
        report = services.operations.closed_unresolved_snapshot()
        assert report.unresolved_operation_refs == ("close-original",)
        assert report.active_usage_ids == ("close-usage",)
        # A node surface that never held a node must not invoke the node-access
        # enumeration: the close inventory still reports the unresolved
        # operation/usage, and a policy without node access does not fail close.
        policy.node_allowed = False
        report_no_nodes = services.operations.closed_unresolved_snapshot()
        assert report_no_nodes.unresolved_operation_refs == ("close-original",)
        assert report_no_nodes.active_usage_ids == ("close-usage",)
    finally:
        store.close()


def test_closed_inventory_still_enforces_node_acl_when_a_node_exists(tmp_path):
    """The node-access ACL is retained whenever a node record actually exists:
    only the never-enabled (empty) node surface skips the enumeration."""
    store = SqliteStorePort(tmp_path / "core.sqlite")
    policy = _LocalPolicy()
    env = Environment("controlled-env", store=store, policy=policy, principal_scope="local", resource_extension_snapshot=_test_resource_snapshot)
    services = unit_services(env)
    try:
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO env_domain_records(environment, namespace, record_id, revision, payload) "
                "VALUES (?, 'agents.nodes', 'node-1:1', 1, ?)",
                (env.environment_id, '{"record": {"nodeRef": {"environment": "controlled-env",'
                                     ' "instanceId": "node-1", "generation": 1}}}'))
        env.close()
        policy.node_allowed = False
        with pytest.raises(AdmissionRefusedError):
            services.operations.closed_unresolved_snapshot()
    finally:
        store.close()


def test_store_close_cut_serializes_lifecycle_record_outside_admission_lock(tmp_path):
    import sqlite3
    import threading

    path = tmp_path / "core.sqlite"
    store = SqliteStorePort(path)
    env = Environment("controlled-env", store=store, policy=_LocalPolicy(), principal_scope="local", resource_extension_snapshot=_test_resource_snapshot)
    services = unit_services(env)
    provider_ref = {"environmentNamespace": env.environment_id, "providerId": "controlled",
                    "generation": 1, "contractVersion": "1",
                    "implementationDigest": "sha256:" + "a" * 64}
    request = RequestKey(env.environment_id, "local", "lifecycle-racing")
    step = StepIntent("release", provider_ref, "fixed-input", "original-correlation")
    intent = OperationIntent("lifecycle-racing", "agent-release", None,
                             {"environmentNamespace": env.environment_id}, (step,))
    store.reserve_operation(request, "fixed-digest", intent)
    claim = store.claim_operation_step(request, "fixed-digest", step)
    assert claim.claimed
    env.close()
    inside_inspection, allow_close, attempting_record = (threading.Event() for _ in range(3))
    results, record_errors = [], []

    def inspect():
        report = services.operations.closed_unresolved_snapshot()
        inside_inspection.set()
        assert allow_close.wait(10)
        return report

    def closing():
        results.append(store.inspect_and_close(inspect))

    def recording():
        attempting_record.set()
        try:
            # AgentLifecycle._record calls this StorePort method without
            # Environment._admission_lock. Its SQLite RLock must still order
            # this result relative to inventory and writer closure.
            store.record_operation_step(request, "fixed-digest", step.step_id,
                step.input_digest, claim.step.revision, "concluded",
                {"evidenceRef": {"controlled": "late"}}, usages=(UsageMutation(
                    "late-usage", 0, None,
                    operation_holder(request, intent.operation_ref),
                    {"environmentNamespace": env.environment_id, "resourceId": "late"},
                    ("use",), "active"),))
        except BaseException as exc:  # noqa: BLE001
            record_errors.append(exc)

    close_thread = threading.Thread(target=closing)
    record_thread = threading.Thread(target=recording)
    close_thread.start()
    try:
        assert inside_inspection.wait(10)
        record_thread.start()
        assert attempting_record.wait(10)
        assert record_thread.is_alive()  # Store RLock held by inventory+close
    finally:
        allow_close.set()
    close_thread.join(10)
    record_thread.join(10)
    assert not close_thread.is_alive() and not record_thread.is_alive()
    assert len(results) == 1
    assert results[0].unresolved_operation_refs == ("lifecycle-racing",)
    assert results[0].active_usage_ids == ()
    assert len(record_errors) == 1 and isinstance(record_errors[0], sqlite3.ProgrammingError)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM env_usages WHERE usage_id='late-usage'").fetchone()[0] == 0
