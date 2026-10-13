"""Synthetic authority-port acceptance for review application commands.

These adapters exercise use-case ordering only; they are not production
authentication, reviewer-admission, or control implementations.
"""
from contextlib import contextmanager
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from ordessa_engineering.adapters.persistence.sqlite import engineering_library as storage
from ordessa_engineering.adapters.persistence.sqlite.blob_bytes import reference_for
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.usecases.artifacts import ArtifactUseCases
from ordessa_engineering.application.contracts.commands import CommandContext, ReadSet
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.reviews.models import ReviewControlExpectation, ReviewSetExpectation, ReviewSetKey
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.reviews.targets import (Target, TargetSet)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.domain.reviews.identity import (RecordIdentity)
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy,
    CheckKey,
    CheckPolicy,
    CriterionSetRef,
    CurrentReviewTrust,
    Observation,
    ReviewPlan,
    ReviewRecord,
    ReviewRequirement,
    observations_digest,
)
from ordessa_engineering.domain.reviews.evidence import (VerifiedReviewerEvidence)


LIBRARY_ID = "test.review-usecases"
CREATED_AT = "2026-10-09T12:00:00.000000Z"
TEST_ACTOR = ActorRef("test-human", "human", "synthetic-test-issuer")
REVIEWER = ActorRef("test-reviewer", "human", "synthetic-review-issuer")
RAW_RESPONSE = b'{"answer":"synthetic"}'


class SyntheticAccess:
    """Test-only allow adapter; ActorRef fields do not authorize production use."""

    def __init__(self):
        self.calls = []

    def require(self, context, operation):
        self.calls.append((context, operation))


class SyntheticAdmission:
    """Test-only review evidence source with controllable race hooks."""

    def __init__(self, library, blobs):
        self.library = library
        self.blobs = blobs
        self.plan_calls = 0
        self.verify_calls = 0
        self.trust_calls = 0
        self.method_guard_depth = 0
        self.trust_guard_depth = 0
        self.on_verify = None
        self.on_trust = None
        self.verdicts = {}
        self.inactive_review_ids = set()
        self.last_raw_response_ref = None
        self.bad_raw_digest = False
        self.other_plan = None
        self.revoke_trust = False

    @contextmanager
    def guard_plan(self, context, plan):
        assert not self.library._connection.in_transaction
        self.plan_calls += 1
        self.method_guard_depth += 1
        try:
            if plan.review_id in self.inactive_review_ids:
                raise ApplicationError("METHOD_UNAVAILABLE")
            yield object()
        finally:
            try:
                if not self.library._closed:
                    assert not self.library._connection.in_transaction
                    assert self.library._connection.execute(
                        "SELECT COUNT(*) FROM eng_review_plans WHERE review_id=?",
                        (plan.review_id,),
                    ).fetchone() == (1,)
            finally:
                self.method_guard_depth -= 1

    def verify_response(self, context, plan, request, raw_response_ref):
        assert not self.library._connection.in_transaction
        assert type(raw_response_ref) is BlobRef
        raw_response = self.blobs.read_verified(raw_response_ref)
        self.last_raw_response_ref = raw_response_ref
        self.verify_calls += 1
        callback, self.on_verify = self.on_verify, None
        if callback is not None:
            callback()
        selected_plan = self.other_plan or plan
        verdict = self.verdicts.get(selected_plan.review_id, "pass")
        observation = Observation(selected_plan.check_keys[0], verdict, (), "Synthetic evidence.")
        response_digest = hashlib.sha256(raw_response).hexdigest()
        raw_ref = raw_response_ref
        if self.bad_raw_digest:
            response_digest = "f" * 64
            # This remains a valid v2 record value so rejection exercises the
            # application binding check, not a constructor failure.
            raw_ref = BlobRef(Digest("sha256", response_digest), raw_response_ref.byte_length,
                              raw_response_ref.media_type, raw_response_ref.storage_object_id)
        evidence = VerifiedReviewerEvidence(
            scope=selected_plan.scope,
            reviewer=REVIEWER,
            roles=("reviewer",),
            verifier_id="synthetic-verifier",
            verifier_version="1",
            trust_version=7,
            request_digest=selected_plan.request_digest,
            raw_response_digest=Digest("sha256", response_digest),
            observations_digest=observations_digest((observation,)),
            capability_digest=Digest("sha256", "c" * 64),
        )
        return ReviewRecord(
            identity=RecordIdentity(context.scope, selected_plan.review_id,
                                    context.received_at, TEST_ACTOR, schema_version=2),
            plan=selected_plan,
            reviewer_evidence=evidence,
            observations=(observation,),
            raw_response_ref=raw_ref,
        )

    @contextmanager
    def guard_trust(self, context, records):
        assert not self.library._connection.in_transaction
        self.trust_calls += 1
        self.trust_guard_depth += 1
        callback, self.on_trust = self.on_trust, None
        try:
            if callback is not None:
                callback()
            current = tuple(
                CurrentReviewTrust(
                    record.ref,
                    record.reviewer_evidence.verifier_id,
                    record.reviewer_evidence.trust_version + (1 if self.revoke_trust else 0),
                )
                for record in records
            )
            yield current
        finally:
            try:
                # record_response must retain the trust guard through the durable
                # command/review commit, not just through the preflight check.
                if records and not self.library._closed and all(
                    record.plan.review_id in self._recorded_ids() for record in records
                ):
                    assert not self.library._connection.in_transaction
            finally:
                self.trust_guard_depth -= 1

    def _recorded_ids(self):
        return {row[0] for row in self.library._connection.execute(
            "SELECT review_id FROM eng_reviews")}


