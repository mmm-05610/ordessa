"""A1 Agent-domain owners (spec 026/010 T010-01).

Five owners are internal modules of ONE Agent domain — not five cores, not
five schedulers. Each owns exactly one fact class and holds the ONLY write
face for it: consumers see frozen snapshots and dispatch operations, never a
generic setter. One canonical AgentTarget maps to one owner; a second
registration for the same target is a conflict (the single-writer rule).

The memory dictionaries here are the domain state store with a StorePort
injection seam reserved (005 provides the durable implementation later).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

_TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class AgentOwnerError(Exception):
    code = "AGENT_OWNER_ERROR"


class AuthorityConflictError(AgentOwnerError):
    """A second writer for one canonical target — refused at the boundary."""

    code = "AUTHORITY_CONFLICT"


class UnknownOutcome(AgentOwnerError):
    """The submission outcome is unknown: query, never re-dispatch."""

    code = "UNKNOWN_OUTCOME"


@dataclass(frozen=True)
class ConfigSnapshot:
    owner_ref: str
    revision: int
    observed_evidence: str  # native | unset | unknown
    fields: Mapping[str, str]  # field -> known | unset | unknown
    resolved: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OperationSummary:
    operation_id: str
    patch_kinds: tuple[str, ...]
    source_ref: str
    submitted_at_order: int
    state: str  # pending | applied | unknown | conflict


@dataclass(frozen=True)
class SubmissionReceipt:
    submission_id: str
    consumed_draft_revision: int
    outcome: str  # accepted | known-rejected | unknown
    query_request_key: str | None = None


class ConfigOwner:
    """The ONLY writer of a target's configuration chain."""

    def __init__(self, target: str) -> None:
        if not _TARGET.match(target):
            raise AgentOwnerError(f"malformed target {target!r}")
        self._target = target
        self._revision = 0
        self._fields: dict[str, str] = {}
        self._resolved: dict[str, Any] = {}
        self._operations: list[OperationSummary] = []
        self._op_seq = 0
        self._observed = "unset"

    @property
    def target(self) -> str:
        return self._target

    def snapshot(self) -> ConfigSnapshot:
        return ConfigSnapshot(
            owner_ref=f"agent-config:{self._target}",
            revision=self._revision,
            observed_evidence=self._observed,
            # deep immutability: nested maps are read-only views, not shallow
            # freezes pretending to be safe
            fields=MappingProxyType(dict(self._fields)),
            resolved=MappingProxyType(dict(self._resolved)),
        )

    def submit_operation(
        self, patch: Mapping[str, Any], source_ref: str, *, unset: tuple[str, ...] = (),
    ) -> OperationSummary:
        """One operation = one operationId. A same-Profile re-select is a NEW
        operation (never a no-op reuse of an old id)."""
        self._op_seq += 1
        kinds: list[str] = []
        for name, value in patch.items():
            self._fields[name] = "known"
            self._resolved[name] = value
            kinds.append("present")
        for name in unset:
            self._fields[name] = "unset"
            self._resolved.pop(name, None)
            kinds.append("unset")
        summary = OperationSummary(
            operation_id=f"op-{self._target}-{self._op_seq}",
            patch_kinds=tuple(kinds),
            source_ref=source_ref,
            submitted_at_order=self._op_seq,
            state="pending",
        )
        self._operations.append(summary)
        self._revision += 1
        return summary

    def report_evidence(self, observed: str, fields: Mapping[str, str] | None = None) -> None:
        """Trusted Harness evidence: known/unset/unknown per field. A repeated
        identical observation never unlocks a pending unknown (that needs a
        NEW complete snapshot)."""
        if observed not in ("native", "unset", "unknown"):
            raise AgentOwnerError(f"bad observed evidence {observed!r}")
        self._observed = observed
        if fields is not None:
            for name, state in fields.items():
                if state not in ("known", "unset", "unknown"):
                    raise AgentOwnerError(f"bad field state {state!r}")
                self._fields[name] = state

    def list_operations(self) -> tuple[OperationSummary, ...]:
        return tuple(self._operations)


