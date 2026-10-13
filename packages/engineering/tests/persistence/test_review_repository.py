"""SQLite acceptance for review facts, complete sets, controls, and fences."""
from __future__ import annotations
from ordessa_engineering.application.usecases.material_closure import verify_material

from pathlib import Path
from dataclasses import replace
import hashlib

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.domain.reviews.codec import encode_control
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, InlinePayload
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.artifacts.method_binding import (MethodRef)
from ordessa_engineering.domain.reviews.targets import (Target, TargetSet)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.mechanisms.hashing import (record_digest)
from ordessa_engineering.domain.common.models.identity import (ActorRef)
from ordessa_engineering.domain.reviews.identity import (RecordIdentity)
from ordessa_engineering.domain.reviews.models import (
    AggregationPolicy,
    CheckKey,
    CheckPolicy,
    CriterionSetRef,
    Observation,
    ReviewControl,
    ReviewControlExpectation,
    ReviewPlan,
    ReviewRecord,
    ReviewRequirement,
    ReviewSetExpectation,
    observations_digest,
)
from ordessa_engineering.domain.reviews.evidence import (VerifiedReviewerEvidence)


LIBRARY_ID = "test.review-repository"
CREATED_AT = "2026-10-09T12:00:00.000000Z"
ACTOR = ActorRef("reviewer-1", "human", "test-issuer")
SCOPE = Scope("realm-1", "project-1")


def _open(path: Path, schema_version: int = 5):
    library = EngineeringLibrary.create(path.resolve(), library_id=LIBRARY_ID,
                                         schema_version=schema_version)
    return library, SQLiteUoWFactory(library)


def _digest(label: str) -> Digest:
    return record_digest("review-repository-test", {"label": label})


def _real_target(uow, artifact_id: str = "target-1") -> ArtifactRevisionRef:
    uow.engineering.create(Artifact(SCOPE, artifact_id, "specification", CREATED_AT))
    revision = ArtifactRevision(
        SCOPE, artifact_id, "revision-1", CREATED_AT, ACTOR,
        InlinePayload.from_value("application/json", "urn:test:review-target", {"value": "real"}),
    )
    verify_material(revision, uow.engineering.validated_budget())
    return uow.engineering.append_revision(revision, expected_version=0)


def _requirement(target_ref: ArtifactRevisionRef, *, requirement_id: str = "requirement-1",
                 phase_key: str = "before", roles: tuple[str, ...] = ("reviewer",)) -> ReviewRequirement:
    target = Target("proposed", target_ref)
    check = CheckKey(target, "criterion-1")
    return ReviewRequirement(
        SCOPE, requirement_id, 1, "quality", TargetSet((target,)),
        MethodRef("method-1", "1.0.0", 1, _digest("method")),
        CriterionSetRef("criteria-1", 1, _digest("criteria")),
        (check,), roles, phase_key,
    )


def _plan(requirement: ReviewRequirement, review_id: str) -> ReviewPlan:
    check = requirement.required_check_keys[0]
    return ReviewPlan(review_id, requirement, (CheckPolicy(check, True, True),),
                      AggregationPolicy(), ("reviewer",))


def _record(plan: ReviewPlan, result: str = "pass") -> ReviewRecord:
    observations = (Observation(plan.check_keys[0], result, (), f"observed {result}"),)
    reviewer = VerifiedReviewerEvidence(
        SCOPE, ACTOR, ("reviewer",), "test-verifier", "1", 1,
        plan.request_digest, _digest(f"response-{plan.review_id}"),
        observations_digest(observations), _digest("capability"),
    )
    return ReviewRecord(RecordIdentity(SCOPE, plan.review_id, CREATED_AT, ACTOR),
                        plan, reviewer, observations)


def _create_and_insert(uow, requirement: ReviewRequirement, review_id: str,
                       result: str = "pass") -> ReviewRecord:
    plan = _plan(requirement, review_id)
    request = uow.reviews.create_plan(plan)
    record = _record(plan, result)
    uow.reviews.insert_review(record, expected_request_version=request.version, fence=request.fence)
    return record


def _seed(path: Path):
    library, factory = _open(path)
    with factory.begin(SCOPE, "write") as uow:
        target_ref = _real_target(uow)
        uow.commit()
    return library, factory, target_ref


@pytest.mark.parametrize("shared,foreign_locator", [(False, False), (True, False), (True, True)],
    ids=["distinct-budget-refused", "shared-content-counted-once", "shared-content-foreign-locator-refused"])
