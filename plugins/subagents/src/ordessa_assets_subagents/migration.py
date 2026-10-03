"""T05: the dry-run import of provably-pure legacy definitions (FR13/FR14, G10).

This module reads **row shapes**, never a database. A legacy row arrives as a
plain mapping, a frozen dataclass of column values, or a DB row object that
exposes ``keys()`` plus indexing — the caller does the reading and converts;
nothing here opens SQLite, a data root or a user HOME, and no legacy module is
imported (the shapes come from the read-only inventory, matrix §1).

The decision table is `specs/011-q3-subagents/legacy-inventory-matrix.md` §3,
one constant per row so a verdict can cite itself:

* M-01 the legacy delegation **grant table** (``parent_profile_id`` /
  ``child_profile_id``) — an authorization edge of the old dispatcher: REJECT,
  never definition content (FR12);
* M-02 the old dispatcher's synthesized tool pair and its schemas: REJECT;
* M-03 cycle / turn / timeout **policy** of the delegation service: KEEP-LEGACY;
* M-04 **call history** rows of the old run path: KEEP-LEGACY (run history is
  not migrated by default, data-model §状态和迁移);
* M-05 the synthesized **MCP entry** the old wire exposed to models:
  KEEP-LEGACY (keeping it with its owner is required; moving it here is not);
* M-06 a Profile row used *as* a delegate: UNKNOWN — the role summary was a
  projection field, not a column of its table, so content provenance is not
  provable from the row and no classifier here promotes it;
* M-07 a generic asset-catalogue row: UNKNOWN unless its ``kind`` is one this
  domain declares to hold role bodies **and** the digest-referenced content is
  supplied, re-hashes to that digest, decodes as a role body and validates as a
  revision — then, and only then, MIGRATE_CANDIDATE; a ``kind`` that is not role
  content is REJECT, and a body that reaches outside itself is REJECT (FR14);
* M-08 a Profile-to-asset **binding**: an assignment intent for the assignment
  owner (T04) — never a definition and never an approval (FR02);
* M-09 skill frontmatter content: REJECT — another domain's (Q1).

Two properties are structural, not conventional.

1. *No code path accepts a dispatch-shaped row.* Every classifier branch returns
   a decision and never a plan, so a grant edge / roster / tool schema / policy
   / history fact can never contribute a target definition id: when a row
   bundles such a fact with an otherwise-importable body, the refusal wins and
   the aggregate is reported as un-importable.
   :meth:`LegacyImporter.apply_import` then re-runs `classify` on the rows it is
   handed, so a manifest line whose row does not classify as a candidate is
   refused before the first write.
2. *The importer cannot invent content.* A candidate persists only with an
   explicit `dto.SourceApproval` whose ``content_digest`` is the manifest's
   digest and whose ``origin_ref`` **is** the legacy key, so the recorded
   ``legacy_key -> definitionId`` mapping is reversible (matrix §"Identity,
   format and idempotency rules (G10)").

Target ids are a pure function of ``(legacy_key, content_digest)`` — opaque,
never derived from a name or slug, and identical across stores and re-runs,
which is what makes a dry-run byte/ID stable.

Two digests travel through this module and they answer different questions.
The manifest's `content_digest` is `digest.bytes_digest` over the legacy row's
own bytes: it is what the legacy table attested, and it is the anchor for the
id and for G10's byte equality. A stored revision's `content_digest` is the
domain's `digest.revision_digest` over the whole revision *including* its
approval — so the two differ by design, and a rollback verifies the first
against the stored body rather than against the second.

The legacy dispatch vocabulary (the delegation module's roster resolver, cycle
guard, grant-edge helper, tool builder and the MCP entry name it synthesized)
appears nowhere in this file outside the docstrings; a test scans this module's
AST to prove it, and a companion test mutates a copy of this source to prove the
scan can fail.
"""
from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field, is_dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from . import decoder, limits
from .digest import bytes_digest, canonical_digest, is_digest, revision_digest
from .dto import SOURCE_ORIGINS, DefinitionRevision, SourceApproval
from .errors import (
    ASSIGNMENT_CONFLICT,
    DEFINITION_INVALID,
    PERMISSION_EXCEEDS_CEILING,
    REVISION_STALE,
    TARGET_CONFLICT,
    DomainError,
)
from .service import DefinitionService
from .store import DefinitionStore

__all__ = [
    "CATALOGUE_KINDS",
    "EDGE_KEYS",
    "ImportContext",
    "ImportableContent",
    "ImportedItem",
    "ImportResult",
    "LegacyAssetRow",
    "LegacyBindingRow",
    "LegacyGrantRow",
    "LegacyImporter",
    "LegacyProfileRow",
    "LegacyRowReport",
    "MATRIX_DOC",
    "MATRIX_ROWS",
    "MatrixRow",
    "MigrationDecision",
    "MigrationDecisionKind",
    "MigrationManifest",
    "MigrationManifestItem",
    "ROLE_CONTENT_KINDS",
    "RollbackSample",
    "classify",
    "classify_rows",
    "definition_id_for",
    "dry_run",
]

#: Where the decision table this module implements lives.
MATRIX_DOC = "specs/011-q3-subagents/legacy-inventory-matrix.md §3"

#: One entry per matrix row, so every reason names its own row.
MATRIX_ROWS: dict[str, str] = {
    "M-01": "legacy delegation grant table",
    "M-02": "the old dispatcher's synthesized tool pair",
    "M-03": "cycle / turn / timeout policy of the delegation service",
    "M-04": "call history of the old run path",
    "M-05": "the synthesized MCP entry exposed to models",
    "M-06": "a Profile row used as a delegate",
    "M-07": "a generic asset-catalogue row",
    "M-08": "a Profile-to-asset binding",
    "M-09": "skill frontmatter content under an asset root",
}


class MatrixRow:
    """The matrix row ids of §3, as names instead of bare literals."""

    GRANT_EDGE = "M-01"
    DISPATCH_TOOL_SCHEMA = "M-02"
    RUNTIME_POLICY = "M-03"
    CALL_HISTORY = "M-04"
    MCP_SYNTHESIS = "M-05"
    PROFILE_AS_DELEGATE = "M-06"
    ASSET_CATALOGUE = "M-07"
    PROFILE_ASSET_BINDING = "M-08"
    SKILL_CONTENT = "M-09"


class MigrationDecisionKind(str, Enum):
    """The matrix's verdicts, plus the binding's own category."""

    #: Provably pure role content with a stable identity and a verified digest.
    MIGRATE_CANDIDATE = "migrate_candidate"
    #: Not provable from data alone; an explicit approval round owns the call.
    UNKNOWN = "unknown"
    #: Stays with its current owner (dispatch / security run history).
    KEEP_LEGACY = "keep_legacy"
    #: Must never enter this store.
    REJECT = "reject"
    #: A desired choice for the assignment owner: never a definition, never an
    #: approval — promoting it needs `approveAssignmentUpdate` (FR02).
    ASSIGNMENT_INTENT = "assignment_intent"


# -- the legacy row shapes this module reads --------------------------------


class LegacyAssetRow(Protocol):
    """One asset-catalogue row: the columns of `server_assets` and nothing else.

    `content` is the digest-referenced body, read and supplied by the caller;
    it is what makes an M-07 row provable or not. A caller that cannot supply
    the body gets UNKNOWN — this module never guesses at content.
    """

    legacy_key: str
    kind: str
    name: str
    description: str | None
    latest_revision: int
    digest: str
    source: str | None
    content: str | None
    revision: int | None


