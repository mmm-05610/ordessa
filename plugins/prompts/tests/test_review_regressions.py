"""Review follow-ups PR-R1 / PR-R2 / PR-R3
(specs/011-q2-prompts-commands/review-notes.md, "prompts" section).

* PR-R1 — the transaction-body invariant ("only ``steps()`` inside a write
  transaction") is pinned with an explicit counter-example, and the
  production paths are shown to respect it;
* PR-R2 — an update response never reports a null body digest: a patch that
  does not touch the body echoes the live latest digest;
* PR-R3 — the ``fault_after`` test seam is never injected by the production
  assembly (proved against the assembled plugin, not only the store class).

Gates: G02 (transaction discipline), G05 (response shape honesty).
"""
from __future__ import annotations

import ast
import base64
import sqlite3
from pathlib import Path

import pytest

from ordessa_prompts.api import PromptError, body_digest
from ordessa_prompts.backend.records import PromptRecords
from ordessa_prompts.backend.service import PromptsService
from ordessa_prompts.backend.storage import PromptsStore
from ordessa_prompts.plugin import PromptsServerPlugin

from server_plugin_api import ServerPluginContext

SRC = Path(__file__).resolve().parents[1] / "src" / "ordessa_prompts"


def _enc(text: bytes) -> str:
    return base64.b64encode(text).decode("ascii")


# -- PR-R1 ---------------------------------------------------------------------

def test_a_reader_call_inside_the_write_transaction_fails_and_rolls_back(tmp_path,
                                                                        db_rows):
    """`PromptsStore.read()` opens a second ``BEGIN``, and the write lock is
    not reentrant: calling any repository reader from inside a write
    transaction must fail *and* take the whole transaction down with it —
    no revision, no metadata bump, no receipt. This pins the "only steps()
    inside the transaction body" convention the review asked for."""
    store = PromptsStore(tmp_path / "pr-r1" / "prompts.db")
    records = PromptRecords(store)
    service = PromptsService(records, server_scope="s", subject_provider=lambda: "op")
    prompt_id = service.create(kind="instruction", scope={"kind": "library"},
                              title="invariant", description=None,
                              body=b"original body",
                              operation_key="k-inv-create")["id"]

    def nested_reader(step: int) -> None:
        if step == 1:
            # a repository reader, called from inside the open write txn
            records.get_record(prompt_id)

    store.fault_after = nested_reader
    with pytest.raises(sqlite3.OperationalError) as exc:
        service.update(prompt_id, expected_metadata_version=1,
                       expected_latest_revision=1,
                       patch={"body": b"body that must never persist",
                             "title": "must not persist"},
                       operation_key="k-inv-update")
    assert "cannot start a transaction within a transaction" in str(exc.value)
    store.fault_after = None

    head = db_rows(store, "SELECT * FROM prompt_records WHERE id=?", (prompt_id,))[0]
    assert int(head["metadata_version"]) == 1, "the nested call bumped metadata"
    assert int(head["latest_revision"]) == 1, "the nested call moved latest"
    assert head["title"] == "invariant"
    revisions = db_rows(store, "SELECT * FROM prompt_revisions")
    assert len(revisions) == 1
    assert bytes(revisions[0]["body"]) == b"original body"
    assert db_rows(store, "SELECT * FROM prompt_idempotency WHERE key=?",
                   ("k-inv-update",)) == [], "the nested call left a receipt"
    # the connection is usable again: the same write applies for real
    applied = service.update(prompt_id, expected_metadata_version=1,
                             expected_latest_revision=1,
                             patch={"body": b"body that must never persist",
                                   "title": "must not persist"},
                             operation_key="k-inv-update")
    assert applied["latestRevision"] == 2 and applied["title"] == "must not persist"
    store.close()


