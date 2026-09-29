"""Resource references: declared here, resolved by their owners (FR05, G09).

A reference is an owner/version *declaration*, never an executable path or a
credential. Two different questions are answered by two different parties:

* **may this reference be used at all** — the permissions authority
  (`ceiling.CeilingAuthority`, in practice `permissions_seam.PermissionsSeam`
  over the real `permissions.authorizer@1` port) rules per reference owner; a
  denial keeps the §C5 code the authority's ruling mapped to and names the
  item;
* **what are its facts** — the owning service's resolver protocol.

An unresolvable reference yields an item-level `REFERENCE_UNRESOLVED`
diagnostic and the declaration still saves (the owning service may simply
be absent); the runtime path (`fail_fast`) refuses instead. When an authority
is wired but cannot answer, the reference is refused, never admitted by
default. Whatever a resolver hands back is sanitized: credential- or
path-shaped keys are dropped before the value can reach a snapshot, so a
compromised or sloppy resolver — including one replaying a real authority
payload — cannot smuggle a secret into the stored facts
(FR05 "引用由各属主授权解析，不复制秘密").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence

from . import dto, errors
from .ceiling import AdmissionContext, CeilingAuthority
from .scopes import Diagnostic

#: The authority-derived verdict keys a snapshot may carry: the verdict, the §C5
#: code, whether it stands, and the approval id the ruling binds to. Their codes
#: are chosen so that nothing argument-shaped or credential-shaped can be named
#: here at all. The ruling's own `payload` travels as data and is sanitized like
#: any other owner-supplied value.
_AUTHORITY_EVIDENCE_KEYS = ("admitted", "standing", "code", "authorityCode", "approvalId")

#: Case-insensitive match on the *last dotted segment* of a key, so nested
#: payloads (`{"auth":{"token":...}}`) are sanitized too.
_BANNED_TOKENS = frozenset({
    "token", "tokens", "api_key", "apikey", "secret", "secrets", "password",
    "passwd", "credential", "credentials", "authorization", "access_key",
    "access_token", "refresh_token", "client_secret",
    "path", "file_path", "filepath", "exec", "executable", "binary",
    "command", "commands", "argv", "shell", "cwd", "home",
})
_BANNED_WORDS = frozenset({
    "token", "apikey", "secret", "password", "passwd", "credential",
    "authorization", "access", "refresh", "exec", "executable", "binary",
    "command", "argv", "shell", "cwd", "home", "path",
})

RESERVATION_NOTE = "declaration only; the owning service authorizes at use time"


class ModelResolver(Protocol):
    def resolve_model(self, ref: dto.ModelRef) -> Mapping[str, Any] | None: ...


class ToolResolver(Protocol):
    def resolve_tool(self, ref: dto.ToolRef) -> Mapping[str, Any] | None: ...


class McpResolver(Protocol):
    def resolve_mcp(self, ref: dto.McpRef) -> Mapping[str, Any] | None: ...


class SkillResolver(Protocol):
    def resolve_skill(self, ref: dto.SkillRef) -> Mapping[str, Any] | None: ...


@dataclass(frozen=True)
class ResolvedReference:
    kind: str
    owner_id: str
    revision: str | None
    facts: Mapping[str, Any]
    #: The sanitized verdict evidence of the authority ruling, when one was
    #: taken. Empty means "no ruling was taken or it granted nothing".
    authority: Mapping[str, Any] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "owner_id": self.owner_id,
            "revision": self.revision,
            "facts": dict(self.facts),
            "authority": dict(self.authority),
        }


@dataclass(frozen=True)
class ReferenceResolution:
    references: tuple[ResolvedReference, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def unresolved(self) -> bool:
        return len(self.diagnostics) > 0


def _is_poisoned(key: str) -> bool:
    leaf = key.strip().lower().replace("-", "_").replace(".", "_")
    segments = {seg for seg in leaf.split("_") if seg}
    return leaf in _BANNED_TOKENS or bool(segments & _BANNED_WORDS)


def sanitize_facts(value: Any) -> Any:
    """Drop credential-shaped and executable-path entries; keep plain facts."""
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_facts(item)
            for key, item in value.items()
            if not _is_poisoned(str(key))
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_facts(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def authority_evidence(ruling: Any) -> Mapping[str, Any]:
    """The authority ruling reduced to snapshot-safe evidence.

    Only the declared keys can be carried, and they go through `sanitize_facts`
    like any other payload: a ruling object that somehow holds a token, a path
    or a raw argument payload cannot reach a stored snapshot through this path.
    """
    raw = {
        "admitted": bool(getattr(ruling, "admitted", False)),
        "standing": bool(getattr(ruling, "standing", False)),
        "code": getattr(ruling, "code", None),
        "authorityCode": getattr(ruling, "authority_code", None),
        "approvalId": getattr(ruling, "approval_id", None),
        "payload": dict(getattr(ruling, "payload", None) or {}),
    }
    kept = {key: raw[key] for key in _AUTHORITY_EVIDENCE_KEYS}
    kept["payload"] = raw["payload"]
    return sanitize_facts(kept)


def _resolve_one(
    *,
    kind: str,
    ref: Any,
    resolver: Any,
    method: str,
    diagnostics: list[Diagnostic],
    subject: AdmissionContext | None = None,
    authority: CeilingAuthority | None = None,
) -> ResolvedReference | None:
    item_id = f"{kind}:{ref.owner_id}"
    evidence: Mapping[str, Any] = {}
    if authority is not None:
        if subject is None:
            diagnostics.append(
                Diagnostic(
                    errors.ADAPTER_MISSING,
                    item_id=item_id,
                    detail="no admission subject was supplied, so the authority cannot "
                           "be told whose declaration this is; refusing instead of "
                           "defaulting to permissive",
                )
            )
            return None
        if not authority.is_available():
            diagnostics.append(
                Diagnostic(
                    errors.ADAPTER_MISSING,
                    item_id=item_id,
                    detail="the permissions authority is wired but cannot rule on this "
                           "reference; refusing instead of defaulting to permissive",
                )
            )
            return None
        ruling = authority.adjudicate(
            subject, kind, ref.owner_id, field_name=f"references.{item_id}",
        )
        evidence = authority_evidence(ruling)
        if not ruling.admitted:
            diagnostics.append(
                Diagnostic(
                    ruling.code or errors.PERMISSION_EXCEEDS_CEILING,
                    item_id=item_id,
                    detail=f"the permissions authority refused this reference: "
                           f"{ruling.detail or 'no reason given'}",
                )
            )
            return None
    if resolver is None:
        diagnostics.append(
            Diagnostic(
                errors.REFERENCE_UNRESOLVED,
                item_id=item_id,
                detail="no resolver injected for this reference kind; "
                       + RESERVATION_NOTE,
            )
        )
        return None
    facts = getattr(resolver, method)(ref)
    if facts is None:
        diagnostics.append(
            Diagnostic(
                errors.REFERENCE_UNRESOLVED,
                item_id=item_id,
                detail="owning service could not resolve this reference; "
                       + RESERVATION_NOTE,
            )
        )
        return None
    return ResolvedReference(
        kind=kind,
        owner_id=ref.owner_id,
        revision=ref.revision,
        facts=sanitize_facts(dict(facts)),
        authority=evidence,
    )


def rematch_tool_names(
    typed_names: Sequence[str],
    native_tool_table: Mapping[str, Mapping[str, Any]] | None,
) -> tuple[tuple[ResolvedReference, ...], tuple[Diagnostic, ...]]:
    """Re-match user-typed tool strings against the target-native table.

    A typed string is never treated as a permission: it only selects a row
    of the supplied table, and the resolved facts come from the table, not
    from the string (data-model §资源引用). A missing table is unverifiable
    and fails closed.
    """
    resolved: list[ResolvedReference] = []
    diagnostics: list[Diagnostic] = []
    for name in sorted(set(typed_names)):
        entry = None if native_tool_table is None else native_tool_table.get(name)
        if entry is None:
            diagnostics.append(
                Diagnostic(
                    errors.REFERENCE_UNRESOLVED,
                    item_id=f"tool-name:{name}",
                    detail="name not present in the target-native tool table; "
                           "a typed string grants nothing",
                )
            )
            continue
        resolved.append(
            ResolvedReference(kind="tool-name", owner_id=name, revision=None,
                              facts=sanitize_facts(dict(entry)))
        )
    return tuple(resolved), tuple(diagnostics)


def resolve_references(
    revision: dto.DefinitionRevision,
    *,
    models: ModelResolver | None = None,
    tools: ToolResolver | None = None,
    mcps: McpResolver | None = None,
    skills: SkillResolver | None = None,
    fail_fast: bool = False,
    authority: CeilingAuthority | None = None,
) -> ReferenceResolution:
    """Resolve every declaration in one revision.

    Unresolvable references produce diagnostics by default (the data still
    saves); `fail_fast` turns the first one into a typed refusal for the
    runtime path (`resolvePreview`).

    With an `authority` (the permissions seam over `permissions.authorizer@1`)
    each reference's per-owner authorisation is put to that authority first: a
    refusal is reported with the code the authority's ruling mapped to rather
    than flattened into `REFERENCE_UNRESOLVED`, because "the owner has no
    answer" and "the authority says no" are different §C5 findings — and either
    way the reference stays a declaration that grants nothing.
    """
    resolved: list[ResolvedReference] = []
    diagnostics: list[Diagnostic] = []
    subject = None if authority is None else authority.subject_for(revision)
    plan: list[tuple[str, Any, Any, str]] = []
    if revision.declared_model_ref is not None:
        plan.append(("model", revision.declared_model_ref, models, "resolve_model"))
    for ref in revision.tool_refs:
        plan.append(("tool", ref, tools, "resolve_tool"))
    for ref in revision.mcp_refs:
        plan.append(("mcp", ref, mcps, "resolve_mcp"))
    for ref in revision.skill_refs:
        plan.append(("skill", ref, skills, "resolve_skill"))
    for kind, ref, resolver, method in plan:
        item = _resolve_one(kind=kind, ref=ref, resolver=resolver,
                            method=method, diagnostics=diagnostics,
                            subject=subject, authority=authority)
        if item is not None:
            resolved.append(item)
    if diagnostics and fail_fast:
        raise errors.refused(
            diagnostics[0].code,
            item_id=diagnostics[0].item_id,
            detail=diagnostics[0].detail,
        )
    return ReferenceResolution(references=tuple(resolved),
                               diagnostics=tuple(diagnostics))