class LegacyProfileRow(Protocol):
    """One Profile row as the old delegation module projected it.

    There is no description column here (matrix §1: the summary a roster entry
    carried was a projection field), which is exactly why this shape can only
    ever be UNKNOWN.
    """

    legacy_key: str
    name: str
    harness_type: str
    config_revision: int
    config_object_digest: str
    description: str | None


class LegacyGrantRow(Protocol):
    """One row of the old delegation grant table: a pure authorization edge."""

    parent_profile_id: str
    child_profile_id: str
    created_at: str


class LegacyBindingRow(Protocol):
    """One Profile-to-asset binding: a pinned revision plus an enabled flag."""

    profile_id: str
    asset_id: str
    revision: int
    enabled: bool


#: The dispatch-edge field names. A row exposing any of them gets an M-01 fact,
#: and an M-01 fact makes the row un-importable whatever else it carries.
EDGE_KEYS: frozenset[str] = frozenset({
    "parent_profile_id", "child_profile_id", "granted_by", "grant_id",
})
#: The callable-schema shape (M-02): a tool the old dispatcher synthesised.
TOOL_SCHEMA_KEYS: frozenset[str] = frozenset({
    "tool_schema", "input_schema", "parameters_schema", "function_name",
    "tool_pair", "synthesized_tools", "roster", "roster_entry", "availability",
    "delegation_summary",
})
#: The delegation service's own runtime policy (M-03).
POLICY_KEYS: frozenset[str] = frozenset({
    "max_turns", "turn_limit", "max_depth", "timeout_seconds",
    "cycle_chain", "delegation_chain", "inline_names", "roster_limit",
})
#: A row of the old run path's call history (M-04).
HISTORY_KEYS: frozenset[str] = frozenset({
    "parent_turn_id", "turn_id", "task_id", "run_state", "recovery_pending",
})
#: The MCP entry the old composition exposed to models (M-05).
MCP_KEYS: frozenset[str] = frozenset({
    "mcp_entry", "mcp_server_name", "server_entry", "composition_entry",
})
#: The skill frontmatter shape (M-09).
SKILL_KEYS: frozenset[str] = frozenset({
    "skill_root", "frontmatter_path", "skill_name", "instructions_path",
})
KIND_KEYS: tuple[str, ...] = ("kind", "asset_kind")
CONTENT_KEYS: tuple[str, ...] = ("content", "content_text", "body", "role_body")
#: The digest columns that attest content, each with the table it belongs to.
DIGEST_KEYS: tuple[tuple[str, str], ...] = (
    ("digest", "server_assets"),
    ("config_object_digest", "server_profiles"),
)
ID_KEYS: tuple[str, ...] = ("legacy_key", "key", "id", "asset_id", "profile_id")
TABLE_KEYS: tuple[str, ...] = ("table", "source_table", "legacy_table")

#: The catalogue kinds this domain declares to hold role bodies. The legacy
#: catalogue's own kinds are deliberately absent — none of them is role content,
#: which is why §3 puts M-07 at UNKNOWN and sends M-09 away as REJECT. An
#: approved *kind* is still only half the proof: the body has to re-hash.
ROLE_CONTENT_KINDS: frozenset[str] = frozenset({
    "subagent", "role_definition", "agent_role",
})
#: Kinds the legacy catalogue really used; named so a refusal can say which one.
CATALOGUE_KINDS: frozenset[str] = frozenset({"skill", "mcp", "command", "plugin"})

#: A body that reaches out to another file, host or shell template is not a
#: self-contained definition (FR14). `service` keeps the equivalent predicate
#: module-private, so this import path carries its own conservative copy.
_REACH_OUT_MARKERS: tuple[str, ...] = (
    "![[", "@[[", "@import", "{{include", "http://", "https://", "ftp://",
)

_ID_SEED = "ordessa-q3-legacy-import/"
_PLACEHOLDER = "sha256:" + "0" * 64
_PREVIEW_PRINCIPAL = "preview:anonymous"
_PREVIEW_MOMENT = "1970-01-01T00:00:00Z"


def _refuse(code: str, item: str | None, detail: str) -> DomainError:
    return DomainError(code, item_id=item, detail=detail)


class _RowView:
    """A legacy row as a key set plus bounded field reads, nothing more."""

    __slots__ = ("_row", "_data", "keys")

    def __init__(self, row: Any) -> None:
        data = _as_column_mapping(row)
        if data is None:
            if not _is_row_object(row):
                raise _refuse(
                    DEFINITION_INVALID, "legacy_row",
                    "a legacy row is a mapping of columns, a row dataclass or a "
                    "DB row exposing keys(); this module opens no connection",
                )
            self._row = row
            self._data = None
            self.keys = frozenset(
                name for name in dir(row) if not name.startswith("_")
            )
        else:
            self._row = None
            self._data = data
            self.keys = frozenset(str(name) for name in data)

    def has_any(self, names: Iterable[str]) -> bool:
        return any(name in self.keys for name in names)

    def overlapping(self, names: Iterable[str]) -> tuple[str, ...]:
        return tuple(sorted(name for name in names if name in self.keys))

    def raw(self, name: str) -> Any:
        if self._data is not None:
            return self._data.get(name)
        return getattr(self._row, name, None)

    def text(self, *names: str) -> str | None:
        """The first named field holding a plain scalar, as text."""
        for name in names:
            value = self.raw(name)
            if value is None or isinstance(value, bool):
                continue
            if isinstance(value, (str, int, float)):
                return str(value)
        return None

    def flag(self, name: str) -> bool | None:
        value = self.raw(name)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.lower() in ("0", "1", "true", "false"):
            return value.lower() in ("1", "true")
        return None

    def table_hint(self) -> str | None:
        return self.text(*TABLE_KEYS)

    def legacy_key(self) -> str:
        for name in ("legacy_key", "key"):
            value = self.raw(name)
            if value is None:
                continue
            if not isinstance(value, (str, int)):
                raise _refuse(
                    DEFINITION_INVALID, name,
                    "a legacy key is text or an integer id, never "
                    f"{type(value).__name__}",
                )
            return _bounded_key(str(value), item=name)
        identity = self.text(*ID_KEYS)
        if identity is not None:
            return f"{self._inferred_table()}:{identity}"
        return f"{self._inferred_table()}:row-{self.row_digest()}"

    def digest(self) -> tuple[str | None, str | None]:
        """The recorded content digest and the column it came from."""
        for name, table in DIGEST_KEYS:
            value = self.text(name)
            if value is not None:
                return value, table
        return None, None

    def content(self) -> str | None:
        for name in CONTENT_KEYS:
            value = self.raw(name)
            if isinstance(value, str):
                return value
            if isinstance(value, bytes):
                try:
                    return value.decode("utf-8", errors="strict")
                except UnicodeDecodeError:
                    return None
        return None

    def pinned_revision(self) -> int | None:
        """The revision the supplied body belongs to, never the newest one.

        A catalogue row can carry a body of a different revision than its
        `latest_revision` column; trusting `latest_revision` over the row would
        pin an unattested number, so an unrecorded revision is not provable.
        """
        value = self.text("content_revision", "revision")
        if value is None:
            return None
        text = value.strip()
        try:
            number = int(text)
        except ValueError:
            return None
        return number if number >= 1 and str(number) == text else None

    def role_name(self) -> str | None:
        return self.text("name", "display_name")

    def role_description(self) -> str | None:
        return self.text("description")

    def kind(self) -> str | None:
        return self.text(*KIND_KEYS)

    def _inferred_table(self) -> str:
        hint = self.table_hint()
        if hint is not None:
            return hint
        for keys, table in _TABLE_BY_KEYS:
            if self.has_any(keys):
                return table
        return "legacy_row"

    def row_digest(self) -> str:
        """A stable digest over the row's scalar columns, as a key fallback."""
        scalar = {
            name: _scalar_of(self.raw(name))
            for name in sorted(self.keys)
            if _scalar_of(self.raw(name)) is not None
        }
        return canonical_digest(scalar).removeprefix("sha256:")[:16]


