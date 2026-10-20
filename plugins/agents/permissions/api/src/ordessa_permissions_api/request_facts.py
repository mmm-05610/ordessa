"""The facts a decision is made from, and the state of the thing it gates.

Two rules shape this module. First, only a *digest* of the arguments is ever
carried: the raw arguments are an unbounded, secret-bearing payload and this
domain has no field for them. Second, every trusted field is required - a
missing principal, session, channel or generation fails closed here instead of
reaching the synthesizer as an implicit default (FR-02).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final, Mapping, Sequence

from .codes import PolicyRefusal, probe
from .rules import _text

__all__ = [
    "ArgumentDigest",
    "ExecutionState",
    "OperationRequest",
    "build_operation_request",
]

_RECORD_FIELDS: Final[Mapping[str, str]] = {
    "principal": "principal",
    "server_instance_id": "serverInstanceId",
    "session_id": "sessionId",
    "native_session_id": "nativeSessionId",
    "execution_id": "executionId",
    "native_generation": "nativeGeneration",
    "tool_key": "toolKey",
    "target": "target",
    "argument_digest": "argumentDigest",
    "ceiling_revision": "ceilingRevision",
    "policy_revision": "policyRevision",
    "native_request_id": "nativeRequestId",
}
_REQUIRED: Final[tuple[str, ...]] = tuple(
    name for name in _RECORD_FIELDS if name != "target")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_OK = re.compile(r"[^\x00-\x1f\x7f]{1,512}\Z")


@dataclass(frozen=True)
class ArgumentDigest:
    """A digest of the operation arguments. There is no constructor for raw ones."""

    value: str

    @classmethod
    def of(cls, value: Any) -> "ArgumentDigest":
        return cls(value)

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _HEX64.fullmatch(self.value) is None:
            # The shape alone rules out a payload: a 64-character lowercase hex
            # digest cannot be a command line, a path list or a secret.
            raise PolicyRefusal("PERMISSION_REQUEST_INVALID",
                                source="request.ArgumentDigest (a 64-char hex digest"
                                       " is required)",
                                target=_shape(self.value))


def _shape(value: Any) -> str:
    if isinstance(value, str):
        return f"{len(value)} chars"
    return type(value).__name__


class ExecutionState(str, Enum):
    """What the gated execution is doing right now.

    `UNKNOWN` is its own answer: an outcome we cannot resolve is never folded
    into `not actionable`, and never into a permission.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @property
    def actionable(self) -> bool:
        return self is ExecutionState.RUNNING

    @property
    def outcome_is_resolved(self) -> bool:
        return self is not ExecutionState.UNKNOWN

    @classmethod
    def of(cls, value: Any) -> "ExecutionState":
        if isinstance(value, cls):
            return value
        try:
            return cls(value)
        except ValueError:
            raise PolicyRefusal("PERMISSION_REQUEST_INVALID", source="request.ExecutionState.of",
                                target=probe(value)) from None


