"""Ordinary operation current-step integrity over the existing SQLite ledger.

These cases exercise the storage contract only; they do not run a provider or
Harness.  Staged operations have separate recipe-history checks.
"""
import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment.errors import GuaranteeUnavailableError, UnknownResultError
from ordessa_execution_api.environment.operations import (
    OperationIntent,
    StepIntent,
    UsageMutation,
    operation_holder,
    safe_json,
)
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from ordessa_units.bindings.contracts import DirectoryBindingRef
from ordessa_units.admission.invocation import (
    InvocationCurrentState,
    InvocationGrant,
    InvocationIssuer,
)


_DIGEST = "fixed-request-digest"
_TARGET = {
    "environmentNamespace": "env",
    "hostId": "fixture-host",
    "nativeRealm": "fixture-realm",
    "objectId": "fixture-node",
    "scope": "unit",
    "generation": 1,
}
_PROVIDER = {
    "environmentNamespace": "env",
    "providerId": "fixture-provider",
    "version": "1.0",
    "generation": 1,
}


def _request(request_id="operation-request"):
    return RequestKey("env", "principal", request_id)


def _intent(request=None):
    request = request or _request()
    env = request.environment_namespace
    steps = tuple(
        StepIntent(
            step_id,
            {**_PROVIDER, "environmentNamespace": env},
            f"input-{step_id}",
            f"correlation-{step_id}",
        )
        for step_id in ("first", "tail")
    )
    context = {
        "environmentNamespace": env,
        "directoryBindingRef": DirectoryBindingRef(
            env, "fixture-binding", 1, "sha256:" + "a" * 64
        ).to_dict(),
        "invocationBindings": {
            step.step_id: {
                "action": "apply",
                "targetRef": {**_TARGET, "environmentNamespace": env},
                "delegationRef": None,
                "cleanup": False,
            }
            for step in steps
        },
    }
    return OperationIntent(
        "fixture-operation",
        "operation-claim-integrity-fixture",
        None,
        context,
        steps,
        None,
    )


def _conclude(store, request, intent, step):
    claim = store.claim_operation_step(request, _DIGEST, step)
    assert claim.claimed
    return store.record_operation_step(
        request,
        _DIGEST,
        step.step_id,
        step.input_digest,
        claim.step.revision,
        "concluded",
        {"evidenceRef": f"controlled-{step.step_id}"},
    )


def _pending_usage(request, intent, usage_id):
    return UsageMutation(
        usage_id,
        0,
        None,
        operation_holder(request, intent.operation_ref),
        {"environmentNamespace": request.environment_namespace, "resourceId": "fixture-resource"},
        ("use",),
        "active",
    )


def _issuer(store, request, intent):
    class Authority:
        issuer_ref = {"environmentNamespace": "env", "issuerId": "fixture-authority"}
        revision = "authority-rev-1"

        def authorize(self, request, actions, target_ref, delegation_ref):
            return InvocationGrant(
                principal_scope=request.principal_scope,
                delegation_ref=delegation_ref,
                actions=actions,
                target_ref=target_ref,
                authority_revision=self.revision,
                expires_at=100,
                issuer_ref=self.issuer_ref,
            )

        def revalidate(self, grant, request, actions, target_ref):
            return self.authorize(request, actions, target_ref, grant.delegation_ref)

    class CurrentState:
        directory_ref = DirectoryBindingRef(
            "env", "fixture-binding", 1, "sha256:" + "a" * 64
        )

        def inspect(self, request, provider_ref, context_ref, target_ref, action):
            return InvocationCurrentState(
                provider_ref, True, 0, self.directory_ref, True, None, None
            )

    return InvocationIssuer(store, Authority(), CurrentState(), clock=lambda: 50)


def _counts(store):
    return (
        store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0],
        store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0],
        store._conn.execute(
            "SELECT operation_revision FROM env_requests WHERE request_id=?",
            ("operation-request",),
        ).fetchone()[0],
    )


def test_missing_current_row_fails_read_query_and_claim_without_writes(tmp_path):
    store = SqliteStorePort(tmp_path / "current-row.sqlite")
    request, intent = _request(), _intent()
    store.reserve_operation(request, _DIGEST, intent)
    try:
        assert store.claim_operation_step(request, _DIGEST, intent.steps[0]).claimed
        store._conn.execute(
            "DELETE FROM env_request_steps WHERE environment=? AND principal=? AND request_id=? AND step_id=?",
            (request.environment_namespace, request.principal_scope, request.request_id, "first"),
        )
        store._conn.commit()
        before = _counts(store)

        with pytest.raises(GuaranteeUnavailableError):
            store.read_operation(request)
        with pytest.raises(GuaranteeUnavailableError):
            store.read_operation_step(request, "tail")
        with pytest.raises(GuaranteeUnavailableError):
            _issuer(store, request, intent).issue_query(request, _DIGEST, "first")
        with pytest.raises(GuaranteeUnavailableError):
            store.claim_operation_step(
                request, _DIGEST, intent.steps[0],
                (_pending_usage(request, intent, "current-claim-usage"),),
            )
        with pytest.raises(GuaranteeUnavailableError):
            store.claim_operation_step(
                request, _DIGEST, intent.steps[1],
                (_pending_usage(request, intent, "next-claim-usage"),),
            )

        assert _counts(store) == before
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
    finally:
        store.close()


