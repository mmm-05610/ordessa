"""SQLite persistence for the E5 persistent-reference seam (spec 026, T005-11).

:class:`SqliteRelationshipStore` implements the ``RelationshipPort`` semantics
(contract E5, frozen in ``ordessa_environment_api``) on top of one
``SqliteStorePort``. The reference semantics are the in-memory implementation
in ``pacthold.environment``; this module makes them DURABLE:

* relations live in the existing ``env_relations`` table (frozen columns:
  relation_id / source_entity / source_revision / target_entity / payload);
  the payload column carries the canonical-JSON encoding of the reference;
* change reservations live in the new ``env_change_reservations`` table
  (added to ``_SCHEMA`` with ``CREATE TABLE IF NOT EXISTS`` — idempotent for
  databases created before the table existed);

E5 rules implemented here:

* ``publish_reference_set`` is a FULL REPLACEMENT of one source version's
  declared set, inside ONE transaction — a crash leaves the previous complete
  set or the new complete set, never a half set;
* republication of the SAME set under the SAME operation id is a no-op: no
  row is touched and the durable coverage epoch is not re-stamped;
* new relations and open destructive change reservations never pass the same
  gate: a delete/rewrite ticket on a target refuses publishing new relations
  to it, and vice versa published relations refuse delete/rewrite prepares;
* a reservation is DURABLE: close/reopen, TTL or process death never releases
  it — ``release_reservation(executed=True)`` is the only release path; a
  refused destructive intent still leaves its ticket recorded (no empty-set
  fake safety);
* published relations are returned by ``inspect_incoming`` regardless of
  whether the declaring plugin is still active — the read is a key lookup on
  this table, never a business-DB scan.

C2 discipline is inherited, not reimplemented: this wrapper opens no
connection of its own and always goes through the store's public
``transaction()`` seam, so same-root single-writer exclusivity applies
unchanged, and no DB transaction is held across an external call.
"""
from __future__ import annotations

import json
import time
from typing import Any, Mapping, Sequence

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
from ordessa_environment_api.codec import canonical_json

from .store import SqliteStorePort

__all__ = ["SqliteRelationshipStore"]

_DESTRUCTIVE_KINDS = ("delete", "rewrite")
_CHANGE_KINDS = ("archive", "delete", "rewrite")

# Neutral stable resource keys. ``CanonicalFactTarget`` is the frozen slot key;
# callers may also pass a (realm, namespace, entity) tuple or the encoded
# ``realm:namespace:entity`` form. The encoding is unambiguous: realm and
# identity_namespace grammars never contain ':', only stable_entity_id may, so
# ``split(":", 2)`` round-trips exactly.


def _as_target(key: CanonicalFactTarget | tuple[str, str, str] | str) -> CanonicalFactTarget:
    """Normalize every accepted key form to the frozen DTO (validating)."""
    if isinstance(key, CanonicalFactTarget):
        return key
    if isinstance(key, (tuple, list)):
        if len(key) != 3:
            raise ValueError(
                f"tuple target key must be (realm, identity_namespace, stable_entity_id), got {key!r}"
            )
        return CanonicalFactTarget(key[0], key[1], key[2])
    if isinstance(key, str):
        parts = key.split(":", 2)
        if len(parts) != 3 or not all(parts):
            raise ValueError(
                f"encoded target key {key!r} must be 'realm:identity_namespace:stable_entity_id'"
            )
        return CanonicalFactTarget(*parts)
    raise TypeError(f"unsupported target key form: {type(key).__name__}")


def _target_text(key: CanonicalFactTarget | tuple[str, str, str] | str) -> str:
    target = _as_target(key)
    return f"{target.realm}:{target.identity_namespace}:{target.stable_entity_id}"


