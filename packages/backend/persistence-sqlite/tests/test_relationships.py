"""005 T005-11 gates — durable E5 persistent references over SQLite.

Pinned semantics (in-memory reference ``pacthold.environment``, contract E5 in
``specs/026-open-environment-migration/contracts/resource-references.md``):

* published relations survive store reopen AND declarer absence —
  ``inspect_incoming`` is a key lookup on the declared-relations table, never
  live activation state and never a business-DB scan;
* full replacement per (source, revision); the SAME set under the SAME
  operation id is a no-op (row count AND durable coverage epoch unchanged);
* new relations and open destructive reservations never pass the same gate:
  publish is refused while a delete/rewrite reservation holds the target, and
  only ``release_reservation(executed=True)`` reopens it;
* published relations refuse delete/rewrite prepare; the refused intent still
  leaves a DURABLE reservation that survives close/reopen (never auto-released);
* crash windows (real SIGKILL subprocesses, ``print(flush=True)`` + sleep
  handshake as in ``test_store_port.py``): a relation set is either fully
  published or fully absent after a crash — never a half set (transaction
  atomicity) — and a committed set survives SIGKILL (WAL durability).

The mid-publish window is made deterministic by holding the transaction open
from a wrapped module-level write helper in the CHILD process (fault injection
at the transaction boundary); the parent then SIGKILLs the child exactly
between the partial write and the commit. No assertion is conditioned on
timing: every window asserts a strict invariant.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ordessa_persistence_sqlite import SqliteStorePort
from ordessa_persistence_sqlite.relationships import SqliteRelationshipStore
from ordessa_environment_api import (
    AdmissionRefusedError,
    CanonicalFactTarget,
    ChangeReservation,
    EnvironmentError,
    IdentityMismatchError,
    PersistentReference,
    ReferenceStatus,
    RevisionSelector,
)

_SOURCE = CanonicalFactTarget(realm="profile", identity_namespace="workspace", stable_entity_id="profile-1")
_SOURCE_2 = CanonicalFactTarget(realm="profile", identity_namespace="workspace", stable_entity_id="profile-2")
_TARGET = CanonicalFactTarget(realm="provider", identity_namespace="workspace", stable_entity_id="provider-1")
_TARGET_2 = CanonicalFactTarget(realm="model", identity_namespace="workspace", stable_entity_id="model-9")
_SOURCE_TEXT = "profile:workspace:profile-1"
_TARGET_TEXT = "provider:workspace:provider-1"


def _ref(
    relation_id: str,
    *,
    source: CanonicalFactTarget = _SOURCE,
    source_revision: str = "v1",
    target: CanonicalFactTarget = _TARGET,
    operation_id: str = "op-pub-1",
) -> PersistentReference:
    return PersistentReference(
        relation_id=relation_id,
        source_key=source,
        source_revision=source_revision,
        target_key=target,
        revision_selector=RevisionSelector(op="exact", revision="v1"),
        declaring_owner_domain="profile",
        policy_contract_id="profile.resource-ref",
        policy_contract_version=1,
        operation_id=operation_id,
        source_commit_evidence="ev-1",
    )


def _relation_ids(view) -> list[str]:
    return sorted(r.relation_id for r in view["relations"])


# -- positive: published relations survive reopen and declarer absence ---------


def test_published_relations_survive_reopen_and_declarer_absence(tmp_path):
    db = tmp_path / "rel.sqlite3"
    store1 = SqliteStorePort(db)
    port1 = SqliteRelationshipStore(store1)
    port1.publish_reference_set(
        _SOURCE, "v1", (_ref("rel-1"), _ref("rel-2", target=_TARGET_2)), "op-pub-1"
    )
    stamped_epoch = port1.inspect_incoming(_TARGET)["relations"][0].coverage_epoch
    store1.close()  # declarer gone: process exits, nothing stays in memory

    store2 = SqliteStorePort(db)  # same path, clean reopen (writer released)
    port2 = SqliteRelationshipStore(store2)
    try:
        provider_view = port2.inspect_incoming(_TARGET, "archive")
        assert _relation_ids(provider_view) == ["rel-1"]
        assert provider_view["coverage"] == "known"
        assert provider_view["blocking-destructive-change"] is False
        assert provider_view["target"] == _TARGET
        rel = provider_view["relations"][0]
        assert rel.status is ReferenceStatus.PUBLISHED  # retire activation never unpublishes
        assert rel.source_key == _SOURCE
        assert rel.target_key == _TARGET
        assert rel.revision_selector == RevisionSelector(op="exact", revision="v1")
        assert rel.operation_id == "op-pub-1"
        assert rel.coverage_epoch == stamped_epoch  # restart never re-stamps

        model_view = port2.inspect_incoming(_TARGET_2, "delete")
        assert _relation_ids(model_view) == ["rel-2"]
        assert model_view["blocking-destructive-change"] is True

        absent = port2.inspect_incoming(
            CanonicalFactTarget("provider", "workspace", "provider-absent"), "delete"
        )
        assert absent["relations"] == ()
        assert absent["coverage"] == "unknown"  # never reported as proven 'no references'
        assert absent["blocking-destructive-change"] is False
    finally:
        store2.close()


# -- idempotency: same set + same operation is a no-op --------------------------


def test_republish_same_set_same_operation_is_a_noop(tmp_path):
    store = SqliteStorePort(tmp_path / "rel.sqlite3")
    port = SqliteRelationshipStore(store)
    try:
        the_set = (_ref("rel-1"), _ref("rel-2", target=_TARGET_2))
        port.publish_reference_set(_SOURCE, "v1", the_set, "op-pub-1")

        def source_row_count() -> int:
            return store.transaction().execute(
                "SELECT COUNT(*) FROM env_relations WHERE source_entity=? AND source_revision=?",
                (_SOURCE_TEXT, "v1"),
            ).fetchone()[0]

        assert source_row_count() == 2
        before_epoch = port.inspect_incoming(_TARGET)["relations"][0].coverage_epoch

        port.publish_reference_set(_SOURCE, "v1", the_set, "op-pub-1")  # same set, same op
        assert source_row_count() == 2  # count unchanged — no delete/reinsert cycle
        after_epoch = port.inspect_incoming(_TARGET)["relations"][0].coverage_epoch
        assert after_epoch == before_epoch  # epoch NOT re-stamped → genuinely a no-op
        assert _relation_ids(port.inspect_incoming(_TARGET, "archive")) == ["rel-1"]

        # a DIFFERENT set for the same (source, revision) is a full replacement
        port.publish_reference_set(_SOURCE, "v1", (_ref("rel-1"),), "op-pub-2")
        assert source_row_count() == 1
        assert _relation_ids(port.inspect_incoming(_TARGET, "archive")) == ["rel-1"]
        assert port.inspect_incoming(_TARGET_2)["coverage"] == "unknown"
    finally:
        store.close()


def test_relation_source_mismatch_is_refused(tmp_path):
    store = SqliteStorePort(tmp_path / "rel.sqlite3")
    port = SqliteRelationshipStore(store)
    try:
        with pytest.raises(IdentityMismatchError):
            port.publish_reference_set(
                _SOURCE, "v1", (_ref("rel-1", source=_SOURCE_2),), "op-x"
            )
        with pytest.raises(IdentityMismatchError):  # same key, different revision
            port.publish_reference_set(_SOURCE, "v2", (_ref("rel-1"),), "op-x")
        assert port.inspect_incoming(_TARGET)["relations"] == ()
    finally:
        store.close()


def test_tuple_and_encoded_key_forms_normalize_to_one_canonical_target(tmp_path):
    store = SqliteStorePort(tmp_path / "rel.sqlite3")
    port = SqliteRelationshipStore(store)
    try:
        port.publish_reference_set(
            ("profile", "workspace", "profile-1"), "v1", (_ref("rel-1"),), "op-pub-1"
        )
        view = port.inspect_incoming(_TARGET_TEXT, "archive")  # encoded string form
        assert _relation_ids(view) == ["rel-1"]
        assert view["target"] == _TARGET  # normalized back to the frozen DTO
        # an entity id containing ':' must round-trip exactly (split(":", 2))
        colon = CanonicalFactTarget("profile", "workspace", "profile:extra")
        port.publish_reference_set(
            colon, "v1", (_ref("rel-9", source=colon, target=_TARGET_2),), "op-pub-9"
        )
        assert port.inspect_incoming(_TARGET_2)["relations"][0].source_key == colon
        with pytest.raises(ValueError):
            port.inspect_incoming("provider:workspace")  # not a full triple
    finally:
        store.close()


# -- counterexample 1: destructive reservation gates publish --------------------


def test_destructive_reservation_blocks_publish_until_executed_release(tmp_path):
    store = SqliteStorePort(tmp_path / "rel.sqlite3")
    port = SqliteRelationshipStore(store)
    try:
        reservation = port.prepare_resource_change(_TARGET, "v1", "delete", "op-del-1")
        assert isinstance(reservation, ChangeReservation)
        assert reservation.change_kind == "delete"

        with pytest.raises(AdmissionRefusedError, match="destructive"):
            port.publish_reference_set(_SOURCE, "v1", (_ref("rel-1"),), "op-pub-1")
        assert port.inspect_incoming(_TARGET)["relations"] == ()  # nothing sneaked past the gate

        # one open ticket per target — even an archive kind waits its turn
        with pytest.raises(AdmissionRefusedError, match="already holds"):
            port.prepare_resource_change(_TARGET, "v1", "archive", "op-arch-1")

        # not-executed release keeps the reservation (and the gate shut)
        port.release_reservation("op-del-1", executed=False)
        with pytest.raises(AdmissionRefusedError):
            port.publish_reference_set(_SOURCE, "v1", (_ref("rel-1"),), "op-pub-1")

        # releasing an unknown operation id is a silent no-op — the gate stays
        port.release_reservation("op-absent", executed=True)
        with pytest.raises(AdmissionRefusedError):
            port.publish_reference_set(_SOURCE, "v1", (_ref("rel-1"),), "op-pub-1")

        # the ONLY release path: explicit executed=True
        port.release_reservation("op-del-1", executed=True)
        port.publish_reference_set(_SOURCE, "v1", (_ref("rel-1"),), "op-pub-1")
        assert _relation_ids(port.inspect_incoming(_TARGET, "archive")) == ["rel-1"]

        # an archive ticket is NOT destructive: new relations still pass the gate
        port.prepare_resource_change(_TARGET, "v1", "archive", "op-arch-2")
        port.publish_reference_set(
            _SOURCE_2, "v1", (_ref("rel-9", source=_SOURCE_2),), "op-pub-2"
        )
        port.release_reservation("op-arch-2", executed=True)
    finally:
        store.close()


# -- counterexample 2: published relations gate destructive prepare, and the
#    reservation is durable across reopen ---------------------------------------


def test_published_relations_block_destructive_prepare_and_reservation_is_durable(tmp_path):
    db = tmp_path / "rel.sqlite3"
    store1 = SqliteStorePort(db)
    port1 = SqliteRelationshipStore(store1)
    port1.publish_reference_set(_SOURCE, "v1", (_ref("rel-1"),), "op-pub-1")
    with pytest.raises(AdmissionRefusedError, match="rel-1"):
        port1.prepare_resource_change(_TARGET, "v9", "delete", "op-del-1")
    store1.close()  # reopen must NOT dissolve the recorded reservation

    store2 = SqliteStorePort(db)
    port2 = SqliteRelationshipStore(store2)
    try:
        # the refused destructive intent survived the restart: new relations to
        # the target stay gated (external commit unknown keeps the block, E5)
        with pytest.raises(AdmissionRefusedError, match="op-del-1"):
            port2.publish_reference_set(
                _SOURCE_2, "v1", (_ref("rel-2", source=_SOURCE_2),), "op-pub-2"
            )
        with pytest.raises(AdmissionRefusedError, match="already holds"):
            port2.prepare_resource_change(_TARGET, "v9", "rewrite", "op-del-2")

        # a different target is untouched — ordinary work continues (no env-wide lock)
        port2.prepare_resource_change(_TARGET_2, "v1", "delete", "op-del-3")
        port2.release_reservation("op-del-3", executed=True)

        # explicit executed release reopens the ticket gate; the PUBLISHED
        # relation then blocks the destructive prepare on its own
        port2.release_reservation("op-del-1", executed=True)
        with pytest.raises(AdmissionRefusedError, match="rel-1"):
            port2.prepare_resource_change(_TARGET, "v9", "rewrite", "op-del-2")
        port2.release_reservation("op-del-2", executed=True)

        # archive is not destructive: published relations do not block it
        archive = port2.prepare_resource_change(_TARGET, "v9", "archive", "op-arch-1")
        assert archive.change_kind == "archive"
        port2.release_reservation("op-arch-1", executed=True)

        # and no step above ever touched the published relation itself
        assert _relation_ids(port2.inspect_incoming(_TARGET, "delete")) == ["rel-1"]
    finally:
        store2.close()


def test_unknown_change_kind_is_typed_refused(tmp_path):
    store = SqliteStorePort(tmp_path / "rel.sqlite3")
    port = SqliteRelationshipStore(store)
    try:
        with pytest.raises(EnvironmentError, match="unknown change kind"):
            port.prepare_resource_change(_TARGET, "v1", "replace", "op-x")
    finally:
        store.close()


# -- crash windows (T005-05 pattern: real SIGKILL subprocesses) ------------------

_KILL_SCRIPT = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {src!r})
    from ordessa_persistence_sqlite import SqliteStorePort
    from ordessa_persistence_sqlite.relationships import SqliteRelationshipStore
    from ordessa_environment_api import CanonicalFactTarget, PersistentReference, RevisionSelector

    SOURCE = CanonicalFactTarget("profile", "workspace", "profile-1")
    TARGET = CanonicalFactTarget("provider", "workspace", "provider-1")

    def ref(rid, source_revision="v1"):
        return PersistentReference(
            relation_id=rid, source_key=SOURCE, source_revision=source_revision,
            target_key=TARGET, revision_selector=RevisionSelector("exact", "v1"),
            declaring_owner_domain="profile", policy_contract_id="profile.resource-ref",
            policy_contract_version=1, operation_id="op-kill",
            source_commit_evidence="ev-1",
        )

    store = SqliteStorePort(sys.argv[1])
    port = SqliteRelationshipStore(store)
    window = sys.argv[2]

    if window == "pre-publish":
        print("READY", flush=True)     # nothing published yet
        time.sleep(30)

    port.publish_reference_set(        # first complete set, committed
        SOURCE, "v1", (ref("rel-kill-a1"), ref("rel-kill-a2")), "op-kill-a")

    if window == "mid-publish":
        # fault injection IN THE CHILD: hold the second publish's transaction
        # open after half the rows are written, so the parent's SIGKILL lands
        # deterministically between the partial write and the commit
        import ordessa_persistence_sqlite.relationships as rel_mod
        original = rel_mod._apply_publication
        def half_then_hold(conn, source_text, source_revision, rows):
            original(conn, source_text, source_revision, rows[: len(rows) // 2])
            print("MID", flush=True)   # transaction OPEN, half written, uncommitted
            time.sleep(30)
        rel_mod._apply_publication = half_then_hold

    if window in ("mid-publish", "post-publish"):
        print("READY", flush=True)     # set A durable, set B not started
        port.publish_reference_set(
            SOURCE, "v2",
            tuple(ref(f"rel-kill-b{{i:03d}}", "v2") for i in range(8)), "op-kill-b")

    print("DONE", flush=True)          # set B committed
    time.sleep(30)
""")

