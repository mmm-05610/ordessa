"""T011-01: the capture transaction — one immutable record pinning exactly
what a submission was created from:

- draft (draftId/revision/text/attachment ids + refs),
- the consumed config operation ids,
- the base fact/revision the capture anchored to,
- the target identity, the binding identity,
- the deployment schema version, and the guarantee level.

UI selection and late edits NEVER modify a capture: the transaction deep-copies
its inputs at capture time and freezes them (MappingProxyType, the A1
deep-freeze rule). Anything that must survive a crash or a late reconcile
reads the CAPTURE, never re-derives it from live state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from ordessa_environment_api.guarantee import GuaranteeLevel


class CaptureError(ValueError):
    """A malformed capture request is refused, never half-recorded."""


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _deep_freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(v) for v in value)
    return value


@dataclass(frozen=True)
class CaptureTransaction:
    submission_id: str
    draft: Mapping[str, Any]
    config_op_ids: tuple[str, ...]
    base: str
    target: Mapping[str, Any]
    binding: Mapping[str, Any]
    schema: str
    guarantee: GuaranteeLevel

    @classmethod
    def capture(
        cls,
        *,
        submission_id: str,
        draft: Mapping[str, Any],
        config_op_ids: tuple[str, ...] | list[str],
        base: str,
        target: Mapping[str, Any],
        binding: Mapping[str, Any],
        schema: str,
        guarantee: GuaranteeLevel | str,
    ) -> "CaptureTransaction":
        if not isinstance(submission_id, str) or not submission_id.strip():
            raise CaptureError("submission_id must name the submission")
        if not isinstance(draft, Mapping):
            raise CaptureError("draft must map")
        draft_id = draft.get("draftId")
        draft_revision = draft.get("draftRevision")
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise CaptureError("draft must carry a stable draftId")
        if not isinstance(draft_revision, int) or draft_revision < 0:
            raise CaptureError("draft must carry its captured revision")
        if not isinstance(draft.get("text"), str):
            raise CaptureError("draft must carry its captured text")
        attachment_ids = draft.get("attachmentIds", ())
        if not isinstance(attachment_ids, (list, tuple)) or not all(isinstance(i, str) for i in attachment_ids):
            raise CaptureError("draft attachmentIds must be id strings")
        ops = tuple(config_op_ids)
        if not ops or not all(isinstance(op, str) and op.strip() for op in ops):
            raise CaptureError("config_op_ids must name the consumed operations")
        if len(set(ops)) != len(ops):
            raise CaptureError("config_op_ids must not repeat: one capture, one consumption")
        if not isinstance(base, str) or not base.strip():
            raise CaptureError("base must name the anchored fact/revision")
        if not isinstance(target, Mapping) or not target:
            raise CaptureError("target must map the submission target identity")
        if not isinstance(binding, Mapping) or not binding:
            raise CaptureError("binding must map the session binding identity")
        if not isinstance(schema, str) or not schema.strip():
            raise CaptureError("schema must name the deployment schema version")
        try:
            level = guarantee if isinstance(guarantee, GuaranteeLevel) else GuaranteeLevel.from_wire(str(guarantee))
        except ValueError as exc:
            raise CaptureError(str(exc)) from exc
        return cls(
            submission_id=submission_id,
            draft=_deep_freeze(dict(draft)),
            config_op_ids=ops,
            base=base,
            target=_deep_freeze(dict(target)),
            binding=_deep_freeze(dict(binding)),
            schema=schema,
            guarantee=level,
        )
