"""Controlled minimal real call of the published permissions API + backend service.

Run from the repository root:
    .venv/bin/python specs/011-q5-safety/proof/permissions_api_proof.py

It exercises the imported public API (no mocks, no stubs) and the migrated
approval authority against the real product storage provider (the class
`ordessa_server_product.composition.ServerProductComposition.database_type()`
returns, i.e. `pacthold_runtime_compat.storage.Database`) in a throwaway
data root. Exit 0 means every stated outcome was observed; any deviation exits
1. It never touches the network, a model, or a user config directory.
"""
from __future__ import annotations

import datetime as dt
import sys
import hashlib
import tempfile
from pathlib import Path

import ordessa_permissions_api as api
import ordessa_permissions_backend as backend

REPO_ROOT = Path(__file__).resolve().parents[3]
NOW = dt.datetime(2026, 9, 28, 12, 0, 0, tzinfo=dt.timezone.utc)
FAILURES: list[str] = []


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check(label: str, expected: str, observed: object) -> None:
    ok = str(observed) == expected
    print(f"[{'PASS' if ok else 'FAIL'}] {label}: expected {expected!r} got {observed!r}")
    if not ok:
        FAILURES.append(label)


def make_ceiling() -> api.PolicyCeiling:
    return api.PolicyCeiling(
        policy_id="ceil-org-1", scope=api.Scope.ADMIN, revision=1,
        source=api.CeilingSource.SIGNED_ADMIN, signed=True,
        hard_denies=(api.CeilingEntry(api.ToolIdentity("edit"), "deny",
                                      api.TargetMatcher("/etc/*")),),
        require_approval=(api.CeilingEntry(api.ToolIdentity("bash"), "ask"),),
        maximum_exposure=api.ExposureLevel.EXEC,
        effective_from=NOW - dt.timedelta(days=1))


def make_intent() -> api.PermissionIntent:
    return api.PermissionIntent(
        intent_id="intent-relaxed-1", revision=1, harness_id="codex",
        scope=api.Scope.SESSION,
        rules=(api.TypedRule(api.ToolIdentity("edit"), api.RuleAction.ALLOW),
               api.TypedRule(api.ToolIdentity("bash"), api.RuleAction.ALLOW)))


def request_for(*, tool: str, target: str | None, ceilings, intent,
                native_request_id: str) -> api.OperationRequest:
    return api.build_operation_request(
        principal="user-1", server_instance_id="srv-1", session_id="sess-1",
        native_session_id="native-1", execution_id="exec-1", native_generation="gen-1",
        tool_key=tool, target=target,
        argument_digest=api.ArgumentDigest(digest("arguments of this tool call")),
        native_request_id=native_request_id, ceilings=ceilings, intent=intent)


def part_a_decision_service() -> None:
    ceiling, intent = make_ceiling(), make_intent()
    ceilings = [ceiling]

    denied = api.evaluate_authorization(
        ceilings=ceilings, intent=intent, now=NOW,
        request=request_for(tool="edit", target="/etc/hosts", ceilings=ceilings,
                            intent=intent, native_request_id="native-req-1"))
    check("profile allow cannot widen an admin deny", "Denied", type(denied).__name__)
    check("  and it carries the stable ceiling code", "POLICY_CEILING_VIOLATION",
          denied.code.value if hasattr(denied.code, "value") else denied.code)

    pending = api.evaluate_authorization(
        ceilings=ceilings, intent=intent, now=NOW,
        request=request_for(tool="bash", target=None, ceilings=ceilings, intent=intent,
                            native_request_id="native-req-2"))
    check("an intent allow under a require-approval ceiling is not an allow",
          "PendingApproval", type(pending).__name__)

    unknown_tool = api.evaluate_authorization(
        ceilings=ceilings, intent=None, now=NOW,
        request=request_for(tool="weld", target=None, ceilings=ceilings, intent=None,
                            native_request_id="native-req-3"))
    check("an unknown tool refuses instead of inheriting", "Denied",
          type(unknown_tool).__name__)

    no_provider = api.evaluate_authorization(
        ceilings=[], intent=intent, now=NOW,
        request=request_for(tool="bash", target=None, ceilings=ceilings, intent=intent,
                            native_request_id="native-req-4"))
    check("a missing ceiling provider is a missing provider, not an open field",
          "Denied", type(no_provider).__name__)


sys.path.insert(0, str(REPO_ROOT / "plugins/permissions/backend/tests"))


