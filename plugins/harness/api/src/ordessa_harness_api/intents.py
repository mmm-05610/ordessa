"""C3 sealed intent vocabulary. Owners are injected by the registration context."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias, Union

from .errors import ContractError
from .schema import JsonValue, _JsonSnapshotField, looks_secret_name, read_snapshot, snapshot_json


def _id(value: str, label: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ContractError(f"invalid {label}")


@dataclass(frozen=True)
class IntentSource:
    facet_id: str
    item_id: str
    contribution_version: str

    def __post_init__(self) -> None:
        for name in ("facet_id", "item_id", "contribution_version"):
            _id(getattr(self, name), name)


@dataclass(frozen=True)
class TargetHandle:
    """Opaque server-issued target; never a filesystem path."""

    handle_id: str
    generation: int

    def __post_init__(self) -> None:
        _id(self.handle_id, "handle_id")
        if type(self.generation) is not int or self.generation < 0:
            raise ContractError("invalid target generation")


@dataclass(frozen=True)
class FieldPath:
    segments: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.segments, (tuple, list)):
            raise ContractError("invalid structured field path")
        if not self.segments or any(not isinstance(s, str) or not s or s in {".", ".."} or "/" in s or "\\" in s for s in self.segments):
            raise ContractError("invalid structured field path")
        object.__setattr__(self, "segments", tuple(self.segments))


def _source(value: object) -> None:
    if not isinstance(value, IntentSource):
        raise ContractError("intent needs IntentSource")


def _target(value: object) -> None:
    if not isinstance(value, TargetHandle):
        raise ContractError("intent needs TargetHandle")


def _field_path(value: object) -> None:
    if not isinstance(value, FieldPath):
        raise ContractError("intent needs FieldPath")


@dataclass(frozen=True)
class SetField(_JsonSnapshotField):
    _snapshot_field = "typed_value"
    source: IntentSource
    target: TargetHandle
    field_path: FieldPath
    typed_value: JsonValue
    kind: Literal["set-field"] = field(default="set-field", init=False)

    def __post_init__(self) -> None:
        _source(self.source)
        _target(self.target)
        _field_path(self.field_path)
        if any(looks_secret_name(segment) for segment in self.field_path.segments):
            raise ContractError("secret-bearing field must use BindSecret")
        self._seal_json_field()


@dataclass(frozen=True)
class ResetField:
    source: IntentSource
    target: TargetHandle
    field_path: FieldPath
    baseline_rule: Literal["remove-key", "native-default", "restore-owned-baseline"]
    kind: Literal["reset-field"] = field(default="reset-field", init=False)

    def __post_init__(self) -> None:
        _source(self.source)
        _target(self.target)
        _field_path(self.field_path)
        if self.baseline_rule not in {"remove-key", "native-default", "restore-owned-baseline"}:
            raise ContractError("unknown baseline rule")


def _relative_name(name: str) -> None:
    _id(name, "relative_name")
    if name.startswith("/") or "\\" in name or any(part in {"", ".", ".."} for part in name.split("/")):
        raise ContractError("content name must be relative and normalized")


@dataclass(frozen=True)
class ContentRef:
    reference: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        _id(self.reference, "content reference")
        if len(self.sha256) != 64 or any(ch not in "0123456789abcdef" for ch in self.sha256):
            raise ContractError("invalid content digest")
        if type(self.size) is not int or self.size < 0:
            raise ContractError("invalid content size")


@dataclass(frozen=True)
class MountContent:
    source: IntentSource
    target: TargetHandle
    relative_name: str
    immutable_content_ref: ContentRef
    mode: Literal["read-only", "executable"]
    kind: Literal["mount-content"] = field(default="mount-content", init=False)

    def __post_init__(self) -> None:
        _source(self.source)
        _target(self.target)
        if not isinstance(self.immutable_content_ref, ContentRef):
            raise ContractError("mount needs ContentRef")
        _relative_name(self.relative_name)
        if self.mode not in {"read-only", "executable"}:
            raise ContractError("unknown content mode")


@dataclass(frozen=True)
class RemoveOwnedContent:
    source: IntentSource
    target: TargetHandle
    relative_name: str
    kind: Literal["remove-owned-content"] = field(default="remove-owned-content", init=False)

    def __post_init__(self) -> None:
        _source(self.source)
        _target(self.target)
        _relative_name(self.relative_name)


@dataclass(frozen=True)
class BindSecret:
    source: IntentSource
    target: TargetHandle
    slot: str
    secret_ref: str
    kind: Literal["bind-secret"] = field(default="bind-secret", init=False)

    def __post_init__(self) -> None:
        _source(self.source)
        _target(self.target)
        _id(self.slot, "slot")
        _id(self.secret_ref, "secret_ref")


@dataclass(frozen=True, init=False)
class InvokeAction:
    source: IntentSource
    action_id: str
    schema_version: str
    typed_payload: JsonValue
    expected_observation: str
    kind: Literal["invoke-action"] = field(default="invoke-action", init=False)

    def __init__(self, source: IntentSource, action_id: str, schema_version: str,
                 typed_payload: JsonValue, expected_observation: str):
        _source(source)
        _id(action_id, "action_id")
        _id(schema_version, "schema_version")
        _id(expected_observation, "expected_observation")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "action_id", action_id)
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "expected_observation", expected_observation)
        object.__setattr__(self, "_json_snapshot", snapshot_json(typed_payload))
        object.__setattr__(self, "kind", "invoke-action")

    @property  # type: ignore[no-redef]
    def typed_payload(self) -> JsonValue:
        return read_snapshot(object.__getattribute__(self, "_json_snapshot"))


Intent: TypeAlias = Union[SetField, ResetField, MountContent, RemoveOwnedContent, BindSecret, InvokeAction]


@dataclass(frozen=True)
class IntentSet:
    intents: tuple[Intent, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.intents, (tuple, list)):
            raise ContractError("intents must be a tuple or list")
        if any(type(intent) not in {SetField, ResetField, MountContent, RemoveOwnedContent, BindSecret, InvokeAction} for intent in self.intents):
            raise ContractError("unknown intent kind")
        object.__setattr__(self, "intents", tuple(self.intents))
