"""The private data root for the domain: a self-owned SQLite file.

The domain's durable data lives under a private root it is *given explicitly*
(data-model.md: ``ordessa.assets.command-templates`` service data root; the
Server core DB must not carry these business tables). Two deliberate choices:

* the connection and its path are injected — constructing :class:`TemplateStore`
  opens nothing; :meth:`TemplateStore.initialize` and :meth:`connect` do, and are
  called by the service seam, never at import (G01/G20, ``test_isolation``);
* tables are namespaced ``ct_*`` in a file the Server never opens, so a template
  revision can never be mistaken for a ``server_assets`` row or a Skill.

The content-address/record *pattern* (digest required before publish, opaque id,
idempotency ledger) is borrowed from ``ordessa_server_compat/assets/records.py``;
the asset-kind vocabulary and its host DB are not.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from ..api import schema
from ..api.dto import (
    Assignment,
    ParameterSpec,
    Template,
    TemplateRevision,
)
from ..api.errors import (
    CasConflictError,
    ContentMissingError,
    IdempotencyConflictError,
    InvalidDocumentError,
    RevisionUnapprovedError,
)
from ..expansion.digest import revision_digest
from ..expansion.parser import parse
from ..expansion.renderer import check_publish_coverage

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ct_template (
    id TEXT PRIMARY KEY,
    owner_principal TEXT NOT NULL,
    display_name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'user',
    latest_revision INTEGER NOT NULL DEFAULT 0,
    entity_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
CREATE TABLE IF NOT EXISTS ct_revision (
    template_id TEXT NOT NULL REFERENCES ct_template(id),
    revision INTEGER NOT NULL,
    body TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    approved_at TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (template_id, revision)
);
CREATE TABLE IF NOT EXISTS ct_assignment (
    scope TEXT NOT NULL,
    scope_identity TEXT NOT NULL,
    harness_id TEXT NOT NULL DEFAULT '',
    template_id TEXT NOT NULL REFERENCES ct_template(id),
    state TEXT NOT NULL,
    pinned_revision INTEGER,
    entity_version INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, scope_identity, harness_id, template_id)
);
CREATE TABLE IF NOT EXISTS ct_idempotency (
    scope TEXT NOT NULL,
    key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
"""


def _parameters_json(parameters: Sequence[ParameterSpec]) -> str:
    return json.dumps([asdict(s) for s in parameters], sort_keys=True, ensure_ascii=False)


def _parameters_from_json(raw: str) -> "tuple[ParameterSpec, ...]":
    items = json.loads(raw)
    specs: list[ParameterSpec] = []
    for item in items:
        choices = item.get("choices")
        if choices is not None:
            item = {**item, "choices": tuple(choices)}
        specs.append(ParameterSpec(**item))
    return tuple(specs)