_TABLE_BY_KEYS: tuple[tuple[frozenset[str], str], ...] = (
    (EDGE_KEYS, "server_subagent_grants"),
    (TOOL_SCHEMA_KEYS | MCP_KEYS, "legacy_dispatch_surface"),
    (HISTORY_KEYS, "server_turns"),
    (POLICY_KEYS, "legacy_runtime_policy"),
    (frozenset({"profile_id", "asset_id"}), "server_profile_assets"),
    (frozenset({"harness_type", "config_object_digest"}), "server_profiles"),
    (frozenset({"kind", "digest"}), "server_assets"),
)

#: Column names that mark an object as a legacy row rather than an arbitrary one.
_ROW_MARKERS = (
    "legacy_key", "id", "kind", "name", "digest", "parent_profile_id",
    "child_profile_id", "asset_id", "profile_id", "harness_type", "latest_revision",
)


def _as_column_mapping(row: Any) -> dict[str, Any] | None:
    """A mapping, or a DB-row object exposing keys() plus indexing."""
    if isinstance(row, Mapping):
        return {str(key): value for key, value in row.items()}
    keys = getattr(row, "keys", None)
    if callable(keys):
        try:
            names = list(keys())
            return {str(name): row[name] for name in names}
        except (TypeError, IndexError, KeyError):
            return None
    return None


def _is_row_object(value: Any) -> bool:
    if is_dataclass(value) and not isinstance(value, type):
        return True
    return any(hasattr(value, marker) for marker in _ROW_MARKERS)


def _scalar_of(value: Any) -> str | None:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _bounded_key(value: str, *, item: str) -> str:
    if not value:
        raise _refuse(DEFINITION_INVALID, item, "a legacy key is not empty")
    if len(value) > limits.MAX_SOURCE_REF_CHARS:
        raise _refuse(
            DEFINITION_INVALID, item,
            f"a legacy key fits {limits.MAX_SOURCE_REF_CHARS} characters",
        )
    if value.startswith("/") or value.startswith("~") or value.startswith(".."):
        raise _refuse(
            DEFINITION_INVALID, item,
            "a legacy key is a provenance label, never a host path",
        )
    return value


# -- the decisions ----------------------------------------------------------


@dataclass(frozen=True)
class ImportableContent:
    """The decoded body of one candidate: content, its pinned number, its name."""

    role_body: str
    revision: int
    content_digest: str
    display_name: str
    document: Mapping[str, Any] = field(repr=False, default_factory=dict)


@dataclass(frozen=True)
class MigrationDecision:
    """One matrix verdict: its row id, its category, its reason, its plan."""

    legacy_key: str
    decision: MigrationDecisionKind
    matrix_row: str
    reason: str
    content_digest: str | None = None
    target_definition_id: str | None = None
    target_revision: int | None = None
    content: ImportableContent | None = field(repr=False, default=None)

    def as_report(self) -> dict[str, str]:
        return {
            "legacy_key": self.legacy_key,
            "decision": self.decision.value,
            "matrix_row": self.matrix_row,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LegacyRowReport:
    """Every verdict for one input row, so a bundled row reports whole.

    A row may carry more than one legacy fact (a catalogue body plus a
    delegation grant on the same identifier): `primary` is the verdict the
    manifest records, `observations` lists each fact in matrix order, and
    `importable` holds only when a *single* fact is a migrate candidate — an
    aggregate never plans a target id.
    """

    legacy_key: str
    primary: MigrationDecision
    observations: tuple[MigrationDecision, ...] = ()

    @property
    def decision(self) -> MigrationDecisionKind:
        return self.primary.decision

    @property
    def importable(self) -> bool:
        return (
            len(self.observations) == 1
            and self.primary.decision is MigrationDecisionKind.MIGRATE_CANDIDATE
        )

    def as_report(self) -> dict[str, Any]:
        return {
            "legacy_key": self.legacy_key,
            "decision": self.primary.decision.value,
            "matrix_row": self.primary.matrix_row,
            "reason": self.primary.reason,
            "observations": [item.as_report() for item in self.observations],
        }


def classify(row: Any) -> MigrationDecision:
    """The matrix verdict over one legacy row: it reads, it never writes."""
    return _report_of(_view_of(row)).primary


def classify_rows(rows: Iterable[Any]) -> tuple[LegacyRowReport, ...]:
    """Every input row with all of its verdicts, in the input's own order."""
    return tuple(_report_of(view) for view in (_view_of(row) for row in rows))


def _view_of(row: Any) -> _RowView:
    return row if isinstance(row, _RowView) else _RowView(row)


def _report_of(view: _RowView) -> LegacyRowReport:
    observations = _facts_of(view)
    primary = (
        _aggregate(view, observations)
        if len(observations) > 1
        else observations[0]
    )
    return LegacyRowReport(
        legacy_key=primary.legacy_key, primary=primary, observations=observations
    )


def _facts_of(view: _RowView) -> tuple[MigrationDecision, ...]:
    """Each legacy fact a row carries, one verdict each, in matrix order.

    Every branch returns a decision and never a plan, which is what keeps a
    dispatch fact out of an aggregate's target id.
    """
    key = view.legacy_key()
    facts: list[MigrationDecision] = []

    edge = view.overlapping(EDGE_KEYS)
    if edge:
        facts.append(_decide(
            key, MigrationDecisionKind.REJECT, MatrixRow.GRANT_EDGE,
            reason=(
                f"{MATRIX_ROWS[MatrixRow.GRANT_EDGE]}: an authorization edge of "
                f"the old dispatcher is not definition content and never a "
                f"licence for a new definition (FR12); the columns "
                f"{'/'.join(edge)} name the delegation mechanism this domain "
                f"must not absorb"
            ),
        ))

    if view.has_any(TOOL_SCHEMA_KEYS):
        facts.append(_decide(
            key, MigrationDecisionKind.REJECT, MatrixRow.DISPATCH_TOOL_SCHEMA,
            reason=(
                f"{MATRIX_ROWS[MatrixRow.DISPATCH_TOOL_SCHEMA]}: a synthesized "
                "tool schema is the delegation service's surface and belongs to "
                "its owner; a content store has no use for it"
            ),
        ))

    if view.has_any(MCP_KEYS):
        facts.append(_decide(
            key, MigrationDecisionKind.KEEP_LEGACY, MatrixRow.MCP_SYNTHESIS,
            reason=(
                f"{MATRIX_ROWS[MatrixRow.MCP_SYNTHESIS]}: the old authorization "
                "edge keeps its owner — keeping it is required, moving it into "
                "this store is not (T13)"
            ),
        ))

    if view.has_any(HISTORY_KEYS):
        facts.append(_decide(
            key, MigrationDecisionKind.KEEP_LEGACY, MatrixRow.CALL_HISTORY,
            reason=(
                f"{MATRIX_ROWS[MatrixRow.CALL_HISTORY]}: run history is not "
                "migrated by default (data-model §状态和迁移)"
            ),
        ))

    if view.has_any(POLICY_KEYS):
        facts.append(_decide(
            key, MigrationDecisionKind.KEEP_LEGACY, MatrixRow.RUNTIME_POLICY,
            reason=(
                f"{MATRIX_ROWS[MatrixRow.RUNTIME_POLICY]}: runtime policy of the "
                "delegation service, not a definition ceiling"
            ),
        ))

    if view.kind() == "skill" or view.has_any(SKILL_KEYS):
        facts.append(_decide(
            key, MigrationDecisionKind.REJECT, MatrixRow.SKILL_CONTENT,
            reason=(
                f"{MATRIX_ROWS[MatrixRow.SKILL_CONTENT]}: a different domain, "
                "owned by Q1; no amount of approval makes it this store's content"
            ),
        ))

    binding = _binding_fact(view, key)
    if binding is not None:
        facts.append(binding)

    catalogue = _catalogue_fact(view, key)
    if catalogue is not None:
        facts.append(catalogue)

    if not facts:
        facts.append(_decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.ASSET_CATALOGUE,
            reason=(
                "the row names no legacy fact this matrix covers: an unknown "
                "shape is never guessed into a definition"
            ),
        ))
    return tuple(facts)


