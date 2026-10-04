"""Durable Agent-domain mapping for reliable submissions (C2/T011-09).

This module owns only the Agent-side capture and result journal. It never
creates or dispatches through an Environment. The host injects this domain
store and the protected fingerprint port; production assembly calls the
existing Environment/declared Harness seams between the explicit journal
steps. Recovery only looks up the original RequestKey.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from ordessa_environment_api import RequestKey
from ordessa_environment_api.ports import ProtectedFingerprintPort


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_submission_journal (
    environment_namespace TEXT NOT NULL,
    principal_scope TEXT NOT NULL,
    request_id TEXT NOT NULL,
    request_comparison TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    protected_fingerprint TEXT NOT NULL,
    fingerprint_descriptor TEXT NOT NULL,
    encoded_input TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('mapped', 'possibly-submitted', 'completed')),
    config_apply TEXT,
    input_acceptance TEXT,
    run_result TEXT,
    PRIMARY KEY (environment_namespace, principal_scope, request_id)
);
"""


class SubmissionJournalError(RuntimeError):
    """Base for domain-journal refusals."""


class JournalConflictError(SubmissionJournalError):
    """A logical request key was reused with different captured content."""


class ReliableSubmissionUnsupported(SubmissionJournalError):
    """Required durable, fingerprint, immutable-content, or submit capability is absent."""


class JournalEntryMissingError(SubmissionJournalError):
    """A result or state transition has no durable capture mapping."""


class JournalTransitionError(SubmissionJournalError):
    """A journal transition would skip or reverse the C2 handshake."""


class TransactionProvider(Protocol):
    """The host's existing durable domain store; no module-global DB is used."""

    def transaction(self) -> sqlite3.Connection: ...


@dataclass(frozen=True)
class ReliableCapabilities:
    """Host declarations required before this module accepts a reliable capture.

    The fingerprint itself is never a boolean declaration: a real protected
    port must be injected into ``SubmissionJournal`` and computes the MAC.
    """

    backend_durable: bool
    conditional_submit: bool
    immutable_attachments: bool

    def missing(self) -> tuple[str, ...]:
        return tuple(
            name for name in (
                "backend_durable",
                "conditional_submit",
                "immutable_attachments",
            )
            if getattr(self, name) is not True
        )