class SyntheticControl:
    """Test-only evidence port for terminal review control changes."""

    def __init__(self, library):
        self.library = library
        self.calls = []

    @contextmanager
    def guard_control(self, context, expectations, *, state, reason, replacement_ref):
        assert not self.library._connection.in_transaction
        self.calls.append((context, expectations, state, reason, replacement_ref))
        yield (Digest("sha256", "d" * 64),)


class CountingBlobStore:
    """Test-only call counter around the actual Library-backed blob adapter."""

    def __init__(self, library):
        self.store = SQLiteBlobStore(library)
        self.authority_id = self.store.authority_id
        self.put_calls = 0
        self.read_calls = 0

    def put_verified(self, raw_bytes, expected_digest, media_type):
        self.put_calls += 1
        return self.store.put_verified(raw_bytes, expected_digest, media_type)

    def read_verified(self, ref):
        self.read_calls += 1
        return self.store.read_verified(ref)


@pytest.fixture
def environment(tmp_path: Path):
    path = (tmp_path / "review-usecases.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=6)
    factory = SQLiteUoWFactory(library)
    access = SyntheticAccess()
    blobs = CountingBlobStore(library)
    admission = SyntheticAdmission(library, blobs)
    control = SyntheticControl(library)
    try:
        yield library, factory, access, admission, control
    finally:
        library.close()


def _scope(project_id="project-1"):
    return Scope("realm-1", project_id)


def _context(scope, request_id):
    return CommandContext(scope, "principal-1", TEST_ACTOR, request_id, CREATED_AT, "trace-1")


def _create_source(factory, scope):
    artifacts = ArtifactUseCases(factory, SyntheticAccess())
    result = artifacts.create({
        "kind": "plan",
        "initial": {
            "media_type": "application/json",
            "schema_id": "urn:test:review-subject",
            "inline_value": {"source": "synthetic"},
        },
    }, _context(scope, "source-artifact"))
    value = result.result["revision_ref"]
    return ArtifactRevisionRef(
        value["realm_id"], value["project_id"], value["artifact_id"],
        value["revision_id"], Digest(**value["digest"]),
    )


def _plan(scope, subject, review_id="review-1"):
    target = Target("primary", subject)
    target_set = TargetSet((target,))
    key = CheckKey(target, "criterion-1")
    requirement = ReviewRequirement(
        scope=scope,
        requirement_id="requirement-1",
        requirement_version=1,
        purpose="quality",
        expected_targets=target_set,
        method_ref=MethodRef("method-1", "1.0", 1, Digest("sha256", "a" * 64)),
        criterion_set_ref=CriterionSetRef("criteria-1", 1, Digest("sha256", "b" * 64)),
        required_check_keys=(key,),
        eligible_reviewer_roles=("reviewer",),
        phase_key="phase-1",
    )
    policy = CheckPolicy(key, required=True, blocking=True)
    return ReviewPlan(review_id, requirement, (policy,), AggregationPolicy(), ("reviewer",))


_USE_ADMISSION_BLOBS = object()


def _review_usecases(factory, access, admission, control=None, *, blobs=_USE_ADMISSION_BLOBS):
    selected_blobs = (
        (admission.blobs if admission is not None else CountingBlobStore(factory.library))
        if blobs is _USE_ADMISSION_BLOBS else blobs
    )
    return ReviewUseCases(factory, access, admission, control, blobs=selected_blobs)


def _plan_review(usecases, plan, scope, request_id=None):
    return usecases.plan(plan, _context(scope, request_id or f"plan-{plan.review_id}"))


def _record_review(usecases, plan, scope, *, request_id=None, raw_response=RAW_RESPONSE):
    return usecases.record_response(
        plan.review_id, raw_response,
        _context(scope, request_id or f"record-{plan.review_id}"),
        expected_request_version=0, fence=1,
    )


def test_facade_exact_review_history_is_not_a_current_trust_gate(environment):
    import asyncio
    from ordessa_engineering.application.api.service import EngineeringService
    library, factory, access, admission, control = environment
    scope = _scope()
    plan = _plan(scope, _create_source(factory, scope))
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    _record_review(usecases, plan, scope)
    historical = usecases.query_set(plan.requirement, _context(scope, "history-source")).reviews[0]
    from dataclasses import asdict
    admission.revoke_trust = True
    before = (admission.verify_calls, admission.trust_calls, _counts(library))
    value = asyncio.run(EngineeringService(factory, access).query("engineering.references.resolve",
        {"ref": asdict(historical.record.ref)}, _context(scope, "history-read")))
    assert value == historical
    assert (admission.verify_calls, admission.trust_calls, _counts(library)) == before
    with pytest.raises(ApplicationError, match="UNTRUSTED_REVIEWER"):
        usecases.gate(plan.requirement, _context(scope, "current-gate"))


def test_public_service_reads_original_request_plan_with_scope_and_access(environment):
    import asyncio
    from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service
    library, factory, access, admission, control = environment
    scope = _scope()
    plan = _plan(scope, _create_source(factory, scope))
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    service = build_engineering_service(factory, EngineeringPorts(access))
    ctx = _context(scope, "request-read")
    before = _counts(library)
    result = asyncio.run(service.query("engineering.reviews.get_request", {"review_id": plan.review_id}, ctx))
    with factory.begin(scope, "read") as uow:
        assert result == {"request": uow.reviews.get_request(plan.review_id),
                          "plan": uow.reviews.get_plan(plan.review_id)}
    assert access.calls[-1] == (ctx, "engineering.reviews.get_request")
    assert _counts(library) == before
    with pytest.raises(ApplicationError, match="NOT_FOUND"):
        asyncio.run(service.query("engineering.reviews.get_request", {"review_id": plan.review_id},
                                  _context(_scope("other-project"), "cross-scope")))
    with pytest.raises(ApplicationError, match="INVALID_INPUT"):
        asyncio.run(service.query("engineering.reviews.get_request", {"review_id": plan.review_id, "scope": {}}, ctx))


def _counts(library):
    return {
        table: library._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("eng_review_plans", "eng_review_requests", "eng_reviews",
                      "eng_review_controls", "eng_commands")
    }


@pytest.mark.parametrize(("verdict", "satisfied", "code"), [
    ("pass", True, "SATISFIED"),
    ("fail", False, "REVIEW_FAILED"),
])
def test_plan_record_query_and_gate_cover_complete_pass_and_fail(
    environment, verdict, satisfied, code,
):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    admission.verdicts[plan.review_id] = verdict
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    result = _record_review(usecases, plan, scope)
    assert result.status == "completed"
    assert admission.verify_calls == 1
    snapshot = usecases.query_set(plan.requirement, _context(scope, "query-pass-fail"))
    assert snapshot.set_version == 1
    assert len(snapshot.reviews) == 1
    assert snapshot.reviews[0].record.complete
    assert snapshot.reviews[0].record.verdict == verdict
    stored_record = snapshot.reviews[0].record
    assert stored_record.identity.schema_version == 2
    assert stored_record.raw_response_ref == admission.last_raw_response_ref
    assert admission.blobs.read_verified(stored_record.raw_response_ref) == RAW_RESPONSE
    gate = usecases.gate(plan.requirement, _context(scope, "gate-pass-fail"))
    assert gate.satisfied is satisfied
    assert gate.code == code
    assert gate.used_review_refs == (snapshot.reviews[0].record.ref,)
    assert _counts(library)["eng_reviews"] == 1


@pytest.mark.parametrize("missing", ["access", "plan_admission", "record_admission"])
def test_missing_access_or_admission_rejects_without_review_facts(environment, missing):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    if missing == "record_admission":
        _plan_review(_review_usecases(factory, access, admission, control), plan, scope)
    usecases = _review_usecases(
        factory, None if missing == "access" else access,
        None if missing in {"plan_admission", "record_admission"} else admission,
        control,
    )
    before = _counts(library)
    with pytest.raises(ApplicationError) as caught:
        if missing == "record_admission":
            _record_review(usecases, plan, scope)
        else:
            _plan_review(usecases, plan, scope)
    assert caught.value.code == ("ACCESS_AUTHORITY_UNAVAILABLE" if missing == "access"
                                 else "REVIEW_AUTHORITY_UNAVAILABLE")
    assert _counts(library) == before
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (0,)


def test_missing_control_port_does_not_mutate_existing_review_facts(environment):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    _record_review(usecases, plan, scope)
    before = _counts(library)
    no_control = _review_usecases(factory, access, admission, None)
    expectation = ReviewControlExpectation(
        usecases.query_set(plan.requirement, _context(scope, "control-query")).reviews[0].record.ref, 0)
    with pytest.raises(ApplicationError) as caught:
        no_control.control_reviews((expectation,), _context(scope, "missing-control"),
                                   state="voided", reason="Synthetic control.")
    assert caught.value.code == "REVIEW_CONTROL_AUTHORITY_UNAVAILABLE"
    assert _counts(library) == before


@pytest.mark.parametrize("bad_evidence", ["raw_digest", "plan", "revoked_trust"])
def test_invalid_or_revoked_admission_does_not_persist_review_fact(environment, bad_evidence):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    if bad_evidence == "raw_digest":
        admission.bad_raw_digest = True
    elif bad_evidence == "plan":
        admission.other_plan = _plan(scope, subject, "different-review")
    else:
        admission.revoke_trust = True
    with pytest.raises(ApplicationError) as caught:
        _record_review(usecases, plan, scope)
    assert caught.value.code == ("UNTRUSTED_REVIEWER" if bad_evidence == "revoked_trust"
                                 else "REVIEW_STALE")
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (0,)
    assert library._connection.execute("SELECT COUNT(*) FROM eng_review_controls").fetchone() == (0,)
    with pytest.raises(ApplicationError) as missing_command:
        usecases.get_command(_context(scope, f"record-{plan.review_id}"))
    assert missing_command.value.code == "COMMAND_NOT_FOUND"


def test_record_guard_acquisition_and_response_verification_are_outside_database_transactions(
    environment, monkeypatch,
):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)

    connection_type = type(library._connection)
    original_commit = connection_type.commit
    observed_business_commits = []

    def commit_requires_live_trust_guard(connection):
        is_record_command = connection.execute(
            "SELECT COUNT(*) FROM eng_commands WHERE operation='engineering.reviews.record' "
            "AND request_id=?", (f"record-{plan.review_id}",),
        ).fetchone()[0] == 1
        if is_record_command:
            assert admission.method_guard_depth == 1
            assert admission.trust_guard_depth == 1
            observed_business_commits.append(True)
        return original_commit(connection)

    monkeypatch.setattr(connection_type, "commit", commit_requires_live_trust_guard)
    record = _record_review(usecases, plan, scope)
    assert record.status == "completed"
    assert admission.verify_calls == 1
    assert admission.trust_calls == 1
    assert admission.method_guard_depth == 0
    assert admission.trust_guard_depth == 0
    assert observed_business_commits == [True]
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)