def _payload_dict(rel: PersistentReference, *, epoch: int | None) -> dict[str, Any]:
    """The stored wire form of one reference (same field names as the DTO).

    ``publish_reference_set`` is the published side of the gate: like the
    in-memory reference, everything it stores is forced to
    ``status=published`` and stamped with the durable coverage epoch.
    """
    payload: dict[str, Any] = {
        "relation_id": rel.relation_id,
        "source_key": _target_text(rel.source_key),
        "source_revision": rel.source_revision,
        "target_key": _target_text(rel.target_key),
        "revision_selector": {
            "op": rel.revision_selector.op,
            "revision": rel.revision_selector.revision,
        },
        "declaring_owner_domain": rel.declaring_owner_domain,
        "policy_contract_id": rel.policy_contract_id,
        "policy_contract_version": rel.policy_contract_version,
        "operation_id": rel.operation_id,
        "source_commit_evidence": rel.source_commit_evidence,
        "status": ReferenceStatus.PUBLISHED.value,
    }
    if epoch is not None:
        payload["coverage_epoch"] = epoch
    return payload


def _content_view(rel: PersistentReference) -> str:
    """Payload content minus the coverage epoch — the idempotency identity."""
    return canonical_json(_payload_dict(rel, epoch=None))


def _payload_text(rel: PersistentReference, *, epoch: int) -> str:
    return canonical_json(_payload_dict(rel, epoch=epoch))


def _reference_from_payload(text: str) -> PersistentReference:
    raw = json.loads(text)
    selector_raw = raw["revision_selector"]
    return PersistentReference(
        relation_id=raw["relation_id"],
        source_key=_as_target(raw["source_key"]),
        source_revision=raw["source_revision"],
        target_key=_as_target(raw["target_key"]),
        revision_selector=RevisionSelector(
            op=selector_raw["op"], revision=selector_raw.get("revision")
        ),
        declaring_owner_domain=raw["declaring_owner_domain"],
        policy_contract_id=raw["policy_contract_id"],
        policy_contract_version=raw["policy_contract_version"],
        operation_id=raw["operation_id"],
        source_commit_evidence=raw["source_commit_evidence"],
        status=ReferenceStatus(raw["status"]),
        coverage_epoch=raw["coverage_epoch"],
    )


def _stored_source_set(
    conn: Any, source_text: str, source_revision: str
) -> tuple[PersistentReference, ...]:
    rows = conn.execute(
        "SELECT payload FROM env_relations "
        "WHERE source_entity=? AND source_revision=? ORDER BY relation_id",
        (source_text, source_revision),
    ).fetchall()
    return tuple(_reference_from_payload(row["payload"]) for row in rows)


def _incoming_refs(conn: Any, target_text: str) -> tuple[PersistentReference, ...]:
    """Key lookup on the declared-relations table — never a business scan.

    Only PUBLISHED rows participate; anything else stored here is ignored on
    read (and nothing else is ever stored today). A corrupt payload raises —
    a read failure is never reported as 'no references'.
    """
    rows = conn.execute(
        "SELECT payload FROM env_relations WHERE target_entity=? ORDER BY relation_id",
        (target_text,),
    ).fetchall()
    refs = [_reference_from_payload(row["payload"]) for row in rows]
    return tuple(ref for ref in refs if ref.status is ReferenceStatus.PUBLISHED)


def _next_coverage_epoch(conn: Any) -> int:
    """Monotonic per-root coverage epoch, durably kept in ``env_meta`` so it
    survives restart (a reopened store must never re-stamp an older epoch)."""
    row = conn.execute("SELECT value FROM env_meta WHERE key='relation_epoch'").fetchone()
    try:
        epoch = int(row["value"]) + 1 if row is not None else 1
    except (TypeError, ValueError):
        epoch = 1
    conn.execute(
        "INSERT OR REPLACE INTO env_meta (key, value) VALUES ('relation_epoch', ?)",
        (str(epoch),),
    )
    return epoch