@dataclass(frozen=True)
class OperationRequest:
    """One pre-side-effect operation, fully attributed."""

    principal: str
    server_instance_id: str
    session_id: str
    native_session_id: str
    execution_id: str
    native_generation: str
    tool_key: str
    argument_digest: ArgumentDigest
    ceiling_revision: str
    policy_revision: str
    native_request_id: str
    target: str | None = None

    @classmethod
    def from_record(cls, raw: Any) -> "OperationRequest":
        source = "request.OperationRequest.from_record"
        if not isinstance(raw, Mapping):
            raise PolicyRefusal("PERMISSION_REQUEST_INVALID", source=source,
                                target=None if raw is None else type(raw).__name__)
        extra = set(raw) - set(_RECORD_FIELDS.values())
        if extra:
            raise PolicyRefusal("PERMISSION_REQUEST_INVALID", source=source,
                               target="unknown request fields: " + ",".join(sorted(extra)))
        values: dict[str, Any] = {}
        for name, wire in _RECORD_FIELDS.items():
            value = raw.get(wire)
            if name != "target" and value is None:
                # A missing trusted fact is a refusal naming the field, never a
                # default the caller did not write.
                raise PolicyRefusal("PERMISSION_REQUEST_INVALID", source=source,
                                   target=f"missing {wire}")
            if name == "argument_digest":
                values[name] = _digest(raw, wire)
            elif name == "target":
                values[name] = None if value is None else _target(value, wire=wire)
            else:
                values[name] = _text(value, code="PERMISSION_REQUEST_INVALID",
                                     source=f"request.{wire}")
        return cls(**values)

    @property
    def operation_digest(self) -> str:
        """The identity one approval may bind to."""
        return hashlib.sha256(json.dumps(
            {
                "principal": self.principal, "session": self.session_id,
                "execution": self.execution_id, "nativeGeneration": self.native_generation,
                "tool": self.tool_key, "target": self.target,
                "arguments": self.argument_digest.value,
                "ceilingRevision": self.ceiling_revision, "policyRevision": self.policy_revision,
            },
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()

    def __str__(self) -> str:
        return (f"OperationRequest(tool={self.tool_key}, target={self.target},"
                f" session={self.session_id}, operation={self.operation_digest[:12]})")


def _digest(raw: Mapping[str, Any], wire: str) -> ArgumentDigest:
    try:
        return ArgumentDigest(str(raw[wire]))
    except PolicyRefusal as refusal:
        raise PolicyRefusal("PERMISSION_REQUEST_INVALID",
                            source=f"request.{wire}", target=refusal.target) from None


def _target(value: Any, *, wire: str) -> str:
    if not isinstance(value, str) or _TARGET_OK.fullmatch(value) is None or not value.strip():
        raise PolicyRefusal("PERMISSION_REQUEST_INVALID", source=f"request.{wire}",
                            target=_shape(value))
    return value


def build_operation_request(*, principal: Any, server_instance_id: Any, session_id: Any,
                            native_session_id: Any, execution_id: Any, native_generation: Any,
                            tool_key: Any, target: Any, argument_digest: Any,
                            native_request_id: Any, ceilings: Any,
                            intent: Any) -> OperationRequest:
    """Assemble a request whose revision pins are read from the objects in force.

    The two revisions are derived, not typed in: a caller cannot pair a fresh
    ceiling with an old pin by accident when it hands over the objects. The
    native request id and the argument digest stay with the caller, because
    only the Harness and the executor can supply them truthfully.
    """
    from .ceilings import PolicyCeiling, intersect_ceilings
    from .intents import NO_INTENT_REVISION, PermissionIntent

    items: Sequence[PolicyCeiling]
    if isinstance(ceilings, PolicyCeiling):
        items = [ceilings]
    elif isinstance(ceilings, (str, bytes)) or not isinstance(ceilings, Sequence):
        raise PolicyRefusal("PERMISSION_REQUEST_INVALID", source="request.build",
                            target=type(ceilings).__name__)
    else:
        items = list(ceilings)
    effective = intersect_ceilings(items)
    if intent is not None and not isinstance(intent, PermissionIntent):
        raise PolicyRefusal("PERMISSION_REQUEST_INVALID", source="request.build",
                            target=type(intent).__name__)
    return OperationRequest.from_record({
        "principal": principal, "serverInstanceId": server_instance_id, "sessionId": session_id,
        "nativeSessionId": native_session_id, "executionId": execution_id,
        "nativeGeneration": native_generation, "toolKey": tool_key, "target": target,
        "argumentDigest": (argument_digest.value if isinstance(argument_digest, ArgumentDigest)
                           else argument_digest),
        "ceilingRevision": effective.revision_digest,
        "policyRevision": NO_INTENT_REVISION if intent is None else intent.revision_digest,
        "nativeRequestId": native_request_id,
    })
