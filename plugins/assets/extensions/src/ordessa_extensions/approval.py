"""EXT-3 — the mandatory approval chain over executable content.

机制 D red line (tasks EXT-2/EXT-3): an executable hook sits in one of
exactly three diagnosable states — `unapproved` (never loaded),
`approved` (loaded, and only while fingerprint AND pin still match),
`revoked` (record kept, never loaded again). No default-allow state, no
silent expiry. Scope of the claim, stated exactly (review round 7): the
ledger keeps the CURRENT record per hook — the three moves
(approve/revoke/revive) are the only in-memory transitions, but a full
transition HISTORY is not kept; `records()` is a state snapshot, not an
audit log. Approval state is diagnosable (`records()`) and revocable
(`revoke()`) as the task demands.

The ledger is in-memory with a snapshot/restore port; persistence
composition is the host's job (this package never touches a path).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from .definitions import HookDefinition, definition_fingerprint
from .security import findings_digest, has_high, scan_definition


class ApprovalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


#: The three total states (no fourth "assume ok" state exists).
UNAPPROVED = "unapproved"
APPROVED = "approved"
REVOKED = "revoked"


@dataclass(frozen=True)
class ApprovalRecord:
    hook_id: str
    fingerprint: str
    pin: str
    approved_by: str
    scope: str
    #: digest of the security findings visible at approval time (EXT-3:
    #: the approver signed off on exactly this surface).
    findings_digest: str
    state: str = APPROVED

    def as_json(self) -> dict[str, Any]:
        return {
            "hookId": self.hook_id, "fingerprint": self.fingerprint,
            "pin": self.pin, "approvedBy": self.approved_by,
            "scope": self.scope, "findingsDigest": self.findings_digest,
            "state": self.state,
        }


def _state_of(record: ApprovalRecord | None) -> str:
    return UNAPPROVED if record is None else record.state


class ApprovalLedger:
    """The one approval state machine for this domain's hook definitions."""

    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}

    def approve(self, definition: HookDefinition, *, approved_by: str,
                scope: str) -> ApprovalRecord:
        """Approve one definition's exact content (fingerprint + pin).

        The ledger NEVER blesses a HIGH-severity injection surface through
        the in-memory transitions (`approve`/`revoke`/`revive` are the
        only doors that mint records here; `restore` is host-storage
        reconstruction, shape-validated per its own contract, and the
        loader's scan gate refuses HIGH content regardless of how a
        record arrived). Re-approval of changed content is a NORMAL flow
        (the new fingerprint replaces the old record); approval of a
        REVOKED hook is refused — revival is an explicit operator
        decision through `revive()`, never a side effect of approving
        new content.
        """
        approver, scope_ok = self._gate_inputs(approved_by, scope)
        existing = self._records.get(definition.hook_id)
        if existing is not None and existing.state == REVOKED:
            raise ApprovalError("HOOK_REVOKED",
                                f"{definition.hook_id} is revoked; revive it"
                                " explicitly before new approval")
        record = self._record_for(definition, approver, scope_ok)
        self._records[definition.hook_id] = record
        return record

    def revoke(self, hook_id: str) -> ApprovalRecord:
        """Revoke one hook; idempotent for already-revoked hooks."""
        record = self._records.get(hook_id)
        if record is None:
            raise ApprovalError("HOOK_UNKNOWN",
                                f"{hook_id!r} was never approved here")
        if record.state == REVOKED:
            return record
        revoked = replace(record, state=REVOKED)
        self._records[hook_id] = revoked
        return revoked

    def revive(self, hook_id: str, definition: HookDefinition, *,
               approved_by: str, scope: str) -> ApprovalRecord:
        """The explicit un-revoke path — SAME red line as `approve()`:
        the inputs are re-gated (approver/scope/HIGH surface), so a shell
        one-liner cannot sneak back through the second door."""
        approver, scope_ok = self._gate_inputs(approved_by, scope)
        record = self._records.get(hook_id)
        if record is None or record.state != REVOKED:
            raise ApprovalError("REVIVE_MISPLACED",
                                f"{hook_id!r} is not revoked")
        if definition.hook_id != hook_id:
            raise ApprovalError("HOOK_ID_MISMATCH",
                                "definition does not name the revoked hook")
        revived = self._record_for(definition, approver, scope_ok)
        self._records[hook_id] = revived
        return revived

    @staticmethod
    def _gate_inputs(approved_by: str, scope: str) -> tuple[str, str]:
        if not approved_by or not isinstance(approved_by, str):
            raise ApprovalError("APPROVER_REQUIRED",
                                "approved_by must name the approver")
        if scope not in ("session", "user", "profile"):
            raise ApprovalError("SCOPE_INVALID",
                                "scope must be session|user|profile")
        return approved_by, scope

    @staticmethod
    def _record_for(definition: HookDefinition, approved_by: str,
                    scope: str) -> ApprovalRecord:
        findings = scan_definition(definition)
        if has_high(findings):
            worst = next(f for f in findings if f.severity == "high")
            raise ApprovalError(
                "SHELL_INJECTION_SURFACE",
                f"{worst.rule}: {worst.detail} — no approval can bless"
                " this; rewrite as a clean argv")
        return ApprovalRecord(
            hook_id=definition.hook_id,
            fingerprint=definition_fingerprint(definition),
            pin=definition.pin, approved_by=approved_by, scope=scope,
            findings_digest=findings_digest(findings))

    def state(self, hook_id: str) -> str:
        return _state_of(self._records.get(hook_id))

    def matches(self, definition: HookDefinition) -> bool:
        """True ONLY while an approved record still matches this exact
        content (fingerprint), version (pin) AND the very surface the
        approver signed (findings digest — a checklist tightening since
        approval forces re-approval instead of grandfathering, round 17)."""
        record = self._records.get(definition.hook_id)
        if record is None or record.state != APPROVED:
            return False
        if (record.fingerprint != definition_fingerprint(definition)
                or record.pin != definition.pin):
            return False
        from .security import findings_digest, scan_definition
        return (record.findings_digest
                == findings_digest(scan_definition(definition)))

    def records(self) -> tuple[ApprovalRecord, ...]:
        """Diagnostics view: every record with its state (EXT-3)."""
        return tuple(self._records.values())

    def snapshot(self) -> list[dict[str, Any]]:
        return [record.as_json() for record in self._records.values()]

    def restore(self, rows: list[dict[str, Any]]) -> None:
        """Restore from `snapshot()` output (host-owned persistence).

        Trust boundary, stated EXACTLY as the mechanism gives it (review
        round 6): the "total state machine / every transition recorded"
        claim holds for the in-memory API only — approve()/revoke()/
        revive() are the sole transition authorities THERE. `restore`
        is host-storage reconstruction: it shape-validates every row
        (state/scope enums, X.Y.Z pin, hex digests, bounded ids) so
        malformed snapshots refuse, but it CANNOT and does not re-run
        the transition gates — a shape-valid snapshot authored by the
        storage layer re-instates whatever states that layer recorded.
        Content-level truth stays gated by `matches()` (exact
        fingerprint+pin) regardless of how a record arrived.
        """
        if not isinstance(rows, list):
            raise ApprovalError("SNAPSHOT_INVALID",
                                "snapshot must be a list of records")
        rebuilt: dict[str, ApprovalRecord] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ApprovalError("SNAPSHOT_INVALID",
                                    "every row must be an object")
            state = row.get("state")
            # unapproved is the DEFAULT absence — a snapshot never needs
            # to carry it, and restoring one would make revoke() succeed
            # for a hook that never transited here (round-11 asymmetry)
            if state not in (APPROVED, REVOKED):
                raise ApprovalError("SNAPSHOT_INVALID",
                                    f"unrestorable record state {state!r}")
            if row.get("scope") not in ("session", "user", "profile"):
                raise ApprovalError("SNAPSHOT_INVALID",
                                    "unknown record scope")
            import re
            for field in ("fingerprint", "findingsDigest"):
                value = row.get(field)
                if (not isinstance(value, str)
                        or not re.fullmatch(r"sha256:[0-9a-f]{64}", value)):
                    raise ApprovalError("SNAPSHOT_INVALID",
                                        f"malformed {field}")
            if (not isinstance(row.get("pin"), str)
                    or not re.fullmatch(r"\d+\.\d+\.\d+", row["pin"])
                    or len(row["pin"]) > 32):
                raise ApprovalError("SNAPSHOT_INVALID",
                                    "malformed pin (need X.Y.Z)")
            approved_by = row.get("approvedBy")
            if (not isinstance(approved_by, str) or not approved_by
                    or len(approved_by) > 128):
                raise ApprovalError("SNAPSHOT_INVALID",
                                    "malformed approvedBy")
            hook_id = row.get("hookId")
            if not isinstance(hook_id, str) or not hook_id or len(
                    hook_id) > 64:
                raise ApprovalError("SNAPSHOT_INVALID", "malformed hookId")
            record = ApprovalRecord(
                hook_id=hook_id, fingerprint=row["fingerprint"],
                pin=row["pin"], approved_by=approved_by,
                scope=row["scope"], findings_digest=row["findingsDigest"],
                state=state)
            rebuilt[record.hook_id] = record
        self._records = rebuilt


__all__ = ["APPROVED", "ApprovalError", "ApprovalLedger", "ApprovalRecord",
           "REVOKED", "UNAPPROVED"]
