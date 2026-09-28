"""T04 / G02 — revisions, CAS and transaction-interruption discipline.

Positive: saving new content adds a revision; an identical body adds no
content revision while metadata still bumps.
Required counter-examples (verification.md G02):
* two clients racing the same expected version over ONE database file —
  exactly one wins, the other gets REVISION_CONFLICT (two ``PromptsStore``
  instances, two service contexts, real threads);
* a transaction interrupted at *any* write step rolls back completely:
  latest never points at a nonexistent revision and no idempotency receipt
  survived (``PromptsStore.fault_after`` is the injection seam);
* a stale expected version refuses the write instead of last-wins.

Gates: G02. Requirements: FR02, FR04.
"""
from __future__ import annotations

import threading

import pytest

from ordessa_prompts.api import (
    InvalidContentError,
    NotFoundError,
    PromptError,
    PromptScope,
    RevisionConflictError,
    body_digest,
)
from ordessa_prompts.backend.records import PromptRecords
from ordessa_prompts.backend.service import PromptsService
from ordessa_prompts.backend.storage import PromptsStore

#: A body fragment that appears nowhere else, so a leak into an error
#: message or a refusal reason is detectable by string search.
CANARY = "CANARY-BODY-must-never-leak"


def _service(store: PromptsStore, subject: str = "operator-1") -> PromptsService:
    return PromptsService(PromptRecords(store), server_scope="g02-server",
                          subject_provider=lambda: subject)


def _create(service: PromptsService, body: bytes = b"first body", key: str = "k-create",
            title: str = "race") -> dict:
    return service.create(kind="instruction", scope={"kind": "library"},
                          title=title, description=None, body=body,
                          operation_key=key)


# -- revision discipline ------------------------------------------------------

def test_new_body_adds_a_revision_and_digest(library_service, records):
    created = _create(library_service)
    assert created["latestRevision"] == 1
    assert created["sha256"] == body_digest(b"first body")
    updated = library_service.update(
        created["id"], expected_metadata_version=1, expected_latest_revision=1,
        patch={"body": b"second body"}, operation_key="k-2")
    assert updated["latestRevision"] == 2
    revision = records.get_revision(created["id"], 2)
    assert revision.sha256 == body_digest(b"second body")
    assert revision.body == b"second body"
    # the old revision survives untouched — restoring an old text means a
    # NEW revision, never a rewind of latest
    assert records.get_revision(created["id"], 1).body == b"first body"


def test_identical_body_adds_no_content_revision_but_metadata_bumps(library_service):
    created = _create(library_service)
    same = library_service.update(
        created["id"], expected_metadata_version=1, expected_latest_revision=1,
        patch={"body": b"first body", "title": "renamed"}, operation_key="k-same")
    assert same["latestRevision"] == 1, "identical bytes must not mint a revision"
    assert same["metadataVersion"] == 2, "metadata change still bumps"
    # PR-R2: an untouched body still reports the live digest, never a hole
    assert same["sha256"] == body_digest(b"first body")


def test_metadata_only_update_bumps_metadata_not_revision_and_echoes_digest(
        library_service, records):
    created = _create(library_service)
    out = library_service.update(created["id"], expected_metadata_version=1,
                                 expected_latest_revision=1,
                                 patch={"description": "note"}, operation_key="k-d")
    assert out["metadataVersion"] == 2 and out["latestRevision"] == 1
    assert out["sha256"] == body_digest(b"first body")
    assert records.get_revision(created["id"]).body == b"first body"


def test_restoring_an_old_text_creates_a_new_revision_never_a_rewind(records,
                                                                    library_service):
    created = _create(library_service, body=b"v1 text")
    library_service.update(created["id"], expected_metadata_version=1,
                           expected_latest_revision=1,
                           patch={"body": b"v2 text"}, operation_key="r-2")
    back = library_service.update(created["id"], expected_metadata_version=2,
                                  expected_latest_revision=2,
                                  patch={"body": b"v1 text"}, operation_key="r-3")
    assert back["latestRevision"] == 3, "latest must move forward, never rewind"
    assert records.get_revision(created["id"], 1).body == b"v1 text"
    assert records.get_revision(created["id"], 2).body == b"v2 text"
    assert records.get_revision(created["id"], 3).body == b"v1 text"


