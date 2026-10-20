"""T04 / G03 — clone, archive, restore and the no-hard-delete rule.

Positive: clone/archive/restore work and existing references keep
resolving. Required counter-examples (verification.md G03):
* archiving must not break a reference that already exists;
* a clone must not follow the source's later changes;
* a retried create must not mint a second entity;
* nothing is ever hard-deleted — the ``RAISE(ABORT)`` triggers themselves
  are asserted, so immutability is storage-enforced, not service discipline.

Gates: G03. Requirements: FR02, FR06.
"""
from __future__ import annotations

import re

import pytest

from ordessa_prompts.api import (
    ArchivedSelectionError,
    IdempotencyConflictError,
    NotFoundError,
    PromptScope,
    RevisionConflictError,
    body_digest,
)
from ordessa_prompts.backend.records import PromptRecords
from ordessa_prompts.backend.service import PromptsService

FORBIDDEN_API_NAME = re.compile(r"(?:^|_)(delete|purge|erase|destroy|drop)(?:_|$)")


def _make(service: PromptsService, body: bytes = b"source body",
          key: str = "k-src", title: str = "source") -> str:
    return service.create(kind="instruction", scope={"kind": "library"},
                          title=title, description=None, body=body,
                          operation_key=key)["id"]


# -- clone ---------------------------------------------------------------------

def test_clone_copies_the_bytes_of_that_moment_and_ignores_later_source_changes(
        library_service, records):
    source_id = _make(library_service, body=b"v1 source")
    clone = library_service.clone(source_id, target_scope={"kind": "library"},
                                  title="cloned", operation_key="k-clone")
    assert clone["id"] != source_id
    assert clone["sourceRevision"] == 1
    assert clone["sha256"] == body_digest(b"v1 source")
    assert records.get_revision(clone["id"]).body == b"v1 source"

    # the source moves on; the clone must not follow it
    library_service.update(source_id, expected_metadata_version=1,
                           expected_latest_revision=1,
                           patch={"body": b"v2 source"}, operation_key="k-src-2")
    assert records.get_revision(source_id).body == b"v2 source"
    after = records.get_revision(clone["id"])
    assert after.body == b"v1 source", "a clone must never follow its source"
    assert after.revision == 1 and after.sha256 == body_digest(b"v1 source")


def test_clone_of_an_explicit_source_revision_takes_that_revision(library_service,
                                                                  records):
    source_id = _make(library_service, body=b"v1 source")
    library_service.update(source_id, expected_metadata_version=1,
                           expected_latest_revision=1,
                           patch={"body": b"v2 source"}, operation_key="k-src-2")
    clone = library_service.clone(source_id, target_scope={"kind": "library"},
                                  title="from v1", source_revision=1,
                                  operation_key="k-clone-v1")
    assert records.get_revision(clone["id"]).body == b"v1 source"
    assert clone["sourceRevision"] == 1


def test_clone_shares_no_mutable_row_with_the_source(library_service, records):
    source_id = _make(library_service)
    clone_id = library_service.clone(source_id, target_scope={"kind": "library"},
                                     title="twin", operation_key="k-twin")["id"]
    library_service.update(clone_id, expected_metadata_version=1,
                           expected_latest_revision=1,
                           patch={"body": b"clone edited"}, operation_key="k-clone-2")
    assert records.get_revision(source_id).body == b"source body"
    assert records.get_record(source_id).latest_revision == 1
    assert records.get_revision(clone_id).body == b"clone edited"


def test_clone_refuses_a_missing_source_or_revision(library_service):
    with pytest.raises(NotFoundError) as exc:
        library_service.clone("prompt_absent-1", target_scope={"kind": "library"},
                              title="t", operation_key="k-1")
    assert exc.value.code == "NOT_FOUND"
    source_id = _make(library_service)
    with pytest.raises(NotFoundError):
        library_service.clone(source_id, target_scope={"kind": "library"},
                              title="t", source_revision=99,
                              operation_key="k-2")


def test_clone_into_a_profile_scope_requires_that_scope_authorisation(store):
    """Copying is not a silent scope promotion: the target profile scope is
    authorised exactly like a create (G06/G08)."""
    bare = PromptsService(PromptRecords(store), server_scope="s",
                          subject_provider=lambda: "operator-1")
    source_id = _make(bare)
    with pytest.raises(Exception) as exc:
        bare.clone(source_id, target_scope={"kind": "profile",
                                            "profileId": "alpha"},
                   title="t", operation_key="k-p")
    assert exc.value.code == "DEPENDENCY_UNAVAILABLE", exc.value


# -- archive / restore ---------------------------------------------------------