def test_raw_set_budget_is_checked_before_any_body_read(tmp_path, monkeypatch, shared, foreign_locator):
    from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
    from ordessa_engineering.adapters.persistence.sqlite import review_repository as repo
    library, factory, target = _seed(tmp_path / "raw-budget.sqlite")
    requirement = _requirement(target)
    blobs = SQLiteBlobStore(library)
    responses = (b"first!", b"first!" if shared else b"second")
    refs = tuple(blobs.put_verified(raw, Digest("sha256", hashlib.sha256(raw).hexdigest()),
                                    "application/octet-stream") for raw in responses)
    try:
        with factory.begin(SCOPE) as uow:
            for index, raw_ref in enumerate(refs):
                plan = _plan(requirement, f"raw-review-{index}")
                request = uow.reviews.create_plan(plan)
                old = _record(plan)
                record = replace(old, identity=replace(old.identity, schema_version=2),
                    reviewer_evidence=replace(old.reviewer_evidence, raw_response_digest=raw_ref.digest),
                    raw_response_ref=raw_ref)
                uow.reviews.insert_review(record, expected_request_version=request.version, fence=request.fence)
            key = uow.reviews.ensure_requirement(requirement)
            uow.commit()
        reads = []
        real_read = repo.read_bytes
        def counted(*args):
            reads.append(args[-1].digest)
            return real_read(*args)
        monkeypatch.setattr(repo, "read_bytes", counted)
        monkeypatch.setattr(repo, "_MAX_RAW_SET_BYTES", 10)
        with factory.begin(SCOPE, "write" if foreign_locator else "read") as uow:
            if foreign_locator:
                from ordessa_engineering.domain.reviews.codec import encode_record
                changed = replace(record, raw_response_ref=replace(record.raw_response_ref,
                    storage_object_id="engineering-blob:foreign:" + record.raw_response_ref.digest.hex))
                # A locator move preserves the digest; every member must still
                # bind to the original byte owner, even after a cache hit.
                assert changed.ref == record.ref
                uow._access.execute("DROP TRIGGER eng_reviews_no_update")
                uow._access.execute("UPDATE eng_reviews SET canonical_bytes=? WHERE review_id=?",
                    (encode_record(changed), record.plan.review_id))
                with pytest.raises(ApplicationError) as error:
                    uow.reviews.read_set(key)
                assert error.value.code == "RECORD_CORRUPT"
                assert reads == [refs[0].digest]
                uow.rollback()
            elif shared:
                assert len(uow.reviews.read_set(key).reviews) == 2
                assert reads == [refs[0].digest]
            else:
                with pytest.raises(ApplicationError) as error:
                    uow.reviews.read_set(key)
                assert error.value.code == "REVIEW_SET_LIMIT"
                assert reads == []
    finally:
        library.close()


