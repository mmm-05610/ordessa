"""T05 / G07 — one snapshot, one transaction, one instant.

Positive: ``resolveSnapshot`` reads every requested latest inside a single
read transaction and freezes the exact revisions and digests.
Required counter-examples (verification.md G07):
* a snapshot may not mix revisions from two instants;
* the composition must not chase ``latest`` twice (one resolution only);
* a slot may not accept a record of the wrong purpose (kind);
* resolving performs no side effect.

Gates: G07. Requirements: FR04, FR05.
"""
from __future__ import annotations

import base64
import sqlite3
import threading

import pytest

from ordessa_prompts.api import (
    NotFoundError,
    PromptError,
    RefKindMismatchError,
    body_digest,
)
from ordessa_prompts.backend.records import PromptRecords
from ordessa_prompts.backend.service import PromptsService
from ordessa_prompts.backend.storage import PromptsStore

BODY_COLUMNS = ("r.prompt_id,r.revision,r.body,r.sha256",)


def _make(service: PromptsService, kind: str = "instruction",
          body: bytes = b"body", title: str = "t", key: str = "k") -> str:
    return service.create(kind=kind, scope={"kind": "library"}, title=title,
                          description=None, body=body, operation_key=key)["id"]


def _traced(store: PromptsStore):
    """Collect every SQL statement the store executes, in order."""
    statements: list[str] = []
    store.connection.set_trace_callback(
        lambda statement: statements.append(statement.strip()))
    return statements


def _windows(statements: "list[str]") -> "list[tuple[int, int]]":
    """The (BEGIN index, COMMIT index) pairs of one traced connection."""
    pairs: list[tuple[int, int]] = []
    open_begin = None
    for index, sql in enumerate(statements):
        if sql == "BEGIN":
            assert open_begin is None, f"nested BEGIN at {index}: {statements}"
            open_begin = index
        elif sql == "COMMIT":
            assert open_begin is not None, f"COMMIT without BEGIN at {index}"
            pairs.append((open_begin, index))
            open_begin = None
    assert open_begin is None, f"an transaction was left open: {statements}"
    return pairs


# -- single transaction --------------------------------------------------------