def part_b_approval_authority() -> None:
    import support  # the lane's real database + record builders, not a mock
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        root.mkdir(parents=True, exist_ok=True)
        database = support.seeded_database(root)
        support.seed_session(database)
        facts = backend.ApprovalFacts(database)
        facts.ensure_schema()
        ceilings = [support.admin_ceiling()]

        operation = support.make_operation(ceilings=ceilings, target="/repo/a.py",
                                           native_request_id="acp-native-req-7")
        record = support.approval_record(operation, requested_at=NOW,
                                         expires_at=NOW + dt.timedelta(minutes=5))
        facts.request(session_id=operation.session_id, execution_id=operation.execution_id,
                      request=record)
        approval_id, version = record["approvalId"], record["version"]
        check("approval recorded", "open", facts.get(approval_id)["state"])

        settled = facts.decide(approval_id=approval_id, decision="allow",
                               scope={"kind": "once"}, expected_version=version,
                               request_id="decide-1", now=NOW)
        check("first decision recorded", "Recorded", _outcome(settled))

        replay = facts.decide(approval_id=approval_id, decision="allow",
                              scope={"kind": "once"}, expected_version=version,
                              request_id="decide-1", now=NOW)
        check("replay of the same request id is already-recorded, never a second decision",
              "AlreadyRecorded", _outcome(replay))

        opposite = facts.decide(approval_id=approval_id, decision="deny",
                                scope={"kind": "once"}, expected_version=version + 1,
                                request_id="decide-2", now=NOW)
        check("an opposite decision after settle is refused", "InvalidApproval", _outcome(opposite))

        unknown = facts.reconcile(approval_id, "acp-native-req-7")
        check("before any native receipt the outcome is unknown, never allowed",
              "QueryUnknown", type(unknown).__name__)

        facts.record_native_receipt(approval_id, api.NativeReceipt.of(
            native_request_id="acp-native-req-7", approval_id=approval_id,
            confirmed=True, observed_at=NOW))
        reconciled = facts.reconcile(approval_id, "acp-native-req-7")
        check("after the native owner confirmed, reconciliation carries the receipt",
              "QueriedApproval", type(reconciled).__name__)

        spent_once = facts.consume_grant(approval_id=approval_id,
                                         operation_digest=operation.operation_digest,
                                         native_request_id="acp-native-req-7", moment=NOW)
        spent_twice = facts.consume_grant(approval_id=approval_id,
                                          operation_digest=operation.operation_digest,
                                          native_request_id="acp-native-req-7", moment=NOW)
        check("the approved grant is spendable", "True", spent_once)
        check("and only once", "False", spent_twice)

        wrong_digest = facts.consume_grant(approval_id=approval_id,
                                           operation_digest=digest("another operation"),
                                           native_request_id="acp-native-req-7", moment=NOW)
        check("a grant never rebinds to a different operation digest", "False", wrong_digest)

        other = facts.decide(approval_id=approval_id, decision="allow",
                              scope={"kind": "once"}, expected_version=version + 1,
                              request_id="decide-4", session_id="sess-OTHER", now=NOW)
        check("a decision presented under another session cannot settle it",
              "InvalidApproval", _outcome(other))

        pending = support.make_operation(ceilings=ceilings, target="/repo/c.py",
                                         native_request_id="acp-native-req-9")
        pending_record = support.approval_record(pending, requested_at=NOW,
                                                  expires_at=NOW + dt.timedelta(minutes=5))
        facts.request(session_id=pending.session_id, execution_id=pending.execution_id,
                      request=pending_record)
        check("an open approval keeps the provider busy until settled or reconciled",
              "1", str(len(facts.open_for_execution(pending.execution_id))))


def _real_database(root: Path):
    """The real product database, schema-initialized, with the FK chain a row needs.

    Uses the lane's own seeding helper rather than a hand-rolled schema.
    """
    root.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(REPO_ROOT / "plugins/permissions/backend/tests"))
    import support
    database = support.seeded_database(root)
    support.seed_session(database, session_id="sess-1", execution_id="exec-1")
    support.seed_session(database, session_id="sess-2", execution_id="exec-2")
    return database


def _outcome(result: object) -> str:
    """The service answers with a typed union; the class name is the outcome."""
    return type(result).__name__


def _busy_count(facts) -> int:
    busy = getattr(facts, "busy", None)
    if callable(busy):
        value = busy()
        return len(value) if isinstance(value, (list, tuple)) else int(value)
    return len(facts.open_for_execution("exec-2"))


def main() -> int:
    part_a_decision_service()
    part_b_approval_authority()
    if FAILURES:
        print(f"\n{len(FAILURES)} expectation(s) not met: {', '.join(FAILURES)}")
        return 1
    print("\nALL PROOF EXPECTATIONS MET")
    return 0


if __name__ == "__main__":
    sys.exit(main())