def _binding_fact(view: _RowView, key: str) -> MigrationDecision | None:
    """M-08: a Profile-to-asset binding is an assignment intent, nothing more."""
    names_profile = "profile_id" in view.keys
    names_asset = "asset_id" in view.keys
    hinted = view.table_hint() == "server_profile_assets"
    if not ((names_profile and names_asset) or (hinted and names_asset)):
        return None
    revision = view.pinned_revision()
    enabled = view.flag("enabled")
    return _decide(
        key, MigrationDecisionKind.ASSIGNMENT_INTENT, MatrixRow.PROFILE_ASSET_BINDING,
        reason=(
            f"{MATRIX_ROWS[MatrixRow.PROFILE_ASSET_BINDING]}: a desired choice "
            f"(pinned revision {revision if revision is not None else 'unrecorded'}, "
            f"enabled {enabled if enabled is not None else 'unrecorded'}) that the "
            "assignment owner approves separately; it is neither a definition "
            "body nor a source approval, so this importer persists nothing from it"
        ),
    )


def _catalogue_fact(view: _RowView, key: str) -> MigrationDecision | None:
    """M-06 / M-07: the two content-bearing legacy shapes."""
    kind = view.kind()
    is_asset = kind is not None or "digest" in view.keys
    is_profile = (
        view.text("harness_type") is not None
        or "config_object_digest" in view.keys
        or view.table_hint() == "server_profiles"
    )
    if not (is_asset or is_profile):
        return None
    if is_profile:
        return _decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.PROFILE_AS_DELEGATE,
            reason=(
                f"{MATRIX_ROWS[MatrixRow.PROFILE_AS_DELEGATE]}: the description "
                "such a row was shown with is a projection field, not a column, "
                "so content provenance is not provable from the row and its "
                "digest attests a config object, not a role body; an explicit "
                "per-item approval round owns that call (G05) and this "
                "classifier never promotes a Profile row"
            ),
        )
    return _asset_decision(view, key, kind)


def _asset_decision(view: _RowView, key: str, kind: str | None) -> MigrationDecision:
    digest, digest_column = view.digest()
    name = view.role_name()
    description = view.role_description()

    if kind is None or kind not in ROLE_CONTENT_KINDS:
        return _decide(
            key, MigrationDecisionKind.REJECT, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                f"the row's kind {kind!r} is not role content: this domain "
                f"declares {sorted(ROLE_CONTENT_KINDS)} only, and a catalogue "
                f"row of another kind — including the legacy kinds "
                f"{sorted(CATALOGUE_KINDS)} — holds no definition body"
            ),
        )
    if name is None or description is None:
        return _decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                "identity is not stable: the row carries a name ("
                + str(name is not None) + ") and a role summary ("
                + str(description is not None) + "); an unnamed role is not "
                "provable content"
            ),
        )
    if digest is None or not is_digest(digest):
        return _decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                f"the recorded digest of {digest_column} is missing or is not a "
                "sha256 content digest, so the content it names cannot be "
                "verified against anything"
            ),
        )
    body = view.content()
    if body is None:
        return _decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                "the digest-referenced body was not supplied with the row, so "
                "nothing here proves the content the digest attests; the caller "
                "reads content and hands it over as a mapping"
            ),
        )
    if bytes_digest(body.encode("utf-8")) != digest:
        return _decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                "the supplied body does not re-hash to the row's recorded "
                "digest, so its provenance is not provable"
            ),
        )
    if decoder.has_credential_shape(body):
        return _decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                "the body carries credential-shaped content, so it is not a "
                "pure definition: declare a resource reference and let its "
                "owner authorise it"
            ),
        )
    try:
        document = decoder.decode_import_document(body, item=key)
    except DomainError as exc:
        return _decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                "the digest-referenced content does not decode as a role body "
                f"({exc.code}: {exc.detail})"
            ),
        )
    if _reaches_out(body) is not None:
        return _decide(
            key, MigrationDecisionKind.REJECT, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                f"a {_reaches_out(body)} directive reaches outside the approved "
                "bytes (FR14), so the body is not a self-contained definition"
            ),
        )
    revision = view.pinned_revision()
    if revision is None:
        return _decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                "the revision these bytes belong to is unrecorded, so no pinned "
                "revision could be preserved; `latest_revision` alone is not "
                "proof of which revision was digested"
            ),
        )
    try:
        decoder.validate_revision(_revision_of(
            definition_id="def_previewplaceholder00000000", revision=revision,
            content=ImportableContent(
                role_body=body, revision=revision, content_digest=digest,
                display_name=name, document=document,
            ),
            approval=_preview_approval(key, digest),
        ))
    except DomainError as exc:
        return _decide(
            key, MigrationDecisionKind.UNKNOWN, MatrixRow.ASSET_CATALOGUE,
            content_digest=digest,
            reason=(
                "the digest-referenced content is not a valid revision body "
                f"({exc.code}: {exc.detail})"
            ),
        )
    plan = ImportableContent(
        role_body=body, revision=revision, content_digest=digest,
        display_name=name, document=document,
    )
    return _decide(
        key, MigrationDecisionKind.MIGRATE_CANDIDATE, MatrixRow.ASSET_CATALOGUE,
        content_digest=digest,
        reason=(
            f"only {MATRIX_ROWS[MatrixRow.ASSET_CATALOGUE]} rows whose "
            "digest-referenced content decodes as a role body qualify: this row "
            "carries a stable identity, a sha256 digest its supplied body "
            "re-hashes to, a pinned revision and a body that validates as a "
            "revision — still only a candidate until an explicit SourceApproval "
            "for exactly these bytes exists (G05)"
        ),
        content=plan,
    )


def _aggregate(view: _RowView, facts: Sequence[MigrationDecision]) -> MigrationDecision:
    """One row, several facts: the worst verdict wins and nothing is planned."""
    ordered = sorted(facts, key=lambda item: _SEVERITY.index(item.decision))
    worst = ordered[0]
    return _decide(
        view.legacy_key(), worst.decision, worst.matrix_row,
        reason=(
            "this row bundles "
            + " + ".join(f"{item.matrix_row}:{item.decision.value}" for item in ordered)
            + f" — the {worst.decision.value} verdict governs, and a legacy "
            "projection aggregate is not provably pure definition content; "
            + worst.reason
        ),
    )


_SEVERITY: tuple[MigrationDecisionKind, ...] = (
    MigrationDecisionKind.REJECT,
    MigrationDecisionKind.KEEP_LEGACY,
    MigrationDecisionKind.ASSIGNMENT_INTENT,
    MigrationDecisionKind.UNKNOWN,
    MigrationDecisionKind.MIGRATE_CANDIDATE,
)


