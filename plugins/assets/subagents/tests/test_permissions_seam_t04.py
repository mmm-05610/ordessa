"""T04 / FR06 + US3 + G09: the Q3 ceiling consumes the REAL permissions authority.

Evidence level: the ruling is taken by Q5's real `Authorizer` over the real
`ApprovalFacts` store, in a pytest `tmp_path` sqlite file. `ApprovalFacts`
documents the database as injected (`transaction()` / `read()`), so the storage
seam is the product's own seam and **nothing inside `ordessa_permissions_*` is
stubbed** in `TestRealAuthority*`. The only fakes in this file are the two
explicitly marked port-boundary doubles (`ScriptedPort`, `SpyPort`): they sit
outside the port, hand back objects built by Q5's real constructors, and exist
where a live store cannot produce an exotic outcome on demand.

Checkpoint `specs/011-plugin-rollout/checkpoints/permissions-api.json` records
the one limit that bounds every claim here: **no pre-effect execution gate
exists in this tree** (Request G1, owner C0). These tests prove adjudication —
that admission consumes the authority's ruling and refuses without one — and
never that a tool side effect was blocked.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib
import inspect
import sqlite3
import sys

import pytest
from ordessa_permissions_api import (
    GRANT_TTL,
    AllowedOnce,
    ApprovalDecision,
    ArgumentDigest,
    AuthorizationDecision,
    BoundGrant,
    BoundedApprovalScope,
    Denied,
    InvalidApproval,
    NativeReceipt,
    PermissionIntent,
    PolicyCeiling,
    PolicyRefusal,
    QueriedApproval,
    QueryUnknown,
    RefusalCode,
    TypedRule,
    UnknownApproval,
    approval_id_for,
    build_operation_request,
    scope_to_record,
)
from ordessa_permissions_backend import (
    ApprovalFacts,
    Authorizer,
    CorrelationConflict,
    OPEN,
    VersionConflict,
)

from ordessa_assets_subagents import ceiling, dto, errors
from ordessa_assets_subagents import permissions_seam as seam_module
from ordessa_assets_subagents.permissions_seam import (
    AUTHORIZER_PORT_NAME,
    DECISION_TO_C5,
    REFUSAL_CODE_TO_C5,
    PermissionsSeam,
    default_approval_scope,
    map_refusal_code,
    tool_key_for,
)
from ordessa_assets_subagents.scopes import (
    AuthorizationContext,
    Principal,
    ProjectId,
    ServerScope,
    SessionId,
)

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 28, 12, 0, 0, tzinfo=UTC)
U1 = Principal("u1")
SCOPE = ServerScope("s1")
SESSION = SessionId("sess-1")
EXECUTION = "turn-1"
DIGEST = "sha256:" + "b" * 64

#: The tables `ApprovalFacts` reads but does not own: the execution row the
#: authority checks for actionability, and the session-event ledger its default
#: writer appends to. Same column names as the product's.
_HOST_TABLES = (
    "CREATE TABLE IF NOT EXISTS server_session_events(session_id TEXT NOT NULL,"
    " seq INTEGER NOT NULL, wire_seq INTEGER, event_id TEXT, turn_id TEXT, kind TEXT,"
    " schema_version INTEGER, data_json TEXT, created_at TEXT)",
    "CREATE TABLE IF NOT EXISTS server_turns(id TEXT PRIMARY KEY, state TEXT NOT NULL)",
)


class TempDatabase:
    """The injected host database: a real sqlite file in `tmp_path`, nothing else."""

    def __init__(self, path) -> None:
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row

    @contextlib.contextmanager
    def transaction(self):
        try:
            yield self._conn
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise

    @contextlib.contextmanager
    def read(self):
        yield self._conn


def revision(**overrides) -> dto.DefinitionRevision:
    base = dict(definition_id="d1", revision=1, content_digest=DIGEST, role_body="body")
    base.update(overrides)
    return dto.DefinitionRevision(**base)


def admin_ceiling(revision_no: int = 1, **overrides) -> PolicyCeiling:
    record = {
        "policyId": "q3-admin", "scope": "admin", "revision": revision_no,
        "source": "signed-admin", "signed": True, "maximumExposure": "full",
        "effectiveFrom": "2020-01-01T00:00:00+00:00",
    }
    record.update(overrides)
    return PolicyCeiling.from_record(record)


def intent_allowing(*keys: str) -> PermissionIntent:
    return PermissionIntent.of(
        intent_id="q3-intent", revision=1, harness_id="claude", scope="user",
        rules=[TypedRule.of(key=key, action="allow", scope="user") for key in keys],
    )


def wire(tmp_path, *, ceilings=None, intent=None, turn_state="running"):
    """Real `ApprovalFacts` + real `Authorizer` + the seam over that port."""
    database = TempDatabase(tmp_path / "approvals.sqlite")
    with database.transaction() as conn:
        for ddl in _HOST_TABLES:
            conn.execute(ddl)
    facts = ApprovalFacts(database)
    facts.ensure_schema()
    with database.transaction() as conn:
        conn.execute("INSERT INTO server_turns(id, state) VALUES (?, ?)",
                     (EXECUTION, turn_state))
    members = [admin_ceiling()] if ceilings is None else list(ceilings)
    ceiling_provider = lambda: list(members)  # noqa: E731
    intent_provider = lambda: intent  # noqa: E731
    clock = lambda: NOW  # noqa: E731
    authorizer = Authorizer(facts=facts, ceiling_provider=ceiling_provider,
                            intent_provider=intent_provider, clock=clock)
    seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                           port_name=AUTHORIZER_PORT_NAME,
                           session_id=SESSION, execution_id=EXECUTION,
                           authorizer=authorizer, ceiling_provider=ceiling_provider,
                           intent_provider=intent_provider, clock=clock,
                           conflict_types=(VersionConflict, CorrelationConflict))
    return facts, authorizer, seam


def settle(facts, authorizer, *, approval_id: str, native_id: str, scope: dict,
           receipt: bool) -> None:
    """The user's own ruling, recorded through the authority's own surface."""
    decided = authorizer.decide(approval_id=approval_id, expected_version=1,
                                decision="allow", scope=scope, operation_key="ui-1",
                                session_id=SESSION.id)
    assert decided.decision is ApprovalDecision.ALLOW, decided
    if receipt:
        facts.record_native_receipt(approval_id, NativeReceipt.of(
            native_request_id=native_id, approval_id=approval_id, confirmed=True,
            observed_at=NOW.isoformat()))


def digest_of(seam, rev, kind, value, *, ceilings=None, intent=None) -> str:
    subject = seam.subject_for(rev)
    """The operation digest, re-derived through their own API.

    Not a reimplementation of the digest: the same inputs are handed to
    `build_operation_request`, so equality proves the seam used their identity
    handling rather than inventing one.
    """
    request = build_operation_request(
        principal=seam.principal.id, server_instance_id=seam.server_scope.id,
        session_id=(subject.session_id.id if subject.session_id
                    else f"declaration:{subject.principal.id}"),
        native_session_id=f"native-{subject.session_id.id if subject.session_id
                           else subject.principal.id}",
        execution_id=subject.execution_id or f"assets-declaration:{rev.definition_id}"
        f"#r{rev.revision}",
        native_generation=f"assets:{rev.content_digest}",
        tool_key=tool_key_for(kind, value), target=f"{kind}:{value}",
        argument_digest=seam.argument_digest(subject, kind, value),
        native_request_id=seam.native_request_id(subject, kind, value),
        ceilings=[admin_ceiling()] if ceilings is None else list(ceilings),
        intent=intent)
    return request.operation_digest


def settle_all(facts, authorizer, seam, rev, *, scope: dict, receipt: bool) -> None:
    """Settle every item the seam still has no ruling for, through the
    authority's own `decide` + native-receipt surface."""
    subject = seam.subject_for(rev)
    for kind, value, field_name in ceiling.admission_items(rev):
        ruling = seam.adjudicate(subject, kind, value, field_name=field_name)
        if ruling.admitted:
            continue
        native_id = seam.native_request_id(subject, kind, value)
        approval_id = approval_id_for(
            operation_digest=digest_of(seam, rev, kind, value),
            native_request_id=native_id)
        settle(facts, authorizer, approval_id=approval_id, native_id=native_id,
               scope=scope, receipt=receipt)