def test_stale_expected_version_refuses_and_does_not_last_wins(library_service,
                                                               records):
    created = _create(library_service, body=b"live body")
    library_service.update(created["id"], expected_metadata_version=1,
                           expected_latest_revision=1,
                           patch={"body": b"winner body"}, operation_key="w-1")
    with pytest.raises(RevisionConflictError) as exc:
        library_service.update(created["id"], expected_metadata_version=1,
                               expected_latest_revision=1,
                               patch={"body": b"loser body"}, operation_key="w-2")
    assert exc.value.details["currentMetadataVersion"] == 2
    assert exc.value.details["currentLatestRevision"] == 2
    assert records.get_revision(created["id"]).body == b"winner body"
    bodies = [records.get_revision(created["id"], n).body for n in (1, 2)]
    assert b"loser body" not in bodies, f"last-wins leaked the stale write: {bodies}"


# -- real two-client CAS race --------------------------------------------------

def test_two_clients_racing_one_expected_version_exactly_one_wins(two_clients,
                                                                  db_rows):
    """Two store instances (own connections, own in-process write lock) over
    one database file, two service subjects, released together by a barrier."""
    clients = two_clients
    prompt_id = clients.service_a.create(
        kind="instruction", scope={"kind": "library"}, title="racers",
        description=None, body=b"base body", operation_key="race-seed")["id"]
    results: dict[str, tuple] = {}
    barrier = threading.Barrier(2)

    def worker(name: str, service: PromptsService, body: bytes, key: str) -> None:
        barrier.wait()
        try:
            out = service.update(prompt_id, expected_metadata_version=1,
                                 expected_latest_revision=1,
                                 patch={"body": body}, operation_key=key)
            results[name] = ("won", out["latestRevision"])
        except RevisionConflictError as exc:
            results[name] = ("conflict", exc.details["currentLatestRevision"])
        except Exception as exc:  # noqa: BLE001 - recorded, then asserted below
            results[name] = ("error", f"{type(exc).__name__}: {exc}")

    threads = [
        threading.Thread(target=worker,
                         args=("x", clients.service_a, b"body x", "race-x")),
        threading.Thread(target=worker,
                         args=("y", clients.service_b, b"body y", "race-y")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "a racer never returned (deadlock?)"

    outcomes = sorted(value[0] for value in results.values())
    assert sorted(results) == ["x", "y"], results
    assert outcomes == ["conflict", "won"], (
        f"CAS did not resolve the race into exactly one win + one conflict: {results}")
    winner = [name for name, value in results.items() if value[0] == "won"][0]
    loser = [name for name, value in results.items() if value[0] == "conflict"][0]
    assert results[loser][1] == 2, "the loser must be told the live revision"
    # read through the *other* client's connection: one committed truth
    assert PromptRecords(clients.store_b).get_revision(prompt_id).body == (
        f"body {winner}".encode())
    stored = [bytes(row["body"]) for row in
              db_rows(clients.store_b,
                      "SELECT body FROM prompt_revisions WHERE prompt_id=?",
                      (prompt_id,))]
    assert f"body {loser}".encode() not in stored, (
        f"the losing racer's body reached storage: {stored}")
    assert len(stored) == 2, stored  # base + winner only


def test_same_operation_key_from_two_subjects_does_not_collide(two_clients, db_rows):
    """Receipt scope = caller subject + operation + target from the *service
    context*, so two clients may legitimately reuse one key string
    (contracts.md §1) without reading each other's receipt."""
    clients = two_clients
    prompt_id = clients.service_a.create(
        kind="instruction", scope={"kind": "library"}, title="dual",
        description=None, body=b"base", operation_key="seed")["id"]
    first = clients.service_a.update(prompt_id, expected_metadata_version=1,
                                     expected_latest_revision=1,
                                     patch={"body": b"by a"}, operation_key="same-key")
    second = clients.service_b.update(prompt_id, expected_metadata_version=2,
                                      expected_latest_revision=2,
                                      patch={"body": b"by b"}, operation_key="same-key")
    assert first["replayed"] is False and second["replayed"] is False
    scopes = {row["scope"] for row in db_rows(
        clients.store_a, "SELECT scope FROM prompt_idempotency WHERE key=?",
        ("same-key",))}
    assert scopes == {f"subject-a|update|{prompt_id}",
                      f"subject-b|update|{prompt_id}"}, scopes


# -- interrupted transactions: no half a revision, no receipt ------------------

SWEEP_OPS = ("create", "update", "clone", "archive")


def _seed_target(store: PromptsStore) -> str:
    return _service(store, "seeder").create(
        kind="instruction", scope={"kind": "library"}, title="seed",
        description=None, body=b"seed body", operation_key="seed-key")["id"]


def _run_op(store: PromptsStore, op: str, target_id: "str | None") -> dict:
    service = _service(store, "sweeper")
    if op == "create":
        return service.create(kind="instruction", scope={"kind": "library"},
                              title="swept", description=None,
                              body=b"swept brand new body",
                              operation_key=f"sweep-{op}")
    if op == "update":
        return service.update(target_id, expected_metadata_version=1,
                              expected_latest_revision=1,
                              patch={"body": b"swept body", "title": "swept title"},
                              operation_key=f"sweep-{op}")
    if op == "clone":
        return service.clone(target_id, target_scope={"kind": "library"},
                             title="swept clone", operation_key=f"sweep-{op}")
    if op == "archive":
        return service.archive(target_id, expected_metadata_version=1,
                               operation_key=f"sweep-{op}")
    raise AssertionError(f"unknown sweep op {op!r}")


def _assert_nothing_persisted(store: PromptsStore, op: str,
                              target_id: "str | None", db_rows) -> None:
    # the seeding create legitimately left its own receipt; only the aborted
    # operation's key must be absent
    swept = db_rows(store, "SELECT * FROM prompt_idempotency WHERE key=?",
                    (f"sweep-{op}",))
    assert swept == [], (
        f"an interrupted {op} left its idempotency receipt behind: {len(swept)}")
    record_rows = db_rows(store, "SELECT * FROM prompt_records")
    revision_rows = db_rows(store, "SELECT * FROM prompt_revisions")
    if op == "create":
        assert record_rows == [], f"interrupted create left a record row"
        assert revision_rows == [], "interrupted create left a revision row"
        return
    assert len(record_rows) == 1, f"interrupted {op} changed the record count"
    assert len(revision_rows) == 1, f"interrupted {op} left extra revision rows"
    head = record_rows[0]
    assert head["id"] == target_id
    assert int(head["metadata_version"]) == 1, f"interrupted {op} bumped metadata"
    assert int(head["latest_revision"]) == 1, (
        f"interrupted {op} moved latest_revision onto a nonexistent revision")
    assert head["archived"] == 0, f"interrupted {op} archived the record"
    assert head["title"] == "seed", f"interrupted {op} changed the title"
    assert bytes(revision_rows[0]["body"]) == b"seed body", (
        f"interrupted {op} replaced the stored body")


def test_interrupted_write_rolls_back_completely_at_every_step(tmp_path, step_trace,
                                                              db_rows):
    """G02's hard counter-example: for *each* write step an operation
    executes, abort right after it and prove the store is back exactly where
    it was — no half revision, no dangling latest pointer, no receipt — then
    show the same request applies for real once the fault is gone.

    The step list is discovered by tracing one successful pass, so the sweep
    keeps covering every statement even when the repository changes shape.
    """
    for op in SWEEP_OPS:
        probe = PromptsStore(tmp_path / f"probe-{op}.db")
        try:
            probe_target = None if op == "create" else _seed_target(probe)
            executed = step_trace.steps_of(probe, lambda: _run_op(probe, op,
                                                                  probe_target))
        finally:
            probe.close()
        assert executed, f"{op} executed no traceable write step at all"
        assert executed == list(range(1, max(executed) + 1)), (
            f"{op} write steps are not a contiguous 1..n sequence: {executed}")
        assert max(executed) >= 3, (
            f"{op} is too short to prove a *partial* rollback: {executed}")

        for step in executed:
            store = PromptsStore(tmp_path / f"sweep-{op}-{step}.db")
            try:
                target_id = None if op == "create" else _seed_target(store)
                step_trace.arm(store, step)
                with pytest.raises(RuntimeError,
                                   match=f"injected abort after write step {step}"):
                    _run_op(store, op, target_id)
                step_trace.disarm(store)
                _assert_nothing_persisted(store, op, target_id, db_rows)

                # the identical request now applies for real: no phantom replay
                out = _run_op(store, op, target_id)
                assert out.get("replayed", False) is False, (
                    f"after the abort, {op} replayed a receipt that was never "
                    f"committed: {out}")
                records = PromptRecords(store)
                if op == "update":
                    assert out["latestRevision"] == 2
                    assert records.get_revision(target_id).body == b"swept body"
                elif op == "archive":
                    assert records.get_record(target_id).archived is True
                elif op == "clone":
                    assert records.get_revision(out["id"]).body == b"seed body"
                    assert records.get_record(out["id"]).metadata_version == 1
                else:
                    assert records.get_record(out["id"]).latest_revision == 1
            finally:
                store.close()


def test_fault_seam_is_none_by_default_and_not_a_constructor_option(store):
    """PR-R3 half 1: the interruption seam is opt-in per store instance; no
    production construction can pass it (the constructor has no such
    parameter), so an assembled store starts disarmed."""
    import inspect

    assert store.fault_after is None
    parameters = inspect.signature(PromptsStore.__init__).parameters
    assert "fault_after" not in parameters and "fault" not in parameters, (
        f"the store can be armed at construction time: {list(parameters)}")


# -- content rules that must refuse before anything is written -----------------

def test_empty_whitespace_nul_invalid_utf8_bom_and_oversize_bodies_refuse_before_saving(
        library_service, records):
    created = _create(library_service)
    for bad in (b"", b"   \n\t ", b"has\x00nul", "中文".encode() + b"\xff\xfe",
                CANARY.encode() + b"\xff\xfe", b"x" * (128 * 1024 + 1),
                b"\xef\xbb\xbfleading bom"):
        with pytest.raises(InvalidContentError) as exc:
            library_service.update(created["id"], expected_metadata_version=1,
                                   expected_latest_revision=1,
                                   patch={"body": bad}, operation_key="k-bad")
        assert exc.value.code in ("INVALID_CONTENT", "LIMIT_EXCEEDED"), exc.value.code
        assert CANARY not in str(exc.value), f"the refusal echoed the body: {exc.value}"
    # nothing changed: no revision, no metadata bump, no receipt for k-bad
    assert records.get_revision(created["id"]).body == b"first body"
    assert records.get_record(created["id"]).metadata_version == 1


def test_unknown_patch_fields_and_empty_patch_refuse_without_touching_state(
        library_service, records):
    created = _create(library_service)
    for patch in ({}, {"bodyt": "typo"}, {"title": "ok", "archived": True}):
        with pytest.raises(PromptError) as exc:
            library_service.update(created["id"], expected_metadata_version=1,
                                   expected_latest_revision=1, patch=patch,
                                   operation_key="k-shape")
        assert exc.value.code == "INVALID_REQUEST", exc.value
    assert records.get_record(created["id"]).metadata_version == 1


def test_updates_against_a_missing_id_refuse_not_found(library_service):
    with pytest.raises(NotFoundError) as exc:
        library_service.update("prompt_does-not-exist",
                               expected_metadata_version=1,
                               expected_latest_revision=1,
                               patch={"title": "x"}, operation_key="k-404")
    assert exc.value.code == "NOT_FOUND"


def test_new_prompt_ids_are_unique_across_records_and_scopes(store):
    """The repository must never hand one id to two entities: a collision
    would let one write overwrite another client's record."""
    records = PromptRecords(store)
    seen: set[str] = set()
    for index in range(40):
        outcome, response = records.create(
            kind="instruction", scope=PromptScope("library"),
            title=f"uniq {index}", description=None, body=b"body",
            idempotency=("subject|create|library", f"uniq-key-{index}",
                         {"index": index}))
        assert outcome == "applied"
        assert response["id"] not in seen
        seen.add(response["id"])
    assert len(seen) == 40