def _decide(
    legacy_key: str,
    decision: MigrationDecisionKind,
    matrix_row: str,
    *,
    reason: str,
    content_digest: str | None = None,
    content: ImportableContent | None = None,
) -> MigrationDecision:
    if matrix_row not in MATRIX_ROWS:
        raise _refuse(DEFINITION_INVALID, "matrix_row", f"no such matrix row {matrix_row}")
    target_id: str | None = None
    target_revision: int | None = None
    if decision is MigrationDecisionKind.MIGRATE_CANDIDATE and content is not None:
        target_id = definition_id_for(legacy_key, content.content_digest)
        target_revision = content.revision
    return MigrationDecision(
        legacy_key=legacy_key, decision=decision, matrix_row=matrix_row, reason=reason,
        content_digest=content_digest, target_definition_id=target_id,
        target_revision=target_revision, content=content,
    )


def _reaches_out(body: str) -> str | None:
    for marker in _REACH_OUT_MARKERS:
        if marker in body:
            return marker
    return None


def _preview_approval(legacy_key: str, digest: str) -> SourceApproval:
    """A stand-in used only to *validate* a body during a dry run."""
    return SourceApproval(
        origin="user-upload", origin_ref=legacy_key, content_digest=digest,
        approved_by_principal=_PREVIEW_PRINCIPAL, approved_at=_PREVIEW_MOMENT,
    )


# -- identity: stable, opaque, never derived from a name --------------------


def definition_id_for(legacy_key: str, content_digest: str) -> str:
    """The import target id for one approved legacy row.

    Opaque and a *pure function* of the legacy key and the content digest, so a
    re-run of a dry run — against a fresh root or a fresh store — names the same
    target, which is what G10's byte/ID equality needs. A `definitionId` is
    never derived from a name or slug (data-model §1), so neither input is a
    display name; the legacy key itself is recorded in
    `SourceApproval.origin_ref`, which is what makes the mapping reversible.
    """
    if not content_digest or not is_digest(content_digest):
        raise _refuse(
            DEFINITION_INVALID, "content_digest",
            "a target id needs the sha256 digest the row attests",
        )
    seed = f"{_ID_SEED}{legacy_key}\n{content_digest}".encode("utf-8")
    return "def_imp_" + hashlib.sha256(seed).hexdigest()[:24]


# -- the dry-run manifest ---------------------------------------------------


@dataclass(frozen=True)
class MigrationManifestItem:
    """One manifest line: the five reported fields plus the row it cites."""

    legacy_key: str
    content_digest: str | None
    target_definition_id: str | None
    target_revision: int | None
    decision: MigrationDecisionKind
    reason: str
    matrix_row: str

    def as_mapping(self) -> dict[str, Any]:
        return {
            "legacy_key": self.legacy_key,
            "content_digest": self.content_digest,
            "target_definition_id": self.target_definition_id,
            "target_revision": self.target_revision,
            "decision": self.decision.value,
            "reason": self.reason,
            "matrix_row": self.matrix_row,
        }


@dataclass(frozen=True)
class MigrationManifest:
    """A deterministic, write-free report over every input row.

    Order is a defined sort key — `(legacy_key, content_digest, matrix_row)` —
    never argument or dict order, and `manifest_digest` covers the sorted lines,
    so two callers holding the same rows hold the same manifest.
    """

    items: tuple[MigrationManifestItem, ...] = ()

    @property
    def manifest_digest(self) -> str:
        return canonical_digest(
            {"manifest": [item.as_mapping() for item in self.items]}
        )

    def planned(self) -> tuple[MigrationManifestItem, ...]:
        return tuple(
            item for item in self.items
            if item.decision is MigrationDecisionKind.MIGRATE_CANDIDATE
        )

    def refused(self) -> tuple[MigrationManifestItem, ...]:
        return tuple(
            item for item in self.items
            if item.decision is not MigrationDecisionKind.MIGRATE_CANDIDATE
        )

    def by_legacy_key(self) -> dict[str, MigrationManifestItem]:
        return {item.legacy_key: item for item in self.items}

    def tally(self) -> dict[str, int]:
        counts = {kind.value: 0 for kind in MigrationDecisionKind}
        for item in self.items:
            counts[item.decision.value] += 1
        return counts

    def as_report(self) -> dict[str, Any]:
        return {
            "manifest_digest": self.manifest_digest,
            "tally": self.tally(),
            "items": [item.as_mapping() for item in self.items],
        }


def dry_run(rows: Iterable[Any]) -> MigrationManifest:
    """The matrix's preview step: a report over every row, and nothing written.

    This function takes no store, no service and no path, so it structurally
    cannot write; :meth:`LegacyImporter.dry_run` delegates here.
    """
    items = [_item_of(classify(row)) for row in rows]
    items.sort(key=_item_sort_key)
    return MigrationManifest(items=tuple(items))


def _item_of(decision: MigrationDecision) -> MigrationManifestItem:
    return MigrationManifestItem(
        legacy_key=decision.legacy_key,
        content_digest=decision.content_digest,
        target_definition_id=decision.target_definition_id,
        target_revision=decision.target_revision,
        decision=decision.decision,
        reason=decision.reason,
        matrix_row=decision.matrix_row,
    )


def _item_sort_key(item: MigrationManifestItem) -> tuple[str, str, str]:
    return (item.legacy_key, item.content_digest or "", item.matrix_row)


# -- the approved import ----------------------------------------------------


@dataclass(frozen=True)
class ImportedItem:
    """One row this import actually persisted, with its reversible mapping."""

    legacy_key: str
    definition_id: str
    revision: int
    content_digest: str
    row_version: int

    def as_mapping(self) -> dict[str, Any]:
        return {
            "legacy_key": self.legacy_key,
            "definition_id": self.definition_id,
            "revision": self.revision,
            "content_digest": self.content_digest,
            "row_version": self.row_version,
        }


@dataclass(frozen=True)
class ImportContext:
    """The identity of one apply, enough to find its own receipts again."""

    principal: str
    server_scope: str
    operation_key: str
    manifest_digest: str

    @property
    def receipt_scope(self) -> str:
        return (
            f"legacy_import:{self.principal}:{self.server_scope}"
            f":{self.manifest_digest}"
        )


@dataclass(frozen=True)
class ImportResult:
    manifest_digest: str
    replayed: bool
    imported: tuple[ImportedItem, ...] = ()
    skipped: tuple[MigrationManifestItem, ...] = ()
    context: ImportContext | None = None

    def mapping_table(self) -> dict[str, str]:
        """The reversible ``legacy_key -> definitionId`` view of this import."""
        return {item.legacy_key: item.definition_id for item in self.imported}

    def as_report(self) -> dict[str, Any]:
        return {
            "manifest_digest": self.manifest_digest,
            "replayed": self.replayed,
            "imported": [item.as_mapping() for item in self.imported],
            "skipped": [item.as_mapping() for item in self.skipped],
            "operation_key": (
                self.context.operation_key if self.context is not None else None
            ),
        }