def test_missing_early_row_does_not_hide_current_tail_or_allow_reclaim(tmp_path):
    store = SqliteStorePort(tmp_path / "past-row.sqlite")
    request, intent = _request(), _intent()
    store.reserve_operation(request, _DIGEST, intent)
    try:
        _conclude(store, request, intent, intent.steps[0])
        assert store.claim_operation_step(request, _DIGEST, intent.steps[1]).claimed
        tail_before = store.read_operation_step(request, "tail")
        store._conn.execute(
            "DELETE FROM env_request_steps WHERE environment=? AND principal=? AND request_id=? AND step_id=?",
            (request.environment_namespace, request.principal_scope, request.request_id, "first"),
        )
        store._conn.commit()

        # Ordinary reads validate the current claim only. The missing historic
        # row cannot make the intact tail look like an unclaimed operation.
        operation = store.read_operation(request)
        assert operation.current_step == "tail"
        assert store.read_operation_step(request, "tail") == tail_before
        query_issuer = _issuer(store, request, intent)
        query = query_issuer.issue_query(request, _DIGEST, "tail")
        verified = query_issuer.verify_and_consume(
            query, "query", intent.steps[1].pinned_provider_ref, _TARGET,
            intent.steps[1].input_digest,
        )
        assert verified["query"] is True

        before = _counts(store)
        with pytest.raises(GuaranteeUnavailableError):
            store.claim_operation_step(
                request, _DIGEST, intent.steps[0],
                (_pending_usage(request, intent, "past-claim-usage"),),
            )
        assert _counts(store) == before
        assert store._conn.execute(
            "SELECT COUNT(*) FROM env_request_steps WHERE step_id='first'"
        ).fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
    finally:
        store.close()


def test_current_none_with_orphan_step_row_is_corrupt(tmp_path):
    store = SqliteStorePort(tmp_path / "orphan-row.sqlite")
    request, intent = _request(), _intent()
    store.reserve_operation(request, _DIGEST, intent)
    try:
        step = intent.steps[0]
        store._conn.execute(
            "INSERT INTO env_request_steps(environment,principal,request_id,step_id,intent_json,revision,outcome,evidence_json) "
            "VALUES(?,?,?,?,?,1,'possibly-dispatched','{}')",
            (request.environment_namespace, request.principal_scope, request.request_id,
             step.step_id, safe_json(step.to_dict())),
        )
        store._conn.commit()
        before = _counts(store)

        with pytest.raises(GuaranteeUnavailableError):
            store.read_operation(request)
        with pytest.raises(GuaranteeUnavailableError):
            store.read_operation_step(request, "first")
        with pytest.raises(GuaranteeUnavailableError):
            store.claim_operation_step(request, _DIGEST, step)

        assert _counts(store) == before
    finally:
        store.close()


def test_reserved_and_refused_no_claim_replay_survives_reopen(tmp_path):
    path = tmp_path / "no-claim-replay.sqlite"
    store = SqliteStorePort(path)
    request, intent = _request(), _intent()
    try:
        reserved = store.reserve_operation(request, _DIGEST, intent)
        assert reserved.status == "reserved" and reserved.current_step is None
        assert store.read_operation(request) == reserved
        assert store.reserve_operation(request, _DIGEST, intent) == reserved
        refused = store.record_operation_outcome(
            request, _DIGEST, reserved.revision, "refused", {"evidenceRef": "controlled-refusal"}
        )
        assert refused.status == "refused" and refused.current_step is None
        assert store.record_operation_outcome(
            request, _DIGEST, reserved.revision, "refused", {"evidenceRef": "controlled-refusal"}
        ) == refused
        with pytest.raises(UnknownResultError):
            store.claim_operation_step(request, _DIGEST, intent.steps[0])
        assert store._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 0
        assert store._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
    finally:
        store.close()

    reopened = SqliteStorePort(path)
    try:
        assert reopened.read_operation(request).status == "refused"
        assert reopened.record_operation_outcome(
            request, _DIGEST, 1, "refused", {"evidenceRef": "controlled-refusal"}
        ).status == "refused"
        with pytest.raises(UnknownResultError):
            reopened.claim_operation_step(request, _DIGEST, intent.steps[0])
        assert reopened._conn.execute("SELECT COUNT(*) FROM env_request_steps").fetchone()[0] == 0
        assert reopened._conn.execute("SELECT COUNT(*) FROM env_usages").fetchone()[0] == 0
    finally:
        reopened.close()


def test_existing_unknown_claim_is_not_reclaimed_and_valid_order_advances(tmp_path):
    store = SqliteStorePort(tmp_path / "ordered-claims.sqlite")
    request, intent = _request(), _intent()
    store.reserve_operation(request, _DIGEST, intent)
    try:
        first_claim = store.claim_operation_step(request, _DIGEST, intent.steps[0])
        assert first_claim.claimed
        assert not store.claim_operation_step(request, _DIGEST, intent.steps[0]).claimed
        unknown = store.record_operation_step(
            request, _DIGEST, "first", intent.steps[0].input_digest,
            first_claim.step.revision, "unknown", {},
        )
        before = _counts(store)
        assert store.claim_operation_step(request, _DIGEST, intent.steps[0]).step == unknown
        assert not store.claim_operation_step(request, _DIGEST, intent.steps[0]).claimed
        with pytest.raises(UnknownResultError):
            store.claim_operation_step(request, _DIGEST, intent.steps[1])
        assert _counts(store) == before

    finally:
        store.close()

    ordered = SqliteStorePort(tmp_path / "ordered-valid.sqlite")
    request, intent = _request("ordered-request"), _intent(_request("ordered-request"))
    try:
        ordered.reserve_operation(request, _DIGEST, intent)
        _conclude(ordered, request, intent, intent.steps[0])
        assert ordered.claim_operation_step(request, _DIGEST, intent.steps[1]).claimed
        assert ordered.read_operation(request).current_step == "tail"
        assert ordered.read_operation_step(request, "first").outcome == "concluded"
        assert ordered.read_operation_step(request, "tail").outcome == "possibly-dispatched"
    finally:
        ordered.close()
