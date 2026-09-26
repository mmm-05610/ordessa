"""SQLite persistence for the additive Minimal Work Core."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4
from datetime import datetime
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence

from . import db
from .errors import DispatchRejected, FinalizationConflict, InputFrozen, WorkCoreError, WorkNotOpen
from .events import (
    RESPONSIBILITY_INTENT_KEY,
    CoreEvent,
    EventType,
    normalize_responsibility_intent,
)
from .models import Execution, Ref, RefType, Work, WorkLifecycle
from .projection import ExecutionProjection, Freshness, Outcome, Phase
from .resource_observations import (
    ResourceObservation,
    ResourceObservationCoverage,
    ResourceObservationKind,
    ResourceObservationResult,
    ResourceObserverRole,
)
from .registry import DispatchReceipt, ExecutionStartReceipt, RecoverySupport
from .finalization import FinalizationReceipt


_CORRELATION_PREFIX = "ref:v1:"
_MAX_CORRELATION_LENGTH = 8192


def _serialize_correlation_ref(ref: Ref) -> str:
    payload = {
        "type": ref.type.value,
        "provider": ref.provider,
        "native_id": ref.native_id,
        "uri": ref.uri,
        "metadata": dict(ref.metadata),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    value = _CORRELATION_PREFIX + encoded
    if len(value) > _MAX_CORRELATION_LENGTH:
        raise ValueError("encoded Dispatch correlation exceeds bounded storage")
    return value


def _parse_correlation_ref(value: str | None) -> tuple[Ref | None, str | None]:
    if value is None:
        return None, None
    if not value.startswith(_CORRELATION_PREFIX):
        return None, value
    try:
        payload = json.loads(value[len(_CORRELATION_PREFIX):])
        ref = Ref(
            RefType(payload["type"]),
            payload["provider"],
            payload["native_id"],
            payload.get("uri"),
            payload.get("metadata") or {},
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None, value
    return ref, None


class WorkNotFound(WorkCoreError):
    pass


class ExecutionNotFound(WorkCoreError):
    pass


class ConcurrencyConflict(WorkCoreError):
    pass


class RefRelation(str, Enum):
    NATIVE = "native"
    INPUT = "input"
    OUTPUT = "output"


def _dump(value: Mapping[str, str]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True)


def _ref_identity_digest(ref: Ref) -> str:
    """Bounded event locator for one exact Ref association.

    Ref metadata is already persisted on core_execution_refs.  Repeating the
    whole serialized map inside a bounded CoreEvent can exceed the per-value
    limit even when every individual Ref metadata item is valid.
    """
    payload = {
        "type": ref.type.value,
        "provider": ref.provider,
        "native_id": ref.native_id,
        "uri": ref.uri,
        "metadata": dict(ref.metadata),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _load(value: str) -> dict[str, str]:
    return json.loads(value)


def _time(value: datetime) -> str:
    return value.isoformat()


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


class CoreRepository:
    """Current-state repository; callers define all native/provider semantics."""

    def create_work(self, work: Work, event: CoreEvent) -> Work:
        conn = db.get_conn()
        with db.write_lock, conn:
            conn.execute(
                "INSERT INTO core_works (id, objective, lifecycle, closure_reason, metadata_json, created_at, updated_at, version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (work.id, work.objective, work.lifecycle.value, work.closure_reason, _dump(work.metadata), _time(work.created_at), _time(work.updated_at), work.version),
            )
            self._append_event(conn, event)
        return self.get_work(work.id)

    def list_works(self) -> tuple[Work, ...]:
        rows = db.get_conn().execute("SELECT * FROM core_works ORDER BY updated_at DESC, id DESC").fetchall()
        return tuple(Work(r["id"], r["objective"], WorkLifecycle(r["lifecycle"]), _parse_time(r["created_at"]), _parse_time(r["updated_at"]), r["closure_reason"], _load(r["metadata_json"]), r["version"]) for r in rows)

    def get_work(self, work_id: str) -> Work:
        row = db.get_conn().execute("SELECT * FROM core_works WHERE id = ?", (work_id,)).fetchone()
        if row is None:
            raise WorkNotFound(work_id)
        return Work(row["id"], row["objective"], WorkLifecycle(row["lifecycle"]), _parse_time(row["created_at"]), _parse_time(row["updated_at"]), row["closure_reason"], _load(row["metadata_json"]), row["version"])

    def list_executions(self, work_id: str) -> tuple[Execution, ...]:
        """Return the current Execution projections belonging to one Work.

        This is deliberately a read-only query.  Calling ``get_work`` first
        preserves the repository's existing WorkNotFound semantics even when
        the requested Work has no executions.
        """
        self.get_work(work_id)
        rows = db.get_conn().execute(
            "SELECT * FROM core_executions WHERE work_id = ? ORDER BY created_at, id",
            (work_id,),
        ).fetchall()
        result: list[Execution] = []
        for row in rows:
            projection = ExecutionProjection(
                Phase(row["phase"]),
                Outcome(row["outcome"]) if row["outcome"] else None,
                None if row["resumable_now"] is None else bool(row["resumable_now"]),
                Freshness(row["freshness"]),
                _parse_time(row["observed_at"]),
            )
            result.append(
                Execution(
                    row["id"],
                    row["work_id"],
                    row["provider_id"],
                    projection,
                    _parse_time(row["created_at"]),
                    _parse_time(row["dispatched_at"]),
                    _parse_time(row["started_at"]),
                    _parse_time(row["ended_at"]),
                    _load(row["provenance_json"]),
                    row["version"],
                )
            )
        return tuple(result)

    def update_work(self, work: Work, *, expected_version: int, event: CoreEvent) -> Work:
        conn = db.get_conn()
        with db.write_lock, conn:
            cursor = conn.execute(
                "UPDATE core_works SET lifecycle = ?, closure_reason = ?, metadata_json = ?, updated_at = ?, version = version + 1 WHERE id = ? AND version = ?",
                (work.lifecycle.value, work.closure_reason, _dump(work.metadata), _time(work.updated_at), work.id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConcurrencyConflict(f"work version changed: {work.id}")
            self._append_event(conn, event)
        return self.get_work(work.id)

    def create_execution(self, execution: Execution, event: CoreEvent) -> Execution:
        if event.type is not EventType.EXECUTION_CREATED:
            raise ValueError("create_execution requires an ExecutionCreated event")
        if event.subject_id != execution.id:
            raise ValueError("ExecutionCreated subject must match execution id")
        if event.data.get("provider") != execution.provider_id:
            raise ValueError("ExecutionCreated provider must match execution")
        responsibility_intent = event.data.get(RESPONSIBILITY_INTENT_KEY)
        if responsibility_intent is None:
            raise ValueError("ExecutionCreated responsibility_intent is required")
        if normalize_responsibility_intent(responsibility_intent) != responsibility_intent:
            raise ValueError("ExecutionCreated responsibility_intent must be normalized")
        conn = db.get_conn()
        p = execution.projection
        with db.write_lock, conn:
            cursor = conn.execute(
                "INSERT INTO core_executions (id, work_id, provider_id, phase, outcome, resumable_now, freshness, observed_at, provenance_json, created_at, dispatched_at, started_at, ended_at, version) "
                "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ? FROM core_works WHERE id = ? AND lifecycle = ?",
                (execution.id, execution.work_id, execution.provider_id, p.phase.value, p.outcome.value if p.outcome else None, p.resumable_now, p.freshness.value, _time(p.observed_at), _dump(execution.provenance), _time(execution.created_at), _time(execution.dispatched_at) if execution.dispatched_at else None, _time(execution.started_at) if execution.started_at else None, _time(execution.ended_at) if execution.ended_at else None, execution.version, execution.work_id, WorkLifecycle.OPEN.value),
            )
            if cursor.rowcount != 1:
                row = conn.execute("SELECT lifecycle FROM core_works WHERE id = ?", (execution.work_id,)).fetchone()
                if row is None:
                    raise WorkNotFound(execution.work_id)
                raise WorkNotOpen(f"work is not open: {execution.work_id} ({row['lifecycle']})")
            self._append_event(conn, event)
        return self.get_execution(execution.id)

    def get_execution(self, execution_id: str) -> Execution:
        with db.write_lock:
            row = db.get_conn().execute("SELECT * FROM core_executions WHERE id = ?", (execution_id,)).fetchone()
        if row is None:
            raise ExecutionNotFound(execution_id)
        projection = ExecutionProjection(Phase(row["phase"]), Outcome(row["outcome"]) if row["outcome"] else None, None if row["resumable_now"] is None else bool(row["resumable_now"]), Freshness(row["freshness"]), _parse_time(row["observed_at"]))
        return Execution(row["id"], row["work_id"], row["provider_id"], projection, _parse_time(row["created_at"]), _parse_time(row["dispatched_at"]), _parse_time(row["started_at"]), _parse_time(row["ended_at"]), _load(row["provenance_json"]), row["version"])

    def get_execution_responsibility_intent(self, execution_id: str) -> str | None:
        """Return the immutable creation intent, or None for a legacy Execution."""
        self.get_execution(execution_id)
        row = db.get_conn().execute(
            "SELECT data_json FROM core_events WHERE subject_id = ? AND type = ? "
            "ORDER BY occurred_at, id LIMIT 1",
            (execution_id, EventType.EXECUTION_CREATED.value),
        ).fetchone()
        if row is None:
            return None
        return _load(row["data_json"]).get(RESPONSIBILITY_INTENT_KEY)

    def update_projection(self, execution: Execution, *, expected_version: int, event: CoreEvent) -> Execution:
        conn = db.get_conn(); p = execution.projection
        with db.write_lock, conn:
            cursor = conn.execute(
                "UPDATE core_executions SET phase = ?, outcome = ?, resumable_now = ?, freshness = ?, observed_at = ?, started_at = ?, ended_at = ?, version = version + 1 WHERE id = ? AND version = ?",
                (p.phase.value, p.outcome.value if p.outcome else None, p.resumable_now, p.freshness.value, _time(p.observed_at), _time(execution.started_at) if execution.started_at else None, _time(execution.ended_at) if execution.ended_at else None, execution.id, expected_version),
            )
            if cursor.rowcount != 1:
                raise ConcurrencyConflict(f"execution version changed: {execution.id}")
            self._append_event(conn, event)
        return self.get_execution(execution.id)

    def finalize_execution(
        self,
        execution_id: str,
        projection: ExecutionProjection,
        native_refs: Sequence[Ref],
        output_refs: Sequence[Ref],
        observations: Sequence[ResourceObservation],
        *,
        idempotency_key: str,
        bundle_digest: str,
        ended_at: datetime,
    ) -> FinalizationReceipt:
        """Commit the complete terminal bundle under one SQLite transaction."""
        conn = db.get_conn()
        with db.write_lock, conn:
            prior = conn.execute(
                "SELECT * FROM core_execution_finalizations WHERE execution_id = ?",
                (execution_id,),
            ).fetchone()
            if prior is not None:
                if prior["idempotency_key"] == idempotency_key and prior["bundle_digest"] == bundle_digest:
                    return FinalizationReceipt(execution_id, idempotency_key, bundle_digest, prior["execution_version"])
                raise FinalizationConflict(f"Execution already finalized: {execution_id}")
            key_owner = conn.execute(
                "SELECT execution_id, bundle_digest FROM core_execution_finalizations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if key_owner is not None:
                raise FinalizationConflict("finalization idempotency key conflicts with another bundle")
            row = conn.execute("SELECT * FROM core_executions WHERE id = ?", (execution_id,)).fetchone()
            if row is None:
                raise ExecutionNotFound(execution_id)
            if row["phase"] == Phase.TERMINAL.value:
                raise FinalizationConflict(f"Execution is already terminal: {execution_id}")

            for ref, relation, event_type in (
                *((ref, RefRelation.NATIVE, EventType.NATIVE_REF_DISCOVERED) for ref in native_refs),
                *((ref, RefRelation.OUTPUT, EventType.REF_ATTACHED) for ref in output_refs),
            ):
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO core_execution_refs (execution_id, relation, type, provider, native_id, uri, metadata_json, created_at, contract_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                    (execution_id, relation.value, ref.type.value, ref.provider, ref.native_id, ref.uri, _dump(ref.metadata), _time(ended_at)),
                )
                if cursor.rowcount == 1:
                    self._append_event(conn, CoreEvent(f"evt_{uuid4().hex}", event_type, execution_id, ended_at, {"type": ref.type.value}))

            # Validate frozen INPUT associations before the first observation INSERT.
            for observation in observations:
                fixed = conn.execute(
                    "SELECT 1 FROM core_execution_refs WHERE execution_id = ? AND relation = ? AND contract_id = ? AND type = ? AND provider = ? AND native_id = ? AND uri IS ? AND metadata_json = ?",
                    (execution_id, RefRelation.INPUT.value, observation.contract_id, observation.ref.type.value, observation.ref.provider, observation.ref.native_id, observation.ref.uri, _dump(observation.ref.metadata)),
                ).fetchone()
                if fixed is None:
                    raise WorkCoreError("resource observation does not address a frozen INPUT association: " + execution_id)
            for observation in observations:
                digest = self.observation_digest(execution_id, observation)
                if conn.execute("SELECT 1 FROM core_resource_observations WHERE observation_digest = ?", (digest,)).fetchone() is not None:
                    continue
                evidence = observation.evidence_ref
                conn.execute(
                    "INSERT INTO core_resource_observations (execution_id, contract_id, ref_type, ref_provider, ref_native_id, ref_uri, ref_meta_json, ref_identity_digest, kind, result, observer_role, observer_id, observed_at, coverage, evidence_type, evidence_provider, evidence_native_id, evidence_uri, evidence_meta_json, detail, observation_digest, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (execution_id, observation.contract_id, observation.ref.type.value, observation.ref.provider, observation.ref.native_id, observation.ref.uri, _dump(observation.ref.metadata), _ref_identity_digest(observation.ref), observation.kind.value, observation.result.value, observation.observer_role.value, observation.observer_id.strip(), _time(observation.observed_at), observation.coverage.value, evidence.type.value if evidence else None, evidence.provider if evidence else None, evidence.native_id if evidence else None, evidence.uri if evidence else None, _dump(evidence.metadata) if evidence else "{}", observation.detail, digest, _time(ended_at)),
                )

            next_version = row["version"] + 1
            cursor = conn.execute(
                "UPDATE core_executions SET phase = ?, outcome = ?, resumable_now = ?, freshness = ?, observed_at = ?, ended_at = ?, version = version + 1 WHERE id = ? AND version = ?",
                (projection.phase.value, projection.outcome.value if projection.outcome else None, projection.resumable_now, projection.freshness.value, _time(projection.observed_at), _time(ended_at), execution_id, row["version"]),
            )
            if cursor.rowcount != 1:
                raise ConcurrencyConflict(f"execution version changed: {execution_id}")
            self._append_event(conn, CoreEvent(f"evt_{uuid4().hex}", EventType.EXECUTION_TERMINAL, execution_id, ended_at, {"phase": projection.phase.value, "freshness": projection.freshness.value, "bundle_digest": bundle_digest}))
            self._append_event(conn, CoreEvent(f"evt_{uuid4().hex}", EventType.EXECUTION_FINALIZED, execution_id, ended_at, {"bundle_digest": bundle_digest}, idempotency_key))
            conn.execute("INSERT INTO core_execution_finalizations (execution_id, idempotency_key, bundle_digest, execution_version, created_at) VALUES (?, ?, ?, ?, ?)", (execution_id, idempotency_key, bundle_digest, next_version, _time(ended_at)))
            return FinalizationReceipt(execution_id, idempotency_key, bundle_digest, next_version)

    def attach_ref(
        self,
        execution_id: str,
        relation: RefRelation,
        ref: Ref,
        event: CoreEvent,
        contract_id: str | None = None,
    ) -> None:
        conn = db.get_conn()
        with db.write_lock, conn:
            if conn.execute(
                "SELECT 1 FROM core_executions WHERE id = ?", (execution_id,)
            ).fetchone() is None:
                raise ExecutionNotFound(execution_id)
            contract_id = contract_id or getattr(event, "data", {}).get("contract_id")
            if relation is RefRelation.INPUT:
                if not contract_id:
                    raise ValueError("input Ref requires contract_id")
                if conn.execute(
                    "SELECT 1 FROM core_dispatches WHERE execution_id = ?",
                    (execution_id,),
                ).fetchone() is not None:
                    raise InputFrozen(
                        f"Execution INPUTs are frozen after Dispatch: {execution_id}"
                    )
            cursor = conn.execute(
                "INSERT OR IGNORE INTO core_execution_refs (execution_id, relation, type, provider, native_id, uri, metadata_json, created_at, contract_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (execution_id, relation.value, ref.type.value, ref.provider, ref.native_id, ref.uri, _dump(ref.metadata), _time(event.occurred_at), contract_id if relation is RefRelation.INPUT else None),
            )
            # A ref-discovery event is a material fact only when the ref was
            # actually added. Re-observation must not manufacture telemetry.
            if cursor.rowcount == 1:
                self._append_event(conn, event)

    def list_refs(self, execution_id: str, relation: RefRelation | None = None) -> list[Ref]:
        query = "SELECT * FROM core_execution_refs WHERE execution_id = ?"; params: tuple = (execution_id,)
        if relation:
            query += " AND relation = ?"; params = (execution_id, relation.value)
        rows = db.get_conn().execute(query, params).fetchall()
        return [Ref(RefType(row["type"]), row["provider"], row["native_id"], row["uri"], _load(row["metadata_json"])) for row in rows]

    def list_input_refs(self, execution_id: str) -> tuple[tuple[str, Ref], ...]:
        """Return the immutable input association snapshot for an Execution."""
        with db.write_lock:
            self.get_execution(execution_id)
            rows = db.get_conn().execute(
                "SELECT * FROM core_execution_refs WHERE execution_id = ? AND relation = ? "
                "ORDER BY created_at, type, provider, native_id",
                (execution_id, RefRelation.INPUT.value),
            ).fetchall()
        result: list[tuple[str, Ref]] = []
        for row in rows:
            if not row["contract_id"]:
                raise WorkCoreError(
                    f"legacy input association has no contract_id: {execution_id}"
                )
            result.append(
                (
                    row["contract_id"],
                    Ref(
                        RefType(row["type"]),
                        row["provider"],
                        row["native_id"],
                        row["uri"],
                        _load(row["metadata_json"]),
                    ),
                )
            )
        return tuple(result)

    def list_events(self, subject_id: str) -> list[CoreEvent]:
        rows = db.get_conn().execute("SELECT * FROM core_events WHERE subject_id = ? ORDER BY occurred_at, id", (subject_id,)).fetchall()
        return [CoreEvent(row["id"], EventType(row["type"]), row["subject_id"], _parse_time(row["occurred_at"]), _load(row["data_json"]), row["idempotency_key"]) for row in rows]

    def create_dispatch_with_inputs(
        self,
        dispatch_id: str,
        execution_id: str,
        inputs: Iterable[tuple[str, Ref]],
        inputs_digest: str,
        idempotency_key: str,
        event: CoreEvent,
    ) -> None:
        """Atomically freeze INPUT associations and create requested Dispatch."""
        if not inputs_digest:
            raise ValueError("inputs_digest is required")
        conn = db.get_conn()
        input_values = tuple(inputs)
        with db.write_lock, conn:
            execution = conn.execute(
                "SELECT id FROM core_executions WHERE id = ?", (execution_id,)
            ).fetchone()
            if execution is None:
                raise ExecutionNotFound(execution_id)
            existing = conn.execute(
                "SELECT id FROM core_dispatches WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            if existing is not None:
                raise DispatchRejected(
                    f"Execution already has a Dispatch: {execution_id}"
                )
            for contract_id, ref in input_values:
                if not contract_id:
                    raise ValueError("input Ref requires contract_id")
                conn.execute(
                    "INSERT INTO core_execution_refs (execution_id, relation, type, provider, native_id, uri, metadata_json, created_at, contract_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (execution_id, RefRelation.INPUT.value, ref.type.value, ref.provider, ref.native_id, ref.uri, _dump(ref.metadata), _time(event.occurred_at), contract_id),
                )
            conn.execute(
                "INSERT INTO core_dispatches (id, execution_id, idempotency_key, state, inputs_digest, created_at, updated_at) "
                "VALUES (?, ?, ?, 'requested', ?, ?, ?)",
                (dispatch_id, execution_id, idempotency_key, inputs_digest, _time(event.occurred_at), _time(event.occurred_at)),
            )
            conn.execute(
                "UPDATE core_executions SET dispatched_at = ?, version = version + 1 WHERE id = ?",
                (_time(event.occurred_at), execution_id),
            )
            self._append_event(conn, event)

    def get_dispatch(self, dispatch_id: str):
        return db.get_conn().execute(
            "SELECT * FROM core_dispatches WHERE id = ?", (dispatch_id,)
        ).fetchone()

    def record_dispatch_accepted(
        self,
        dispatch_id: str,
        receipt: ExecutionStartReceipt | str | None = None,
    ):
        """Atomically persist a typed accepted receipt or a legacy locator."""
        data: dict[str, str] = {}
        correlation: str | None = None
        if isinstance(receipt, ExecutionStartReceipt):
            correlation = (
                _serialize_correlation_ref(receipt.correlation_ref)
                if receipt.correlation_ref is not None
                else None
            )
            data["recovery_support"] = receipt.recovery_support.value
            if receipt.correlation_ref is not None:
                data["correlation_identity_digest"] = _ref_identity_digest(
                    receipt.correlation_ref
                )
        elif isinstance(receipt, str):
            correlation = receipt
        elif receipt is not None:
            raise TypeError("dispatch receipt must be typed, legacy text, or None")
        return self._record_dispatch_terminal(
            dispatch_id,
            "accepted",
            EventType.EXECUTION_DISPATCH_ACCEPTED,
            provider_correlation_ref=correlation,
            extra_data=data,
        )

    def record_dispatch_failed(self, dispatch_id: str, error: str):
        if not isinstance(error, str) or not error.strip():
            raise ValueError("dispatch failure error is required")
        return self._record_dispatch_terminal(
            dispatch_id,
            "failed",
            EventType.EXECUTION_DISPATCH_FAILED,
            error=error.strip()[:256],
        )

    def record_dispatch_ambiguous(self, dispatch_id: str, error: str):
        """Record indeterminate start evidence without changing requested state."""
        if not isinstance(error, str) or not error.strip():
            raise ValueError("dispatch ambiguity error is required")
        conn = db.get_conn()
        now = datetime.now().astimezone()
        with db.write_lock, conn:
            row = conn.execute(
                "SELECT * FROM core_dispatches WHERE id = ?", (dispatch_id,)
            ).fetchone()
            if row is None:
                raise DispatchRejected(f"dispatch not found: {dispatch_id}")
            if row["state"] != "requested":
                raise DispatchRejected(
                    f"dispatch cannot become ambiguous from {row['state']}: {dispatch_id}"
                )
            data = {"dispatch_id": dispatch_id, "stage": "start", "error": error.strip()[:256]}
            self._append_event(
                conn,
                CoreEvent(
                    f"evt_{uuid4().hex}",
                    EventType.EXECUTION_DISPATCH_AMBIGUOUS,
                    row["execution_id"],
                    now,
                    data,
                ),
            )
            conn.execute(
                "UPDATE core_dispatches SET updated_at = ? WHERE id = ?",
                (_time(now), dispatch_id),
            )
            return conn.execute(
                "SELECT * FROM core_dispatches WHERE id = ?", (dispatch_id,)
            ).fetchone()

    def _record_dispatch_terminal(
        self,
        dispatch_id: str,
        state: str,
        event_type: EventType,
        *,
        provider_correlation_ref: str | None = None,
        error: str | None = None,
        extra_data: Mapping[str, str] | None = None,
    ):
        conn = db.get_conn()
        now = datetime.now().astimezone()
        with db.write_lock, conn:
            row = conn.execute(
                "SELECT * FROM core_dispatches WHERE id = ?", (dispatch_id,)
            ).fetchone()
            if row is None:
                raise DispatchRejected(f"dispatch not found: {dispatch_id}")
            if row["state"] == state:
                return row
            if row["state"] != "requested":
                raise DispatchRejected(
                    f"dispatch cannot transition from {row['state']} to {state}: {dispatch_id}"
                )
            conn.execute(
                "UPDATE core_dispatches SET state = ?, provider_correlation_ref = COALESCE(?, provider_correlation_ref), updated_at = ? WHERE id = ?",
                (state, provider_correlation_ref, _time(now), dispatch_id),
            )
            data = {"dispatch_id": dispatch_id}
            if provider_correlation_ref:
                data["provider_correlation_ref"] = provider_correlation_ref
            if error:
                data["error"] = error
            if extra_data:
                data.update(extra_data)
            self._append_event(
                conn,
                CoreEvent(
                    f"evt_{uuid4().hex}",
                    event_type,
                    row["execution_id"],
                    now,
                    data,
                ),
            )
            return conn.execute(
                "SELECT * FROM core_dispatches WHERE id = ?", (dispatch_id,)
            ).fetchone()

    def get_dispatch_receipt(self, dispatch_id: str) -> DispatchReceipt:
        row = self.get_dispatch(dispatch_id)
        if row is None:
            raise DispatchRejected(f"dispatch not found: {dispatch_id}")
        correlation, legacy = _parse_correlation_ref(row["provider_correlation_ref"])
        support: RecoverySupport | None = None
        if row["state"] == "accepted":
            for event in self.list_events(row["execution_id"]):
                if (
                    event.type is EventType.EXECUTION_DISPATCH_ACCEPTED
                    and event.data.get("dispatch_id") == dispatch_id
                ):
                    raw = event.data.get("recovery_support", RecoverySupport.NONE.value)
                    try:
                        support = RecoverySupport(raw)
                    except ValueError:
                        support = RecoverySupport.NONE
                    break
            if support is None:
                support = RecoverySupport.NONE
        return DispatchReceipt(
            row["execution_id"],
            row["id"],
            row["state"],
            row["inputs_digest"],
            support,
            correlation,
            legacy,
        )

    def record_resource_state(
        self,
        execution_id: str,
        ref: Ref,
        resource_state: str,
        evidence_ref: Ref | None = None,
        *,
        occurred_at: datetime | None = None,
    ) -> bool:
        """Persist a changed state using the existing projection event type."""
        if not isinstance(resource_state, str) or not resource_state.strip():
            raise ValueError("resource_state must be a non-empty string")
        resource_state = resource_state.strip()
        if len(resource_state) > 256:
            raise ValueError("resource_state exceeds 256 characters")
        if evidence_ref is not None and evidence_ref.type is not RefType.ARTIFACT:
            raise ValueError("resource evidence must be an ArtifactRef")
        conn = db.get_conn()
        observed_at = occurred_at or datetime.now().astimezone()
        identity = (ref.type.value, ref.provider, ref.native_id, ref.uri, _dump(ref.metadata))
        identity_digest = _ref_identity_digest(ref)
        with db.write_lock, conn:
            self.get_execution(execution_id)
            fixed = conn.execute(
                "SELECT 1 FROM core_execution_refs WHERE execution_id = ? AND relation = ? AND type = ? AND provider = ? AND native_id = ? AND uri IS ? AND metadata_json = ?",
                (execution_id, RefRelation.INPUT.value, *identity),
            ).fetchone()
            if fixed is None:
                raise ValueError(
                    f"resource observation is not a fixed INPUT Ref: {execution_id}"
                )
            latest = None
            rows = conn.execute(
                "SELECT data_json FROM core_events WHERE subject_id = ? AND type = ? ORDER BY occurred_at DESC, id DESC",
                (execution_id, EventType.EXECUTION_PROJECTION_CHANGED.value),
            ).fetchall()
            for row in rows:
                data = _load(row["data_json"])
                digest_matches = data.get("ref_identity_digest") == identity_digest
                legacy_matches = (
                    data.get("ref_type") == identity[0]
                    and data.get("ref_provider") == identity[1]
                    and data.get("ref_native_id") == identity[2]
                    and data.get("ref_uri") == identity[3]
                    and data.get("ref_metadata") == identity[4]
                )
                if data.get("observation_kind") == "resource" and (
                    digest_matches or legacy_matches
                ):
                    latest = data.get("resource_state")
                    break
            if latest == resource_state:
                return False
            data = {
                "observation_kind": "resource",
                "ref_type": identity[0],
                "ref_provider": identity[1],
                "ref_native_id": identity[2],
                "ref_identity_digest": identity_digest,
                "resource_state": resource_state,
            }
            if evidence_ref is not None:
                data.update(
                    {
                        "evidence_type": evidence_ref.type.value,
                        "evidence_provider": evidence_ref.provider,
                        "evidence_native_id": evidence_ref.native_id,
                    }
                )
                if evidence_ref.uri is not None:
                    data["evidence_uri"] = evidence_ref.uri
            self._append_event(
                conn,
                CoreEvent(
                    f"evt_{uuid4().hex}",
                    EventType.EXECUTION_PROJECTION_CHANGED,
                    execution_id,
                    observed_at,
                    data,
                ),
            )
            return True

    def get_dispatch_by_key(self, idempotency_key: str):
        return db.get_conn().execute("SELECT * FROM core_dispatches WHERE idempotency_key = ?", (idempotency_key,)).fetchone()

    def get_dispatch_for_execution(self, execution_id: str):
        return db.get_conn().execute(
            "SELECT * FROM core_dispatches WHERE execution_id = ?", (execution_id,)
        ).fetchone()

    # ── Resource observations (append-only fact ledger) ───────────────

    @staticmethod
    def observation_digest(
        execution_id: str, observation: ResourceObservation
    ) -> str:
        """Stable idempotency digest over the full observation content.

        Evidence metadata participates only when non-empty so digests for
        metadata-free evidence refs stay byte-identical to the pre-008
        algorithm (historical rows are never re-digested either way).
        """
        evidence = None
        if observation.evidence_ref is not None:
            evidence = {
                "type": observation.evidence_ref.type.value,
                "provider": observation.evidence_ref.provider,
                "native_id": observation.evidence_ref.native_id,
                "uri": observation.evidence_ref.uri,
            }
            if observation.evidence_ref.metadata:
                evidence["metadata"] = dict(observation.evidence_ref.metadata)
        payload = {
            "execution_id": execution_id,
            "contract_id": observation.contract_id,
            "ref": {
                "type": observation.ref.type.value,
                "provider": observation.ref.provider,
                "native_id": observation.ref.native_id,
                "uri": observation.ref.uri,
                "metadata": dict(observation.ref.metadata),
            },
            "kind": observation.kind.value,
            "result": observation.result.value,
            "observer_role": observation.observer_role.value,
            "observer_id": observation.observer_id.strip(),
            "observed_at": observation.observed_at.isoformat(),
            "coverage": observation.coverage.value,
            "evidence": evidence,
            "detail": observation.detail,
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    def record_resource_observations(
        self,
        execution_id: str,
        observations: Sequence[ResourceObservation],
        *,
        recorded_at: datetime | None = None,
    ) -> tuple[tuple[int, bool], ...]:
        """INSERT a batch of observation rows inside one SQLite transaction.

        The whole batch is checked against this Execution's frozen INPUT
        associations before any write; any failure — a non-frozen Ref, a
        constraint violation, anything — rolls back every row of the batch.
        A duplicate digest (including duplicates within the same batch) is
        an idempotent no-op.  Returns one ``(row_id, created)`` per input
        observation, in input order.

        The repository offers no update/delete path for this table:
        corrections are new rows and conflicting observers coexist.  Late
        observations on terminal Executions are allowed and never touch
        projection/outcome.
        """
        values = tuple(observations)
        if not values:
            return ()
        conn = db.get_conn()
        now = recorded_at or datetime.now().astimezone()
        results: list[tuple[int, bool]] = []
        with db.write_lock, conn:
            self.get_execution(execution_id)
            # Batch frozen-INPUT validation precedes every write, so a bad
            # entry rejects the whole batch before the first INSERT runs.
            for observation in values:
                fixed = conn.execute(
                    "SELECT 1 FROM core_execution_refs WHERE execution_id = ? "
                    "AND relation = ? AND contract_id = ? AND type = ? "
                    "AND provider = ? AND native_id = ? AND uri IS ? "
                    "AND metadata_json = ?",
                    (
                        execution_id,
                        RefRelation.INPUT.value,
                        observation.contract_id,
                        observation.ref.type.value,
                        observation.ref.provider,
                        observation.ref.native_id,
                        observation.ref.uri,
                        _dump(observation.ref.metadata),
                    ),
                ).fetchone()
                if fixed is None:
                    raise WorkCoreError(
                        "resource observation does not address a frozen INPUT "
                        f"association: {execution_id}"
                    )
            for observation in values:
                digest = self.observation_digest(execution_id, observation)
                existing = conn.execute(
                    "SELECT id FROM core_resource_observations "
                    "WHERE observation_digest = ?",
                    (digest,),
                ).fetchone()
                if existing is not None:
                    results.append((existing["id"], False))
                    continue
                cursor = conn.execute(
                    "INSERT INTO core_resource_observations ("
                    "execution_id, contract_id, ref_type, ref_provider, "
                    "ref_native_id, ref_uri, ref_meta_json, ref_identity_digest, "
                    "kind, result, observer_role, observer_id, observed_at, "
                    "coverage, evidence_type, evidence_provider, "
                    "evidence_native_id, evidence_uri, evidence_meta_json, "
                    "detail, observation_digest, recorded_at) VALUES ("
                    "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        execution_id,
                        observation.contract_id,
                        observation.ref.type.value,
                        observation.ref.provider,
                        observation.ref.native_id,
                        observation.ref.uri,
                        _dump(observation.ref.metadata),
                        _ref_identity_digest(observation.ref),
                        observation.kind.value,
                        observation.result.value,
                        observation.observer_role.value,
                        observation.observer_id.strip(),
                        _time(observation.observed_at),
                        observation.coverage.value,
                        observation.evidence_ref.type.value
                        if observation.evidence_ref
                        else None,
                        observation.evidence_ref.provider
                        if observation.evidence_ref
                        else None,
                        observation.evidence_ref.native_id
                        if observation.evidence_ref
                        else None,
                        observation.evidence_ref.uri
                        if observation.evidence_ref
                        else None,
                        _dump(observation.evidence_ref.metadata)
                        if observation.evidence_ref
                        else "{}",
                        observation.detail,
                        digest,
                        _time(now),
                    ),
                )
                results.append((cursor.lastrowid, True))
        return tuple(results)

    def record_resource_observation(
        self,
        execution_id: str,
        observation: ResourceObservation,
        *,
        recorded_at: datetime | None = None,
    ) -> tuple[int, bool]:
        """Thin single-observation wrapper over the atomic batch append."""
        return self.record_resource_observations(
            execution_id, (observation,), recorded_at=recorded_at
        )[0]

    def list_resource_observations(
        self, execution_id: str
    ) -> tuple[ResourceObservation, ...]:
        """Return every observation for one Execution in ledger order.

        All rows are returned; callers render conflicts side by side.  Rows
        with enum values written by a future schema are surfaced as-is by
        SQLite CHECK constraints — unknown values cannot exist here.
        """
        self.get_execution(execution_id)
        rows = db.get_conn().execute(
            "SELECT * FROM core_resource_observations WHERE execution_id = ? "
            "ORDER BY id",
            (execution_id,),
        ).fetchall()
        result: list[ResourceObservation] = []
        for row in rows:
            evidence = None
            if row["evidence_type"]:
                evidence = Ref(
                    RefType(row["evidence_type"]),
                    row["evidence_provider"],
                    row["evidence_native_id"],
                    row["evidence_uri"],
                    _load(row["evidence_meta_json"]),
                )
            result.append(
                ResourceObservation(
                    contract_id=row["contract_id"],
                    ref=Ref(
                        RefType(row["ref_type"]),
                        row["ref_provider"],
                        row["ref_native_id"],
                        row["ref_uri"],
                        _load(row["ref_meta_json"]),
                    ),
                    kind=ResourceObservationKind(row["kind"]),
                    result=ResourceObservationResult(row["result"]),
                    observer_role=ResourceObserverRole(row["observer_role"]),
                    observer_id=row["observer_id"],
                    observed_at=_parse_time(row["observed_at"]),
                    coverage=ResourceObservationCoverage(row["coverage"]),
                    evidence_ref=evidence,
                    detail=row["detail"],
                )
            )
        return tuple(result)

    def list_unobserved_inputs(self, execution_id: str):
        """Frozen INPUT associations that have no structured observation yet.

        A pure bookkeeping anti-join — Core states which inputs were never
        observed, never what that means.
        """
        frozen = self.list_input_refs(execution_id)
        observed = {
            row["ref_identity_digest"]
            for row in db.get_conn().execute(
                "SELECT DISTINCT ref_identity_digest FROM "
                "core_resource_observations WHERE execution_id = ?",
                (execution_id,),
            )
        }
        return tuple(
            (contract_id, ref)
            for contract_id, ref in frozen
            if _ref_identity_digest(ref) not in observed
        )

    @staticmethod
    def _append_event(conn, event: CoreEvent) -> None:
        conn.execute("INSERT INTO core_events (id, subject_id, type, occurred_at, data_json, idempotency_key) VALUES (?, ?, ?, ?, ?, ?)", (event.id, event.subject_id, event.type.value, _time(event.occurred_at), _dump(event.data), event.idempotency_key))