@dataclass(frozen=True)
class RollbackSample:
    """The reversible half of an import: what maps where, and what to remove.

    Every listed path was verified against the manifest before it was listed:
    the target id derives from the manifest line, the stored body re-hashes to
    the manifest's content digest, and the stored approval's `origin_ref` names
    the same legacy key. A definition that fails that check is reported as
    `untouched_definition_ids` and is never scheduled for removal.
    """

    manifest_digest: str
    store_root: Path
    mapping: tuple[tuple[str, str], ...] = ()
    deletion_paths: tuple[str, ...] = ()
    verified: tuple[dict[str, Any], ...] = ()
    untouched_definition_ids: tuple[str, ...] = ()
    context: ImportContext | None = None

    def mapping_table(self) -> dict[str, str]:
        return dict(self.mapping)

    def as_report(self) -> dict[str, Any]:
        return {
            "manifest_digest": self.manifest_digest,
            "mapping": [{"legacy_key": key, "definition_id": value}
                        for key, value in self.mapping],
            "deletion_paths": list(self.deletion_paths),
            "untouched_definition_ids": list(self.untouched_definition_ids),
        }


class LegacyImporter:
    """Two steps over legacy row shapes: a report, then an approved write.

    The write path *is* the domain's own service and store:
    `DefinitionService.create_definition` carries authentication, the aggregate
    budget, id-stability rules and the per-row receipt; `DefinitionStore`
    carries the immutable revision and the CAS bump that pins the imported
    revision number. No second definition type and no second store live here.
    """

    def __init__(self, service: DefinitionService) -> None:
        self.service = service

    # -- the read-only half ------------------------------------------------

    def dry_run(self, rows: Iterable[Any]) -> MigrationManifest:
        return dry_run(rows)

    def report(self, rows: Iterable[Any]) -> tuple[LegacyRowReport, ...]:
        return classify_rows(rows)

    # -- the approved half -------------------------------------------------

    def apply_import(
        self,
        manifest: MigrationManifest,
        *,
        principal: Any,
        expected_row_version: int,
        operation_key: str,
        approvals: Mapping[str, SourceApproval] | Sequence[SourceApproval],
        rows: Sequence[Any] | None = None,
        server_scope: str | None = None,
        origin_scope: str = "public",
        origin_owner: str = "local",
    ) -> ImportResult:
        """Persist only the candidates that carry an explicit approval.

        `rows` is the same row set the manifest was built over: the write path
        re-runs `classify` on it, so a manifest line whose row does not decide a
        migrate candidate — or whose body drifted since the dry run — is refused
        before the first write. Anything else the matrix decided is reported in
        `skipped` and structurally cannot be written.

        `expected_row_version` is the caller's CAS expectation for each target
        row: a target id is derived from its row, so a fresh import expects 0
        and a row that already exists at another version is `REVISION_STALE`.
        One `operation_key` covers the whole apply: the manifest's own receipt
        replays the recorded result (same payload) or refuses (different
        payload), and each row's service receipt is keyed
        `<operation_key>:<definitionId>` so an operation cannot answer across
        items. `origin_scope` / `origin_owner` say where the imported library
        belongs; the *provenance* of each row is the approval, never these.
        """
        who = _principal_id(principal)
        scope = self._server_scope(server_scope)
        self._authenticate(who, scope)
        self._check_operation_key(operation_key)
        if isinstance(expected_row_version, bool) or not isinstance(
            expected_row_version, int
        ):
            raise _refuse(
                DEFINITION_INVALID, "expected_row_version",
                "an import names the row version it expects",
            )
        if not isinstance(manifest, MigrationManifest):
            raise _refuse(
                DEFINITION_INVALID, "manifest",
                "expected a MigrationManifest produced by a dry run",
            )
        if rows is None:
            raise _refuse(
                DEFINITION_INVALID, "rows",
                "an approved import re-checks its source rows",
            )

        reports = classify_rows(rows)
        decisions = _unique_by_key(reports)

        context = ImportContext(
            principal=who, server_scope=scope, operation_key=operation_key,
            manifest_digest=manifest.manifest_digest,
        )
        request = _request_digest(manifest, approvals, context, expected_row_version)
        receipt = self.service.store.read_receipt(context.receipt_scope, operation_key)
        if receipt is not None:
            if receipt.get("request_digest") != request:
                raise _refuse(
                    ASSIGNMENT_CONFLICT, "operation_key",
                    "that operation key already recorded a different import",
                )
            return ImportResult(
                manifest_digest=manifest.manifest_digest, replayed=True,
                imported=tuple(
                    ImportedItem(**dict(entry))
                    for entry in receipt["result"]["imported"]
                ),
                skipped=manifest.refused(), context=context,
            )

        planned = self._replanned(
            manifest, decisions, approvals=approvals, principal=who,
            expected_row_version=expected_row_version,
        )

        imported = tuple(
            self._write_one(
                item, content, approval,
                principal=who, server_scope=scope, origin_scope=origin_scope,
                origin_owner=origin_owner, operation_key=operation_key,
                expected_row_version=expected_row_version,
            )
            for item, content, approval in planned
        )
        if imported:
            # A report that persisted nothing needs no idempotency receipt:
            # there is no result to replay, and writing one would leave bytes
            # a dry-run-style call should never leave.
            self.service.store.write_receipt(
                scope=context.receipt_scope, operation_key=operation_key,
                request_digest=request,
                result={
                    "manifest_digest": manifest.manifest_digest,
                    "imported": [entry.as_mapping() for entry in imported],
                },
            )
        return ImportResult(
            manifest_digest=manifest.manifest_digest, replayed=False,
            imported=imported, skipped=manifest.refused(), context=context,
        )

    # -- rollback ----------------------------------------------------------

    def rollback_sample(
        self,
        manifest: MigrationManifest,
        store_root: Path | str,
        *,
        context: ImportContext | None = None,
    ) -> RollbackSample:
        """The reversible mapping plus the deletion set of exactly this import.

        Read-only. With a `context` (the one `apply_import` returned) the set
        also names this import's own receipts, so a later apply re-imports from
        zero instead of replaying a row it just deleted.
        """
        root = Path(store_root)
        store = DefinitionStore(root)
        mapping: list[tuple[str, str]] = []
        verified: list[dict[str, Any]] = []
        untouched: list[str] = []
        for item in manifest.planned():
            definition_id = item.target_definition_id
            revision_number = item.target_revision
            if definition_id is None or item.content_digest is None:
                continue
            directory = store.definition_dir(definition_id)
            stored = (
                store.read_revision(definition_id, revision_number or 0)
                if revision_number is not None else None
            )
            if (
                not directory.is_dir()
                or stored is None
                or bytes_digest(stored.role_body.encode("utf-8")) != item.content_digest
                or stored.source is None
                or stored.source.origin_ref != item.legacy_key
            ):
                untouched.append(definition_id)
                continue
            mapping.append((item.legacy_key, definition_id))
            verified.append({
                "legacy_key": item.legacy_key,
                "definition_id": definition_id,
                "revision": revision_number,
                "content_digest": item.content_digest,
                "expected_row_version": 1,
            })
        deletion = [
            _relative_to(root, store.definition_dir(entry["definition_id"]))
            for entry in verified
        ]
        if context is not None:
            deletion.extend(self._receipt_paths(root, store, context, mapping))
        return RollbackSample(
            manifest_digest=manifest.manifest_digest, store_root=root,
            mapping=tuple(mapping), deletion_paths=tuple(sorted(set(deletion))),
            verified=tuple(verified), untouched_definition_ids=tuple(sorted(untouched)),
            context=context,
        )

    def remove_rollback_set(self, sample: RollbackSample) -> tuple[str, ...]:
        """Delete exactly the paths one rollback sample verified."""
        root = sample.store_root
        store = DefinitionStore(root)
        owned = {definition_id for _, definition_id in sample.mapping}
        receipts = (
            set(self._receipt_paths(
                root, store, sample.context, list(sample.mapping),
            ))
            if sample.context is not None else set()
        )
        removed: list[str] = []
        for relative in sample.deletion_paths:
            path = _resolve_under(root, relative)
            if relative.startswith("definitions/"):
                owner = path.relative_to(store.root / "definitions").parts
                if not owner or owner[0] not in owned:
                    raise _refuse(
                        TARGET_CONFLICT, relative,
                        "a rollback set may only remove a definition this import "
                        "verified against its own manifest",
                    )
            elif relative in receipts:
                pass
            else:
                raise _refuse(
                    TARGET_CONFLICT, relative,
                    "a rollback set removes only this import's definitions and "
                    "the receipts of the apply that created them",
                )
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            else:
                continue
            removed.append(relative)
        return tuple(sorted(removed))

    # -- internals ---------------------------------------------------------

    def _server_scope(self, server_scope: str | None) -> str:
        scope = server_scope or getattr(self.service, "default_server_scope", None)
        if not isinstance(scope, str) or not scope:
            raise _refuse(
                DEFINITION_INVALID, "server_scope",
                "an import names the server scope it writes into",
            )
        return scope

    def _authenticate(self, principal: str, server_scope: str) -> None:
        if not self.service.authority.verify_principal(
            principal, server_scope=server_scope
        ):
            raise _refuse(
                PERMISSION_EXCEEDS_CEILING, "principal",
                "the caller is not a principal this server recognises",
            )

    def _check_operation_key(self, operation_key: str) -> None:
        if not isinstance(operation_key, str) or not operation_key:
            raise _refuse(
                DEFINITION_INVALID, "operation_key",
                "every mutation carries an operation key",
            )
        if len(operation_key) > limits.MAX_OPERATION_KEY_CHARS:
            raise _refuse(
                DEFINITION_INVALID, "operation_key",
                f"exceeds {limits.MAX_OPERATION_KEY_CHARS} characters",
            )

    def _receipt_paths(
        self,
        root: Path,
        store: DefinitionStore,
        context: ImportContext,
        mapping: Sequence[tuple[str, str]],
    ) -> tuple[str, ...]:
        """The receipt files of one apply, recomputed from their own inputs."""
        paths = [
            _relative_to(
                root, store.receipt_path(context.receipt_scope, context.operation_key),
            ),
        ]
        for _, definition_id in mapping:
            row = store.read_definition(definition_id)
            if row is None:
                continue
            scope = f"create:{context.principal}:{context.server_scope}/{row['slug']}"
            paths.append(_relative_to(
                root,
                store.receipt_path(
                    scope, _item_operation_key(context.operation_key, definition_id),
                ),
            ))
        return tuple(paths)

    def _replanned(
        self,
        manifest: MigrationManifest,
        decisions: Mapping[str, LegacyRowReport],
        *,
        approvals: Mapping[str, SourceApproval] | Sequence[SourceApproval],
        principal: str,
        expected_row_version: int,
    ) -> tuple[tuple[MigrationManifestItem, ImportableContent, SourceApproval], ...]:
        """Re-run the matrix over the source and check every approval, first.

        Nothing is written by this pass: a single mismatch raises, so a refused
        item cannot leave a half-imported library behind.
        """
        granted = _approvals_by_key(approvals)
        manifest_keys = {item.legacy_key for item in manifest.items}
        if manifest_keys != set(decisions):
            missing = sorted(manifest_keys - set(decisions))
            extra = sorted(set(decisions) - manifest_keys)
            raise _refuse(
                TARGET_CONFLICT, "manifest",
                "the manifest and its source rows disagree "
                f"(manifest-only: {missing}; source-only: {extra})",
            )
        out: list[
            tuple[MigrationManifestItem, ImportableContent, SourceApproval]
        ] = []
        for item in manifest.items:
            report = decisions[item.legacy_key]
            decision = report.primary
            if _verdict_of(decision) != _verdict_of_item(item):
                raise _refuse(
                    ASSIGNMENT_CONFLICT, item.legacy_key,
                    "the source no longer matches the manifest (the row now "
                    f"reads {decision.decision.value} at {decision.matrix_row}); "
                    "run the dry run again",
                )
            if decision.decision is not MigrationDecisionKind.MIGRATE_CANDIDATE:
                continue
            if not report.importable or decision.content is None:
                # Reachable only through a hand-built manifest: a row that
                # bundles a dispatch fact never plans a target here.
                raise _refuse(
                    TARGET_CONFLICT, item.legacy_key,
                    "an aggregate legacy row is never importable as a definition",
                )
            content = decision.content
            approval = granted.get(item.legacy_key)
            if approval is None:
                raise _refuse(
                    DEFINITION_INVALID, item.legacy_key,
                    "only a candidate carrying an explicit SourceApproval is "
                    "persisted, and nothing is approved for this row",
                )
            self._check_approval(item, content, approval, principal)
            self._check_row_version(item, expected_row_version)
            out.append((item, content, approval))
        return tuple(out)

    def _check_row_version(
        self, item: MigrationManifestItem, expected_row_version: int
    ) -> None:
        """The caller's CAS expectation is checked against the target row.

        A target id is derived from the row, so it is either absent (a fresh
        row: the expectation must be 0) or present, and a present row must be
        at exactly the version the caller read.
        """
        target = item.target_definition_id
        if target is None:
            raise _refuse(
                DEFINITION_INVALID, item.legacy_key,
                "a candidate names no target row to compare versions with",
            )
        held = self.service.store.read_definition(target)
        current = 0 if held is None else int(held["row_version"])
        if current != expected_row_version:
            raise _refuse(
                REVISION_STALE, item.legacy_key,
                f"expected row_version {expected_row_version}, the target holds "
                f"{current}",
            )

    def _check_approval(
        self,
        item: MigrationManifestItem,
        content: ImportableContent,
        approval: SourceApproval,
        principal: str,
    ) -> None:
        if not isinstance(approval, SourceApproval):
            raise _refuse(
                DEFINITION_INVALID, item.legacy_key,
                "an approval is a dto.SourceApproval, never a bare flag",
            )
        if approval.origin not in SOURCE_ORIGINS:
            raise _refuse(
                DEFINITION_INVALID, f"{item.legacy_key}.origin",
                f"origin is one of {'/'.join(SOURCE_ORIGINS)}",
            )
        if approval.approved_by_principal != principal:
            raise _refuse(
                PERMISSION_EXCEEDS_CEILING, f"{item.legacy_key}.approved_by_principal",
                "only the approving principal may import this content",
            )
        if approval.origin_ref != item.legacy_key:
            raise _refuse(
                TARGET_CONFLICT, item.legacy_key,
                "the legacy key must be what the approval records in origin_ref, "
                "or the imported mapping is not reversible",
            )
        if approval.content_digest != item.content_digest:
            raise _refuse(
                TARGET_CONFLICT, item.legacy_key,
                "the approval covers other bytes than the manifest's content digest",
            )
        if content.content_digest != item.content_digest:
            raise _refuse(
                ASSIGNMENT_CONFLICT, item.legacy_key,
                "the source body drifted after the dry run",
            )
        if item.target_definition_id is None:
            raise _refuse(
                DEFINITION_INVALID, item.legacy_key,
                "a candidate with no target definition id names no target row",
            )
        try:
            decoder.validate_revision(_revision_of(
                definition_id=item.target_definition_id,
                revision=content.revision, content=content, approval=approval,
            ))
        except DomainError as exc:
            raise _refuse(
                exc.code, item.legacy_key,
                f"the approved content is refused: {exc.detail}",
            ) from None

    def _write_one(
        self,
        item: MigrationManifestItem,
        content: ImportableContent,
        approval: SourceApproval,
        *,
        principal: str,
        server_scope: str,
        origin_scope: str,
        origin_owner: str,
        operation_key: str,
        expected_row_version: int,
    ) -> ImportedItem:
        definition_id = item.target_definition_id
        revision_number = item.target_revision
        if definition_id is None or revision_number is None:
            raise _refuse(
                DEFINITION_INVALID, item.legacy_key, "a candidate names no target",
            )
        slug = str(content.document["slug"])
        if slug in definition_id:
            raise _refuse(
                DEFINITION_INVALID, item.legacy_key,
                "this id and slug pair would read as a derived id: the row is "
                "refused rather than stored under a non-opaque id",
            )
        revision = decoder.validate_revision(_revision_of(
            definition_id=definition_id, revision=revision_number,
            content=content, approval=approval,
        ))
        self._check_ceiling(principal, server_scope, revision, item)
        self.service.create_definition(
            principal,
            server_scope=server_scope,
            slug=slug,
            display_name=content.display_name,
            description=str(content.document["description"]),
            origin_scope=origin_scope,
            origin_owner=origin_owner,
            operation_key=_item_operation_key(operation_key, definition_id),
            expected_row_version=expected_row_version,
            definition_id=definition_id,
        )
        store = self.service.store
        if store.read_revision(definition_id, revision_number) is None:
            store.write_revision(revision)
        live = store.get_definition(definition_id)
        stored_row = live
        if live.latest_revision != revision_number:
            stored_row = replace(
                live, latest_revision=revision_number, row_version=live.row_version + 1,
            )
            store.replace_definition(
                stored_row, expected_row_version=live.row_version,
            )
        return ImportedItem(
            legacy_key=item.legacy_key, definition_id=definition_id,
            revision=revision_number, content_digest=item.content_digest or "",
            row_version=stored_row.row_version,
        )

    def _check_ceiling(
        self,
        principal: str,
        server_scope: str,
        revision: DefinitionRevision,
        item: MigrationManifestItem,
    ) -> None:
        """A definition never raises the ceiling it declares (FR06)."""
        granted = set(self.service.authority.permission_ceiling(principal, server_scope))
        declared = {revision.requested_permission} - {None}
        if not declared <= granted:
            raise _refuse(
                PERMISSION_EXCEEDS_CEILING, item.legacy_key,
                "the definition requests a permission its principal does not hold",
            )