def test_same_key_replay_skips_verification_and_insert_and_conflicts_on_operation_or_raw_change(
    environment,
):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    plan_context = _context(scope, "shared-idempotency-key")
    usecases.plan(plan, plan_context)
    record_context = _context(scope, "record-idempotency-key")
    first = usecases.record_response(plan.review_id, RAW_RESPONSE, record_context,
                                     expected_request_version=0, fence=1)
    calls = admission.verify_calls
    captures = admission.blobs.put_calls
    replay = usecases.record_response(plan.review_id, RAW_RESPONSE, record_context,
                                      expected_request_version=0, fence=1)
    assert replay == first
    assert admission.verify_calls == calls == 1
    assert admission.blobs.put_calls == captures == 1
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)
    with pytest.raises(ApplicationError) as raw_conflict:
        usecases.record_response(plan.review_id, b'{"answer":"changed"}', record_context,
                                 expected_request_version=0, fence=1)
    assert raw_conflict.value.code == "REQUEST_IDENTITY_CONFLICT"
    with pytest.raises(ApplicationError) as operation_conflict:
        usecases.plan(plan, record_context)
    assert operation_conflict.value.code == "REQUEST_IDENTITY_CONFLICT"
    assert admission.verify_calls == calls
    assert admission.blobs.put_calls == captures
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)


