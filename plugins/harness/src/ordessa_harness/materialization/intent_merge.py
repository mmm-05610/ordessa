"""T07 pure intent admission and deterministic conflict planning.

Authorities are server-supplied snapshots. This module never resolves a
handle to a path, opens a file, looks up a secret or invokes an action.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from ordessa_harness_api import (
    ActionDescriptor, BindSecret, ContractError, IntentSet, InvokeAction, MountContent,
    RemoveOwnedContent, ResetField, SetField, TargetDescriptor, TargetHandle,
)


class IntentMergeError(ValueError):
    """Admission or claim conflict; no plan is returned."""


@dataclass(frozen=True)
class TargetAuthority:
    descriptor: TargetDescriptor
    # Server-issued, normalized logical resource identity; no filesystem I/O.
    resource: tuple[str, ...]
    array_fields: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.descriptor, TargetDescriptor):
            raise IntentMergeError("target descriptor required")
        if not isinstance(self.resource, tuple) or not self.resource or any(not isinstance(s, str) or not s or s in {".", ".."} or "/" in s or "\\" in s for s in self.resource):
            raise IntentMergeError("invalid resource identity")
        if not isinstance(self.array_fields, tuple) or any(not isinstance(path, tuple) or not path or any(not isinstance(s, str) or not s for s in path) for path in self.array_fields):
            raise IntentMergeError("invalid array field")
        if any(path not in self.descriptor.allowed_fields for path in self.array_fields):
            raise IntentMergeError("array field lacks target authority")


@dataclass(frozen=True)
class OwnedContent:
    """Server-issued ownership at one target generation and resource identity."""

    target: TargetHandle
    resource: tuple[str, ...]
    relative_name: str
    owner: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, TargetHandle):
            raise IntentMergeError("owned content needs target handle")
        if not isinstance(self.resource, tuple) or not self.resource or any(
            not isinstance(segment, str) or not segment or segment in {".", ".."} or "/" in segment or "\\" in segment
            for segment in self.resource):
            raise IntentMergeError("invalid owned content resource")
        if not isinstance(self.owner, str) or not self.owner.strip():
            raise IntentMergeError("content owner required")
        if not isinstance(self.relative_name, str) or self.relative_name.startswith("/") or "\\" in self.relative_name or any(
            segment in {"", ".", ".."} for segment in self.relative_name.split("/")):
            raise IntentMergeError("invalid owned content name")


@dataclass(frozen=True)
class MergeAuthority:
    targets: tuple[TargetAuthority, ...]
    actions: tuple[ActionDescriptor, ...] = ()
    scope: str = "instance"
    owned_content: tuple[OwnedContent, ...] = ()

    def __post_init__(self) -> None:
        if (not isinstance(self.targets, tuple) or not isinstance(self.actions, tuple) or
                not isinstance(self.owned_content, tuple) or
                any(not isinstance(entry, TargetAuthority) for entry in self.targets) or
                any(not isinstance(entry, ActionDescriptor) for entry in self.actions) or
                any(not isinstance(entry, OwnedContent) for entry in self.owned_content)):
            raise IntentMergeError("immutable authority tuples required")
        if self.scope not in {"instance", "session"}:
            raise IntentMergeError("invalid merge scope")
        ids = [entry.descriptor.handle.handle_id for entry in self.targets]
        if len(ids) != len(set(ids)):
            raise IntentMergeError("duplicate target authority")
        keys = [(action.action_id, action.schema_version) for action in self.actions]
        if len(keys) != len(set(keys)):
            raise IntentMergeError("duplicate action authority")
        for entry in self.targets:
            if entry.descriptor.scope != self.scope:
                raise IntentMergeError("target scope mismatch")
        known = {entry.descriptor.handle.handle_id: entry for entry in self.targets}
        owned_keys: set[tuple[str, tuple[str, ...], str]] = set()
        for content in self.owned_content:
            entry = known.get(getattr(content.target, "handle_id", None))
            if (entry is None or entry.descriptor.handle != content.target or
                    entry.resource != content.resource or entry.descriptor.kind != "directory" or
                    entry.descriptor.codec != "content"):
                raise IntentMergeError("owned content target or generation is stale")
            key = (content.target.handle_id, content.resource, content.relative_name)
            if key in owned_keys:
                raise IntentMergeError("duplicate owned content authority")
            owned_keys.add(key)


@dataclass(frozen=True)
class AuthorizedIntents:
    """The service supplies owner/facet after carrier authorization."""

    owner: str
    facet_id: str
    item_id: str
    contribution_version: str
    intents: IntentSet

    def __post_init__(self) -> None:
        if any(not isinstance(value, str) or not value.strip() for value in
               (self.owner, self.facet_id, self.item_id, self.contribution_version)):
            raise IntentMergeError("owner and source identity required")
        if not isinstance(self.intents, IntentSet):
            raise IntentMergeError("IntentSet required")


@dataclass(frozen=True, order=True)
class MergedIntent:
    owner: str
    facet_id: str
    item_id: str
    contribution_version: str
    kind: str
    target_id: str = ""
    generation: int = 0
    resource: tuple[str, ...] = ()
    field: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True)
class MergedPlan:
    intents: tuple[MergedIntent, ...]


def _prefix(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    return a[:len(b)] == b or b[:len(a)] == a


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def merge_intents(authority: MergeAuthority, submissions: tuple[AuthorizedIntents, ...]) -> MergedPlan:
    """Validate every intent, then return an immutable, order-independent plan.

    Two claims on an equal or nested field/content resource always conflict,
    including equal values from the same owner. Array descendants are one
    indivisible subtree. Invocation IDs and secret slots are exclusive.
    """
    if not isinstance(authority, MergeAuthority) or not isinstance(submissions, tuple):
        raise IntentMergeError("invalid merge input")
    targets = {entry.descriptor.handle.handle_id: entry for entry in authority.targets}
    actions = {(entry.action_id, entry.schema_version): entry for entry in authority.actions}
    owned_content = {(entry.target.handle_id, entry.resource, entry.relative_name): entry.owner
                     for entry in authority.owned_content}
    plans: list[MergedIntent] = []
    claims: list[tuple[tuple[str, ...], str]] = []
    slots: set[str] = set()
    invoked: set[str] = set()
    for submission in submissions:
        if not isinstance(submission, AuthorizedIntents):
            raise IntentMergeError("unauthorized submission")
        for intent in submission.intents.intents:
            source = intent.source
            if source.facet_id != submission.facet_id:
                raise IntentMergeError("source facet differs from authorized facet")
            if source.item_id != submission.item_id:
                raise IntentMergeError("source item differs from authorized item")
            if source.contribution_version != submission.contribution_version:
                raise IntentMergeError("source version differs from authorized version")
            target_id, generation, resource, field, detail = "", 0, (), (), ""
            claim_field: tuple[str, ...] = ()
            if isinstance(intent, InvokeAction):
                action = actions.get((intent.action_id, intent.schema_version))
                if action is None or action.scope != authority.scope:
                    raise IntentMergeError("unauthorized action")
                try:
                    action.input_schema.validate(intent.typed_payload)
                except ContractError as exc:
                    raise IntentMergeError("action payload violates declared schema") from exc
                key = intent.action_id
                if key in invoked:
                    raise IntentMergeError("duplicate action invocation")
                invoked.add(key)
                detail = _json((intent.action_id, intent.schema_version, intent.typed_payload, intent.expected_observation))
            else:
                descriptor_entry = targets.get(intent.target.handle_id)
                if descriptor_entry is None or descriptor_entry.descriptor.handle != intent.target:
                    raise IntentMergeError("unknown or stale target generation")
                descriptor = descriptor_entry.descriptor
                target_id, generation, resource = intent.target.handle_id, intent.target.generation, descriptor_entry.resource
                if isinstance(intent, (SetField, ResetField)):
                    if descriptor.kind != "file" or descriptor.codec not in {"json", "toml", "yaml"}:
                        raise IntentMergeError("field intent needs structured file target")
                    field = intent.field_path.segments
                    if not any(field == allowed or (allowed in descriptor_entry.array_fields and field[:len(allowed)] == allowed)
                               for allowed in descriptor.allowed_fields):
                        raise IntentMergeError("unauthorized field")
                    matching_arrays = (path for path in descriptor_entry.array_fields
                                       if field[:len(path)] == path)
                    # The outermost array owns the whole subtree regardless
                    # of descriptor declaration order.
                    claim_field = min(matching_arrays, key=lambda path: (len(path), path), default=field)
                    if isinstance(intent, ResetField):
                        if intent.baseline_rule not in descriptor.baseline_rules:
                            raise IntentMergeError("unauthorized baseline rule")
                        detail = intent.baseline_rule
                    else:
                        detail = _json(intent.typed_value)
                elif isinstance(intent, (MountContent, RemoveOwnedContent)):
                    if descriptor.kind != "directory" or descriptor.codec != "content":
                        raise IntentMergeError("content intent needs directory target")
                    field = tuple(intent.relative_name.split("/"))
                    claim_field = field
                    if isinstance(intent, RemoveOwnedContent) and owned_content.get(
                        (target_id, resource, intent.relative_name)) != submission.owner:
                        raise IntentMergeError("owned content authority missing or belongs to another owner")
                    detail = _json((intent.immutable_content_ref.reference, intent.immutable_content_ref.sha256, intent.immutable_content_ref.size, intent.mode)) if isinstance(intent, MountContent) else "remove"
                elif isinstance(intent, BindSecret):
                    if descriptor.kind != "environment" or descriptor.codec != "environment":
                        raise IntentMergeError("secret binding needs environment target")
                    if (intent.slot,) not in descriptor.allowed_fields:
                        raise IntentMergeError("unauthorized secret slot")
                    if intent.slot in slots:
                        raise IntentMergeError("duplicate secret slot")
                    slots.add(intent.slot)
                    field = (intent.slot,)
                    claim_field = field
                    detail = intent.secret_ref  # opaque reference; never resolve or reveal value
                else:
                    raise IntentMergeError("unknown intent")
                claim = resource + claim_field
                for previous, previous_kind in claims:
                    if _prefix(claim, previous):
                        raise IntentMergeError(f"overlapping {intent.kind}/{previous_kind} claims")
                claims.append((claim, intent.kind))
            plans.append(MergedIntent(submission.owner, source.facet_id, source.item_id,
                                      source.contribution_version, intent.kind,
                                      target_id, generation, resource, field, detail))
    return MergedPlan(tuple(sorted(plans)))