def _verdict_of(decision: MigrationDecision) -> tuple[Any, ...]:
    return (
        decision.decision, decision.matrix_row, decision.content_digest,
        decision.target_definition_id, decision.target_revision,
    )


def _verdict_of_item(item: MigrationManifestItem) -> tuple[Any, ...]:
    return (
        item.decision, item.matrix_row, item.content_digest,
        item.target_definition_id, item.target_revision,
    )


def _revision_of(
    *,
    definition_id: str,
    revision: int,
    content: ImportableContent,
    approval: SourceApproval,
) -> DefinitionRevision:
    """The revision these exact approved bytes produce, canonical digest included."""
    document = content.document
    provisional = DefinitionRevision(
        definition_id=definition_id, revision=revision, content_digest=_PLACEHOLDER,
        role_body=content.role_body,
        declared_model_ref=document.get("declared_model_ref"),
        tool_refs=tuple(document.get("tool_refs", ())),
        mcp_refs=tuple(document.get("mcp_refs", ())),
        skill_refs=tuple(document.get("skill_refs", ())),
        requested_permission=document.get("requested_permission"),
        isolation=dict(document.get("isolation", {})),
        limits=dict(document.get("limits", {})),
        source=approval,
        retained_native_fields=dict(document.get("retained_native_fields", {})),
    )
    return DefinitionRevision(
        **{
            **decoder.revision_mapping(provisional),
            "content_digest": revision_digest(provisional),
        }
    )