@pytest.mark.parametrize("blob_binding", ["missing", "foreign_authority"])
def test_missing_or_cross_authority_blob_store_refuses_before_capture_or_verification(
    environment, tmp_path, blob_binding,
):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    _plan_review(_review_usecases(factory, access, admission, control), plan, scope)
    before = _counts(library)
    alternate_library = None
    selected_blobs = None
    if blob_binding == "missing":
        usecases = _review_usecases(factory, access, admission, control, blobs=None)
    else:
        alternate_library = EngineeringLibrary.create(
            (tmp_path / "foreign-blob-authority.sqlite").resolve(),
            library_id="test.foreign-blob-authority", schema_version=6,
        )
        selected_blobs = CountingBlobStore(alternate_library)
        usecases = _review_usecases(factory, access, admission, control, blobs=selected_blobs)
    try:
        with pytest.raises(ApplicationError) as caught:
            _record_review(usecases, plan, scope)
        assert caught.value.code == "BLOB_AUTHORITY_UNAVAILABLE"
        assert admission.verify_calls == 0
        assert admission.blobs.put_calls == 0
        assert selected_blobs is None or selected_blobs.put_calls == 0
        assert _counts(library) == before
        assert library._connection.execute(
            "SELECT COUNT(*) FROM eng_commands WHERE operation='engineering.reviews.record'").fetchone() == (0,)
    finally:
        if alternate_library is not None:
            alternate_library.close()


@pytest.mark.parametrize("operation", ["query_set", "gate"])
def test_tampered_raw_blob_corrupts_the_complete_review_set_and_gate(environment, operation):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    _record_review(usecases, plan, scope)
    snapshot = usecases.query_set(plan.requirement, _context(scope, "before-blob-tamper"))
    ref = snapshot.reviews[0].record.raw_response_ref
    with library.transaction() as connection:
        connection.execute("UPDATE eng_method_blobs SET body=? WHERE digest=?",
                           (b"X" * ref.byte_length, ref.digest.hex))

    with pytest.raises(ApplicationError) as caught:
        if operation == "query_set":
            usecases.query_set(plan.requirement, _context(scope, "tampered-query"))
        else:
            usecases.gate(plan.requirement, _context(scope, "tampered-gate"))
    assert caught.value.code == "RECORD_CORRUPT"
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)
    assert library._connection.execute("SELECT COUNT(*) FROM eng_commands WHERE operation='engineering.reviews.record'").fetchone() == (1,)