def request_digest_of(payload: Mapping[str, Any]) -> str:
    """A stable digest of an operation payload for the idempotency ledger.

    Only structural fields participate; it is used to detect a same-key /
    different-payload replay, never to store content.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                           default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


class TemplateStore:
    """Owns the private SQLite file and the content/assignment ledger.

    All mutating operations take an ``operation_key`` (idempotency) and, where a
    versioned entity changes, an ``expected_version`` (CAS). They run in a single
    transaction so a failed write lands nothing.
    """

    def __init__(self, path: Path | str, *, clock: "callable[[], str] | None" = None) -> None:
        # Construction is inert: no file is created, no connection opened.
        self._path = Path(path)
        self._lock = threading.RLock()
        self._clock = clock
        self._initialized = False

    @property
    def path(self) -> Path:
        return self._path

    def _now(self) -> str:
        if self._clock is not None:
            return self._clock()
        import datetime

        return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def for_root(private_root: Path | str, *, clock: "callable[[], str] | None" = None) -> "TemplateStore":
        """A store for the domain's private root: ``<root>/command-templates.sqlite``.

        The caller supplies the root explicitly (the host's scoped data root or a
        test temp directory). Nothing is created or opened until ``initialize``.
        """
        return TemplateStore(Path(private_root) / "command-templates.sqlite", clock=clock)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def initialize(self) -> None:
        """Create the private root and schema. Explicit, never at import."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._transaction() as conn:
                conn.executescript(_SCHEMA)
            self._initialized = True

    def _require_ready(self) -> None:
        if not self._initialized:
            raise InvalidDocumentError("store is not initialized; call initialize() explicitly")

    # -- transaction scope --------------------------------------------------

    @contextlib.contextmanager
    def _transaction(self):
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextlib.contextmanager
    def _read(self):
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    # -- idempotency --------------------------------------------------------

    def _replay_or_record(self, conn: sqlite3.Connection, scope: str, key: str,
                          digest: str, produce: "callable[[], dict[str, Any]]") -> "tuple[str, dict]":
        prior = conn.execute(
            "SELECT request_digest, result_json FROM ct_idempotency WHERE scope=? AND key=?",
            (scope, key)).fetchone()
        if prior is not None:
            if prior["request_digest"] != digest:
                raise IdempotencyConflictError(
                    f"operation key {key!r} was reused with a different payload",
                    detail={"scope": scope})
            return "replay", json.loads(prior["result_json"])
        result = produce()
        conn.execute(
            "INSERT INTO ct_idempotency(scope,key,request_digest,result_json,created_at) "
            "VALUES (?,?,?,?,?)", (scope, key, digest,
                                   json.dumps(result, sort_keys=True, ensure_ascii=False),
                                   self._now()))
        return "committed", result

    # -- templates ----------------------------------------------------------

    def create_template(self, *, template_id: str, owner_principal: str, display_name: str,
                        slug: str, description: str = "", origin: str = "user",
                        operation_key: str) -> Template:
        self._require_ready()
        template = Template(id=template_id, owner_principal=owner_principal,
                            display_name=display_name, slug=slug, description=description,
                            origin=origin, created_at=self._now())
        digest = request_digest_of({"id": template_id, "owner": owner_principal,
                                    "display_name": display_name, "slug": slug,
                                    "description": description, "origin": origin})
        scope = f"ct.create:{template_id}"
        with self._lock, self._transaction() as conn:
            def produce() -> dict:
                clash = conn.execute(
                    "SELECT 1 FROM ct_template WHERE id=?", (template_id,)).fetchone()
                if clash is not None:
                    raise CasConflictError(f"template {template_id!r} already exists")
                conn.execute(
                    "INSERT INTO ct_template(id,owner_principal,display_name,slug,description,"
                    "origin,latest_revision,entity_version,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (template.id, template.owner_principal, template.display_name, template.slug,
                     template.description, template.origin, template.latest_revision,
                     template.entity_version, template.created_at))
                return _template_row(conn, template_id)
            _, row = self._replay_or_record(conn, scope, operation_key, digest, produce)
        return _to_template(row)

    def get_template(self, template_id: str) -> Template:
        self._require_ready()
        with self._read() as conn:
            row = conn.execute("SELECT * FROM ct_template WHERE id=?", (template_id,)).fetchone()
        if row is None:
            raise ContentMissingError(f"template {template_id!r} does not exist")
        return _to_template(row)

    def list_templates(self, *, owner_principal: Optional[str] = None,
                       include_archived: bool = False) -> "list[Template]":
        """Metadata only — body and parameters never appear in a list (FR-09)."""
        self._require_ready()
        sql = "SELECT * FROM ct_template"
        clauses: list[str] = []
        args: list[Any] = []
        if owner_principal is not None:
            clauses.append("owner_principal=?"); args.append(owner_principal)
        if not include_archived:
            clauses.append("archived_at IS NULL")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        with self._read() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_to_template(row) for row in rows]

    # -- revisions ----------------------------------------------------------

    def save_revision(self, template_id: str, *, body: str,
                      parameters: Sequence[ParameterSpec] = (),
                      expected_version: int, operation_key: str) -> TemplateRevision:
        """Publish the next immutable revision under CAS + idempotency (FR-04)."""
        self._require_ready()
        schema.validate_body(body)
        specs = tuple(parameters)
        parsed = parse(body)
        check_publish_coverage(parsed, specs)  # undeclared / unused-required refusal
        digest = revision_digest(body, specs)
        with self._lock, self._transaction() as conn:
            tmpl = conn.execute("SELECT * FROM ct_template WHERE id=?", (template_id,)).fetchone()
            if tmpl is None:
                raise ContentMissingError(f"template {template_id!r} does not exist")
            payload = request_digest_of({"template": template_id, "digest": digest})
            scope = f"ct.save_revision:{template_id}"

            def produce() -> dict:
                if int(tmpl["entity_version"]) != expected_version:
                    raise CasConflictError(
                        f"expected_version {expected_version} != stored "
                        f"{tmpl['entity_version']}", current_version=int(tmpl["entity_version"]))
                new_rev = int(tmpl["latest_revision"]) + 1
                now = self._now()
                conn.execute(
                    "INSERT INTO ct_revision(template_id,revision,body,parameters_json,"
                    "content_digest,created_at) VALUES (?,?,?,?,?,?)",
                    (template_id, new_rev, body, _parameters_json(specs), digest, now))
                conn.execute(
                    "UPDATE ct_template SET latest_revision=?, entity_version=? WHERE id=?",
                    (new_rev, int(tmpl["entity_version"]) + 1, template_id))
                return {"template_id": template_id, "revision": new_rev,
                        "content_digest": digest, "created_at": now,
                        "parameters": json.loads(_parameters_json(specs))}
            _, record = self._replay_or_record(conn, scope, operation_key, payload, produce)
        return TemplateRevision(
            template_id=template_id, revision=int(record["revision"]), body=body,
            parameters=specs, content_digest=record["content_digest"],
            created_at=record["created_at"])

    def approve_revision(self, template_id: str, revision: int, *,
                         expected_version: int, operation_key: str) -> TemplateRevision:
        self._require_ready()
        with self._lock, self._transaction() as conn:
            tmpl = conn.execute("SELECT * FROM ct_template WHERE id=?", (template_id,)).fetchone()
            if tmpl is None:
                raise ContentMissingError(f"template {template_id!r} does not exist")
            rev = conn.execute(
                "SELECT * FROM ct_revision WHERE template_id=? AND revision=?",
                (template_id, revision)).fetchone()
            if rev is None:
                raise ContentMissingError(
                    f"revision {revision} of {template_id!r} does not exist")
            payload = request_digest_of({"template": template_id, "revision": revision})
            scope = f"ct.approve:{template_id}:{revision}"

            def produce() -> dict:
                if int(tmpl["entity_version"]) != expected_version:
                    raise CasConflictError(
                        f"expected_version {expected_version} != stored {tmpl['entity_version']}",
                        current_version=int(tmpl["entity_version"]))
                now = self._now()
                conn.execute(
                    "UPDATE ct_revision SET approved_at=? WHERE template_id=? AND revision=?",
                    (now, template_id, revision))
                conn.execute("UPDATE ct_template SET entity_version=? WHERE id=?",
                             (int(tmpl["entity_version"]) + 1, template_id))
                return {"template_id": template_id, "revision": revision,
                        "content_digest": rev["content_digest"], "approved_at": now,
                        "created_at": rev["created_at"], "body": rev["body"],
                        "parameters": json.loads(rev["parameters_json"])}
            _, record = self._replay_or_record(conn, scope, operation_key, payload, produce)
        return _to_revision(record)

    def get_revision(self, template_id: str, revision: int) -> TemplateRevision:
        self._require_ready()
        with self._read() as conn:
            row = conn.execute(
                "SELECT * FROM ct_revision WHERE template_id=? AND revision=?",
                (template_id, revision)).fetchone()
        if row is None:
            raise ContentMissingError(f"revision {revision} of {template_id!r} does not exist")
        return _row_to_revision(row)

    def revisions(self, template_id: str) -> "list[TemplateRevision]":
        self._require_ready()
        with self._read() as conn:
            rows = conn.execute(
                "SELECT * FROM ct_revision WHERE template_id=? ORDER BY revision",
                (template_id,)).fetchall()
        return [_row_to_revision(row) for row in rows]

    def is_approved(self, template_id: str, revision: int) -> bool:
        self._require_ready()
        with self._read() as conn:
            row = conn.execute(
                "SELECT approved_at FROM ct_revision WHERE template_id=? AND revision=?",
                (template_id, revision)).fetchone()
        if row is None:
            raise ContentMissingError(f"revision {revision} of {template_id!r} does not exist")
        return row["approved_at"] is not None

    def archive_template(self, template_id: str, *, expected_version: int,
                         operation_key: str) -> Template:
        """Archive flags the template; every revision and assignment stays (FR-01)."""
        self._require_ready()
        with self._lock, self._transaction() as conn:
            tmpl = conn.execute("SELECT * FROM ct_template WHERE id=?", (template_id,)).fetchone()
            if tmpl is None:
                raise ContentMissingError(f"template {template_id!r} does not exist")
            payload = request_digest_of({"template": template_id, "archive": True})
            scope = f"ct.archive:{template_id}"

            def produce() -> dict:
                if int(tmpl["entity_version"]) != expected_version:
                    raise CasConflictError(
                        f"expected_version {expected_version} != stored {tmpl['entity_version']}",
                        current_version=int(tmpl["entity_version"]))
                now = self._now()
                conn.execute("UPDATE ct_template SET archived_at=?, entity_version=? WHERE id=?",
                             (now, int(tmpl["entity_version"]) + 1, template_id))
                row = _template_row(conn, template_id)
                return row
            _, row = self._replay_or_record(conn, scope, operation_key, payload, produce)
        return _to_template(row)

    # -- assignments --------------------------------------------------------

    def upsert_assignment(self, assignment: Assignment, *, expected_version: Optional[int],
                          operation_key: str) -> Assignment:
        """Enable/disable one template for a scope, pinning an approved revision.

        An enable must reference an approved, existing revision (G04: an approval
        is required before an enable can pin it). Publishing a newer revision later
        never moves this row's pinned_revision (verified in test_revisions).
        """
        self._require_ready()
        with self._lock, self._transaction() as conn:
            tmpl = conn.execute("SELECT * FROM ct_template WHERE id=?",
                                (assignment.template_id,)).fetchone()
            if tmpl is None:
                raise ContentMissingError(f"template {assignment.template_id!r} does not exist")
            if assignment.state == "enable":
                rev = conn.execute(
                    "SELECT approved_at FROM ct_revision WHERE template_id=? AND revision=?",
                    (assignment.template_id, assignment.pinned_revision)).fetchone()
                if rev is None:
                    raise ContentMissingError(
                        f"revision {assignment.pinned_revision} does not exist")
                if rev["approved_at"] is None:
                    raise RevisionUnapprovedError(
                        f"revision {assignment.pinned_revision} must be approved before it "
                        "can be enabled")
            key_identity = (assignment.scope, assignment.scope_identity,
                            assignment.harness_id or "", assignment.template_id)
            existing = conn.execute(
                "SELECT entity_version FROM ct_assignment "
                "WHERE scope=? AND scope_identity=? AND harness_id=? AND template_id=?",
                key_identity).fetchone()
            payload = request_digest_of({
                "scope": assignment.scope, "identity": assignment.scope_identity,
                "harness": assignment.harness_id, "template": assignment.template_id,
                "state": assignment.state, "pinned": assignment.pinned_revision})
            scope = "ct.assignment:" + ":".join(key_identity)

            def produce() -> dict:
                now = self._now()
                if existing is None:
                    if expected_version not in (None, 1):
                        raise CasConflictError("a new assignment has expected_version 1")
                    conn.execute(
                        "INSERT INTO ct_assignment(scope,scope_identity,harness_id,template_id,"
                        "state,pinned_revision,entity_version,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                        (*key_identity, assignment.state, assignment.pinned_revision, 1, now))
                    version = 1
                else:
                    if expected_version is not None and int(existing["entity_version"]) != expected_version:
                        raise CasConflictError(
                            f"expected_version {expected_version} != stored {existing['entity_version']}",
                            current_version=int(existing["entity_version"]))
                    version = int(existing["entity_version"]) + 1
                    conn.execute(
                        "UPDATE ct_assignment SET state=?, pinned_revision=?, entity_version=?, "
                        "updated_at=? WHERE scope=? AND scope_identity=? AND harness_id=? "
                        "AND template_id=?",
                        (assignment.state, assignment.pinned_revision, version, now, *key_identity))
                return {"scope": assignment.scope, "scope_identity": assignment.scope_identity,
                        "harness_id": assignment.harness_id, "template_id": assignment.template_id,
                        "state": assignment.state, "pinned_revision": assignment.pinned_revision,
                        "entity_version": version, "updated_at": now}
            _, record = self._replay_or_record(conn, scope, operation_key, payload, produce)
        return Assignment(**record)

    def remove_assignment(self, *, scope: str, scope_identity: str, template_id: str,
                          harness_id: Optional[str] = None, expected_version: int,
                          operation_key: str) -> None:
        self._require_ready()
        with self._lock, self._transaction() as conn:
            key_identity = (scope, scope_identity, harness_id or "", template_id)
            existing = conn.execute(
                "SELECT entity_version FROM ct_assignment "
                "WHERE scope=? AND scope_identity=? AND harness_id=? AND template_id=?",
                key_identity).fetchone()
            if existing is None:
                raise ContentMissingError("that assignment does not exist")
            payload = request_digest_of({"remove": key_identity})
            scope_key = "ct.assignment_remove:" + ":".join(key_identity)

            def produce() -> dict:
                if int(existing["entity_version"]) != expected_version:
                    raise CasConflictError(
                        f"expected_version {expected_version} != stored {existing['entity_version']}",
                        current_version=int(existing["entity_version"]))
                conn.execute(
                    "DELETE FROM ct_assignment "
                    "WHERE scope=? AND scope_identity=? AND harness_id=? AND template_id=?",
                    key_identity)
                return {"removed": True}
            self._replay_or_record(conn, scope_key, operation_key, payload, produce)

    def assignments(self, *, scope: Optional[str] = None,
                    scope_identity: Optional[str] = None) -> "list[Assignment]":
        self._require_ready()
        sql = "SELECT * FROM ct_assignment"
        clauses: list[str] = []
        args: list[Any] = []
        if scope is not None:
            clauses.append("scope=?"); args.append(scope)
        if scope_identity is not None:
            clauses.append("scope_identity=?"); args.append(scope_identity)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY scope, scope_identity, harness_id, template_id"
        with self._read() as conn:
            rows = conn.execute(sql, args).fetchall()
        return [_row_to_assignment(row) for row in rows]

    def template_exists(self, template_id: str) -> bool:
        with self._read() as conn:
            return conn.execute("SELECT 1 FROM ct_template WHERE id=?", (template_id,)).fetchone() is not None

    def owners_of(self, template_ids: Iterable[str]) -> "dict[str, str]":
        ids = list(template_ids)
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        with self._read() as conn:
            rows = conn.execute(
                f"SELECT id, owner_principal FROM ct_template WHERE id IN ({marks})", ids).fetchall()
        return {row["id"]: row["owner_principal"] for row in rows}

    def display_of(self, template_id: str) -> "tuple[str, str]":
        """(display_name, slug, is_archived) for a template — for conflict text."""
        with self._read() as conn:
            row = conn.execute("SELECT display_name, slug, archived_at FROM ct_template WHERE id=?",
                               (template_id,)).fetchone()
        if row is None:
            raise ContentMissingError(f"template {template_id!r} does not exist")
        return (row["display_name"], row["slug"])


def _template_row(conn: sqlite3.Connection, template_id: str) -> dict:
    row = conn.execute("SELECT * FROM ct_template WHERE id=?", (template_id,)).fetchone()
    return dict(row)


def _to_template(row: Mapping[str, Any]) -> Template:
    return Template(
        id=row["id"], owner_principal=row["owner_principal"], display_name=row["display_name"],
        slug=row["slug"], description=row["description"], origin=row["origin"],
        latest_revision=int(row["latest_revision"]), entity_version=int(row["entity_version"]),
        created_at=row["created_at"], archived_at=row["archived_at"])


def _to_revision(record: Mapping[str, Any]) -> TemplateRevision:
    params = record["parameters"]
    if isinstance(params, str):
        parameters = _parameters_from_json(params)
    else:
        parameters = tuple(_rebuild_specs(params))
    return TemplateRevision(
        template_id=record["template_id"], revision=int(record["revision"]),
        body=record["body"], parameters=parameters,
        content_digest=record["content_digest"], approved_at=record.get("approved_at"),
        created_at=record["created_at"])


def _rebuild_specs(items: Sequence[Mapping[str, Any]]) -> "list[ParameterSpec]":
    specs: list[ParameterSpec] = []
    for item in items:
        item = dict(item)
        if item.get("choices") is not None:
            item["choices"] = tuple(item["choices"])
        specs.append(ParameterSpec(**item))
    return specs


def _row_to_revision(row: sqlite3.Row) -> TemplateRevision:
    return TemplateRevision(
        template_id=row["template_id"], revision=int(row["revision"]), body=row["body"],
        parameters=_parameters_from_json(row["parameters_json"]),
        content_digest=row["content_digest"], approved_at=row["approved_at"],
        created_at=row["created_at"])


def _row_to_assignment(row: sqlite3.Row) -> Assignment:
    return Assignment(
        scope=row["scope"], scope_identity=row["scope_identity"],
        template_id=row["template_id"], state=row["state"],
        harness_id=row["harness_id"] or None,
        pinned_revision=None if row["pinned_revision"] is None else int(row["pinned_revision"]),
        entity_version=int(row["entity_version"]), updated_at=row["updated_at"])