_SRC = str(Path(__file__).resolve().parents[1] / "src")
_EXPECTED_LINE = {
    "pre-publish": "READY",
    "mid-publish": "MID",
    "post-publish": "DONE",
}


def _kill_at_window(db: Path, window: str) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", _KILL_SCRIPT.format(src=_SRC), str(db), window],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        expected = _EXPECTED_LINE[window]
        seen = ""
        for _ in range(4):
            line = proc.stdout.readline()
            if not line:
                break
            seen = line.strip()
            if seen == expected:
                break
        assert seen == expected, f"child printed {seen!r}, expected {expected!r}"
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
    finally:
        proc.kill()
        proc.wait(timeout=10)
        proc.stdout.close()


def test_kill_before_publish_records_nothing(tmp_path):
    db = tmp_path / "crash.sqlite3"
    _kill_at_window(db, "pre-publish")
    store = SqliteStorePort(db, allow_takeover=True)  # SIGKILL is the failure evidence
    port = SqliteRelationshipStore(store)
    try:
        view = port.inspect_incoming(_TARGET, "delete")
        assert view["relations"] == ()
        assert view["coverage"] == "unknown"
    finally:
        store.close()


def test_kill_mid_publish_rolls_back_to_the_last_complete_set(tmp_path):
    db = tmp_path / "crash.sqlite3"
    _kill_at_window(db, "mid-publish")  # killed INSIDE the open transaction
    store = SqliteStorePort(db, allow_takeover=True)
    port = SqliteRelationshipStore(store)
    try:
        view = port.inspect_incoming(_TARGET, "delete")
        ids = _relation_ids(view)
        # the half-written set B rolled back atomically; the last COMPLETE set
        # A is intact — never a half set
        assert ids == ["rel-kill-a1", "rel-kill-a2"]
        assert not [i for i in ids if i.startswith("rel-kill-b")]
        assert view["coverage"] == "known"
    finally:
        store.close()


def test_kill_after_publish_keeps_the_full_set_published(tmp_path):
    db = tmp_path / "crash.sqlite3"
    _kill_at_window(db, "post-publish")  # killed after set B committed
    store = SqliteStorePort(db, allow_takeover=True)
    port = SqliteRelationshipStore(store)
    try:
        view = port.inspect_incoming(_TARGET, "delete")
        assert _relation_ids(view) == sorted(
            ["rel-kill-a1", "rel-kill-a2"] + [f"rel-kill-b{i:03d}" for i in range(8)]
        )
        assert view["blocking-destructive-change"] is True
    finally:
        store.close()