def test_gate_refuses_active_schema1_review_without_a_durable_raw_response(environment):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    raw_ref = admission.blobs.put_verified(
        RAW_RESPONSE, Digest("sha256", hashlib.sha256(RAW_RESPONSE).hexdigest()),
        "application/octet-stream",
    )
    context = _context(scope, "synthetic-v1-review")
    with factory.begin(scope, "read") as uow:
        frozen_plan = uow.reviews.get_plan(plan.review_id)
        request = uow.reviews.get_request(plan.review_id)
    admitted = admission.verify_response(context, frozen_plan, request, raw_ref)
    legacy = replace(
        admitted,
        identity=replace(admitted.identity, schema_version=1),
        raw_response_ref=None,
    )
    with factory.begin(scope) as uow:
        uow.reviews.insert_review(legacy, expected_request_version=0, fence=1)
        uow.commit()

    stored = usecases.query_set(plan.requirement, _context(scope, "query-v1-review"))
    assert len(stored.reviews) == 1
    assert stored.reviews[0].record.identity.schema_version == 1
    assert stored.reviews[0].record.raw_response_ref is None
    before = _counts(library)
    with pytest.raises(ApplicationError) as caught:
        usecases.gate(plan.requirement, _context(scope, "gate-v1-review"))
    assert caught.value.code == "REVIEW_RAW_RESPONSE_REQUIRED"
    assert _counts(library) == before
    assert admission.method_guard_depth == 0
    assert admission.trust_guard_depth == 0


def test_withdrawal_during_verification_is_journaled_and_late_review_is_rejected(environment):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    admission.on_verify = lambda: usecases.withdraw(
        plan.review_id, _context(scope, "concurrent-withdraw"),
        expected_request_version=0, fence=1)

    result = _record_review(usecases, plan, scope)
    assert result.status == "rejected"
    assert result.result == {"code": "REVIEW_REQUEST_CHANGED"}
    assert usecases.get_command(_context(scope, f"record-{plan.review_id}")) == result
    assert library._connection.execute("SELECT state,fence,version FROM eng_review_requests").fetchone() == (
        "withdrawn", 2, 1)
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (0,)
    assert library._connection.execute("SELECT COUNT(*) FROM eng_review_controls").fetchone() == (0,)


def test_concurrent_same_key_different_raw_completion_wins_without_second_review_fact(environment):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)

    racer_library = EngineeringLibrary.open(library.path, library_id=LIBRARY_ID)
    racer_factory = SQLiteUoWFactory(racer_library)
    racer_usecases = _review_usecases(racer_factory, access, admission, control)
    context = _context(scope, "same-key-race")
    racer_response = b'{"answer":"racer"}'
    racer_results = []

    def complete_racer_first():
        racer_results.append(racer_usecases.record_response(
            plan.review_id, racer_response, context,
            expected_request_version=0, fence=1,
        ))

    # verify_response clears this hook before invoking it, so the inner call
    # completes once and the outer attempt reaches the journal's uniqueness
    # check only after that durable result exists.
    admission.on_verify = complete_racer_first
    try:
        with pytest.raises(ApplicationError) as conflict:
            usecases.record_response(
                plan.review_id, RAW_RESPONSE, context,
                expected_request_version=0, fence=1,
            )
        assert conflict.value.code == "REQUEST_IDENTITY_CONFLICT"
        assert len(racer_results) == 1 and racer_results[0].status == "completed"
        assert usecases.get_command(context) == racer_results[0]
        journal_rows = library._connection.execute(
            "SELECT operation_id FROM eng_commands WHERE operation='engineering.reviews.record' "
            "AND request_id=?", (context.request_id,)).fetchall()
        assert journal_rows == [(racer_results[0].operation_id,)]
        assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)
        assert library._connection.execute("SELECT COUNT(*) FROM eng_review_controls").fetchone() == (1,)
        assert library._connection.execute("SELECT set_version FROM eng_review_sets").fetchone() == (1,)
        snapshot = usecases.query_set(plan.requirement, _context(scope, "race-query"))
        assert len(snapshot.reviews) == 1
        assert snapshot.reviews[0].record.reviewer_evidence.raw_response_digest == Digest(
            "sha256", hashlib.sha256(racer_response).hexdigest())
        assert admission.verify_calls == 2
    finally:
        racer_library.close()