def _json_value(value: Any, *, where: str) -> Any:
    """Copy a JSON-safe input tree; reject handles/paths instead of reopening them."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{where} keys must be strings")
            copied[key] = _json_value(child, where=f"{where}.{key}")
        return copied
    if isinstance(value, (tuple, list)):
        return [_json_value(child, where=where) for child in value]
    raise ValueError(f"{where} must be immutable JSON data; got {type(value).__name__}")


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(child) for child in value)
    return value


def _row_value(encoded: str | None) -> Mapping[str, Any] | None:
    if encoded is None:
        return None
    return _freeze(json.loads(encoded))


@dataclass(frozen=True)
class SubmissionRecord:
    request: RequestKey
    digest: str
    protected_fingerprint: str
    fingerprint_descriptor: Mapping[str, str]
    encoded_input: str
    stage: str
    config_apply: Mapping[str, Any] | None
    input_acceptance: Mapping[str, Any] | None
    run_result: Mapping[str, Any] | None

    @property
    def attachments(self) -> Mapping[str, bytes]:
        payload = json.loads(self.encoded_input)
        encoded = payload["attachments"]
        return MappingProxyType({
            name: base64.b64decode(item["base64"], validate=True)
            for name, item in encoded.items()
        })


@dataclass(frozen=True)
class RecoveryObservation:
    """The existing mapping and same-key backend lookup; never an effect result."""

    submission: SubmissionRecord
    backend_fact: Any


class SubmissionJournal:
    """Agent-only mapping over an injected durable store.

    ``store`` must be the host-created Agent domain store. Environment intent
    belongs to a different StorePort/data file; this class does not reserve an
    Environment request key or combine the two stores in one transaction.
    """

    def __init__(
        self,
        store: TransactionProvider,
        *,
        fingerprint_port: ProtectedFingerprintPort | None = None,
    ) -> None:
        if not callable(getattr(store, "transaction", None)):
            raise ReliableSubmissionUnsupported("reliable mapping requires an injected durable transaction store")
        self._store = store
        self._fingerprint_port = fingerprint_port
        try:
            with self._store.transaction() as connection:
                connection.executescript(_SCHEMA)
        except Exception as exc:
            raise ReliableSubmissionUnsupported("reliable mapping store is unavailable") from exc

    @staticmethod
    def _identity(request: RequestKey) -> tuple[str, str, str]:
        return (request.environment_namespace, request.principal_scope, request.request_id)

    def _read_row(self, request: RequestKey) -> sqlite3.Row | None:
        connection = self._store.transaction()
        connection.row_factory = sqlite3.Row
        return connection.execute(
            "SELECT * FROM agent_submission_journal "
            "WHERE environment_namespace=? AND principal_scope=? AND request_id=?",
            self._identity(request),
        ).fetchone()

    @staticmethod
    def _record(row: sqlite3.Row | None) -> SubmissionRecord | None:
        if row is None:
            return None
        comparison = json.loads(row["request_comparison"])
        key = RequestKey(
            row["environment_namespace"], row["principal_scope"], row["request_id"],
            MappingProxyType(comparison),
        )
        descriptor = _freeze(json.loads(row["fingerprint_descriptor"]))
        return SubmissionRecord(
            request=key,
            digest=row["content_digest"],
            protected_fingerprint=row["protected_fingerprint"],
            fingerprint_descriptor=descriptor,
            encoded_input=row["encoded_input"],
            stage=row["stage"],
            config_apply=_row_value(row["config_apply"]),
            input_acceptance=_row_value(row["input_acceptance"]),
            run_result=_row_value(row["run_result"]),
        )

    def capture(
        self,
        request: RequestKey,
        input_snapshot: Mapping[str, Any],
        *,
        attachments: Mapping[str, bytes | bytearray | memoryview],
        capabilities: ReliableCapabilities,
    ) -> SubmissionRecord:
        """Persist one immutable reliable input mapping before any submission.

        Attachment bytes are copied before hashing. Paths, open handles, and
        mutable payload objects are refused; callers must supply content bytes.
        Same-key identical capture replays the old mapping; changed content is
        a conflict and never mints a new request identity.
        """
        if not isinstance(input_snapshot, Mapping):
            raise ValueError("input_snapshot must be a mapping")
        copied_snapshot = _json_value(input_snapshot, where="input_snapshot")
        if copied_snapshot.get("guarantee") != "reliable":
            raise ReliableSubmissionUnsupported("SubmissionJournal accepts only explicitly reliable captures")
        copied_attachments: dict[str, dict[str, str]] = {}
        for name, content in attachments.items():
            if not isinstance(name, str) or not name:
                raise ValueError("attachment names must be non-empty strings")
            if not isinstance(content, (bytes, bytearray, memoryview)):
                raise ReliableSubmissionUnsupported(
                    f"attachment {name!r} has no immutable content bytes; path/handle fallback is refused"
                )
            copied_attachments[name] = {
                "encoding": "base64",
                "base64": base64.b64encode(bytes(content)).decode("ascii"),
            }

        request_value = {
            "environmentNamespace": request.environment_namespace,
            "principalScope": request.principal_scope,
            "requestId": request.request_id,
            "comparison": _json_value(request.comparison, where="request.comparison"),
        }
        encoded_input = _canonical({
            "request": request_value,
            "capture": copied_snapshot,
            "attachments": copied_attachments,
        })
        content_digest = hashlib.sha256(encoded_input.encode("utf-8")).hexdigest()

        # Existing identical mappings remain queryable after key rotation or
        # key-port loss; they cannot authorize another dispatch.
        existing = self._record(self._read_row(request))
        if existing is not None:
            if existing.digest != content_digest or existing.encoded_input != encoded_input:
                raise JournalConflictError(
                    "logical RequestKey is already mapped to different immutable input"
                )
            return existing

        missing = capabilities.missing()
        if missing:
            raise ReliableSubmissionUnsupported(
                "reliable submission capabilities unavailable: " + ", ".join(missing)
            )
        if self._fingerprint_port is None:
            raise ReliableSubmissionUnsupported(
                "reliable submission requires a protected fingerprint port; no plaintext digest fallback"
            )

        binding_value = copied_snapshot.get("binding")
        if not isinstance(binding_value, Mapping):
            raise ReliableSubmissionUnsupported("reliable capture requires the frozen binding identity")
        binding_digest = hashlib.sha256(_canonical(binding_value).encode("utf-8")).hexdigest()
        descriptor = self._fingerprint_port.describe()
        fingerprint = self._fingerprint_port.fingerprint(request, binding_digest, content_digest)
        descriptor_json = _canonical({
            "algorithm": descriptor.algorithm,
            "keyId": descriptor.key_id,
            "comparisonScope": descriptor.comparison_scope,
        })
        comparison_json = _canonical(request_value["comparison"])

        try:
            with self._store.transaction() as connection:
                connection.execute(
                    "INSERT INTO agent_submission_journal "
                    "(environment_namespace, principal_scope, request_id, request_comparison, "
                    "content_digest, protected_fingerprint, fingerprint_descriptor, encoded_input, stage) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'mapped')",
                    (*self._identity(request), comparison_json, content_digest, fingerprint,
                     descriptor_json, encoded_input),
                )
        except sqlite3.IntegrityError:
            # Another domain writer cannot be assumed impossible merely
            # because callers usually serialize through AgentDomainPlugin.
            concurrent = self._record(self._read_row(request))
            if concurrent is None:
                raise
            if concurrent.digest != content_digest or concurrent.encoded_input != encoded_input:
                raise JournalConflictError("concurrent capture mapped this RequestKey to different content")
            return concurrent
        record = self.read(request)
        if record is None:
            raise SubmissionJournalError("capture committed but its mapping could not be read back")
        return record

    def mark_possibly_submitted(self, request: RequestKey, digest: str) -> SubmissionRecord:
        """Persist the recovery fence; callers may submit only after this returns."""
        with self._store.transaction() as connection:
            row = connection.execute(
                "SELECT content_digest, stage FROM agent_submission_journal "
                "WHERE environment_namespace=? AND principal_scope=? AND request_id=?",
                self._identity(request),
            ).fetchone()
            if row is None:
                raise JournalEntryMissingError("cannot mark a request before its capture mapping is durable")
            if row[0] != digest:
                raise JournalConflictError("possiblySubmitted digest differs from the durable capture")
            if row[1] == "mapped":
                connection.execute(
                    "UPDATE agent_submission_journal SET stage='possibly-submitted' "
                    "WHERE environment_namespace=? AND principal_scope=? AND request_id=? AND stage='mapped'",
                    self._identity(request),
                )
            elif row[1] not in ("possibly-submitted", "completed"):
                raise JournalTransitionError(f"invalid submission stage {row[1]!r}")
        record = self.read(request)
        if record is None:
            raise JournalEntryMissingError("request mapping disappeared after possiblySubmitted")
        return record

    def _record_fact(self, request: RequestKey, column: str, fact: Mapping[str, Any]) -> SubmissionRecord:
        if column not in ("config_apply", "input_acceptance", "run_result"):
            raise ValueError("invalid journal fact column")
        value = _canonical(_json_value(fact, where=column))
        with self._store.transaction() as connection:
            row = connection.execute(
                f"SELECT stage, {column} FROM agent_submission_journal "
                "WHERE environment_namespace=? AND principal_scope=? AND request_id=?",
                self._identity(request),
            ).fetchone()
            if row is None:
                raise JournalEntryMissingError("cannot record a result without a durable submission mapping")
            if row[0] not in ("possibly-submitted", "completed"):
                raise JournalTransitionError("result facts require possiblySubmitted to be durable first")
            if row[1] is None:
                connection.execute(
                    f"UPDATE agent_submission_journal SET {column}=? "
                    "WHERE environment_namespace=? AND principal_scope=? AND request_id=?",
                    (value, *self._identity(request)),
                )
            elif row[1] != value:
                raise JournalConflictError(f"{column} is already recorded with different evidence")
        record = self.read(request)
        if record is None:
            raise JournalEntryMissingError("request mapping disappeared while recording a result")
        return record

    def record_config_apply(self, request: RequestKey, fact: Mapping[str, Any]) -> SubmissionRecord:
        return self._record_fact(request, "config_apply", fact)

    def record_input_acceptance(self, request: RequestKey, fact: Mapping[str, Any]) -> SubmissionRecord:
        return self._record_fact(request, "input_acceptance", fact)

    def record_run_result(self, request: RequestKey, fact: Mapping[str, Any]) -> SubmissionRecord:
        return self._record_fact(request, "run_result", fact)

    def record_completed(self, request: RequestKey) -> SubmissionRecord:
        with self._store.transaction() as connection:
            row = connection.execute(
                "SELECT stage, config_apply, input_acceptance, run_result FROM agent_submission_journal "
                "WHERE environment_namespace=? AND principal_scope=? AND request_id=?",
                self._identity(request),
            ).fetchone()
            if row is None:
                raise JournalEntryMissingError("cannot complete an unknown submission mapping")
            if row[0] == "completed":
                return self.read(request)  # type: ignore[return-value]
            if row[0] != "possibly-submitted":
                raise JournalTransitionError("completion requires possiblySubmitted")
            if any(row[index] is None for index in (1, 2, 3)):
                raise JournalTransitionError("completion requires separate config, input, and run facts")
            connection.execute(
                "UPDATE agent_submission_journal SET stage='completed' "
                "WHERE environment_namespace=? AND principal_scope=? AND request_id=?",
                self._identity(request),
            )
        record = self.read(request)
        if record is None:
            raise JournalEntryMissingError("request mapping disappeared while completing")
        return record

    def read(self, request: RequestKey) -> SubmissionRecord | None:
        return self._record(self._read_row(request))

    def reconcile(
        self,
        request: RequestKey,
        backend_lookup: Callable[[RequestKey], Any],
    ) -> RecoveryObservation | None:
        """Read the old mapping and query only its original key; never dispatch.

        When no mapping exists, the journal will not invent one or issue a
        backend lookup as an automatic repair. The caller supplies the existing
        Environment's authorized read/query seam, not its invoke method.
        """
        record = self.read(request)
        if record is None:
            return None
        return RecoveryObservation(record, backend_lookup(record.request))
