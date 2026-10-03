"""Repository: immutable revisions, metadata CAS, scoped idempotency.

Every mutation is one transaction on the private store; the idempotency
receipt is written in the *same* transaction as the business rows, so a
replay never double-applies and an interrupted transaction leaves neither
receipt nor half a revision behind (G02/G03).

The resource identity is (server scope, id): this store is per Server
data domain, and two Servers that happen to mint the same id never read
through each other (G06) — the separation is physical, not name-based.
"""
from __future__ import annotations

import itertools
import json
import secrets
from typing import Any, Callable, Mapping, Optional

from ..api import (
    ArchivedSelectionError,
    IdempotencyConflictError,
    InvalidRequestError,
    NotFoundError,
    PromptRecord,
    PromptRevision,
    PromptScope,
    RevisionConflictError,
    body_digest,
    validate_body_bytes,
    validate_description,
    validate_kind,
    validate_operation_key,
    validate_title,
)
from .storage import PromptsStore, canonical_digest, utc_now

_LOCAL_SEQ = itertools.count(1)


def new_prompt_id() -> str:
    return f"prompt_{secrets.token_hex(6)}{next(_LOCAL_SEQ)}"


def _row_to_record(row: Any) -> PromptRecord:
    return PromptRecord(
        id=row["id"], kind=row["kind"],
        scope=PromptScope(row["scope_kind"], row["profile_id"]),
        title=row["title"], description=row["description"],
        archived=bool(row["archived"]),
        metadata_version=int(row["metadata_version"]),
        latest_revision=int(row["latest_revision"]),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


class PromptRecords:
    """CAS + idempotency discipline over ``PromptsStore``."""

    def __init__(self, store: PromptsStore, *,
                 id_factory: Callable[[], str] = new_prompt_id) -> None:
        self._store = store
        self._id_factory = id_factory

    # -- reads --------------------------------------------------------------

    def get_record(self, prompt_id: str) -> PromptRecord:
        with self._store.read() as conn:
            row = conn.execute(
                "SELECT * FROM prompt_records WHERE id=?", (prompt_id,)).fetchone()
        if row is None:
            raise NotFoundError(f"no prompt {prompt_id!r} in this Server's library")
        return _row_to_record(row)

    def list_records(self, *, scope: Optional[PromptScope] = None,
                     kind: Optional[str] = None, query: Optional[str] = None,
                     include_archived: bool = False,
                     limit: int = 50, offset: int = 0) -> "tuple[list[PromptRecord], bool]":
        sql = "SELECT * FROM prompt_records"
        where: list[str] = []
        params: list[Any] = []
        if scope is not None:
            where.append("scope_kind=?")
            params.append(scope.kind)
            if scope.profile_id is not None:
                where.append("profile_id=?")
                params.append(scope.profile_id)
        if kind is not None:
            where.append("kind=?")
            params.append(kind)
        if query:
            where.append("(title LIKE ? ESCAPE '\\' OR description LIKE ? ESCAPE '\\')")
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params += [f"%{escaped}%", f"%{escaped}%"]
        if not include_archived:
            where.append("archived=0")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at, id LIMIT ?"
        params.append(limit + 1)
        if offset:
            sql += " OFFSET ?"
            params.append(offset)
        with self._store.read() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        has_more = len(rows) > limit
        return [_row_to_record(row) for row in rows[:limit]], has_more

    def get_revision(self, prompt_id: str, revision: Optional[int] = None) -> PromptRevision:
        with self._store.read() as conn:
            if revision is None:
                row = conn.execute(
                    "SELECT r.* FROM prompt_revisions r "
                    "JOIN prompt_records m ON m.id=r.prompt_id AND m.latest_revision=r.revision "
                    "WHERE r.prompt_id=?", (prompt_id,)).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM prompt_revisions WHERE prompt_id=? AND revision=?",
                    (prompt_id, int(revision))).fetchone()
        if row is None:
            raise NotFoundError(
                f"no revision for prompt {prompt_id!r}"
                + ("" if revision is None else f" at revision {revision}"))
        return PromptRevision(
            prompt_id=row["prompt_id"], revision=int(row["revision"]),
            body=bytes(row["body"]), sha256=row["sha256"], created_at=row["created_at"])

    # -- idempotent writes -----------------------------------------------------

    def create(self, *, kind: str, scope: PromptScope, title: str,
               description: Optional[str], body: bytes,
               idempotency: "tuple[str, str, dict[str, Any]]") -> "tuple[str, dict[str, Any]]":
        """Create record + first revision atomically.

        Returns ("applied"|"replay", response). The receipt scope is
        caller-subject + operation + target; one key never collides
        across subjects.
        """
        kind = validate_kind(kind)
        title = validate_title(title)
        description = validate_description(description)
        validate_body_bytes(body)
        digest = body_digest(body)

        def business(steps: Callable[[str, tuple], Any]) -> dict[str, Any]:
            prompt_id = self._id_factory()
            timestamp = utc_now()
            steps(
                "INSERT INTO prompt_records(id,kind,scope_kind,profile_id,title,"
                "description,archived,metadata_version,latest_revision,created_at,"
                "updated_at) VALUES (?,?,?,?,?,?,0,1,1,?,?)",
                (prompt_id, kind, scope.kind, scope.profile_id, title, description,
                 timestamp, timestamp))
            steps("INSERT INTO prompt_revisions(prompt_id,revision,body,sha256,"
                  "created_at) VALUES (?,1,?,?,?)", (prompt_id, body, digest, timestamp))
            return {"id": prompt_id, "kind": kind, "scope": scope.as_wire(),
                    "title": title, "description": description, "archived": False,
                    "metadataVersion": 1, "latestRevision": 1,
                    "sha256": digest, "createdAt": timestamp, "updatedAt": timestamp}

        return self._write(idempotency=idempotency, guard=lambda steps: None,
                           business=business)

    def update(self, *, prompt_id: str,
               expected_metadata_version: int, expected_latest_revision: int,
               patch: Mapping[str, Any],
               idempotency: "tuple[str, str, dict[str, Any]]") -> "tuple[str, dict[str, Any]]":
        """CAS update of metadata and/or body.

        * a body equal to the latest revision adds no content revision
          (metadata changes still bump metadataVersion);
        * expected versions that miss live state raise RevisionConflictError
          inside the transaction — no last-wins;
        * archived records refuse every mutation (ARCHIVED_SELECTION);
        * the response always carries the digest of the current latest
          revision, whether or not the patch touched the body (PR-R2).
        """
        unknown = set(patch) - {"title", "description", "body"}
        if unknown:
            raise InvalidRequestError(f"unknown patch fields: {sorted(unknown)}")
        if not patch:
            raise InvalidRequestError("patch is empty")
        if "body" in patch:
            body = patch["body"]
            if isinstance(body, str):
                body = body.encode("utf-8")
            validate_body_bytes(body)

        def guard(steps: Callable[[str, tuple], Any]) -> None:
            row = steps("SELECT archived,metadata_version,latest_revision "
                        "FROM prompt_records WHERE id=?", (prompt_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"no prompt {prompt_id!r} in this Server's library")
            if row["archived"]:
                raise ArchivedSelectionError(
                    f"prompt {prompt_id!r} is archived and read-only")

        def business(steps: Callable[[str, tuple], Any]) -> dict[str, Any]:
            row = steps("SELECT * FROM prompt_records WHERE id=?",
                        (prompt_id,)).fetchone()
            if int(row["metadata_version"]) != int(expected_metadata_version) \
                    or int(row["latest_revision"]) != int(expected_latest_revision):
                raise RevisionConflictError(
                    f"prompt {prompt_id!r} moved on; rebase against the current version",
                    currentMetadataVersion=int(row["metadata_version"]),
                    currentLatestRevision=int(row["latest_revision"]))
            timestamp = utc_now()
            new_latest = int(row["latest_revision"])
            # The latest digest is read once, inside this transaction, and
            # always echoed back. A patch that does not touch the body still
            # reports the existing digest (PR-R2): callers never have to tell
            # "body untouched" apart from "digest lost".
            current = steps(
                "SELECT sha256 FROM prompt_revisions WHERE prompt_id=? AND revision=?",
                (prompt_id, new_latest)).fetchone()
            saved_digest: Optional[str] = (None if current is None
                                           else str(current["sha256"]))
            if "body" in patch:
                body = patch["body"]
                if isinstance(body, str):
                    body = body.encode("utf-8")
                wanted_digest = body_digest(body)
                if current is None or current["sha256"] != wanted_digest:
                    new_latest += 1
                    steps("INSERT INTO prompt_revisions(prompt_id,revision,body,"
                          "sha256,created_at) VALUES (?,?,?,?,?)",
                          (prompt_id, new_latest, body, wanted_digest, timestamp))
                    saved_digest = wanted_digest
            title = (validate_title(patch["title"]) if "title" in patch
                     else row["title"])
            if "description" in patch:
                description = validate_description(patch["description"])
            else:
                description = row["description"]
            steps("UPDATE prompt_records SET title=?,description=?,metadata_version=?,"
                  "latest_revision=?,updated_at=? WHERE id=?",
                  (title, description, int(row["metadata_version"]) + 1,
                   new_latest, timestamp, prompt_id))
            return {"id": prompt_id, "title": title, "description": description,
                    "metadataVersion": int(row["metadata_version"]) + 1,
                    "latestRevision": new_latest, "sha256": saved_digest,
                    "updatedAt": timestamp}

        return self._write(idempotency=idempotency, guard=guard, business=business)

    def clone(self, *, source_id: str, source_revision: Optional[int],
              target_scope: PromptScope, title: str,
              idempotency: "tuple[str, str, dict[str, Any]]") -> "tuple[str, dict[str, Any]]":
        """Copy the bytes *at that moment* into a brand-new entity.

        The clone never follows the source's later changes and shares no
        mutable row (G03).
        """
        title = validate_title(title)

        def guard(steps: Callable[[str, tuple], Any]) -> None:
            if steps("SELECT 1 FROM prompt_records WHERE id=?",
                     (source_id,)).fetchone() is None:
                raise NotFoundError(f"no prompt {source_id!r} in this Server's library")

        def business(steps: Callable[[str, tuple], Any]) -> dict[str, Any]:
            head = steps("SELECT kind, description FROM prompt_records WHERE id=?",
                         (source_id,)).fetchone()
            if source_revision is None:
                src = steps(
                    "SELECT r.* FROM prompt_revisions r "
                    "JOIN prompt_records m ON m.id=r.prompt_id AND m.latest_revision=r.revision "
                    "WHERE r.prompt_id=?", (source_id,)).fetchone()
            else:
                src = steps(
                    "SELECT * FROM prompt_revisions WHERE prompt_id=? AND revision=?",
                    (source_id, int(source_revision))).fetchone()
            if src is None:
                raise NotFoundError("the cloned revision does not exist")
            body = bytes(src["body"])
            digest = body_digest(body)
            timestamp = utc_now()
            prompt_id = self._id_factory()
            steps("INSERT INTO prompt_records(id,kind,scope_kind,profile_id,title,"
                  "description,archived,metadata_version,latest_revision,created_at,"
                  "updated_at) VALUES (?,?,?,?,?,?,0,1,1,?,?)",
                  (prompt_id, head["kind"], target_scope.kind, target_scope.profile_id,
                   title, head["description"], timestamp, timestamp))
            steps("INSERT INTO prompt_revisions(prompt_id,revision,body,sha256,"
                  "created_at) VALUES (?,1,?,?,?)", (prompt_id, body, digest, timestamp))
            return {"id": prompt_id, "sourceId": source_id,
                    "sourceRevision": int(src["revision"]), "title": title,
                    "kind": head["kind"], "metadataVersion": 1, "latestRevision": 1,
                    "sha256": digest, "createdAt": timestamp}

        return self._write(idempotency=idempotency, guard=guard, business=business)

    def set_archived(self, *, prompt_id: str, expected_metadata_version: int,
                     archived: bool,
                     idempotency: "tuple[str, str, dict[str, Any]]") -> "tuple[str, dict[str, Any]]":
        def guard(steps: Callable[[str, tuple], Any]) -> None:
            row = steps("SELECT metadata_version FROM prompt_records WHERE id=?",
                        (prompt_id,)).fetchone()
            if row is None:
                raise NotFoundError(f"no prompt {prompt_id!r} in this Server's library")
            if int(row["metadata_version"]) != int(expected_metadata_version):
                raise RevisionConflictError(
                    f"prompt {prompt_id!r} metadata moved on",
                    currentMetadataVersion=int(row["metadata_version"]))

        def business(steps: Callable[[str, tuple], Any]) -> dict[str, Any]:
            row = steps("SELECT metadata_version FROM prompt_records WHERE id=?",
                        (prompt_id,)).fetchone()
            timestamp = utc_now()
            steps("UPDATE prompt_records SET archived=?,metadata_version=?,updated_at=?"
                  " WHERE id=?",
                  (1 if archived else 0, int(row["metadata_version"]) + 1,
                   timestamp, prompt_id))
            return {"id": prompt_id, "archived": archived,
                    "metadataVersion": int(row["metadata_version"]) + 1,
                    "updatedAt": timestamp}

        return self._write(idempotency=idempotency, guard=guard, business=business)

    # -- the shared transaction skeleton ---------------------------------------

    def _write(self, *, idempotency: "tuple[str, str, dict[str, Any]]",
               guard: Callable[[Callable[[str, tuple], Any]], None],
               business: Callable[[Callable[[str, tuple], Any]], dict[str, Any]]
               ) -> "tuple[str, dict[str, Any]]":
        """One transaction: receipt check → guard → business → receipt.

        Transaction-body invariant (PR-R1): inside ``guard``/``business`` the
        only legal store access is the passed ``steps()`` callable, which
        runs on the open write transaction. Calling any repository reader
        here (they open ``PromptsStore.read()``, i.e. a second ``BEGIN``)
        fails with ``sqlite3.OperationalError`` and rolls the whole write
        back; the ``test_review_regressions.py`` PR-R1 case pins that, and
        no production path reaches it.
        """
        scope, key, payload = idempotency
        validate_operation_key(key)
        digest = canonical_digest(dict(payload))
        with self._store.immediate() as conn:
            def steps(sql: str, params: "tuple[Any, ...]" = ()) -> Any:
                return self._store.run_step(sql, params)
            prior = conn.execute(
                "SELECT request_digest, response_json FROM prompt_idempotency "
                "WHERE scope=? AND key=?", (scope, key)).fetchone()
            if prior is not None:
                if prior["request_digest"] != digest:
                    raise IdempotencyConflictError()
                return "replay", json.loads(prior["response_json"])
            guard(steps)
            response = business(steps)
            self._store.run_step(
                "INSERT INTO prompt_idempotency(scope,key,request_digest,response_json,"
                "created_at) VALUES (?,?,?,?,?)",
                (scope, key, digest, json.dumps(response, sort_keys=True), utc_now()))
            return "applied", response

    # -- latest resolution for snapshots (G07) ---------------------------------

    def resolve_latest(self, prompt_ids: "list[str]") -> "list[dict[str, Any]]":
        """Resolve every id's current revision in ONE read transaction:
        one snapshot can never mix two instants of latest."""
        rows: list[dict[str, Any]] = []
        with self._store.read() as conn:
            for prompt_id in prompt_ids:
                row = conn.execute(
                    "SELECT r.prompt_id,r.revision,r.body,r.sha256,r.created_at,"
                    "m.kind,m.title,m.scope_kind,m.profile_id,m.archived,"
                    "m.metadata_version "
                    "FROM prompt_revisions r JOIN prompt_records m ON m.id=r.prompt_id "
                    "WHERE r.prompt_id=? AND r.revision=m.latest_revision",
                    (prompt_id,)).fetchone()
                if row is None:
                    raise NotFoundError(f"no prompt {prompt_id!r} to resolve")
                rows.append(dict(row, body=bytes(row["body"])))
        return rows