@pytest.mark.parametrize("changed_field", ["phase_key", "eligible_reviewer_roles"])
def test_query_empty_review_set_rejects_changed_frozen_requirement(environment, changed_field):
    _library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    empty = usecases.query_set(plan.requirement, _context(scope, "query-original-empty"))
    assert empty.reviews == () and empty.set_version == 0

    if changed_field == "phase_key":
        changed = replace(plan.requirement, phase_key="other-phase")
    else:
        changed = replace(plan.requirement, eligible_reviewer_roles=("reviewer", "observer"))
    with pytest.raises(ApplicationError) as caught:
        usecases.query_set(changed, _context(scope, f"query-changed-{changed_field}"))
    assert caught.value.code == "REQUIREMENT_CONFLICT"
    assert usecases.query_set(plan.requirement, _context(scope, "query-still-empty")).reviews == ()


def test_gate_rechecks_set_version_after_trust_guard_and_rejects_stale_snapshot(environment):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    first_plan = _plan(scope, subject, "review-first")
    second_plan = _plan(scope, subject, "review-second")
    admission.verdicts[second_plan.review_id] = "fail"
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, first_plan, scope)
    _record_review(usecases, first_plan, scope)
    trust_calls_before_gate = admission.trust_calls
    admission.on_trust = lambda: (
        _plan_review(usecases, second_plan, scope),
        _record_review(usecases, second_plan, scope),
    )

    with pytest.raises(ApplicationError) as caught:
        usecases.gate(first_plan.requirement, _context(scope, "gate-stale-set"))
    assert caught.value.code == "REVIEW_SET_CHANGED"
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (2,)
    assert admission.on_trust is None
    assert admission.trust_calls == trust_calls_before_gate + 2
    records = usecases.query_set(first_plan.requirement, _context(scope, "stale-set-record-check"))
    assert {item.record.verdict for item in records.reviews} == {"pass", "fail"}


@pytest.mark.parametrize("operation", ["record", "gate"])
def test_inactive_method_guard_rejects_record_or_gate_without_new_facts(environment, operation):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    if operation == "gate":
        _record_review(usecases, plan, scope)
    before = _counts(library)
    admission.inactive_review_ids.add(plan.review_id)

    with pytest.raises(ApplicationError) as caught:
        if operation == "record":
            _record_review(usecases, plan, scope)
        else:
            usecases.gate(plan.requirement, _context(scope, "inactive-method-gate"))
    assert caught.value.code == "METHOD_UNAVAILABLE"
    assert _counts(library) == before
    assert admission.method_guard_depth == 0
    assert admission.trust_guard_depth == 0
    if operation == "record":
        with pytest.raises(ApplicationError) as missing:
            usecases.get_command(_context(scope, f"record-{plan.review_id}"))
        assert missing.value.code == "COMMAND_NOT_FOUND"
        assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (0,)
    else:
        assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)


def test_control_port_evidence_changes_projection_but_preserves_review_fact(environment):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    _record_review(usecases, plan, scope)
    before = usecases.query_set(plan.requirement, _context(scope, "control-before"))
    controlled = usecases.control_reviews(
        (ReviewControlExpectation(before.reviews[0].record.ref, 0),),
        _context(scope, "control-void"), state="voided", reason="Synthetic void decision.")
    assert controlled.status == "completed"
    after = usecases.query_set(plan.requirement, _context(scope, "control-after"))
    assert len(after.reviews) == 1
    assert after.reviews[0].record == before.reviews[0].record
    assert after.reviews[0].control.state == "voided"
    assert after.reviews[0].control.control_evidence == (Digest("sha256", "d" * 64),)
    assert after.reviews[0].control.version == 1
    assert after.set_version == before.set_version + 1
    assert library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)
    assert library._connection.execute("SELECT COUNT(*) FROM eng_review_control_events").fetchone() == (2,)
    gate = usecases.gate(plan.requirement, _context(scope, "gate-after-void"))
    assert (gate.satisfied, gate.code) == (False, "REVIEW_INCOMPLETE")
    assert len(control.calls) == 1


def test_artifact_command_binds_review_set_expectation_and_journals_stale_refusal(environment):
    library, factory, access, admission, control = environment
    scope = _scope()
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    reviews = _review_usecases(factory, access, admission, control)
    _plan_review(reviews, plan, scope)
    _record_review(reviews, plan, scope)
    before = reviews.query_set(plan.requirement, _context(scope, "artifact-expectation-read"))
    reviews.control_reviews(
        (ReviewControlExpectation(before.reviews[0].record.ref, 0),),
        _context(scope, "artifact-expectation-control"), state="voided", reason="Advance set version.")

    artifacts = ArtifactUseCases(factory, access)
    result = artifacts.append_revision({
        "artifact_id": subject.artifact_id,
        "expected_version": 1,
        "parents": [{
            "kind": "artifact_revision", "realm_id": subject.realm_id,
            "project_id": subject.project_id, "artifact_id": subject.artifact_id,
            "revision_id": subject.revision_id,
            "digest": {"algorithm": subject.digest.algorithm, "hex": subject.digest.hex},
        }],
        "payload": {"media_type": "application/json", "schema_id": "urn:test:append",
                    "inline_value": {"append": True}},
    }, _context(scope, "stale-review-read-set"), read_set=ReadSet(
        scope, (), review_sets=(ReviewSetExpectation(before.key, before.set_version),)))
    assert result.status == "rejected"
    assert result.result == {"code": "REVIEW_SET_CHANGED"}
    assert artifacts.get_command(_context(scope, "stale-review-read-set")) == result
    assert library._connection.execute("SELECT COUNT(*) FROM eng_artifact_revisions").fetchone() == (1,)
    assert library._connection.execute("SELECT COUNT(*) FROM eng_commands WHERE operation='engineering.artifacts.append_revision'").fetchone() == (1,)