def test_resolve_latest_runs_one_begin_for_the_whole_resolution(store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    ids = [_make(service, body=f"body {index}".encode(), title=f"t{index}",
                 key=f"k{index}") for index in range(5)]
    statements = _traced(store)
    try:
        rows = PromptRecords(store).resolve_latest(ids)
    finally:
        store.connection.set_trace_callback(None)
    assert len(rows) == 5
    begins = [index for index, sql in enumerate(statements) if sql == "BEGIN"]
    commits = [index for index, sql in enumerate(statements) if sql == "COMMIT"]
    assert len(begins) == 1, f"the resolution opened {len(begins)} transactions"
    assert len(commits) == 1, f"the resolution closed {len(commits)} transactions"
    body_reads = [index for index, sql in enumerate(statements)
                  if BODY_COLUMNS[0] in sql]
    assert len(body_reads) == 5, (
        f"expected five body resolutions, saw {len(body_reads)}")
    assert all(begins[0] < index < commits[0] for index in body_reads), (
        "a body read happened outside the single resolution transaction")


def test_a_snapshot_resolves_all_bodies_in_one_call_and_one_transaction(store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    ids = [_make(service, body=f"content {index}".encode(), title=f"t{index}",
                 key=f"k{index}") for index in range(3)]
    persona_id = _make(service, kind="persona", body=b"persona content",
                       title="p", key="kp")
    calls: list[list[str]] = []
    records = service._records  # noqa: SLF001 - spy on the composition
    original = records.resolve_latest

    def spy(prompt_ids):
        calls.append(list(prompt_ids))
        return original(prompt_ids)

    records.resolve_latest = spy  # type: ignore[method-assign]
    statements = _traced(store)
    try:
        snapshot = service.resolve_snapshot(
            {"instructions": [{"promptId": pid} for pid in ids],
             "persona": {"promptId": persona_id}})
    finally:
        store.connection.set_trace_callback(None)
        records.resolve_latest = original  # type: ignore[method-assign]

    assert len(calls) == 1, f"the snapshot chased latest {len(calls)} times"
    assert set(calls[0]) == {*ids, persona_id}, calls[0]
    assert snapshot.total_body_bytes() == sum(
        len(f"content {index}".encode()) for index in range(3)) + len(
        b"persona content")
    body_reads = [sql for sql in statements if BODY_COLUMNS[0] in sql]
    assert len(body_reads) == 4, body_reads
    # every content read sits inside ONE BEGIN..COMMIT window: the metadata
    # authorisation checks may run earlier, but no body is ever read twice
    # from two different instants
    content_windows = [(start, end) for start, end in _windows(statements)
                       if any(start < index < end
                              for index, sql in enumerate(statements)
                              if BODY_COLUMNS[0] in sql)]
    assert len(content_windows) == 1, (
        f"bodies were read across {len(content_windows)} transactions: {statements}")


def test_a_snapshot_never_mixes_two_instants(tmp_path):
    """A reader holds one transaction open and reads record 1; a second
    client commits a new revision of record 2 *while that transaction is
    open*; the open transaction still reads record 2's old revision — that
    is exactly the guarantee the single-transaction resolution relies on."""
    path = tmp_path / "instant" / "prompts.db"
    reader_store = PromptsStore(path)
    reader = PromptsService(PromptRecords(reader_store), server_scope="s",
                            subject_provider=lambda: "reader")
    first = _make(reader, body=b"first old", title="one", key="k-one")
    second = _make(reader, body=b"second old", title="two", key="k-two")

    writer_store = PromptsStore(path)
    writer = PromptsService(PromptRecords(writer_store), server_scope="s",
                            subject_provider=lambda: "writer")
    done = threading.Event()
    outcome: dict[str, object] = {}

    def concurrent_write() -> None:
        try:
            writer.update(second, expected_metadata_version=1,
                          expected_latest_revision=1,
                          patch={"body": b"second NEW"}, operation_key="k-race")
            outcome["result"] = "committed"
        except BaseException as exc:  # noqa: BLE001 - recorded for the assert
            outcome["result"] = f"refused:{type(exc).__name__}"
        finally:
            done.set()

    # the resolution statement the repository itself uses, kept byte-identical
    resolve_sql = (
        "SELECT r.prompt_id,r.revision,r.body,r.sha256,r.created_at,"
        "m.kind,m.title,m.scope_kind,m.profile_id,m.archived,m.metadata_version "
        "FROM prompt_revisions r JOIN prompt_records m ON m.id=r.prompt_id "
        "WHERE r.prompt_id=? AND r.revision=m.latest_revision")

    thread = threading.Thread(target=concurrent_write)
    conn = reader_store.connection
    conn.execute("BEGIN")
    try:
        row_one = conn.execute(resolve_sql, (first,)).fetchone()
        assert bytes(row_one["body"]) == b"first old"
        thread.start()
        # the writer is blocked on the open read transaction; give it a moment
        assert not done.wait(0.3), "the writer committed inside an open read txn"
        row_two = conn.execute(resolve_sql, (second,)).fetchone()
        assert bytes(row_two["body"]) == b"second old", (
            "the open snapshot saw a revision committed after it started")
        assert int(row_two["revision"]) == 1
    finally:
        conn.execute("COMMIT")
    thread.join(timeout=60)
    assert not thread.is_alive(), "the writer never unblocked"
    assert outcome["result"] == "committed", outcome
    # after the snapshot closed, the new revision is live for the next one
    after = PromptRecords(reader_store).get_revision(second)
    assert after.body == b"second NEW" and after.revision == 2
    writer_store.close()
    reader_store.close()


# -- frozen revisions, digests and determinism ---------------------------------

def test_snapshot_freezes_exact_revisions_and_digests(store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    prompt_id = _make(service, body=b"snapshot me", title="frozen", key="k-freeze")
    snapshot = service.resolve_snapshot({"instructions": [{"promptId": prompt_id}]})
    item = snapshot.resolved[0]
    assert (item.revision, item.sha256) == (1, body_digest(b"snapshot me"))
    assert snapshot.instructions_order == (prompt_id,)
    assert snapshot.source_metadata_versions == {prompt_id: 1}
    assert snapshot.server_scope == "s"
    # a second resolution of unchanged content yields the same content digest
    again = service.resolve_snapshot({"instructions": [{"promptId": prompt_id}]})
    assert again.content_digest == snapshot.content_digest
    assert again.snapshot_id != snapshot.snapshot_id
    # an edit moves the digest, and the old snapshot object is untouched
    service.update(prompt_id, expected_metadata_version=1,
                   expected_latest_revision=1,
                   patch={"body": b"snapshot me v2"}, operation_key="k-freeze-2")
    moved = service.resolve_snapshot({"instructions": [{"promptId": prompt_id}]})
    assert moved.resolved[0].revision == 2
    assert moved.content_digest != snapshot.content_digest
    assert item.revision == 1 and item.body == b"snapshot me"


def test_the_digest_order_is_the_selection_order_not_the_id_order(store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    ids = [_make(service, body=f"body {index}".encode(), title=f"t{index}",
                 key=f"k{index}") for index in range(3)]
    forward = service.resolve_snapshot(
        {"instructions": [{"promptId": pid} for pid in ids]})
    backward = service.resolve_snapshot(
        {"instructions": [{"promptId": pid} for pid in reversed(ids)]})
    assert forward.instructions_order == tuple(ids)
    assert backward.instructions_order == tuple(reversed(ids))
    assert forward.content_digest != backward.content_digest, (
        "an ordered selection must digest in the chosen order")
    assert [item.body for item in backward.resolved] == [
        f"body {index}".encode() for index in reversed(range(3))]


# -- slot/purpose validation ----------------------------------------------------

def test_each_slot_only_accepts_its_own_purpose(store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    instruction = _make(service, kind="instruction", body=b"an instruction",
                        title="i", key="k-i")
    persona = _make(service, kind="persona", body=b"a persona", title="p",
                    key="k-p")
    replacement = _make(service, kind="system-replacement", body=b"a replacement",
                        title="r", key="k-r")

    ok = service.resolve_snapshot({"instructions": [{"promptId": instruction}],
                                   "persona": {"promptId": persona},
                                   "systemReplacement": {"promptId": replacement}})
    assert [item.kind for item in ok.resolved] == [
        "instruction", "persona", "system-replacement"]

    with pytest.raises(RefKindMismatchError) as exc:
        service.resolve_snapshot({"instructions": [{"promptId": persona}]})
    assert exc.value.code == "REF_KIND_MISMATCH"
    assert "instruction" in exc.value.message
    with pytest.raises(RefKindMismatchError):
        service.resolve_snapshot({"instructions": [{"promptId": replacement}]})
    instruction2 = _make(service, kind="instruction", body=b"another instruction",
                         title="i2", key="k-i2")
    with pytest.raises(RefKindMismatchError):
        service.resolve_snapshot({"instructions": [{"promptId": instruction}],
                                 "persona": {"promptId": instruction2}})
    with pytest.raises(RefKindMismatchError):
        service.resolve_snapshot(
            {"systemReplacement": {"promptId": persona}})
    # the same record may not fill two slots at all (a shape refusal, before
    # any kind check)
    with pytest.raises(PromptError) as overlap:
        service.resolve_snapshot({"instructions": [{"promptId": instruction}],
                                 "persona": {"promptId": instruction}})
    assert overlap.value.code == "INVALID_CONTENT"


def test_duplicate_and_conflicting_refs_refuse_before_resolution(store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    instruction = _make(service, body=b"i", title="i", key="k-dup-i")
    persona = _make(service, kind="persona", body=b"p", title="p", key="k-dup-p")

    with pytest.raises(PromptError) as duplicate:
        service.resolve_snapshot({"instructions": [{"promptId": instruction},
                                                   {"promptId": instruction}]})
    assert duplicate.value.code == "INVALID_CONTENT"
    with pytest.raises(PromptError) as overlap:
        service.resolve_snapshot({"instructions": [{"promptId": persona}],
                                  "persona": {"promptId": persona}})
    assert overlap.value.code == "INVALID_CONTENT"
    with pytest.raises(PromptError) as same:
        service.resolve_snapshot({"persona": {"promptId": persona},
                                  "systemReplacement": {"promptId": persona}})
    assert same.value.code == "INVALID_CONTENT"
    with pytest.raises(PromptError) as pin:
        service.resolve_snapshot({"instructions": [{"promptId": instruction,
                                                   "track": "revision"}]})
    assert pin.value.code == "INVALID_CONTENT"


def test_resolving_an_unknown_id_refuses_not_found(store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    with pytest.raises(NotFoundError):
        service.resolve_snapshot({"instructions": [{"promptId": "prompt_absent-9"}]})


# -- no side effects -------------------------------------------------------------

def test_resolve_and_preview_write_nothing_and_create_no_files(tmp_path, store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    prompt_id = _make(service, body=b"side effect free", title="x", key="k-x")
    before = {table: len(list(store.connection.execute(f"SELECT * FROM {table}")))
              for table in ("prompt_records", "prompt_revisions",
                           "prompt_idempotency")}
    snapshot = service.resolve_snapshot({"instructions": [{"promptId": prompt_id}]})
    preview = service.preview({"instructions": [{"promptId": prompt_id}]})
    after = {table: len(list(store.connection.execute(f"SELECT * FROM {table}")))
             for table in ("prompt_records", "prompt_revisions",
                           "prompt_idempotency")}
    assert before == after, "resolution wrote rows"
    wire = snapshot.as_wire()
    assert base64.b64decode(wire["resolved"][0]["bodyBase64"]) == b"side effect free"
    assert preview["basis"] == "same-transaction snapshot as resolve_snapshot"
    assert preview["claim"].startswith("This is the Ordessa-configured content only")
    assert "NOT_NATIVE_FULL_SYSTEM_PROMPT" in preview["diagnostics"]
    assert not [path for path in tmp_path.rglob("*")
                if path.is_file() and path.suffix != ".db"]


def test_preview_labels_its_order_and_never_claims_the_native_prompt(store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "op")
    instruction = _make(service, body=b"i", title="i", key="k-pv-i")
    persona = _make(service, kind="persona", body=b"p", title="p", key="k-pv-p")
    replacement = _make(service, kind="system-replacement", body=b"r", title="r",
                        key="k-pv-r")
    preview = service.preview({"instructions": [{"promptId": instruction}],
                               "persona": {"promptId": persona},
                               "systemReplacement": {"promptId": replacement}})
    assert preview["compositionOrder"] == ["system-replacement", "persona",
                                          f"instruction:{instruction}"]
    assert preview["revisions"] == {instruction: 1, persona: 1, replacement: 1}
    assert preview["totalBodyBytes"] == len(b"i") + len(b"p") + len(b"r")
    assert "full system prompt" in preview["claim"].lower()
