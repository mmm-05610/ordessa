"""Deterministic, single-pass renderer for the closed syntax (FR-05).

Given a parsed body and its declared parameter schema plus supplied arguments,
the renderer validates every argument, resolves ``project-ref`` values through
an authorized port, substitutes each placeholder **exactly once** and emits a
byte-stable result.

Two properties are the safety story:

* **No second expansion.** The substituted text is copied verbatim; a value
  containing ``$``, ``{{other}}``, ``/``, newlines or Markdown is never re-scanned
  or re-interpreted. Placeholders found *inside* a value are inert.
* **Bounded output.** The rendered bytes are checked against
  :data:`MAX_RENDERED_BYTES` before being returned, so a long argument cannot
  blow up the draft.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Optional, Protocol, Sequence

from ..api import schema
from ..api.dto import ParameterSpec
from ..api.errors import (
    ParameterInvalidError,
    UnknownParameterError,
    UnresolvedParameterError,
    OutputLimitError,
)
from .parser import Literal, ParsedBody, Placeholder, Segment

#: A project reference is an opaque token ("alpha"), never a path. Any value
#: carrying a path separator, a Windows drive/UNC marker, a null byte or a
#: traversal segment is a forgery and is refused before it reaches the port.
_FORGED_PATH = re.compile(r"[/\\]|\.\.|[\x00]|^[A-Za-z]:|~")


@dataclass(frozen=True)
class ProjectRef:
    """A resolved project reference: an explicit display value + stable id.

    Constructed only by an authorized resolver, never by parsing user text, so a
    caller cannot forge a path into a rendered message.
    """

    display: str
    stable_id: str

    def render(self) -> str:
        return self.display


class ProjectResolver(Protocol):
    """The authorized project port a ``project-ref`` value is resolved against.

    Implementations are supplied by the host (a Workspace service). Absence is a
    genuine gap: a ``project-ref`` template then refuses to render rather than
    guessing a path.
    """

    def resolve(self, principal: str, reference: str) -> Optional[ProjectRef]:
        ...


@dataclass(frozen=True)
class RenderResult:
    text: str
    rendered_bytes: int
    digest: str


def _validate_scalar(spec: ParameterSpec, value: object) -> "str | int":
    if spec.kind == "integer":
        if type(value) is not int or isinstance(value, bool):
            raise ParameterInvalidError(
                f"parameter {spec.name!r} must be an integer, got {type(value).__name__}")
        if spec.minimum is not None and value < spec.minimum:
            raise ParameterInvalidError(f"parameter {spec.name!r} is below {spec.minimum}")
        if spec.maximum is not None and value > spec.maximum:
            raise ParameterInvalidError(f"parameter {spec.name!r} is above {spec.maximum}")
        return value
    # string / enum / project-ref all arrive as text.
    if not isinstance(value, str):
        raise ParameterInvalidError(f"parameter {spec.name!r} must be a string")
    if spec.kind == "enum":
        if value not in (spec.choices or ()):
            raise ParameterInvalidError(f"parameter {spec.name!r} is not one of the choices")
    if spec.max_length is not None and len(value) > spec.max_length:
        raise ParameterInvalidError(
            f"parameter {spec.name!r} exceeds max_length {spec.max_length}")
    return value


def check_publish_coverage(parsed: ParsedBody, parameters: Sequence[ParameterSpec]) -> None:
    """Schema integrity for a revision about to be stored.

    Enforces data-model.md's two publish rules: no undeclared placeholder, and no
    *required* parameter that the body never references (which could never be
    satisfied at render time). Optional parameters may go unused.
    """
    declared = {spec.name for spec in parameters}
    for name in parsed.placeholder_names:
        if name not in declared:
            raise UnknownParameterError(
                f"body references undeclared placeholder {name!r}")
    for spec in parameters:
        if spec.required and spec.name not in parsed.placeholder_names:
            raise UnknownParameterError(
                f"required parameter {spec.name!r} is never referenced by the body")


def check_coverage(parsed: ParsedBody, parameters: Sequence[ParameterSpec],
                   arguments: Mapping[str, object]) -> None:
    """Every placeholder is declared; every required parameter is supplied.

    Called by the library before a revision is publishable and by the renderer
    so a stored revision can never reference an undeclared name.
    """
    check_publish_coverage(parsed, parameters)
    declared = {spec.name for spec in parameters}
    for spec in parameters:
        if spec.required and spec.default is None and spec.name not in arguments:
            raise ParameterInvalidError(f"required parameter {spec.name!r} is missing")
    for name in arguments:
        if name not in declared:
            raise UnknownParameterError(f"argument {name!r} is not a declared parameter")


def render(
    parsed: ParsedBody,
    parameters: Sequence[ParameterSpec],
    arguments: Mapping[str, object],
    *,
    principal: str,
    resolver: Optional[ProjectResolver] = None,
) -> RenderResult:
    """Validate and substitute once, returning byte-stable text + digest."""
    by_name = {spec.name: spec for spec in parameters}
    check_coverage(parsed, parameters, arguments)

    out: list[str] = []
    for segment in parsed.segments:
        if isinstance(segment, Literal):
            out.append(segment.text)
            continue
        spec = by_name[segment.name]
        raw = arguments.get(segment.name, spec.default)
        if raw is None:
            raise ParameterInvalidError(f"parameter {segment.name!r} has no value")
        if spec.kind == "project-ref":
            out.append(_resolve_ref(spec.name, raw, principal, resolver))
        else:
            value = _validate_scalar(spec, raw)
            out.append(str(value))
    text = "".join(out)
    encoded = text.encode("utf-8")
    if len(encoded) > schema.MAX_RENDERED_BYTES:
        raise OutputLimitError(
            f"rendered output {len(encoded)} bytes exceeds {schema.MAX_RENDERED_BYTES}")
    from .digest import rendered_digest
    return RenderResult(text=text, rendered_bytes=len(encoded), digest=rendered_digest(text))


def _resolve_ref(name: str, raw: object, principal: str,
                 resolver: Optional[ProjectResolver]) -> str:
    if resolver is None:
        # Genuine absence is reported, never silently substituted (FR-08). The
        # gap is registered in specs/.../api-requests.md (project-ref port).
        raise UnresolvedParameterError(
            f"project-ref parameter {name!r} cannot be resolved: no authorized "
            "project port is wired")
    if not isinstance(raw, str) or not raw.strip():
        raise ParameterInvalidError(f"project-ref {name!r} needs a reference token")
    if _FORGED_PATH.search(raw):
        # A forged host path never reaches the resolver.
        raise ParameterInvalidError(
            f"project-ref {name!r} must be a project reference, not a path")
    resolved = resolver.resolve(principal, raw)
    if resolved is None:
        raise UnresolvedParameterError(
            f"project-ref {name!r} reference {raw!r} is not authorized for this principal")
    if not isinstance(resolved, ProjectRef):
        raise UnresolvedParameterError(f"project port returned an unexpected shape for {name!r}")
    return resolved.render()