def put(seam, rev, kind, value, *, field_name):
    """Put exactly one declared item to the seam, under its own subject."""
    return seam.adjudicate(seam.subject_for(rev), kind, value, field_name=field_name)


class ScriptedPort:
    """PORT-BOUNDARY FAKE: answers `evaluate` with a pre-built §C1 object.

    The objects are Q5's real classes, built through their real constructors;
    only the *ruling* is scripted, so an outcome a live store cannot be driven
    to produce on demand can still be tested for its mapping.
    """

    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.calls: list[dict] = []

    def evaluate(self, **kwargs):
        self.calls.append(kwargs)
        return self.outcome

    def reconcile(self, approval_id, native_request_id):
        return QueryUnknown(reason="scripted-port-has-no-record")


class SpyPort:
    """PORT-BOUNDARY SPY: delegates every call to the real authorizer and keeps
    the kwargs, so what the authority was actually told is observable."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.evaluate_calls: list[dict] = []
        self.reconcile_calls: list[tuple] = []

    def evaluate(self, **kwargs):
        self.evaluate_calls.append(kwargs)
        return self.inner.evaluate(**kwargs)

    def reconcile(self, approval_id, native_request_id):
        self.reconcile_calls.append((approval_id, native_request_id))
        return self.inner.reconcile(approval_id, native_request_id)


class TestRealAuthorityRoundTrip:
    def test_intent_allow_admits_and_the_evidence_names_the_port(self, tmp_path) -> None:
        _facts, _authorizer, seam = wire(tmp_path, intent=intent_allowing("task"))
        admitted = ceiling.admit(revision(), seam)
        assert admitted.effective_tools == frozenset()
        assert any("permissions.authorizer@1" in item for item in admitted.evidence), \
            admitted.evidence
        # The authority's ALLOW ruling is a single-use grant: admitted, never standing.
        assert admitted.single_use_fields == ("definition",)
        assert not admitted.is_standing

    def test_an_unsettled_approval_admits_nothing_and_reaches_the_store(
        self, tmp_path
    ) -> None:
        facts, _authorizer, seam = wire(tmp_path, intent=None)
        rev = revision()
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(rev, seam)
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert "definition" in exc.value.item_id
        native_id = seam.native_request_id(seam.subject_for(rev), "definition", "d1")
        approval_id = approval_id_for(
            operation_digest=digest_of(seam, rev, "definition", "d1"),
            native_request_id=native_id)
        row = facts.peek(approval_id)
        assert row is not None and row["state"] == OPEN, (
            "the authority never actually ran: no approval fact was written")

    def test_hard_denied_tool_is_refused_naming_its_item_field(self, tmp_path) -> None:
        _facts, _authorizer, seam = wire(
            tmp_path,
            ceilings=[admin_ceiling(deny=[{"key": "bash", "action": "deny"}])],
            intent=intent_allowing("task"),
        )
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(tool_refs=(dto.ToolRef("Bash"),)), seam)
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert "toolRefs.Bash" in exc.value.item_id

    def test_a_tool_the_vocabulary_has_no_word_for_is_operation_unknown(
        self, tmp_path
    ) -> None:
        _facts, authorizer, seam = wire(tmp_path, intent=intent_allowing("task"))
        spy = SpyPort(authorizer)
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               session_id=SESSION, execution_id=EXECUTION,
                               authorizer=spy, ceiling_provider=lambda: [admin_ceiling()],
                               intent_provider=lambda: intent_allowing("task"),
                               clock=lambda: NOW)
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(tool_refs=(dto.ToolRef("Grep"),)), seam)
        assert exc.value.code == errors.OPERATION_UNKNOWN
        assert "toolRefs.Grep" in exc.value.item_id
        # The refusal is taken from their vocabulary check, before any ruling is
        # put to the port: an unnamed tool cannot be "approved" into existence.
        assert all(call["tool_identity"].key != "grep" for call in spy.evaluate_calls)

    def test_a_once_approval_admits_once_and_the_next_use_is_a_conflict(
        self, tmp_path
    ) -> None:
        facts, authorizer, seam = wire(tmp_path, intent=None)
        rev = revision(tool_refs=(dto.ToolRef("Bash"),))
        with pytest.raises(errors.DomainError):
            ceiling.admit(rev, seam)  # pending: nothing granted
        settle_all(facts, authorizer, seam, rev, scope={"kind": "once"}, receipt=True)
        admitted = ceiling.admit(rev, seam)  # the settled approvals now answer
        assert "Bash" in admitted.effective_tools
        assert admitted.single_use_fields, (
            "a 'once' approval was recorded as a standing grant")
        assert not admitted.is_standing
        assert all("single-use" in item for item in admitted.evidence), admitted.evidence
        with pytest.raises(errors.DomainError) as second:
            ceiling.admit(rev, seam)  # the grant is spent: it was never a permission
        assert second.value.code == errors.ASSIGNMENT_CONFLICT
        assert "toolRefs.Bash" in second.value.item_id

    def test_only_a_bounded_settled_scope_reads_as_standing(self, tmp_path) -> None:
        facts, authorizer, seam = wire(tmp_path, intent=None)
        rev = revision()
        with pytest.raises(errors.DomainError):
            ceiling.admit(rev, seam)
        settle_all(facts, authorizer, seam, rev,
                   scope={"kind": "bounded", "until": "session_end",
                          "environmentId": None},
                   receipt=True)
        admitted = ceiling.admit(rev, seam)
        assert admitted.single_use_fields == ()
        assert admitted.is_standing
        assert any("standing" in item for item in admitted.evidence), admitted.evidence
        # The authority, not this adapter, decided that it stands.
        assert seam.consultations, "no ruling was ever taken"

    def test_an_unconfirmed_native_result_stays_unknown(self, tmp_path) -> None:
        facts, authorizer, seam = wire(tmp_path, intent=None)
        rev = revision()
        with pytest.raises(errors.DomainError):
            ceiling.admit(rev, seam)
        native_id = seam.native_request_id(seam.subject_for(rev), "definition", "d1")
        approval_id = approval_id_for(
            operation_digest=digest_of(seam, rev, "definition", "d1"),
            native_request_id=native_id)
        # The user allowed it, but the native owner never confirmed the request
        # (checkpoint limitation G2): the ruling must not read as a grant.
        settle(facts, authorizer, approval_id=approval_id, native_id=native_id,
               scope={"kind": "once"}, receipt=False)
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(rev, seam)
        assert exc.value.code == errors.OPERATION_UNKNOWN
        assert "APPROVAL_RESULT_UNKNOWN" in (exc.value.detail or "")


class TestTheSubjectCarriesTheVerifiedIdentity:
    def test_a_self_reported_subject_is_refused_before_any_ruling(self, tmp_path) -> None:
        _facts, authorizer, seam = wire(tmp_path, intent=intent_allowing("task"))
        spy = SpyPort(authorizer)
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               session_id=SESSION, execution_id=EXECUTION,
                               authorizer=spy, ceiling_provider=lambda: [admin_ceiling()],
                               intent_provider=lambda: intent_allowing("task"),
                               clock=lambda: NOW)
        claim = ceiling.AdmissionContext(          # assembled from request data
            principal=Principal("attacker"), server_scope=SCOPE, harness_id="claude",
            definition_id="d1", revision=1, content_digest=DIGEST)
        ruling = seam.adjudicate(claim, "tool", "Read", field_name="toolRefs.Read")
        assert not ruling.admitted
        assert ruling.code == errors.PERMISSION_EXCEEDS_CEILING
        assert ruling.field_name == "principal"
        assert spy.evaluate_calls == [], "an unverified claim reached the authority"

    def test_a_ceiling_issued_for_another_identity_is_not_ruled_on(
        self, tmp_path
    ) -> None:
        # The grants and the authority have to belong to the same verified party,
        # otherwise u2's authority could wave u1's ceiling record through.
        _facts, authorizer, seam = wire(tmp_path, intent=intent_allowing("task"))
        other = ceiling.AdmissionContext.from_service(
            principal=Principal("u2"), server_scope=ServerScope("s2"),
            harness_id="other-brand", revision=revision())
        ruling = seam.adjudicate(other, "tool", "Read", field_name="toolRefs.Read")
        assert not ruling.admitted
        assert ruling.code == errors.ASSIGNMENT_CONFLICT
        assert ruling.field_name == "principal"

    def test_the_subject_is_the_same_for_every_item_of_one_admission(
        self, tmp_path
    ) -> None:
        _facts, _authorizer, seam = wire(
            tmp_path, intent=intent_allowing("task", "read", "bash"))
        rev = revision(tool_refs=(dto.ToolRef("Read"), dto.ToolRef("Bash")))
        admitted = ceiling.admit(rev, seam)
        assert admitted.effective_tools == frozenset({"Read", "Bash"})
        assert len(seam.consultations) == len(ceiling.admission_items(rev))

    def test_the_ruling_carries_the_authoritys_record_as_data(self, tmp_path) -> None:
        _facts, _authorizer, seam = wire(tmp_path, intent=intent_allowing("read"))
        ruling = put(seam, revision(), "tool", "Read", field_name="toolRefs.Read")
        assert ruling.payload["singleUse"] is True
        assert ruling.payload["ceilingRevision"] == "q3-admin@1"
        assert set(ruling.payload) <= {
            "approvalId", "operationDigest", "target", "ceilingRevision",
            "policyRevision", "nativeGeneration", "expiresAt", "singleUse"}


class TestAbsentAuthorityStillRefuses:
    def test_no_object_on_the_port_is_a_typed_refusal(self, tmp_path) -> None:
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               ceiling_provider=lambda: [admin_ceiling()])
        assert not seam.is_available()
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(), seam)
        assert exc.value.code == errors.ADAPTER_MISSING

    def test_a_port_lookup_that_raises_counts_as_absent(self) -> None:
        def broken() -> object:
            raise RuntimeError("plugin not loaded")

        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               authorizer_provider=broken,
                               ceiling_provider=lambda: [admin_ceiling()])
        ruling = put(seam, revision(), "definition", "d1", field_name="definition")
        assert not ruling.admitted
        assert ruling.code == errors.ADAPTER_MISSING

    def test_no_trusted_ceiling_in_force_refuses_instead_of_defaulting(self) -> None:
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               authorizer=ScriptedPort(None), ceiling_provider=lambda: [])
        ruling = put(seam, revision(), "definition", "d1", field_name="definition")
        assert not ruling.admitted
        assert ruling.code == errors.ADAPTER_MISSING

    def test_a_wired_but_unusable_authorizer_is_unavailable(self) -> None:
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               authorizer=object())
        assert not seam.is_available()
        ruling = put(seam, revision(), "definition", "d1", field_name="definition")
        assert ruling.code == errors.ADAPTER_MISSING

    def test_admit_refuses_when_the_authority_reports_itself_unavailable(
        self, tmp_path
    ) -> None:
        _facts, _authorizer, seam = wire(tmp_path, intent=intent_allowing("task"))
        granted = ceiling.Ceiling(
            principal=U1, server_scope=SCOPE, harness_id="claude",
            allowed_tools=frozenset({"Read"}),
            authority=PermissionsSeam(principal=U1, server_scope=SCOPE,
                                      harness_id="claude"))
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(tool_refs=(dto.ToolRef("Read"),)), granted)
        assert exc.value.code == errors.ADAPTER_MISSING
        assert seam.is_available()  # the wired one is fine; the injected empty one is not


class TestDecisionMapping:
    @pytest.mark.parametrize(
        "outcome,expected_code",
        [
            (Denied.of(code=RefusalCode.POLICY_CEILING_VIOLATION, evidence_ref="evid_1",
                       reason="the ceiling denies this"),
             errors.PERMISSION_EXCEEDS_CEILING),
            (Denied.of(code="policy_deny", evidence_ref="evid_1", reason="the policy denies"),
             errors.PERMISSION_EXCEEDS_CEILING),
            (Denied.of(code=RefusalCode.PERMISSION_UNKNOWN_TOOL, evidence_ref="evid_1",
                       reason="not in the vocabulary"),
             errors.OPERATION_UNKNOWN),
            (Denied.of(code=RefusalCode.POLICY_ADAPTER_MISSING, evidence_ref="evid_1",
                       reason="no trusted ceiling"),
             errors.ADAPTER_MISSING),
            (Denied.of(code=RefusalCode.POLICY_SCOPE_UNVERIFIED, evidence_ref="evid_1",
                       reason="unverified provenance"),
             errors.OPERATION_UNKNOWN),
            (Denied.of(code=RefusalCode.APPROVAL_RESULT_UNKNOWN, evidence_ref="evid_1",
                       reason="native result unconfirmed"),
             errors.OPERATION_UNKNOWN),
            (Denied.of(code=RefusalCode.APPROVAL_STALE, evidence_ref="evid_1",
                       reason="stale grant"),
             errors.ASSIGNMENT_CONFLICT),
            (Denied.of(code=RefusalCode.APPROVAL_NOT_ACTIONABLE, evidence_ref="evid_1",
                       reason="the execution ended"),
             errors.ASSIGNMENT_CONFLICT),
            # A code this adapter has not been taught must stay unknown. Built
            # through the dataclass (not `.of`) because their normaliser would
            # refuse an undeclared spelling — which is exactly the point.
            (Denied(code="POLICY_FROM_A_FUTURE_VERSION", evidence_ref="evid_1",
                    reason="the adapter has no mapping for this"),
             errors.OPERATION_UNKNOWN),
            (UnknownApproval(reason="provider_unavailable"), errors.OPERATION_UNKNOWN),
            (QueryUnknown(reason="native_receipt_unobserved"), errors.OPERATION_UNKNOWN),
            (InvalidApproval(reason="approval_expired"), errors.ASSIGNMENT_CONFLICT),
            (VersionConflict(version=3), errors.ASSIGNMENT_CONFLICT),
            (AuthorizationDecision.of(
                native_request_id="n-1", operation_digest="a" * 64, tool="task",
                subject="u1", action="allow", reason="a decision record is not a ruling",
                policy_digest="q3-admin@1", expires_at=NOW + GRANT_TTL),
             errors.OPERATION_UNKNOWN),
            (None, errors.OPERATION_UNKNOWN),
            ("allowed", errors.OPERATION_UNKNOWN),
        ],
    )
    def test_every_answer_lands_on_a_declared_c5_code(self, outcome,
                                                      expected_code) -> None:
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               session_id=SESSION, execution_id=EXECUTION,
                               authorizer=ScriptedPort(outcome),
                               ceiling_provider=lambda: [admin_ceiling()],
                               conflict_types=(VersionConflict,),
                               clock=lambda: NOW)
        ruling = put(seam, revision(), "tool", "Bash", field_name="toolRefs.Bash")
        assert ruling.admitted is False
        assert ruling.code == expected_code
        assert ruling.standing is False
        # §C5: the refusal names the item-level field.
        refusal = ruling.refusal(revision())
        assert "toolRefs.Bash" in refusal.item_id

    def test_the_refusal_code_table_covers_their_whole_closed_vocabulary(self) -> None:
        covered = set(REFUSAL_CODE_TO_C5)
        assert covered >= {code.value for code in RefusalCode}, covered
        assert "policy_deny" in covered
        assert map_refusal_code("NOT_A_CODE") == errors.OPERATION_UNKNOWN
        assert map_refusal_code(RefusalCode.APPROVAL_STALE) == errors.ASSIGNMENT_CONFLICT
        assert map_refusal_code(None) == errors.OPERATION_UNKNOWN

    def test_the_decision_table_documents_every_outcome_class(self) -> None:
        assert DECISION_TO_C5["PendingApproval"] == errors.PERMISSION_EXCEEDS_CEILING
        assert DECISION_TO_C5["UnknownApproval"] == errors.OPERATION_UNKNOWN
        assert DECISION_TO_C5["VersionConflict"] == errors.ASSIGNMENT_CONFLICT
        assert set(DECISION_TO_C5) >= {
            "AllowedOnce", "PendingApproval", "UnknownApproval", "QueryUnknown",
            "InvalidApproval", "VersionConflict", "CorrelationConflict",
        }

    def test_a_correlation_conflict_from_the_store_is_a_conflict(self, tmp_path) -> None:
        from ordessa_permissions_backend import CorrelationConflict

        class _ConflictPort:
            def evaluate(self, **kwargs):
                raise CorrelationConflict("approval_1", "receipt names another request")

            def reconcile(self, approval_id, native_request_id):
                return QueryUnknown(reason="unavailable")

        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               session_id=SESSION, execution_id=EXECUTION,
                               authorizer=_ConflictPort(),
                               ceiling_provider=lambda: [admin_ceiling()],
                               conflict_types=(CorrelationConflict,))
        ruling = put(seam, revision(), "tool", "Read", field_name="toolRefs.Read")
        assert ruling.code == errors.ASSIGNMENT_CONFLICT

    def test_an_authorizer_that_explodes_never_admits(self) -> None:
        class _BrokenPort:
            def evaluate(self, **kwargs):
                raise ZeroDivisionError("boom")

            def reconcile(self, approval_id, native_request_id):
                raise ZeroDivisionError("boom")

        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               authorizer=_BrokenPort(),
                               ceiling_provider=lambda: [admin_ceiling()])
        ruling = put(seam, revision(), "tool", "Read", field_name="toolRefs.Read")
        assert not ruling.admitted
        assert ruling.code == errors.OPERATION_UNKNOWN


class TestIdentityIsTheirs:
    def test_the_approval_identity_is_minted_by_their_constructor(self, tmp_path) -> None:
        facts, _authorizer, seam = wire(tmp_path, intent=None)
        rev = revision()
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(rev, seam)
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        # Re-minted independently through their API, it must be the same id the
        # ruling carries and the row the store holds.
        digest = digest_of(seam, rev, "definition", "d1")
        approval_id = approval_id_for(
            operation_digest=digest,
            native_request_id=seam.native_request_id(seam.subject_for(rev),
                                                     "definition", "d1"))
        assert facts.peek(approval_id) is not None
        assert approval_id.startswith("approval_")

    def test_argument_digest_carries_identity_and_cannot_carry_a_payload(self) -> None:
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude")
        digest = seam.argument_digest(seam.subject_for(revision()), "tool", "Bash")
        assert ArgumentDigest.of(digest).value == digest  # their shape check passes
        assert len(digest) == 64
        with pytest.raises(PolicyRefusal):
            ArgumentDigest.of("rm -rf / --no-preserve-root")

    def test_the_default_scope_asked_for_is_once_never_bounded(self) -> None:
        scope = default_approval_scope()
        assert scope_to_record(scope) == {"kind": "once"}
        assert scope_to_record(BoundedApprovalScope()) == {
            "kind": "bounded", "until": "session_end", "environmentId": None}
        assert scope_to_record(scope) != scope_to_record(BoundedApprovalScope())

    def test_the_principal_is_the_verified_one_and_definition_text_cannot_change_it(
        self, tmp_path
    ) -> None:
        _facts, authorizer, _seam = wire(tmp_path, intent=intent_allowing("task"))
        spy = SpyPort(authorizer)
        seam = PermissionsSeam(
            principal=U1, server_scope=SCOPE, harness_id="claude",
            port_name=AUTHORIZER_PORT_NAME, session_id=SESSION,
            execution_id=EXECUTION, authorizer=spy,
            ceiling_provider=lambda: [admin_ceiling()],
            intent_provider=lambda: intent_allowing("task"), clock=lambda: NOW)
        # The revision *claims* to have been approved by somebody else; that
        # string is content, not identity, and must not reach the authority.
        rev = revision(source=dto.SourceApproval(
            origin="user-upload", origin_ref="x", content_digest=DIGEST,
            approved_by_principal="u:attacker", approved_at="2026-09-28T10:00:00+00:00"))
        admitted = ceiling.admit(rev, seam)
        assert admitted.effective_tools == frozenset()
        assert spy.evaluate_calls, "the port was never consulted"
        assert all(call["principal"] == "u1" for call in spy.evaluate_calls)
        assert not any("attacker" in str(call) for call in spy.evaluate_calls)

    def test_a_self_reported_project_is_refused_before_the_port_is_consulted(
        self, tmp_path
    ) -> None:
        _facts, authorizer, _seam = wire(tmp_path, intent=intent_allowing("task"))
        spy = SpyPort(authorizer)
        unverified = AuthorizationContext.issued_by_service(U1, SCOPE)
        with pytest.raises(errors.DomainError) as exc:
            PermissionsSeam.for_authorization(unverified, harness_id="claude",
                                      claimed_project_id="p-forged", authorizer=spy)
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert exc.value.item_id == "project_id"
        assert spy.evaluate_calls == []
        verified = AuthorizationContext.issued_by_service(U1, SCOPE, ProjectId("p1"))
        seam = PermissionsSeam.for_authorization(verified, harness_id="claude",
                                         port_name=AUTHORIZER_PORT_NAME,
                                         claimed_project_id="p1", authorizer=spy,
                                         session_id=SESSION, execution_id=EXECUTION,
                                         ceiling_provider=lambda: [admin_ceiling()],
                                         intent_provider=lambda: intent_allowing("task"),
                                         clock=lambda: NOW)
        assert seam.project_id == ProjectId("p1")
        assert seam.port_name == AUTHORIZER_PORT_NAME
        admitted = ceiling.admit(revision(), seam)
        assert admitted.effective_tools == frozenset()

    def test_a_foreign_one_shot_grant_is_a_conflict_and_spends_nothing(
        self, tmp_path
    ) -> None:
        facts, _authorizer, _seam = wire(tmp_path, intent=intent_allowing("task"))
        foreign = build_operation_request(
            principal=U1.id, server_instance_id=SCOPE.id, session_id=SESSION.id,
            native_session_id="native-sess-1", execution_id=EXECUTION,
            native_generation="assets-foreign", tool_key="task", target="definition:zz",
            argument_digest="d" * 64, native_request_id="native-foreign-1",
            ceilings=[admin_ceiling()], intent=intent_allowing("task"))
        foreign_approval_id = approval_id_for(
            operation_digest=foreign.operation_digest,
            native_request_id=foreign.native_request_id)
        facts.request(session_id=SESSION.id, execution_id=EXECUTION, request={
            "approvalId": foreign_approval_id, "sessionId": SESSION.id,
            "executionId": EXECUTION, "nativeRequestId": foreign.native_request_id,
            "operationDigest": foreign.operation_digest, "toolKey": "task",
            "target": "definition:zz", "ceilingRevision": foreign.ceiling_revision,
            "policyRevision": foreign.policy_revision,
            "nativeGeneration": foreign.native_generation,
            "requestedAt": NOW.isoformat(),
            "expiresAt": (NOW + GRANT_TTL).isoformat(), "version": 1,
        })
        grant = BoundGrant.of(approval_id=foreign_approval_id, request=foreign,
                              expires_at=NOW + GRANT_TTL)
        seam = PermissionsSeam(
            principal=U1, server_scope=SCOPE, harness_id="claude",
            port_name=AUTHORIZER_PORT_NAME, session_id=SESSION,
            execution_id=EXECUTION, authorizer=ScriptedPort(AllowedOnce(grant)),
            ceiling_provider=lambda: [admin_ceiling()],
            intent_provider=lambda: intent_allowing("task"), clock=lambda: NOW)
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(), seam)
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT
        assert "definition" in exc.value.item_id
        assert facts.grant_fields(foreign_approval_id)["consumed"] is False


class TestToolKeyMapping:
    def test_declared_tool_names_map_onto_their_closed_vocabulary(self) -> None:
        assert tool_key_for("tool", "Read") == "read"
        assert tool_key_for("tool", "bash") == "bash"
        assert tool_key_for("tool", "WebFetch") == "webfetch"
        assert tool_key_for("tool", "external_directory") == "external_directory"
        assert tool_key_for("skill", "any-skill") == "skill"
        assert tool_key_for("model", "gpt-x") == "task"
        assert tool_key_for("mcp", "srv") == "task"
        assert tool_key_for("permission_mode", "bypassPermissions") == "task"
        assert tool_key_for("isolation", "sandbox=off") == "task"

    def test_an_unknown_name_raises_their_typed_refusal_not_a_guess(self) -> None:
        with pytest.raises(PolicyRefusal) as exc:
            tool_key_for("tool", "Grep")
        assert exc.value.code == RefusalCode.PERMISSION_UNKNOWN_TOOL.value

    def test_an_item_kind_with_no_mapping_is_refused_by_the_seam(self) -> None:
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               authorizer=ScriptedPort(None),
                               ceiling_provider=lambda: [admin_ceiling()])
        ruling = put(seam, revision(), "mystery", "x", field_name="mystery")
        assert ruling.code == errors.OPERATION_UNKNOWN


class TestPortNameAndConflictTypesArriveByInjection:
    """SR-15 option 3, the Q3 side: the seam imports nothing from Q5's
    provider package, so the port *name* and the conflict *types* are wiring
    inputs the composition injects. The name has a documented default that only
    ever *phrases* a ruling (it resolves nothing — the authority itself must
    still be injected); the conflict types default to none, and that default is
    fail-closed: an unrecognised conflict is `OPERATION_UNKNOWN`, never the
    silent 'the authority did not object'."""

    def test_an_absent_port_name_is_the_documented_name_and_resolves_nothing(
        self
    ) -> None:
        """SR-15 option 3, as ruled: the name has a documented default, the
        *authority* does not. Nothing injected means the seam speaks
        `AUTHORIZER_PORT_NAME`, and that string puts a ruling to no port — an
        uninjected authority is refused and never reached."""
        port = ScriptedPort(UnknownApproval(reason="would-be-ignored"))
        without_authority = PermissionsSeam(
            principal=U1, server_scope=SCOPE, harness_id="claude",
            session_id=SESSION, execution_id=EXECUTION,
            ceiling_provider=lambda: [admin_ceiling()], clock=lambda: NOW)
        assert without_authority.port_name == AUTHORIZER_PORT_NAME, (
            "the documented default is the module literal, not a value invented "
            "per message")
        assert not without_authority.is_available()
        ruling = put(without_authority, revision(), "definition", "d1",
                     field_name="definition")
        assert not ruling.admitted
        assert ruling.code == errors.ADAPTER_MISSING
        assert AUTHORIZER_PORT_NAME in ruling.detail, ruling.detail

        named = PermissionsSeam(principal=U1, server_scope=SCOPE,
                                harness_id="claude", port_name="   ",
                                session_id=SESSION, execution_id=EXECUTION,
                                ceiling_provider=lambda: [admin_ceiling()])
        refused = put(named, revision(), "definition", "d1", field_name="definition")
        assert refused.code == errors.ADAPTER_MISSING and not refused.admitted

        # The default name changes no verdict: with an authority whose answer is
        # "unknown", the seam still refuses rather than reading the fallback as
        # an objection-less port.
        unknown = PermissionsSeam(principal=U1, server_scope=SCOPE,
                                  harness_id="claude", session_id=SESSION,
                                  execution_id=EXECUTION, authorizer=port,
                                  ceiling_provider=lambda: [admin_ceiling()],
                                  clock=lambda: NOW)
        verdict = put(unknown, revision(), "definition", "d1", field_name="definition")
        assert not verdict.admitted and verdict.code == errors.OPERATION_UNKNOWN

    def test_a_blank_port_name_is_not_a_port_name(self) -> None:
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name="   ",
                               authorizer=ScriptedPort(None),
                               ceiling_provider=lambda: [admin_ceiling()])
        assert not seam.is_available()
        ruling = put(seam, revision(), "definition", "d1", field_name="definition")
        assert ruling.code == errors.ADAPTER_MISSING

    def test_refusals_quote_the_injected_name_not_the_documented_literal(
        self, tmp_path
    ) -> None:
        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name="custom.authorizer@9",
                               ceiling_provider=lambda: [admin_ceiling()])
        ruling = put(seam, revision(), "definition", "d1", field_name="definition")
        assert ruling.code == errors.ADAPTER_MISSING
        assert "custom.authorizer@9" in ruling.detail
        assert AUTHORIZER_PORT_NAME not in ruling.detail, (
            "the documented literal is refusing where the injected name should "
            "be — it must stay prose, never a resolution key")

    def test_an_unrecognised_authorizer_exception_is_operation_unknown(
        self, tmp_path
    ) -> None:
        class _ExplodingPort:
            def evaluate(self, **kwargs):
                raise RuntimeError("authority exploded")

            def reconcile(self, approval_id, native_request_id):
                raise RuntimeError("authority exploded")

        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               authorizer=_ExplodingPort(),
                               ceiling_provider=lambda: [admin_ceiling()],
                               conflict_types=(KeyError,))
        ruling = put(seam, revision(), "tool", "Read", field_name="toolRefs.Read")
        assert not ruling.admitted
        assert ruling.code == errors.OPERATION_UNKNOWN, (
            "an unrecognised failure must never read as 'no objection'")

    def test_a_backend_conflict_is_not_recognised_until_injected(self) -> None:
        class _CorrelatingPort:
            def evaluate(self, **kwargs):
                raise CorrelationConflict("approval_1", "receipt names another request")

        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               authorizer=_CorrelatingPort(),
                               ceiling_provider=lambda: [admin_ceiling()])
        ruling = put(seam, revision(), "tool", "Read", field_name="toolRefs.Read")
        assert ruling.code == errors.OPERATION_UNKNOWN, (
            "the empty default must not smuggle the mapping back in")

    def test_injected_conflict_exception_maps_to_assignment_conflict(
        self, tmp_path
    ) -> None:
        class InjectedCorrelation(Exception):
            def __init__(self, detail: str) -> None:
                super().__init__(detail)
                self.detail = detail

        class _ConflictingPort:
            def evaluate(self, **kwargs):
                raise InjectedCorrelation("receipt names another request")

        seam = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                               port_name=AUTHORIZER_PORT_NAME,
                               authorizer=_ConflictingPort(),
                               ceiling_provider=lambda: [admin_ceiling()],
                               conflict_types=(InjectedCorrelation,))
        ruling = put(seam, revision(), "tool", "Read", field_name="toolRefs.Read")
        assert not ruling.admitted
        assert ruling.code == errors.ASSIGNMENT_CONFLICT
        assert "correlation/version conflict" in ruling.detail
        assert "InjectedCorrelation" in ruling.detail, (
            "the refusal must name which injected type it recognised: " + ruling.detail)

    def test_injected_conflict_outcome_maps_to_assignment_conflict(
        self, tmp_path
    ) -> None:
        class InjectedVersionOutcome:  # not an exception: an outcome object
            reason = "approval_version_conflict"

        def seam_with(**extra) -> PermissionsSeam:
            return PermissionsSeam(principal=U1, server_scope=SCOPE,
                                   harness_id="claude", port_name=AUTHORIZER_PORT_NAME,
                                   authorizer=ScriptedPort(InjectedVersionOutcome()),
                                   ceiling_provider=lambda: [admin_ceiling()],
                                   **extra)

        injected = seam_with(conflict_types=(InjectedVersionOutcome,))
        assert put(injected, revision(), "tool", "Read",
                   field_name="toolRefs.Read").code == errors.ASSIGNMENT_CONFLICT
        untaught = seam_with()
        assert put(untaught, revision(), "tool", "Read",
                   field_name="toolRefs.Read").code == errors.OPERATION_UNKNOWN

    def test_the_live_conflict_table_is_built_from_the_injection_alone(self) -> None:
        """The anti-vacuity pair for the two tests above, at table level.

        `DECISION_TO_C5` *documents* the mapping; the table a seam consults is
        derived from `conflict_types` and nothing else — so restoring a
        hard-coded row set (the shape the deleted backend import used to give)
        is red here even while every behavioural test above still passes.
        """
        class Injected(Exception):
            pass

        assert seam_module.conflict_decision_table((Injected,)) == {
            "Injected": errors.ASSIGNMENT_CONFLICT}
        assert seam_module.conflict_decision_table(()) == {}, (
            "an empty injection must yield an empty table, not a remembered one")
        # a bare string is not a type: it cannot widen the recognised set
        assert seam_module.conflict_decision_table(
            (Injected, "VersionConflict")) == {"Injected": errors.ASSIGNMENT_CONFLICT}

        taught = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude",
                                 conflict_types=(Injected,))
        untaught = PermissionsSeam(principal=U1, server_scope=SCOPE, harness_id="claude")
        assert taught.conflict_table == {"Injected": errors.ASSIGNMENT_CONFLICT}
        assert untaught.conflict_table == {}
        assert set(taught.conflict_table.values()) <= set(DECISION_TO_C5.values()), (
            "an injected conflict must land on a declared §C5 code")
        assert {"VersionConflict", "CorrelationConflict"} <= set(DECISION_TO_C5)

    def test_the_seam_module_never_names_the_backend_package(self) -> None:
        source = inspect.getsource(seam_module)
        assert "ordessa_permissions_backend" not in source, (
            "AGENTS.md rule 3: Q5's provider package is not this plugin's "
            "contract; the port name and conflict types arrive by injection")

    def test_the_seam_imports_with_the_backend_blocked(self) -> None:
        class _BlockBackend:
            def __init__(self) -> None:
                self.hits: list[str] = []

            def find_spec(self, fullname, path=None, target=None):
                if fullname == "ordessa_permissions_backend" or fullname.startswith(
                        "ordessa_permissions_backend."):
                    self.hits.append(fullname)
                    raise ImportError(f"blocked for the isolation probe: {fullname}")
                return None

        blocker = _BlockBackend()
        snapshot = dict(sys.modules)
        sys.modules.pop("ordessa_assets_subagents.permissions_seam", None)
        sys.meta_path.insert(0, blocker)
        try:
            mod = importlib.import_module("ordessa_assets_subagents.permissions_seam")
            assert blocker.hits == [], (
                "the seam re-imported Q5's backend while loading: "
                f"{blocker.hits}")
            sig = inspect.signature(mod.PermissionsSeam.__init__)
            assert "port_name" in sig.parameters and "conflict_types" in sig.parameters
            # capability: the blocker really bites, so a hits==[] above is proof
            sys.modules.pop("ordessa_permissions_backend", None)
            with pytest.raises(ImportError, match="blocked"):
                importlib.import_module("ordessa_permissions_backend")
            assert blocker.hits == ["ordessa_permissions_backend"]
        finally:
            if blocker in sys.meta_path:
                sys.meta_path.remove(blocker)
            sys.modules.clear()
            sys.modules.update(snapshot)