def test_the_same_invariant_holds_for_every_write_entry_point(tmp_path, db_rows):
    """No mutation entry point may sneak a reader into its transaction body:
    arming a nested read at every step of every write must fail the same way
    and roll back the same way."""
    ops = ("create", "update", "clone", "archive")
    for op in ops:
        store = PromptsStore(tmp_path / f"pr-r1-{op}" / "prompts.db")
        records = PromptRecords(store)
        service = PromptsService(records, server_scope="s",
                                 subject_provider=lambda: "op")
        target = service.create(kind="instruction", scope={"kind": "library"},
                                title="seed", description=None, body=b"seed body",
                                operation_key="k-seed")["id"]
        before_records = len(db_rows(store, "SELECT * FROM prompt_records"))
        before_revisions = len(db_rows(store, "SELECT * FROM prompt_revisions"))

        def nested(step: int) -> None:
            records.get_record(target)

        store.fault_after = nested
        with pytest.raises(sqlite3.OperationalError):
            if op == "create":
                service.create(kind="instruction", scope={"kind": "library"},
                               title="late", description=None, body=b"late body",
                               operation_key=f"k-{op}")
            elif op == "update":
                service.update(target, expected_metadata_version=1,
                               expected_latest_revision=1,
                               patch={"body": b"late body"},
                               operation_key=f"k-{op}")
            elif op == "clone":
                service.clone(target, target_scope={"kind": "library"},
                              title="late clone", operation_key=f"k-{op}")
            else:
                service.archive(target, expected_metadata_version=1,
                                operation_key=f"k-{op}")
        store.fault_after = None
        assert len(db_rows(store, "SELECT * FROM prompt_records")) == before_records
        assert len(db_rows(store, "SELECT * FROM prompt_revisions")) == before_revisions
        assert db_rows(store, "SELECT * FROM prompt_idempotency WHERE key=?",
                       (f"k-{op}",)) == []
        store.close()


def test_production_paths_never_trigger_the_nested_transaction_error(
        plugin_registration):
    """The invariant is respected on the assembled service: driving every
    mutation through the wire raises no sqlite nesting error at all."""
    _plugin, _registration, handlers = plugin_registration
    prompt_id = handlers["prompts.create"]({
        "requestId": "r-1", "kind": "instruction", "scope": {"kind": "library"},
        "title": "nested check", "body": _enc(b"one"),
        "operationKey": "k-nested-1"})["id"]
    handlers["prompts.update"]({
        "requestId": "r-2", "id": prompt_id, "expectedVersion": 1,
        "expectedRevision": 1, "patch": {"bodyBase64": _enc(b"two")},
        "operationKey": "k-nested-2"})
    handlers["prompts.clone"]({
        "requestId": "r-3", "sourceId": prompt_id,
        "targetScope": {"kind": "library"}, "title": "clone of check",
        "operationKey": "k-nested-3"})
    handlers["prompts.archive"]({
        "requestId": "r-4", "id": prompt_id, "expectedVersion": 2,
        "operationKey": "k-nested-4"})
    handlers["prompts.restore"]({
        "requestId": "r-5", "id": prompt_id, "expectedVersion": 3,
        "operationKey": "k-nested-5"})
    handlers["prompts.importText"]({
        "requestId": "r-6", "contentBase64": _enc(b"imported"),
        "operationKey": "k-nested-6"})
    listed = handlers["prompts.list"]({"requestId": "r-7"})
    snapshot = handlers["prompts.resolveSnapshot"]({
        "requestId": "r-8", "selection": {"instructions": [{"promptId": prompt_id}]}})
    assert listed["items"] and snapshot["resolved"][0]["revision"] == 2
    # every service-level reader also works while no write txn is open
    assert handlers["prompts.get"]({"requestId": "r-9", "id": prompt_id})["title"]
    assert handlers["prompts.getRevision"](
        {"requestId": "r-10", "id": prompt_id, "revision": 1})["revision"] == 1
    assert handlers["prompts.exportText"]({"requestId": "r-11", "id": prompt_id})
    assert handlers["prompts.preview"]({
        "requestId": "r-12", "selection": {"instructions": [{"promptId": prompt_id}]}})


# -- PR-R2 ---------------------------------------------------------------------