def _apply_publication(
    conn: Any, source_text: str, source_revision: str, rows: Sequence[tuple[str, str, str]]
) -> None:
    """Full-replacement write for one source version; the caller owns the
    transaction. Module-level so crash-window tests can hold the transaction
    open between the DELETE+partial INSERT and the commit — the product path
    itself is always delete-all + insert-all in one commit."""
    conn.execute(
        "DELETE FROM env_relations WHERE source_entity=? AND source_revision=?",
        (source_text, source_revision),
    )
    for relation_id, target_text, payload in rows:
        conn.execute(
            "INSERT INTO env_relations "
            "(relation_id, source_entity, source_revision, target_entity, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (relation_id, source_text, source_revision, target_text, payload),
        )


def _write_reservation(conn: Any, reservation: ChangeReservation) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO env_change_reservations "
        "(reservation_id, target_entity, expected_revision, change_kind, operation_id, "
        " refused_relations, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            reservation.reservation_id,
            _target_text(reservation.target_key),
            reservation.expected_revision,
            reservation.change_kind,
            reservation.operation_id,
            canonical_json(reservation.refused_relations),
            time.time(),
        ),
    )


class SqliteRelationshipStore:
    """Durable ``RelationshipPort`` over one ``SqliteStorePort`` (E5, T005-11).

    Key forms accepted for source/target keys: the frozen
    ``CanonicalFactTarget``, a ``(realm, identity_namespace, stable_entity_id)``
    tuple, or the encoded ``realm:identity_namespace:stable_entity_id`` string.
    All normalize to one canonical text form before any comparison or storage.
    """

    def __init__(self, store: SqliteStorePort) -> None:
        if not hasattr(store, "transaction"):
            raise TypeError(
                "SqliteRelationshipStore wraps a StorePort exposing a transaction() seam"
            )
        self._store = store

    # -- E5 publish / inspect -------------------------------------------------

    def publish_reference_set(
        self,
        source_key: CanonicalFactTarget | tuple[str, str, str] | str,
        source_revision: str,
        relations: Sequence[PersistentReference],
        operation_id: str,
    ) -> None:
        """Full replacement of one source version's declared set (E5).

        Serialized with change reservations at the same gate: while a
        delete/rewrite ticket holds any target of the set, the whole publish
        is refused. Idempotent: the SAME set under the SAME operation id writes
        nothing at all (rows and the durable coverage epoch stay untouched);
        a different set or operation replaces the previous declaration inside
        ONE transaction — a crash leaves the old or the new complete set.
        """
        source_text = _target_text(source_key)
        prepared: list[PersistentReference] = []
        for rel in relations:
            if not isinstance(rel, PersistentReference):
                raise TypeError("publish_reference_set relations must be PersistentReference")
            if _target_text(rel.source_key) != source_text or rel.source_revision != source_revision:
                raise IdentityMismatchError(
                    f"relation {rel.relation_id} declares source "
                    f"{_target_text(rel.source_key)}@{rel.source_revision}, "
                    f"not {source_text}@{source_revision}"
                )
            prepared.append(rel)
        incoming_views = tuple(_content_view(rel) for rel in prepared)
        conn = self._store.transaction()
        with conn:
            # the same gate: a new relation and an open destructive change on
            # that target can never both pass
            for rel in prepared:
                holder = conn.execute(
                    "SELECT reservation_id FROM env_change_reservations "
                    "WHERE target_entity=? AND change_kind IN ('delete', 'rewrite') LIMIT 1",
                    (_target_text(rel.target_key),),
                ).fetchone()
                if holder is not None:
                    raise AdmissionRefusedError(
                        f"target {_target_text(rel.target_key)} holds destructive change "
                        f"reservation {holder['reservation_id']}; new relations to it are refused"
                    )
            stored = _stored_source_set(conn, source_text, source_revision)
            if tuple(_content_view(r) for r in stored) == incoming_views:
                return  # idempotent republication — no write, no epoch re-stamp
            epoch = _next_coverage_epoch(conn)
            _apply_publication(
                conn,
                source_text,
                source_revision,
                [
                    (rel.relation_id, _target_text(rel.target_key), _payload_text(rel, epoch=epoch))
                    for rel in prepared
                ],
            )

    def inspect_incoming(
        self,
        target_key: CanonicalFactTarget | tuple[str, str, str] | str,
        change_kind: str = "archive",
        coverage_epoch: int = 0,
    ) -> Mapping[str, Any]:
        """Declared incoming relations + coverage verdict (E5).

        Reads the declared-relations table only — never a business-DB scan —
        so relations survive declarer retirement and store restart. Absence of
        a declared relation is reported as coverage ``unknown`` (never as a
        proven 'no references'): content written outside the contract keeps
        its potential-relation block. Same shape as the in-memory reference:
        ``target`` / ``relations`` / ``coverage`` /
        ``blocking-destructive-change``.
        """
        target = _as_target(target_key)
        conn = self._store.transaction()
        incoming = _incoming_refs(conn, _target_text(target))
        return {
            "target": target,
            "relations": incoming,
            "coverage": "known" if incoming else "unknown",
            "blocking-destructive-change": change_kind in _DESTRUCTIVE_KINDS and bool(incoming),
        }

    # -- E5 change admission ---------------------------------------------------

    def prepare_resource_change(
        self,
        target_key: CanonicalFactTarget | tuple[str, str, str] | str,
        expected_revision: str,
        change_kind: str,
        operation_id: str,
    ) -> ChangeReservation:
        """One durable admission ticket per target change (E5).

        A second open ticket on the same target refuses (the same operation id
        re-prepares idempotently). A delete/rewrite on a target with published
        relations is refused AFTER its ticket is durably recorded — the
        recorded destructive intent survives close/reopen/process death and
        keeps new relations to the target gated until explicit resolution.
        Ordinary reads and non-conflicting targets continue unaffected.
        """
        if change_kind not in _CHANGE_KINDS:
            raise EnvironmentError(f"unknown change kind {change_kind!r}")
        target = _as_target(target_key)
        target_text = _target_text(target)
        conn = self._store.transaction()
        destructive = change_kind in _DESTRUCTIVE_KINDS
        blocked_by: tuple[str, ...] = ()
        with conn:
            other = conn.execute(
                "SELECT reservation_id FROM env_change_reservations "
                "WHERE target_entity=? AND reservation_id<>?",
                (target_text, operation_id),
            ).fetchone()
            if other is not None:
                raise AdmissionRefusedError(
                    f"target {target_text} already holds change reservation "
                    f"{other['reservation_id']}; reservations are released only by "
                    "explicit executed evidence"
                )
            incoming = _incoming_refs(conn, target_text)
            blocked_by = tuple(r.relation_id for r in incoming)
            reservation = ChangeReservation(
                reservation_id=operation_id,
                target_key=target,
                expected_revision=expected_revision,
                change_kind=change_kind,
                operation_id=operation_id,
                refused_relations=blocked_by if destructive and blocked_by else (),
            )
            _write_reservation(conn, reservation)
        # the ticket is committed before any refusal surfaces: a refused
        # destructive intent still leaves its durable reservation behind
        if destructive and blocked_by:
            raise AdmissionRefusedError(
                f"destructive change on {target_text} blocked by published relations "
                f"{blocked_by}; reservation {operation_id} stays recorded until "
                "explicit resolution"
            )
        return reservation

    def release_reservation(self, operation_id: str, *, executed: bool) -> None:
        """The ONLY release path for a reservation (E5).

        ``executed=True`` deletes the ticket row; ``executed=False`` records
        the not-executed outcome and keeps the gate shut. Close/reopen, TTL
        and process death never release anything, and releasing an unknown
        operation id is a silent no-op (in-memory parity).
        """
        if not executed:
            return  # not executed: the reservation stays until evidence resolves it
        conn = self._store.transaction()
        with conn:
            conn.execute(
                "DELETE FROM env_change_reservations WHERE reservation_id=?",
                (operation_id,),
            )