def _principal_id(principal: Any) -> str:
    value = principal if isinstance(principal, str) else getattr(principal, "id", None)
    if not isinstance(value, str):
        raise _refuse(
            DEFINITION_INVALID, "principal", "a principal is a namespaced id string",
        )
    return decoder.check_text(value, item="principal",
                              max_chars=limits.MAX_PRINCIPAL_CHARS)


def _unique_by_key(
    reports: Sequence[LegacyRowReport],
) -> dict[str, LegacyRowReport]:
    out: dict[str, LegacyRowReport] = {}
    for report in reports:
        if report.legacy_key in out:
            raise _refuse(
                TARGET_CONFLICT, report.legacy_key,
                "one legacy key appears twice in the source set; a manifest line "
                "must name exactly one row",
            )
        out[report.legacy_key] = report
    return out


def _approvals_by_key(
    approvals: Mapping[str, SourceApproval] | Sequence[SourceApproval],
) -> dict[str, SourceApproval]:
    if isinstance(approvals, Mapping):
        return {str(key): value for key, value in approvals.items()}
    if isinstance(approvals, (str, bytes)):
        raise _refuse(
            DEFINITION_INVALID, "approvals",
            "an approval set maps a legacy key to a SourceApproval",
        )
    by_ref: dict[str, SourceApproval] = {}
    for entry in approvals:
        approval = _as_approval(entry)
        by_ref[approval.origin_ref] = approval
    return by_ref


def _as_approval(entry: Any) -> SourceApproval:
    source = getattr(entry, "source", None)
    approval = source if isinstance(source, SourceApproval) else entry
    if not isinstance(approval, SourceApproval):
        raise _refuse(
            DEFINITION_INVALID, "approvals",
            "an approval set holds dto.SourceApproval values",
        )
    return approval


def _request_digest(
    manifest: MigrationManifest,
    approvals: Mapping[str, SourceApproval] | Sequence[SourceApproval],
    context: ImportContext,
    expected_row_version: int,
) -> str:
    """The payload identity of one apply: same digest, same recorded result.

    The caller's approval set counts as part of the payload, so a different
    approval under the same operation key is a conflict, not a second import.
    """
    if isinstance(approvals, Mapping):
        shown: Any = {
            str(key): _approval_of(value) for key, value in approvals.items()
        }
    else:
        shown = [_approval_of(entry) for entry in approvals]
    return canonical_digest({
        "manifest": [item.as_mapping() for item in manifest.items],
        "approvals": shown,
        "expected_row_version": expected_row_version,
        "principal": context.principal,
        "server_scope": context.server_scope,
    })


def _approval_of(entry: Any) -> Any:
    approval = entry if isinstance(entry, SourceApproval) else _as_approval(entry)
    return {
        "origin": approval.origin, "origin_ref": approval.origin_ref,
        "content_digest": approval.content_digest,
        "approved_by_principal": approval.approved_by_principal,
        "approved_at": approval.approved_at,
    }


def _item_operation_key(operation_key: str, definition_id: str) -> str:
    """One caller key, many item receipts: the item key names its own target, so
    a repeat of the same operation cannot answer across items."""
    return f"{operation_key}:{definition_id}"


def _relative_to(root: Path, path: Path) -> str:
    try:
        return str(Path(path).relative_to(Path(root)))
    except ValueError:
        raise _refuse(
            TARGET_CONFLICT, str(path), "a rollback path escapes the store root",
        ) from None


def _resolve_under(root: Path, relative: str) -> Path:
    candidate = Path(root) / relative
    if not DefinitionStore(root).holds_path(candidate):
        raise _refuse(TARGET_CONFLICT, relative, "a rollback path escapes the store root")
    return candidate