def test_an_update_without_a_body_patch_echoes_the_live_digest(store):
    """PR-R2: a caller must never be left guessing between "body untouched"
    and "digest lost"."""
    service = PromptsService(PromptRecords(store), server_scope="s",
                            subject_provider=lambda: "op")
    created = service.create(kind="instruction", scope={"kind": "library"},
                             title="digest", description=None, body=b"v1 body",
                             operation_key="k-digest-create")
    assert created["sha256"] == body_digest(b"v1 body")

    metadata_only = service.update(created["id"], expected_metadata_version=1,
                                   expected_latest_revision=1,
                                   patch={"title": "renamed only"},
                                   operation_key="k-digest-title")
    assert metadata_only["sha256"] == body_digest(b"v1 body")
    assert metadata_only["latestRevision"] == 1
    assert PromptRecords(store).get_revision(created["id"]).sha256 == (
        metadata_only["sha256"])

    described = service.update(created["id"], expected_metadata_version=2,
                               expected_latest_revision=1,
                               patch={"description": "a note"},
                               operation_key="k-digest-desc")
    assert described["sha256"] == body_digest(b"v1 body")

    edited = service.update(created["id"], expected_metadata_version=3,
                            expected_latest_revision=1,
                            patch={"body": b"v2 body"}, operation_key="k-digest-v2")
    assert edited["sha256"] == body_digest(b"v2 body")

    same = service.update(created["id"], expected_metadata_version=4,
                          expected_latest_revision=2,
                          patch={"body": b"v2 body", "title": "again"},
                          operation_key="k-digest-same")
    assert same["latestRevision"] == 2
    assert same["sha256"] == body_digest(b"v2 body")

    # each response agrees with the body it describes, and the last one
    # agrees with the stored latest revision
    responses = [(created, b"v1 body"), (metadata_only, b"v1 body"),
                 (described, b"v1 body"), (edited, b"v2 body"),
                 (same, b"v2 body")]
    latest = PromptRecords(store).get_revision(created["id"])
    for response, body in responses:
        assert response["sha256"], f"null digest in an update response: {response}"
        assert response["sha256"] == body_digest(body), response
    assert latest.sha256 == same["sha256"] == body_digest(b"v2 body")


def test_clone_and_get_responses_always_carry_the_digest(store):
    service = PromptsService(PromptRecords(store), server_scope="s",
                            subject_provider=lambda: "op")
    created = service.create(kind="instruction", scope={"kind": "library"},
                             title="clone source", description=None,
                             body=b"clone me", operation_key="k-shape-src")
    clone = service.clone(created["id"], target_scope={"kind": "library"},
                          title="the clone", operation_key="k-shape-clone")
    assert clone["sha256"] == body_digest(b"clone me")
    fetched = service.get(created["id"])
    assert fetched["sha256"] == body_digest(b"clone me")
    assert fetched["bodyByteSize"] == len(b"clone me")
    revision = service.get_revision(created["id"], 1)
    assert revision["sha256"] == body_digest(b"clone me")
    assert revision["byteSize"] == len(b"clone me")


# -- PR-R3 ---------------------------------------------------------------------

def _call_nodes(source: str, name: str) -> "list[ast.Call]":
    tree = ast.parse(source)
    return [node for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (isinstance(node.func, ast.Name) and node.func.id == name
                 or isinstance(node.func, ast.Attribute) and node.func.attr == name)]


def test_the_production_assembly_never_arms_the_fault_seam():
    """The seam is reachable only by assigning ``store.fault_after`` after
    construction; the Server plugin assembly does not do that, and the store
    constructor accepts no fault parameter at all."""
    plugin_source = (SRC / "plugin.py").read_text(encoding="utf-8")
    assert "fault_after" not in plugin_source, (
        "the production assembly touches the test seam")
    service_source = (SRC / "backend" / "service.py").read_text(encoding="utf-8")
    records_source = (SRC / "backend" / "records.py").read_text(encoding="utf-8")
    assert "fault_after =" not in service_source and "fault_after" not in records_source

    calls = _call_nodes(plugin_source, "PromptsStore")
    assert len(calls) == 1, calls
    construction = calls[0]
    assert len(construction.args) <= 1, (
        "the assembled store passes unexpected positional arguments")
    passed_keywords = {keyword.arg for keyword in construction.keywords}
    assert passed_keywords == set(), (
        f"the assembly configures the store with: {passed_keywords}")


def test_an_assembled_plugin_store_starts_disarmed_and_serves_writes(
        tmp_path):
    context_store_path = tmp_path / "pr-r3" / "prompts.db"
    plugin = PromptsServerPlugin(store_path=context_store_path)
    registration = plugin.build(ServerPluginContext(
        plugin_id=plugin.descriptor().id, data_root=tmp_path, ports={}))
    assembled_store = plugin._store  # noqa: SLF001 - the assembly seam check
    assert assembled_store.fault_after is None
    assert registration.provided_ports["prompts.service"]._records._store.fault_after \
        is None  # noqa: SLF001
    handlers = {descriptor.method_id: descriptor.handler
                for descriptor in registration.methods}
    created = handlers["prompts.create"]({
        "requestId": "r-pr3", "kind": "instruction",
        "scope": {"kind": "library"}, "title": "assembled write",
        "body": "Ym9keQ==", "operationKey": "k-pr3"})
    assert created["latestRevision"] == 1
    assert PromptRecords(assembled_store).get_revision(created["id"]).body == b"body"
    with pytest.raises(PromptError):
        handlers["prompts.get"]({"requestId": "r-pr3-x", "id": "prompt_absent-1"})
    registration.disposal()