def test_archive_filters_new_selection_lists_but_existing_references_still_resolve(
        library_service, records):
    referenced = _make(library_service, body=b"referenced body", key="k-ref")
    _make(library_service, body=b"fresh body", key="k-fresh", title="fresh")
    selection = {"instructions": [{"promptId": referenced}], "persona": None,
                 "systemReplacement": None}
    before = library_service.resolve_snapshot(selection)

    library_service.archive(referenced, expected_metadata_version=1,
                            operation_key="k-archive")

    listed = library_service.list()
    assert referenced not in [item["id"] for item in listed["items"]], (
        "archived content must not appear in a new selection list")
    shown = library_service.list(include_archived=True)
    assert referenced in [item["id"] for item in shown["items"]]

    # an existing reference keeps resolving its latest: the archive did not
    # disconnect anything
    after = library_service.resolve_snapshot(selection)
    assert [item.body for item in after.resolved] == [b"referenced body"]
    assert after.resolved[0].revision == before.resolved[0].revision
    # ... and a later edit of restored content still reaches that reference
    library_service.restore(referenced, expected_metadata_version=2,
                            operation_key="k-restore")
    library_service.update(referenced, expected_metadata_version=3,
                           expected_latest_revision=1,
                           patch={"body": b"referenced body v2"},
                           operation_key="k-after-restore")
    moved = library_service.resolve_snapshot(selection)
    assert moved.resolved[0].revision == 2
    assert moved.resolved[0].body == b"referenced body v2"


def test_archived_content_is_read_only_and_restore_makes_it_editable_again(
        library_service, records):
    prompt_id = _make(library_service)
    library_service.archive(prompt_id, expected_metadata_version=1,
                            operation_key="k-arch")
    for index, patch in enumerate(({"body": b"new text"},
                                   {"title": "renamed while archived"},
                                   {"description": "note while archived"})):
        with pytest.raises(ArchivedSelectionError) as exc:
            library_service.update(prompt_id, expected_metadata_version=2,
                                   expected_latest_revision=1, patch=patch,
                                   operation_key=f"k-arch-{index}")
        assert exc.value.code == "ARCHIVED_SELECTION"
    head = records.get_record(prompt_id)
    assert head.metadata_version == 2 and head.latest_revision == 1
    assert head.archived is True

    restored = library_service.restore(prompt_id, expected_metadata_version=2,
                                       operation_key="k-restore")
    assert restored["archived"] is False and restored["metadataVersion"] == 3
    edited = library_service.update(prompt_id, expected_metadata_version=3,
                                    expected_latest_revision=1,
                                    patch={"body": b"editable again"},
                                    operation_key="k-edit-after-restore")
    assert edited["latestRevision"] == 2
    assert records.get_revision(prompt_id).body == b"editable again"


def test_archive_and_restore_are_metadata_cas_protected(library_service):
    prompt_id = _make(library_service)
    library_service.archive(prompt_id, expected_metadata_version=1,
                            operation_key="k-a1")
    with pytest.raises(RevisionConflictError) as exc:
        library_service.archive(prompt_id, expected_metadata_version=1,
                                operation_key="k-a2")
    assert exc.value.code == "REVISION_CONFLICT"
    assert exc.value.details["currentMetadataVersion"] == 2
    with pytest.raises(RevisionConflictError):
        library_service.restore(prompt_id, expected_metadata_version=1,
                                operation_key="k-r1")


# -- retries must not double-apply --------------------------------------------

def test_retry_of_the_same_key_and_payload_replays_without_a_second_entity(
        library_service, store, db_rows):
    first = library_service.create(kind="instruction", scope={"kind": "library"},
                                   title="only once", description=None,
                                   body=b"one body", operation_key="k-once")
    retry = library_service.create(kind="instruction", scope={"kind": "library"},
                                   title="only once", description=None,
                                   body=b"one body", operation_key="k-once")
    assert first["replayed"] is False and retry["replayed"] is True
    assert retry["id"] == first["id"], "a retry minted a second entity"
    rows = db_rows(store, "SELECT * FROM prompt_records")
    assert len(rows) == 1, f"the retry created an extra record row: {len(rows)}"
    assert len(db_rows(store, "SELECT * FROM prompt_revisions")) == 1


def test_same_key_with_a_different_payload_is_refused_and_changes_nothing(
        library_service, store, db_rows):
    first = library_service.create(kind="instruction", scope={"kind": "library"},
                                   title="original", description=None,
                                   body=b"one body", operation_key="k-clash")
    with pytest.raises(IdempotencyConflictError) as exc:
        library_service.create(kind="instruction", scope={"kind": "library"},
                               title="sneaky second", description=None,
                               body=b"a different body", operation_key="k-clash")
    assert exc.value.code == "IDEMPOTENCY_CONFLICT"
    assert len(db_rows(store, "SELECT * FROM prompt_records")) == 1
    assert library_service.get(first["id"])["title"] == "original"
    assert library_service.get(first["id"])["bodyBase64"]  # body untouched
    records = PromptRecords(store)
    assert records.get_revision(first["id"]).body == b"one body"