class SubmissionOwner:
    """The ONLY writer of submission outcomes for one target."""

    def __init__(self, target: str) -> None:
        self._target = target
        self._receipts: dict[str, SubmissionReceipt] = {}
        self._seq = 0
        self._dispatch_count: dict[str, int] = {}

    def submit(self, draft_revision: int, capture: Mapping[str, Any]) -> SubmissionReceipt:
        """Unknown outcomes keep their request association and are NEVER
        automatically re-dispatched — the caller queries by the same key."""
        self._seq += 1
        submission_id = f"sub-{self._target}-{self._seq}"
        key = f"req-{submission_id}"
        self._dispatch_count[key] = self._dispatch_count.get(key, 0) + 1
        outcome = str(capture.get("outcome", "accepted"))
        if outcome == "unknown":
            receipt = SubmissionReceipt(
                submission_id=submission_id,
                consumed_draft_revision=draft_revision,
                outcome="unknown",
                query_request_key=key,
            )
        elif outcome == "known-rejected":
            receipt = SubmissionReceipt(
                submission_id=submission_id,
                consumed_draft_revision=draft_revision,
                outcome="known-rejected",
            )
        else:
            receipt = SubmissionReceipt(
                submission_id=submission_id,
                consumed_draft_revision=draft_revision,
                outcome="accepted",
            )
        self._receipts[submission_id] = receipt
        return receipt

    def query(self, submission_id: str) -> SubmissionReceipt | None:
        return self._receipts.get(submission_id)

    def dispatch_count(self, submission_id: str) -> int:
        return self._dispatch_count.get(f"req-{submission_id}", 0)


class SessionOwner:
    """The ONLY writer of the logical session list for one target."""

    def __init__(self, target: str) -> None:
        self._target = target
        self._sessions: dict[str, Mapping[str, Any]] = {}

    def upsert(self, session_id: str, fields: Mapping[str, Any]) -> Mapping[str, Any]:
        record = dict(self._sessions.get(session_id, {}))
        record.update(fields)
        frozen = dict(record)
        self._sessions[session_id] = frozen
        return frozen

    def list(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(dict(v) for v in self._sessions.values())


class RunOwner:
    """The ONLY writer of run states for one target (evidence projection)."""

    def __init__(self, target: str) -> None:
        self._target = target
        self._runs: dict[str, dict[str, Any]] = {}

    def report(self, run_id: str, state: str, *, reason: str | None = None) -> None:
        if state not in ("running", "completed", "cancelled", "failed", "unknown"):
            raise AgentOwnerError(f"bad run state {state!r}")
        self._runs[run_id] = {"state": state, "reason": reason}

    def query(self, run_id: str) -> Mapping[str, Any] | None:
        run = self._runs.get(run_id)
        return dict(run) if run is not None else None


class InteractionOwner:
    """The ONLY writer of interaction records for one target."""

    def __init__(self, target: str) -> None:
        self._target = target
        self._interactions: dict[str, dict[str, Any]] = {}

    def record(self, interaction_id: str, fields: Mapping[str, Any]) -> None:
        self._interactions[interaction_id] = dict(fields)

    def list(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(dict(v) for v in self._interactions.values())


class AgentOwnerRegistry:
    """One canonical target maps to ONE set of owners — second writer refused."""

    def __init__(self) -> None:
        self._targets: dict[str, dict[str, Any]] = {}

    def register(self, target: str) -> Mapping[str, Any]:
        if target in self._targets:
            raise AuthorityConflictError(
                f"target {target!r} already has its owners — one writer per canonical target")
        owners = {
            "config": ConfigOwner(target),
            "session": SessionOwner(target),
            "submission": SubmissionOwner(target),
            "run": RunOwner(target),
            "interaction": InteractionOwner(target),
        }
        self._targets[target] = owners
        return owners

    def owners_of(self, target: str) -> Mapping[str, Any] | None:
        return self._targets.get(target)
