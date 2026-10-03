"""Value objects for the command-templates domain (data-model.md).

Frozen dataclasses that validate on construction, so an invalid id, an oversize
body or a malformed parameter schema can never be stored or rendered. These are
the shapes the Server method family and the frontend contracts both speak.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

from . import schema as _schema
from .errors import InvalidDocumentError

#: Parameter kinds the first version supports (FR-05 / data-model.md).
PARAMETER_KINDS = ("string", "enum", "integer", "project-ref")


@dataclass(frozen=True)
class ParameterSpec:
    """One declared template parameter.

    ``kind`` is one of :data:`PARAMETER_KINDS`. ``required`` parameters must be
    supplied; ``enum`` carries ``choices``; ``integer`` carries an optional
    inclusive ``minimum``/``maximum``; ``string``/``project-ref`` may bound
    ``max_length``. Nothing here admits a shell, URL, file or expression value.
    """

    name: str
    kind: str = "string"
    required: bool = True
    default: "str | int | None" = None
    max_length: Optional[int] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    choices: "tuple[str, ...] | None" = None

    def __post_init__(self) -> None:
        _schema.validate_param_name(self.name)
        if self.kind not in PARAMETER_KINDS:
            raise InvalidDocumentError(
                f"parameter {self.name!r} kind {self.kind!r} is not one of {PARAMETER_KINDS}")
        if type(self.required) is not bool:
            raise InvalidDocumentError(f"parameter {self.name!r} required must be a boolean")
        if self.kind == "enum":
            if not self.choices or len(set(self.choices)) != len(self.choices):
                raise InvalidDocumentError(
                    f"enum parameter {self.name!r} needs non-empty unique choices")
            if any(not isinstance(choice, str) for choice in self.choices):
                raise InvalidDocumentError(f"enum choices for {self.name!r} must be strings")
        else:
            if self.choices is not None:
                raise InvalidDocumentError(f"only enum parameters may declare choices ({self.name!r})")
        if self.kind == "integer":
            for bound in (self.minimum, self.maximum):
                if bound is not None and type(bound) is not int:
                    raise InvalidDocumentError(f"integer bounds for {self.name!r} must be ints")
            if (self.minimum is not None and self.maximum is not None
                    and self.minimum > self.maximum):
                raise InvalidDocumentError(f"integer range for {self.name!r} is inverted")
        else:
            if self.minimum is not None or self.maximum is not None:
                raise InvalidDocumentError(f"only integer parameters may declare a range ({self.name!r})")
        if self.max_length is not None:
            if type(self.max_length) is not int or self.max_length <= 0:
                raise InvalidDocumentError(f"max_length for {self.name!r} must be a positive int")
        if self.default is not None:
            self._check_default(self.default)

    def _check_default(self, value: object) -> None:
        if self.kind == "integer":
            if type(value) is not int:
                raise InvalidDocumentError(f"default for integer parameter {self.name!r} must be int")
        elif self.kind == "enum":
            if value not in (self.choices or ()):
                raise InvalidDocumentError(f"default for enum {self.name!r} is not a choice")
        else:
            if not isinstance(value, str):
                raise InvalidDocumentError(f"default for {self.kind} parameter {self.name!r} must be str")


def _specs(value: Sequence[ParameterSpec]) -> "tuple[ParameterSpec, ...]":
    if not isinstance(value, (tuple, list)):
        raise InvalidDocumentError("parameters must be a sequence of ParameterSpec")
    specs = tuple(value)
    for spec in specs:
        if not isinstance(spec, ParameterSpec):
            raise InvalidDocumentError("every parameter must be a ParameterSpec")
    _schema.require_unique([s.name for s in specs], "parameter")
    return specs


@dataclass(frozen=True)
class TemplateRevision:
    """One immutable body+schema revision, addressed by ``content_digest``.

    The digest is computed over the normalized body and the canonical schema so
    that re-publishing identical inputs yields identical bytes (G05).
    """

    template_id: str
    revision: int
    body: str
    parameters: "tuple[ParameterSpec, ...]" = ()
    content_digest: str = ""
    approved_at: Optional[str] = None
    created_at: str = ""
    immutable: bool = True

    def __post_init__(self) -> None:
        _schema.validate_template_id(self.template_id)
        if type(self.revision) is not int or self.revision < 1:
            raise InvalidDocumentError("revision must be a positive integer")
        _schema.validate_body(self.body)
        object.__setattr__(self, "parameters", _specs(self.parameters))
        if type(self.immutable) is not bool or not self.immutable:
            raise InvalidDocumentError("a revision is always immutable")

    @property
    def is_approved(self) -> bool:
        return self.approved_at is not None

    def spec(self, name: str) -> Optional[ParameterSpec]:
        for spec in self.parameters:
            if spec.name == name:
                return spec
        return None


@dataclass(frozen=True)
class Template:
    """The stable content entity. ``entity_version`` drives CAS (FR-11)."""

    id: str
    owner_principal: str
    display_name: str
    slug: str
    description: str = ""
    origin: str = "user"  # user | imported
    latest_revision: int = 0
    entity_version: int = 1
    created_at: str = ""
    archived_at: Optional[str] = None

    def __post_init__(self) -> None:
        _schema.validate_template_id(self.id)
        _schema.validate_slug(self.slug)
        _schema.validate_text_field(self.display_name, "display_name", _schema.MAX_DISPLAY_NAME_CHARS)
        _schema.validate_text_field(self.description, "description", _schema.MAX_DESCRIPTION_CHARS,
                                    required=False)
        if self.origin not in ("user", "imported"):
            raise InvalidDocumentError("template origin must be 'user' or 'imported'")
        if type(self.latest_revision) is not int or self.latest_revision < 0:
            raise InvalidDocumentError("latest_revision must be a non-negative integer")
        if type(self.entity_version) is not int or self.entity_version < 1:
            raise InvalidDocumentError("entity_version must be a positive integer")

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


@dataclass(frozen=True)
class Assignment:
    """A user/project/harness enable/disable rule pinning an approved revision.

    ``state`` is ``enable`` or ``disable``; ``pinned_revision`` is only required
    for ``enable`` and must reference an approved revision. ``expected_version``
    carries the CAS guard for the write, not the resolved value.
    """

    scope: str  # user-global|user-harness|project|project-harness|profile
    scope_identity: str
    template_id: str
    state: str  # enable | disable
    harness_id: Optional[str] = None
    pinned_revision: Optional[int] = None
    entity_version: int = 1
    updated_at: str = ""

    SCOPES = ("user-global", "user-harness", "project", "project-harness", "profile")

    def __post_init__(self) -> None:
        if self.scope not in self.SCOPES:
            raise InvalidDocumentError(f"assignment scope {self.scope!r} is unknown")
        _schema.validate_text_field(self.scope_identity, "scope_identity", 120)
        _schema.validate_template_id(self.template_id)
        if self.state not in ("enable", "disable"):
            raise InvalidDocumentError("assignment state must be 'enable' or 'disable'")
        if self.state == "enable":
            if self.pinned_revision is None:
                raise InvalidDocumentError("an enable assignment must pin an approved revision")
            if type(self.pinned_revision) is not int or self.pinned_revision < 1:
                raise InvalidDocumentError("pinned_revision must be a positive integer")
        elif self.pinned_revision is not None:
            raise InvalidDocumentError("a disable assignment must not pin a revision")
        if (self.scope in ("user-harness", "project-harness")) != (self.harness_id is not None):
            raise InvalidDocumentError("harness-scoped assignments require a harness_id and vice versa")


@dataclass(frozen=True)
class Target:
    """The real resolution target: authenticated principal + concrete scopes.

    Project/server/harness/profile identity comes from real services upstream;
    this value object only carries them and never fabricates an absence.
    """

    principal: str
    server_identity: str
    project_id: Optional[str] = None
    harness_id: Optional[str] = None
    profile_id: Optional[str] = None
    profile_revision: Optional[int] = None

    def __post_init__(self) -> None:
        _schema.validate_text_field(self.principal, "principal", 120)
        _schema.validate_text_field(self.server_identity, "server_identity", 120)


@dataclass(frozen=True)
class ExpansionReceipt:
    """A bounded, expiring record of one preview/insert (data-model.md).

    It stores digests, never the rendered body or the argument values, so it is
    safe to keep in memory without leaking user content into lists/logs (FR-09).
    """

    operation_id: str
    principal: str
    target_fingerprint: str
    template_id: str
    revision: int
    argument_digest: str
    rendered_digest: str
    rendered_size: int
    draft_id: Optional[str]
    draft_revision: Optional[int]
    created_at: str
    expires_at: str

    def fingerprint(self) -> "tuple[str, str, str, int, str]":
        """Identity of the render a later insert must still match (FR-12)."""
        return (self.principal, self.target_fingerprint, self.template_id,
                self.revision, self.rendered_digest)