def test_a_write_without_a_caller_key_never_dedupes_real_work(store):
    """Without an operationKey the service mints a per-request key, so two
    genuine creates stay two entities and neither is reported as a replay."""
    service = PromptsService(PromptRecords(store), server_scope="s",
                             subject_provider=lambda: "operator-1")
    first = service.create(kind="instruction", scope={"kind": "library"},
                           title="no key one", description=None, body=b"body one")
    second = service.create(kind="instruction", scope={"kind": "library"},
                            title="no key two", description=None, body=b"body two")
    assert first["replayed"] is False and second["replayed"] is False
    assert first["id"] != second["id"]
    assert len(PromptRecords(store).list_records()[0]) == 2


# -- no hard delete, ever ------------------------------------------------------

def test_no_public_api_can_hard_delete_content(library_service, records):
    """The domain surface must not offer deletion at all (first release:
    history revisions and frozen snapshots are kept)."""
    for target in (library_service, records):
        public = [name for name in dir(target) if not name.startswith("_")]
        offenders = [name for name in public if FORBIDDEN_API_NAME.search(name)]
        assert offenders == [], (
            f"{type(target).__name__} exposes a deletion entry point: {offenders}")
        assert not [name for name in public
                    if any(word in name.lower()
                           for word in ("delete", "purge", "destroy", "erase"))]


def test_database_triggers_refuse_revision_update_revision_delete_and_record_delete(
        library_service, store, db_rows):
    """G03/G02 storage-level proof: the rules are triggers, so even a client
    holding the connection directly cannot rewrite or drop content."""
    prompt_id = _make(library_service, body=b"immutable body")
    before_revisions = db_rows(store, "SELECT * FROM prompt_revisions")
    assert len(before_revisions) == 1

    with pytest.raises(Exception) as update_exc:
        store.connection.execute("UPDATE prompt_revisions SET body=? WHERE prompt_id=?",
                                 (b"tampered body", prompt_id))
    assert "immutable" in str(update_exc.value), update_exc.value

    with pytest.raises(Exception) as delete_rev_exc:
        store.connection.execute("DELETE FROM prompt_revisions WHERE prompt_id=?",
                                 (prompt_id,))
    assert "must not be deleted" in str(delete_rev_exc.value), delete_rev_exc.value

    with pytest.raises(Exception) as delete_rec_exc:
        store.connection.execute("DELETE FROM prompt_records WHERE id=?", (prompt_id,))
    assert "hard-deleted" in str(delete_rec_exc.value), delete_rec_exc.value

    store.connection.rollback()
    after_revisions = db_rows(store, "SELECT * FROM prompt_revisions")
    assert [bytes(row["body"]) for row in after_revisions] == [b"immutable body"]
    assert len(db_rows(store, "SELECT * FROM prompt_records")) == 1
    assert PromptRecords(store).get_record(prompt_id).id == prompt_id


def test_revisions_are_never_modified_in_place_across_a_normal_edit(library_service,
                                                                    store, db_rows):
    prompt_id = _make(library_service, body=b"revision one")
    library_service.update(prompt_id, expected_metadata_version=1,
                           expected_latest_revision=1,
                           patch={"body": b"revision two"}, operation_key="k-r2")
    rows = {int(row["revision"]): (bytes(row["body"]), row["sha256"])
            for row in db_rows(store, "SELECT * FROM prompt_revisions")}
    assert set(rows) == {1, 2}
    assert rows[1] == (b"revision one", body_digest(b"revision one"))
    assert rows[2] == (b"revision two", body_digest(b"revision two"))


def test_a_frozen_snapshot_object_keeps_its_revisions_after_later_edits(
        library_service):
    prompt_id = _make(library_service, body=b"snapshot body")
    selection = {"instructions": [{"promptId": prompt_id}]}
    frozen = library_service.resolve_snapshot(selection)
    library_service.update(prompt_id, expected_metadata_version=1,
                           expected_latest_revision=1,
                           patch={"body": b"edited later"}, operation_key="k-later")
    assert frozen.resolved[0].revision == 1
    assert frozen.resolved[0].body == b"snapshot body"
    assert frozen.content_digest
    later = library_service.resolve_snapshot(selection)
    assert later.resolved[0].revision == 2
    assert later.content_digest != frozen.content_digest
