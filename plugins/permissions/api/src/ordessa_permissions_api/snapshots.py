"""A snapshot binds one decision to one runtime identity.

The binding fields are the whole point: a decision produced for one
server instance, session, native channel and runtime generation says nothing
about any other, and a snapshot missing one of them is refused instead of
defaulting. The digest is recomputed on the way in, so a record cannot keep an
old digest after one field was swapped.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Final, Mapping

from .codes import PolicyRefusal

__all__ = ["EffectivePolicySnapshot", "MAX_SNAPSHOT_TTL"]

_RECORD_FIELDS: Final[Mapping[str, str]] = {
    "server_instance_id": "serverInstanceId",
    "session_id": "sessionId",
    "native_session_id": "nativeSessionId",
    "runtime_generation": "runtimeGeneration",
    "principal": "principal",
    "ceiling_revision": "ceilingRevision",
    "intent_revision": "intentRevision",
    "issued_at": "issuedAt",
    "expires_at": "expiresAt",
}
_TEXT_OK = re.compile(r"[^\x00-\x1f\x7f]{1,256}\Z")
MAX_SNAPSHOT_TTL = dt.timedelta(minutes=5)
_MISSING = object()


@dataclass(frozen=True)
class EffectivePolicySnapshot:
    """The policy world one decision was made in, and how long it stands."""

    server_instance_id: str
    session_id: str
    native_session_id: str
    runtime_generation: str
    principal: str
    ceiling_revision: str
    intent_revision: str
    issued_at: dt.datetime
    expires_at: dt.datetime
    digest: str

    @classmethod
    def issue(cls, *, server_instance_id: Any, session_id: Any, native_session_id: Any,
              runtime_generation: Any, principal: Any, ceiling_revision: Any,
              intent_revision: Any, issued_at: Any, expires_at: Any) -> "EffectivePolicySnapshot":
        fields = {
            "server_instance_id": server_instance_id, "session_id": session_id,
            "native_session_id": native_session_id, "runtime_generation": runtime_generation,
            "principal": principal, "ceiling_revision": ceiling_revision,
            "intent_revision": intent_revision, "issued_at": issued_at,
            "expires_at": expires_at,
        }
        checked = {name: _field(value, name=name) for name, value in fields.items()}
        start, end = checked["issued_at"], checked["expires_at"]
        if not isinstance(start, dt.datetime) or not isinstance(end, dt.datetime):
            raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source="snapshots.issue",
                                target="issuedAt/expiresAt must be aware datetimes")
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source="snapshots.issue",
                                target="expiresAt must be after an aware issuedAt")
        if end - start > MAX_SNAPSHOT_TTL:
            raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source="snapshots.issue",
                                target=f"validity is bounded to {MAX_SNAPSHOT_TTL}")
        digest = _digest(checked)
        return cls(**checked, digest=digest)

    @classmethod
    def from_record(cls, raw: Any) -> "EffectivePolicySnapshot":
        source = "snapshots.EffectivePolicySnapshot.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        wire_to_field = {wire: field for field, wire in _RECORD_FIELDS.items()}
        extra = set(raw) - set(wire_to_field) - {"digest"}
        if extra:
            raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source=source,
                               target="unknown snapshot fields: " + ",".join(sorted(extra)))
        for field in ("digest", *_RECORD_FIELDS.values()):
            if raw.get(field) is None:
                raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source=source,
                                   target=f"missing {field}")
        fields = {name: _field(raw[wire], name=wire) for name, wire in _RECORD_FIELDS.items()}
        snapshot = cls(**fields, digest=str(raw["digest"]))
        if snapshot.digest != _digest(fields):
            # Recomputed, never trusted: a record that kept an old digest while a
            # bound field changed is a forged snapshot.
            raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source=f"{source} (digest)",
                                target="snapshot digest does not match its bindings")
        return snapshot

    def as_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            wire: getattr(self, name) for name, wire in _RECORD_FIELDS.items()
        }
        record["digest"] = self.digest
        return record

    @property
    def binding_fields(self) -> tuple[str, ...]:
        return tuple(_RECORD_FIELDS)

    def covers(self, **bindings: Any) -> bool:
        """Every binding given must match; a partial probe never says 'close enough'."""
        for name, value in bindings.items():
            if value is _MISSING:
                continue
            if name not in _RECORD_FIELDS:
                raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source="snapshots.covers",
                                    target=name)
            if getattr(self, name) != value:
                return False
        return True

    def valid_at(self, moment: dt.datetime) -> bool:
        if not isinstance(moment, dt.datetime) or moment.tzinfo is None:
            return False
        return self.issued_at <= moment <= self.expires_at

    def age_at(self, moment: dt.datetime) -> dt.timedelta:
        return moment - self.issued_at


def _field(value: Any, *, name: str) -> Any:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source=f"snapshots.{name}",
                                target="naive timestamp")
        return value
    if not isinstance(value, str) or _TEXT_OK.fullmatch(value) is None or not value.strip():
        raise PolicyRefusal("PERMISSION_SNAPSHOT_INVALID", source=f"snapshots.{name}",
                            target=None if value is None else type(value).__name__)
    return value


def _digest(fields: Mapping[str, Any]) -> str:
    canonical = {
        _RECORD_FIELDS[name]: (value.isoformat() if isinstance(value, dt.datetime) else value)
        for name, value in fields.items()
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
