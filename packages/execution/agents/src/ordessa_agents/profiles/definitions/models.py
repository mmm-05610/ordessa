"""Profile identity, fixed revisions and deeply immutable configuration intent."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from .json_values import JsonValue, Omitted, OMITTED, freeze_json, _object
from .validation import (ProfileValidationError, validate_ref, validate_entry,
                         validate_declaration_fields, validate_content_fields)

@dataclass(frozen=True)
class ConfigurationDeclaration:
    declaration_id: str
    configuration_kind: str
    schema_version: str
    action: Literal["value", "reset", "disabled"]
    requirement: Literal["required", "optional"]
    payload: JsonValue | Omitted = OMITTED
    # None means field omitted; an empty tuple means explicitly supplied [].
    resource_refs: tuple[Mapping[str, JsonValue], ...] | None = None

    def __post_init__(self):
        if self.payload is not OMITTED:
            object.__setattr__(self, "payload", freeze_json(self.payload))
        if self.resource_refs is not None:
            if not isinstance(self.resource_refs, (tuple, list)):
                raise ProfileValidationError("resourceRefs must be an array")
            object.__setattr__(self, "resource_refs", tuple(_object(ref) for ref in self.resource_refs))
        validate_declaration_fields(
            self.declaration_id, self.configuration_kind, self.schema_version,
            self.action, self.requirement, has_payload=self.payload is not OMITTED,
            payload=self.payload, resource_refs=self.resource_refs or ())


@dataclass(frozen=True)
class ProfileContent:
    schema_version: str
    harness_definition_ref: Mapping[str, JsonValue]
    declarations: tuple[ConfigurationDeclaration, ...]
    # Existing optional metadata stays expressible, including explicitly empty {}.
    metadata: Mapping[str, JsonValue] | None = None

    def __post_init__(self):
        object.__setattr__(self, "harness_definition_ref", _object(self.harness_definition_ref))
        if not isinstance(self.declarations, (list, tuple)) or any(
                type(item) is not ConfigurationDeclaration for item in self.declarations):
            raise ProfileValidationError("typed configuration declarations required")
        object.__setattr__(self, "declarations", tuple(self.declarations))
        if self.metadata is not None:
            object.__setattr__(self, "metadata", _object(self.metadata))
        validate_content_fields(self.schema_version, self.harness_definition_ref,
                                self.declarations, self.metadata, omitted_value=OMITTED)


@dataclass(frozen=True)
class ProfileRevisionRef:
    environment_namespace: str
    profile_id: str
    revision: int
    digest: str

    def __post_init__(self):
        validate_ref(self.environment_namespace, self.profile_id, self.revision, self.digest)

@dataclass(frozen=True)
class ProfileRevision:
    ref: ProfileRevisionRef
    content: ProfileContent

    def __post_init__(self):
        if type(self.ref) is not ProfileRevisionRef or type(self.content) is not ProfileContent:
            raise ProfileValidationError("typed revision reference and content required")
        validate_content_fields(self.content.schema_version, self.content.harness_definition_ref,
                                self.content.declarations, self.content.metadata,
                                omitted_value=OMITTED,
                                environment=self.ref.environment_namespace)


@dataclass(frozen=True)
class Profile:
    profile_id: str
    version: int
    name: str
    archived_at: str | None
    current_revision: ProfileRevisionRef

    def __post_init__(self):
        if type(self.current_revision) is not ProfileRevisionRef:
            raise ProfileValidationError("fixed Profile revision reference required")
        validate_entry(self.profile_id, self.version, self.name,
                       self.archived_at, self.current_revision)

    @property
    def archived(self) -> bool:
        return self.archived_at is not None