def test_read_set_retains_pass_and_fail_counterevidence_and_replay_is_idempotent(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "counterevidence.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        passed = _create_and_insert(uow, requirement, "review-pass", "pass")
        failed = _create_and_insert(uow, requirement, "review-fail", "fail")
        key = uow.reviews.ensure_requirement(requirement)
        before = uow.reviews.read_set(key)
        assert {item.record.ref for item in before.reviews} == {passed.ref, failed.ref}
        assert {item.record.verdict for item in before.reviews} == {"pass", "fail"}

        # Replaying an identical persisted ID returns the original reference and
        # does not create another observation or increment the phantom fence.
        replayed = uow.reviews.insert_review(passed, expected_request_version=0, fence=1)
        after = uow.reviews.read_set(key)
        assert replayed == passed.ref
        assert after.set_version == before.set_version == 2
        assert len(after.reviews) == 2
        uow.commit()
    library.close()


@pytest.mark.parametrize(
    "replacement",
    [
        {"phase_key": "after"},
        {"roles": ("reviewer", "approver")},
    ],
    ids=("phase-changed", "eligible-roles-changed"),
)
def test_same_requirement_identity_rejects_changed_phase_or_roles(
    tmp_path: Path, replacement: dict,
) -> None:
    library, factory, target_ref = _seed(tmp_path / "requirement-conflict.sqlite")
    original = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        key = uow.reviews.ensure_requirement(original)
        changed = _requirement(target_ref, **replacement)
        with pytest.raises(ApplicationError) as conflict:
            uow.reviews.ensure_requirement(changed)
        assert conflict.value.code == "REQUIREMENT_CONFLICT"
        assert uow.reviews.read_set(key).set_version == 0
        uow.commit()
    library.close()


def test_empty_set_version_is_a_phantom_fence_after_first_insert(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "phantom.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        plan = _plan(requirement, "first-review")
        uow.reviews.create_plan(plan)
        key = uow.reviews.ensure_requirement(requirement)
        empty = uow.reviews.read_set(key)
        assert empty.set_version == 0 and empty.reviews == ()
        uow.commit()

    with factory.begin(SCOPE, "write") as uow:
        record = _create_and_insert(uow, requirement, "first-review", "fail")
        with pytest.raises(ApplicationError) as stale:
            uow.reviews.check_expectations((ReviewSetExpectation(key, empty.set_version),))
        assert stale.value.code == "REVIEW_SET_CHANGED"
        assert uow.reviews.read_set(key).reviews[0].record.ref == record.ref
        uow.commit()
    library.close()


def test_two_connections_reject_stale_complete_set_after_new_fail(tmp_path: Path) -> None:
    path = tmp_path / "two-connections.sqlite"
    library_a, factory_a, target_ref = _seed(path)
    library_b = EngineeringLibrary.open(path.resolve(), library_id=LIBRARY_ID)
    factory_b = SQLiteUoWFactory(library_b)
    requirement = _requirement(target_ref)
    with factory_a.begin(SCOPE, "write") as uow:
        first = _create_and_insert(uow, requirement, "review-old", "pass")
        key = uow.reviews.ensure_requirement(requirement)
        uow.commit()

    # Capture A's complete-set expectation, end its read transaction, then let
    # B append counterevidence before A checks that old expectation.
    with factory_a.begin(SCOPE, "read") as uow:
        stale_snapshot = uow.reviews.read_set(key)
        assert stale_snapshot.reviews[0].record.ref == first.ref
        uow.commit()
    with factory_b.begin(SCOPE, "write") as uow:
        failed = _create_and_insert(uow, requirement, "review-new-fail", "fail")
        uow.commit()
    with factory_a.begin(SCOPE, "write") as uow:
        with pytest.raises(ApplicationError) as stale:
            uow.reviews.check_expectations((ReviewSetExpectation(key, stale_snapshot.set_version),))
        assert stale.value.code == "REVIEW_SET_CHANGED"
        current = uow.reviews.read_set(key)
        assert {item.record.ref for item in current.reviews} == {first.ref, failed.ref}
        assert any(item.record.verdict == "fail" for item in current.reviews)
        uow.commit()
    library_a.close()
    library_b.close()


def test_group_void_and_replace_each_bump_once_and_preserve_every_record(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "group-control.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        records = tuple(_create_and_insert(uow, requirement, name)
                        for name in ("void-a", "void-b", "old", "replacement"))
        key = uow.reviews.ensure_requirement(requirement)
        before = uow.reviews.read_set(key)
        void_refs = (records[0].ref, records[1].ref)
        voided = uow.reviews.control_group(
            tuple(ReviewControlExpectation(ref, 0) for ref in void_refs),
            state="voided", reason="superseded evidence", evidence=(_digest("void"),),
        )
        assert voided.set_version == before.set_version + 1
        assert {item.record.ref for item in voided.reviews} == {record.ref for record in records}
        assert {item.control.state for item in voided.reviews
                if item.record.ref in void_refs} == {"voided"}

        replaced = uow.reviews.control_group(
            (ReviewControlExpectation(records[2].ref, 0),),
            state="replaced", reason="new review supersedes old", evidence=(_digest("replace"),),
            replacement_ref=records[3].ref,
        )
        assert replaced.set_version == voided.set_version + 1
        assert {item.record.ref for item in replaced.reviews} == {record.ref for record in records}
        by_ref = {item.record.ref: item for item in replaced.reviews}
        assert by_ref[records[2].ref].control.state == "replaced"
        assert by_ref[records[2].ref].control.replacement_ref == records[3].ref
        assert by_ref[records[3].ref].control.state == "active"
        uow.commit()
    library.close()


def test_control_group_rejects_cross_requirement_replacement_atomically(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "cross-requirement.sqlite")
    original_req = _requirement(target_ref, requirement_id="req-original")
    other_req = _requirement(target_ref, requirement_id="req-other")
    with factory.begin(SCOPE, "write") as uow:
        original = _create_and_insert(uow, original_req, "review-original")
        replacement = _create_and_insert(uow, other_req, "review-other")
        original_key = uow.reviews.ensure_requirement(original_req)
        with pytest.raises(ApplicationError) as stale:
            with uow.isolate():
                uow.reviews.control_group(
                    (ReviewControlExpectation(original.ref, 0),), state="replaced",
                    reason="invalid cross-requirement replacement", evidence=(_digest("cross"),),
                    replacement_ref=replacement.ref,
                )
        assert stale.value.code == "REVIEW_STALE"
        snapshot = uow.reviews.read_set(original_key)
        assert snapshot.set_version == 1
        assert snapshot.reviews[0].control.state == "active"
        uow.commit()
    library.close()


def test_isolated_control_failure_rolls_back_events_projection_and_set_version(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "control-rollback.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        record = _create_and_insert(uow, requirement, "review-rollback")
        key = uow.reviews.ensure_requirement(requirement)
        before = uow.reviews.read_set(key)
        with pytest.raises(ApplicationError) as refusal:
            with uow.isolate():
                uow.reviews.control_group(
                    (ReviewControlExpectation(record.ref, 0),), state="voided",
                    reason="should roll back", evidence=(_digest("rollback"),),
                )
                raise ApplicationError("BUSINESS_REFUSED")
        assert refusal.value.code == "BUSINESS_REFUSED"
        after = uow.reviews.read_set(key)
        assert after == before
        event_count = uow._access.execute(
            "SELECT count(*) FROM eng_review_control_events WHERE review_id=?", (record.plan.review_id,),
        ).fetchone()[0]
        assert event_count == 1
        uow.commit()
    library.close()

    reopened = EngineeringLibrary.open((tmp_path / "control-rollback.sqlite").resolve(), library_id=LIBRARY_ID)
    with SQLiteUoWFactory(reopened).begin(SCOPE, "read") as uow:
        persisted = uow.reviews.read_set(key)
        assert persisted == before
        uow.commit()
    reopened.close()


def test_projection_history_mismatch_is_rejected_and_event_history_is_immutable(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "control-history.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        record = _create_and_insert(uow, requirement, "review-history")
        terminal = ReviewControl(SCOPE, record.plan.review_id, "voided", reason="bad projection",
                                 control_evidence=(_digest("history"),), version=1)
        with pytest.raises(ApplicationError) as immutable:
            uow._access.execute(
                "UPDATE eng_review_control_events SET canonical_bytes=? WHERE review_id=? AND version=0",
                (encode_control(terminal), record.plan.review_id),
            )
        assert immutable.value.code == "STORAGE_CONSTRAINT"

        # The materialized projection may be written, but it cannot claim a
        # terminal state without the corresponding immutable event.
        uow._access.execute(
            "UPDATE eng_review_controls SET state='voided',version=1,canonical_bytes=? WHERE review_id=?",
            (encode_control(terminal), record.plan.review_id),
        )
        with pytest.raises(ApplicationError) as corrupt:
            uow.reviews.get_review(record.ref)
        assert corrupt.value.code == "RECORD_CORRUPT"
        uow.rollback()
    library.close()


def test_withdrawn_request_fence_rejects_late_review_response(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "withdraw-fence.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        plan = _plan(requirement, "late-review")
        request = uow.reviews.create_plan(plan)
        record = _record(plan)
        withdrawn = uow.reviews.withdraw_request(
            plan.review_id, expected_version=request.version, fence=request.fence,
        )
        assert (withdrawn.state, withdrawn.version, withdrawn.fence) == ("withdrawn", 1, 2)
        with pytest.raises(ApplicationError) as late:
            uow.reviews.insert_review(record, expected_request_version=request.version, fence=request.fence)
        assert late.value.code == "REVIEW_REQUEST_CHANGED"
        key = uow.reviews.ensure_requirement(requirement)
        assert uow.reviews.read_set(key).reviews == ()
        uow.commit()
    library.close()


def test_read_mode_handle_lifecycle_and_schema4_review_unavailability(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "read-mode.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        uow.reviews.create_plan(_plan(requirement, "read-mode-review"))
        uow.commit()

    with factory.begin(SCOPE, "read") as uow:
        repository = uow.reviews
        with pytest.raises(ApplicationError) as read_only:
            repository.create_plan(_plan(requirement, "forbidden-write"))
        assert read_only.value.code == "READ_ONLY_UOW"
        uow.commit()
    with pytest.raises(ApplicationError) as expired:
        repository.get_request("read-mode-review")
    assert expired.value.code == "UOW_NOT_ACTIVE"
    library.close()

    legacy, legacy_factory = _open(tmp_path / "schema4.sqlite", schema_version=4)
    with legacy_factory.begin(SCOPE, "read") as uow:
        with pytest.raises(ApplicationError) as unavailable:
            _ = uow.reviews
        assert unavailable.value.code == "REVIEW_SCHEMA_REQUIRED"
        uow.commit()
    legacy.close()


def test_review_target_corruption_is_reported_as_corrupt_stored_review(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "damaged-target.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        record = _create_and_insert(uow, requirement, "review-target-damaged")
        # Isolated synthetic-store corruption bypasses the real immutability
        # guard; the repository must still validate every stored target ref.
        uow._access.execute("DROP TRIGGER eng_artifact_revisions_no_update")
        uow._access.execute(
            "UPDATE eng_artifact_revisions SET canonical_bytes=? WHERE revision_id=?",
            (b"{}", target_ref.revision_id),
        )
        with pytest.raises(ApplicationError) as corrupt:
            uow.reviews.get_review(record.ref)
        assert corrupt.value.code == "RECORD_CORRUPT"
        uow.rollback()
    library.close()


@pytest.mark.parametrize("damaged_table", ("requirement", "plan", "set"))
def test_damaged_requirement_plan_or_set_projection_is_rejected(
    tmp_path: Path, damaged_table: str,
) -> None:
    library, factory, target_ref = _seed(tmp_path / f"damaged-{damaged_table}.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        record = _create_and_insert(uow, requirement, f"review-damaged-{damaged_table}")
        key = uow.reviews.ensure_requirement(requirement)
        if damaged_table == "requirement":
            uow._access.execute("DROP TRIGGER eng_review_requirements_no_update")
            uow._access.execute(
                "UPDATE eng_review_requirements SET canonical_bytes=? WHERE requirement_id=?",
                (b"{}", requirement.requirement_id),
            )
            read = lambda: uow.reviews.read_set(key)
        elif damaged_table == "plan":
            uow._access.execute("DROP TRIGGER eng_review_plans_no_update")
            uow._access.execute(
                "UPDATE eng_review_plans SET canonical_bytes=? WHERE review_id=?",
                (b"{}", record.plan.review_id),
            )
            read = lambda: uow.reviews.get_review(record.ref)
        else:
            uow._access.execute(
                "UPDATE eng_review_sets SET canonical_key=? WHERE set_digest=?",
                (b"{}", key.digest.hex),
            )
            read = lambda: uow.reviews.read_set(key)

        with pytest.raises(ApplicationError) as corrupt:
            read()
        assert corrupt.value.code == "RECORD_CORRUPT"
        uow.rollback()
    library.close()


def test_oversized_corrupt_review_blob_is_rejected_by_bounded_sql_read(tmp_path: Path) -> None:
    library, factory, target_ref = _seed(tmp_path / "oversized-review.sqlite")
    requirement = _requirement(target_ref)
    with factory.begin(SCOPE, "write") as uow:
        record = _create_and_insert(uow, requirement, "review-oversized")
        uow._access.execute("DROP TRIGGER eng_reviews_no_update")
        uow._access.execute("PRAGMA ignore_check_constraints=ON")
        uow._access.execute(
            "UPDATE eng_reviews SET canonical_bytes=zeroblob(?) WHERE review_id=?",
            (2 * 1024 * 1024 + 1, record.plan.review_id),
        )

        observed_lengths: list[int] = []
        bounded_review_selects: list[str] = []
        review_blob_values: list[object] = []
        original_execute = uow._access.execute

        class CursorProbe:
            def __init__(self, cursor, *, is_review_row: bool):
                self.cursor = cursor
                self.is_review_row = is_review_row

            def _observe(self, row):
                if row is not None:
                    for value in row:
                        if type(value) is bytes:
                            observed_lengths.append(len(value))
                    if self.is_review_row:
                        review_blob_values.append(row[2])
                return row

            def fetchone(self):
                return self._observe(self.cursor.fetchone())

            def fetchall(self):
                return [self._observe(row) for row in self.cursor.fetchall()]

        def probe_execute(sql, parameters=()):
            cursor = original_execute(sql, parameters)
            if sql.lstrip().upper().startswith("SELECT") and "canonical_bytes" in sql:
                bounded_review_selects.append(sql)
                return CursorProbe(cursor, is_review_row="FROM eng_reviews" in sql)
            return cursor

        uow._access.execute = probe_execute
        with pytest.raises(ApplicationError) as corrupt:
            uow.reviews.get_review(record.ref)
        assert corrupt.value.code == "RECORD_CORRUPT"
        assert any("CASE WHEN typeof(canonical_bytes)='blob'" in sql
                   and "length(canonical_bytes)<=2097152" in sql and "FROM eng_reviews" in sql
                   for sql in bounded_review_selects)
        assert review_blob_values == [None]
        assert max(observed_lengths, default=0) <= 2 * 1024 * 1024
        uow.rollback()
    library.close()