def test_blob_capture_lost_reply_closes_then_reopen_finds_only_durable_bytes(tmp_path, monkeypatch):
    path = (tmp_path / "review-blob-commit-unknown.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=6)
    scope = _scope()
    factory = SQLiteUoWFactory(library)
    access = SyntheticAccess()
    blobs = CountingBlobStore(library)
    admission = SyntheticAdmission(library, blobs)
    control = SyntheticControl(library)
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    _plan_review(_review_usecases(factory, access, admission, control), plan, scope)
    library.close()

    connection_type = storage._LibraryConnection

    class LostCaptureReply(connection_type):
        def commit(self):
            result = super().commit()
            if getattr(self, "lose_reply", False):
                self.lose_reply = False
                raise RuntimeError("synthetic committed blob-capture reply loss")
            return result

    monkeypatch.setattr(storage, "_LibraryConnection", LostCaptureReply)
    reopened = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    capture_store = CountingBlobStore(reopened)
    admission.library = reopened
    admission.blobs = capture_store
    usecases = _review_usecases(SQLiteUoWFactory(reopened), access, admission, control)
    context = _context(scope, "unknown-blob-capture")
    reopened._connection.lose_reply = True
    with pytest.raises(ApplicationError) as unknown:
        usecases.record_response(plan.review_id, RAW_RESPONSE, context,
                                 expected_request_version=0, fence=1)
    assert unknown.value.code == "BLOB_COMMIT_UNKNOWN"
    assert unknown.value.retry == "reconcile"
    assert reopened._closed
    assert admission.verify_calls == 0
    assert capture_store.put_calls == 1

    expected_ref = reference_for(
        LIBRARY_ID, RAW_RESPONSE,
        Digest("sha256", hashlib.sha256(RAW_RESPONSE).hexdigest()),
        "application/octet-stream",
    )
    final_library = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    try:
        with SQLiteUoWFactory(final_library).begin(scope, "read") as uow:
            assert uow.commands.get(context.key) is None
            assert uow._access.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (0,)
            uow.commit()
        assert final_library._connection.execute(
            "SELECT byte_length,body FROM eng_method_blobs WHERE digest=?",
            (expected_ref.digest.hex,),
        ).fetchone() == (len(RAW_RESPONSE), RAW_RESPONSE)
        assert SQLiteBlobStore(final_library).read_verified(expected_ref) == RAW_RESPONSE
        assert final_library._connection.execute(
            "SELECT COUNT(*) FROM eng_commands WHERE operation='engineering.reviews.record'").fetchone() == (0,)
        assert final_library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (0,)
    finally:
        final_library.close()


def test_commit_lost_reply_reopen_and_replay_do_not_verify_or_insert_twice(tmp_path, monkeypatch):
    path = (tmp_path / "review-commit-unknown.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=6)
    scope = _scope()
    factory = SQLiteUoWFactory(library)
    access = SyntheticAccess()
    blobs = CountingBlobStore(library)
    admission = SyntheticAdmission(library, blobs)
    control = SyntheticControl(library)
    subject = _create_source(factory, scope)
    plan = _plan(scope, subject)
    usecases = _review_usecases(factory, access, admission, control)
    _plan_review(usecases, plan, scope)
    library.close()

    connection_type = storage._LibraryConnection

    class LostCommitReply(connection_type):
        def commit(self):
            result = super().commit()
            if getattr(self, "lose_reply", False):
                self.lose_reply = False
                raise RuntimeError("synthetic committed review reply loss")
            return result

    monkeypatch.setattr(storage, "_LibraryConnection", LostCommitReply)
    reopened = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    admission.library = reopened
    reopened_blobs = CountingBlobStore(reopened)
    admission.blobs = reopened_blobs
    usecases = _review_usecases(SQLiteUoWFactory(reopened), access, admission, control)
    context = _context(scope, "unknown-review-record")
    admission.on_verify = lambda: setattr(reopened._connection, "lose_reply", True)
    with pytest.raises(ApplicationError) as unknown:
        usecases.record_response(plan.review_id, RAW_RESPONSE, context,
                                 expected_request_version=0, fence=1)
    assert unknown.value.code == "COMMIT_UNKNOWN"
    assert unknown.value.retry == "reconcile"
    assert reopened._closed
    assert admission.verify_calls == 1
    assert admission.method_guard_depth == 0
    assert admission.trust_guard_depth == 0

    final_library = EngineeringLibrary.open(path, library_id=LIBRARY_ID)
    try:
        admission.library = final_library
        final_blobs = CountingBlobStore(final_library)
        admission.blobs = final_blobs
        restored = _review_usecases(SQLiteUoWFactory(final_library), access, admission, control)
        saved = restored.get_command(context)
        assert saved.status == "completed"
        assert final_library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)
        replay = restored.record_response(plan.review_id, RAW_RESPONSE, context,
                                          expected_request_version=0, fence=1)
        assert replay == saved
        assert admission.verify_calls == 1
        assert final_blobs.put_calls == 0
        assert final_library._connection.execute("SELECT COUNT(*) FROM eng_reviews").fetchone() == (1,)
        assert final_library._connection.execute("SELECT COUNT(*) FROM eng_commands").fetchone() == (3,)
        restored_set = restored.query_set(plan.requirement, _context(scope, "reopen-raw-query"))
        raw_ref = restored_set.reviews[0].record.raw_response_ref
        assert restored_set.reviews[0].record.identity.schema_version == 2
        assert final_blobs.read_verified(raw_ref) == RAW_RESPONSE
    finally:
        final_library.close()


@pytest.mark.parametrize('changed', ['none', 'plan', 'version', 'fence', 'withdrawn'])
def test_pending_evidence_artifact_checks_original_request_in_write_transaction(environment, changed):
    from ordessa_engineering.domain.reviews.models import ReviewRequestExpectation
    library, factory, access, admission, control = environment
    scope = _scope()
    plan = _plan(scope, _create_source(factory, scope))
    reviews = _review_usecases(factory, access, admission, control)
    _plan_review(reviews, plan, scope)
    predicate = ReviewRequestExpectation(scope, plan.review_id, plan.plan_digest, 0, 1)
    if changed == 'plan':
        predicate = replace(predicate, expected_plan_digest=Digest('sha256', 'f' * 64))
    elif changed == 'version':
        predicate = replace(predicate, expected_request_version=1)
    elif changed == 'fence':
        predicate = replace(predicate, expected_fence=2)
    elif changed == 'withdrawn':
        with factory.begin(scope) as uow:
            uow.reviews.withdraw_request(plan.review_id, expected_version=0, fence=1)
            uow.commit()
    artifacts = ArtifactUseCases(factory, access)
    result = artifacts.create({'kind': 'other', 'initial': {
        'media_type': 'application/json', 'schema_id': 'urn:test:pending-evidence',
        'inline_value': {'provider_evidence': 'fixture-only'}}},
        _context(scope, 'pending-evidence'), read_set=ReadSet(scope, (), review_requests=(predicate,)))
    if changed == 'none':
        assert result.status == 'completed'
        assert library._connection.execute('SELECT COUNT(*) FROM eng_artifact_revisions').fetchone() == (2,)
    else:
        assert result.status == 'rejected'
        assert result.result == {'code': 'REVIEW_REQUEST_CHANGED'}
        assert library._connection.execute('SELECT COUNT(*) FROM eng_artifact_revisions').fetchone() == (1,)
    with factory.begin(scope, "read") as uow:
        current = uow.reviews.get_request(plan.review_id)
        assert current.state == ('withdrawn' if changed == 'withdrawn' else 'requested')
        assert current.version == (1 if changed == 'withdrawn' else 0)
        assert uow.reviews.read_set(ReviewSetKey.for_requirement(plan.requirement)).reviews == ()
    assert artifacts.get_command(_context(scope, 'pending-evidence')) == result


def test_pending_request_predicate_cannot_change_under_same_command_key(environment):
    from ordessa_engineering.domain.reviews.models import ReviewRequestExpectation
    library, factory, access, admission, control = environment
    scope = _scope()
    plan = _plan(scope, _create_source(factory, scope))
    _plan_review(_review_usecases(factory, access, admission, control), plan, scope)
    predicate = ReviewRequestExpectation(scope, plan.review_id, plan.plan_digest, 0, 1)
    artifacts = ArtifactUseCases(factory, access)
    body = {'kind': 'other', 'initial': {'media_type': 'application/json',
        'schema_id': 'urn:test:pending', 'inline_value': {'raw': 'fixture'}}}
    context = _context(scope, 'same-pending-key')
    result = artifacts.create(body, context, read_set=ReadSet(scope, (), review_requests=(predicate,)))
    assert result.status == 'completed'
    with pytest.raises(ApplicationError, match='REQUEST_IDENTITY_CONFLICT'):
        artifacts.create(body, context, read_set=ReadSet(scope, (),
            review_requests=(replace(predicate, expected_fence=2),)))
    assert library._connection.execute('SELECT COUNT(*) FROM eng_artifact_revisions').fetchone() == (2,)


def test_empty_pending_request_projection_preserves_historical_identity():
    from dataclasses import asdict
    from ordessa_engineering.application.contracts.commands import read_set_projection
    reads = ReadSet(_scope(), ())
    old = asdict(reads)
    del old['review_requests']
    assert read_set_projection(reads) == old
