"""Controlled process-crash and exact original-root writer recovery controls."""
from multiprocessing import get_context
from pathlib import Path
import json
import os
import sqlite3

import pytest

from ordessa_server.composition.runtime import DataRootOwner
from pacthold.adapters.sqlite.environment.store import SqliteStorePort


def _crashed_writer(root_text):
    root = Path(root_text)
    owner = DataRootOwner(root)
    owner.acquire()
    store = SqliteStorePort(root / "state" / "core.sqlite")
    with store.transaction() as connection:
        connection.execute("INSERT INTO env_meta(key,value) VALUES('environment_id','crash-env')")
    # No Store.close or owner.release: the OS releases only this dead process's
    # lock, while the original SQL token and durable identity remain.
    os._exit(0)


def test_crashed_process_root_proof_permits_exact_sql_marker_takeover(tmp_path):
    root = tmp_path / "data"
    child = get_context("spawn").Process(target=_crashed_writer, args=(str(root),))
    try:
        child.start()
        child.join(timeout=10)
        assert child.exitcode == 0
    finally:
        if child.pid is not None and child.is_alive():
            child.terminate()
            child.join(timeout=5)
            if child.is_alive():
                child.kill()
                child.join(timeout=5)
    owner = DataRootOwner(root)
    owner.acquire()
    try:
        store = SqliteStorePort(root / "state" / "core.sqlite", allow_takeover=True)
        try:
            with store.transaction() as connection:
                assert connection.execute("SELECT value FROM env_meta WHERE key='environment_id'").fetchone()[0] == "crash-env"
                assert connection.execute("SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone()[0] == store.writer_token
        finally:
            store.close()
    finally:
        owner.release()
    with sqlite3.connect(root / "state" / "core.sqlite") as connection:
        assert connection.execute("SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone() is None


def test_live_original_root_owner_still_refuses_second_writer(tmp_path):
    root = tmp_path / "data"
    original = DataRootOwner(root)
    original.acquire()
    try:
        store = SqliteStorePort(root / "state" / "core.sqlite")
        try:
            second = DataRootOwner(root)
            with pytest.raises(RuntimeError, match="DATA_ROOT_IN_USE"):
                second.acquire()
            with store.transaction() as connection:
                assert connection.execute("SELECT owner_token FROM env_writer_lock WHERE id=1").fetchone()[0] == store.writer_token
        finally:
            store.close()
    finally:
        original.release()


def _agent_tools_fingerprint():
    from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
    return ProtectedFingerprintHmac({"fixture": b"controlled-crash-key"}, active_key_id="fixture")


def _crashed_agent_tools(root_text, receipt_text):
    from ordessa_server.composition.agent_tools import AgentServiceConfiguration, build_agent_runtime
    from ordessa_infrastructure.identifiers import RequestKey
    from ordessa_infrastructure.database.records import DomainWrite
    from ordessa_units.definitions.operations import OperationIntent, StepIntent, UsageMutation, operation_holder
    runtime = build_agent_runtime(AgentServiceConfiguration(Path(root_text)),
                                  fingerprint_port=_agent_tools_fingerprint())
    env = runtime.core_binding.environment
    store = env.store_port
    request = RequestKey(env.environment_id, "local", "original-crash-request")
    step = StepIntent("effect", {"environmentNamespace": env.environment_id,
                                 "providerId": "controlled-crash", "version": 1,
                                 "generation": 1}, "original-input", "original-correlation")
    intent = OperationIntent("original-crash-operation", "controlled-crash", None,
                             {"environmentNamespace": env.environment_id}, (step,))
    holder = operation_holder(request, intent.operation_ref)
    usage = UsageMutation("original-crash-usage", 0, None, holder,
                          {"environmentNamespace": env.environment_id,
                           "resourceId": "controlled-crash-resource"}, ("use",), "active")
    store.reserve_operation(request, "original-crash-digest", intent,
                            writes=(DomainWrite("controlled.capability", "original", 0,
                                                {"enabled": True}),), usages=(usage,))
    assert store.claim_operation_step(request, "original-crash-digest", step).claimed
    store.record_operation_step(request, "original-crash-digest", "effect",
                                step.input_digest, 1, "unknown", {})
    receipt = {"environmentId": env.environment_id,
               "requestId": request.request_id,
               "operationDigest": store.read_operation(request).digest,
               "stepOutcome": store.read_operation_step(request, "effect").outcome,
               "usageState": store.read_usages(env.environment_id, holder)[0]["state"],
               "writerToken": store.writer_token}
    with open(receipt_text, "w", encoding="utf-8") as output:
        json.dump(receipt, output)
        output.flush()
        os.fsync(output.fileno())
    os._exit(0)


def test_product_root_proof_recovers_same_environment_after_crash(tmp_path):
    from ordessa_server.composition.agent_tools import AgentServiceConfiguration, build_agent_runtime
    root = tmp_path / "product"
    receipt_path = tmp_path / "crashed-product-receipt.json"
    child = get_context("spawn").Process(target=_crashed_agent_tools,
                                         args=(str(root), str(receipt_path)))
    try:
        child.start()
        child.join(timeout=15)
        assert child.exitcode == 0
    finally:
        if child.pid is not None and child.is_alive():
            child.terminate()
            child.join(timeout=5)
            if child.is_alive():
                child.kill()
                child.join(timeout=5)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["stepOutcome"] == "unknown" and receipt["usageState"] == "active"
    # The product validates its exact Host-issued RootOwnershipPort before
    # permitting the Store's exact-token takeover. No claim is re-dispatched.
    recovered = build_agent_runtime(AgentServiceConfiguration(root),
                                    fingerprint_port=_agent_tools_fingerprint())
    try:
        from ordessa_infrastructure.identifiers import RequestKey
        from ordessa_units.definitions.operations import operation_holder
        env = recovered.core_binding.environment
        store = env.store_port
        assert env.environment_id == receipt["environmentId"]
        request = RequestKey(env.environment_id, "local", receipt["requestId"])
        operation = store.read_operation(request)
        assert operation is not None and operation.digest == receipt["operationDigest"]
        assert operation.status == "unknown"
        assert store.read_operation_step(request, "effect").outcome == "unknown"
        assert store.read_domain(env.environment_id, "controlled.capability", "original")["value"] == {"enabled": True}
        rows = store.read_usages(env.environment_id,
                                 operation_holder(request, operation.intent.operation_ref))
        assert len(rows) == 1 and rows[0]["usageId"] == "original-crash-usage"
        assert rows[0]["state"] == "active" and rows[0]["rights"] == ["use"]
        assert rows[0]["targetRef"] == {"environmentNamespace": env.environment_id,
                                        "resourceId": "controlled-crash-resource"}
        assert store.writer_token != receipt["writerToken"]
        assert store.reserve_operation(request, operation.digest, operation.intent) == operation
        assert not store.claim_operation_step(request, operation.digest, operation.intent.steps[0]).claimed
        assert store.read_operation_step(request, "effect").outcome == "unknown"
    finally:
        recovered.stop()
