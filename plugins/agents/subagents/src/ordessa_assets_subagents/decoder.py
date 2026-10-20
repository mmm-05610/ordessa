"""Strict, fail-closed decoding and value validation (spec FR01/FR06, gate G04).

Two rules hold this module together:

* nothing is guessed — a wrong type, a missing required field, an oversized or
  undecodable value is a typed refusal naming the item, raised before any
  write or native effect;
* a field the decoder does not understand is **kept verbatim** in
  `retained_native_fields` and never folded into an effective view, so an
  unmapped brand-specific field cannot be silently dropped and reported as
  applied (`is_compilable`, harness-adapters.md §格式映射).
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Iterable, Mapping

from . import limits
from .digest import DIGEST_RE, revision_digest
from .dto import (
    ORIGIN_SCOPES,
    SOURCE_ORIGINS,
    AgentDefinition,
    DefinitionRevision,
    McpRef,
    ModelRef,
    SkillRef,
    SourceApproval,
    ToolRef,
)
from .errors import DEFINITION_INVALID, PERMISSION_EXCEEDS_CEILING, DomainError

_SLUG_RE = limits._SLUG_RE
_REF_REVISION_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_PRINCIPAL_RE = re.compile(r"\A[a-z][a-z0-9_-]*:[A-Za-z0-9._:-]+\Z")
_TIMESTAMP_RE = re.compile(
    r"\A\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\Z"
)
#: A key that names a credential holder, wherever it appears as a mapping key.
_SECRET_KEY_RE = re.compile(
    r"\A(?:[\w.-]*[_-])?(?:api[_-]?key|apikey|access[_-]?key|secret[_-]?key"
    r"|client[_-]?secret|private[_-]?key|password|passwd|credential|authorization"
    r"|token|secret|bearer|cookie)(?:[_-][\w.-]*)?\Z",
    re.I,
)
#: An assignment-shaped mention of such a key inside a text value.
_CREDENTIAL_LINE_RE = re.compile(
    r"(?im)^[ \t]*[\"']?[\w .-]*"
    r"(?:api[_-]?key|apikey|access[_-]?key|secret[_-]?key|client[_-]?secret"
    r"|private[_-]?key|password|passwd|credential|authorization|token|secret"
    r"|bearer|cookie)[\w .-]*[\"']?[ \t]*[:=][ \t]*[\"']?\S"
)
_CREDENTIAL_VALUE_RES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bbearer[ \t]+[A-Za-z0-9._~+/=-]{16,}"),
)
_CONTROL_OK = "\t\n\r"
_REPLACEMENT = "\ufffd"
_DIGEST_MAX = len("sha256:") + 64


def _invalid(item: str, reason: str) -> DomainError:
    return DomainError(DEFINITION_INVALID, item_id=item, detail=reason)


def _exceeds(item: str, reason: str) -> DomainError:
    return DomainError(PERMISSION_EXCEEDS_CEILING, item_id=item, detail=reason)


# -- credential and text shape ---------------------------------------------


def _iter_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, entry in value.items():
            yield str(key)
            yield from _iter_keys(entry)
    elif isinstance(value, (list, tuple)):
        for entry in value:
            yield from _iter_keys(entry)


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for entry in value.values():
            yield from _iter_strings(entry)
    elif isinstance(value, (list, tuple)):
        for entry in value:
            yield from _iter_strings(entry)


def has_credential_shape(value: Any) -> bool:
    """True when a payload holds something that reads like a credential.

    Keys are matched structurally; a text value only when it is assignment- or
    token-shaped, so prose about a model's token budget still saves while a
    literal secret cannot be carried in by a body or a native fragment.
    """
    if any(_SECRET_KEY_RE.match(key) for key in _iter_keys(value)):
        return True
    for text in _iter_strings(value):
        if _CREDENTIAL_LINE_RE.search(text):
            return True
        if any(pattern.search(text) for pattern in _CREDENTIAL_VALUE_RES):
            return True
    return False


def is_credential_named(value: str) -> bool:
    """True when a name or literal reads as a credential: a key shape or a token."""
    return bool(
        _SECRET_KEY_RE.match(value)
        or _CREDENTIAL_LINE_RE.search(value)
        or any(pattern.search(value) for pattern in _CREDENTIAL_VALUE_RES)
    )


def check_credential_free(value: Any, *, item: str) -> None:
    if has_credential_shape(value):
        raise _exceeds(
            item,
            "credential-shaped content is never stored; declare a resource "
            "reference and let its owner authorise it",
        )


def check_text(
    value: Any,
    *,
    item: str,
    max_chars: int | None = None,
    max_bytes: int | None = None,
) -> str:
    """Bounded, UTF-8-safe text: no NUL, no control characters, no lossy bytes.

    A value must survive a UTF-8 round trip byte-identically, so an
    already-lossy string (a replacement character, a lone surrogate) is a
    refusal rather than a stored surprise.
    """
    if not isinstance(value, str):
        raise _invalid(item, f"expected a string, got {type(value).__name__}")
    if "\x00" in value:
        raise _invalid(item, "NUL bytes are never accepted")
    for index, char in enumerate(value):
        code = ord(char)
        if (code < 0x20 and char not in _CONTROL_OK) or code == 0x7F:
            raise _invalid(item, f"control character U+{code:04X} at offset {index}")
        if 0x80 <= code <= 0x9F:
            raise _invalid(item, f"control character U+{code:04X} at offset {index}")
        if 0xD800 <= code <= 0xDFFF:
            raise _invalid(item, f"lone surrogate U+{code:04X} at offset {index}")
        if code in (0xFFFE, 0xFFFF):
            raise _invalid(item, f"non-character U+{code:04X} at offset {index}")
    if _REPLACEMENT in value:
        raise _invalid(item, "a replacement character means the text is already lossy")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise _invalid(item, f"is not encodable as UTF-8 at offset {exc.start}") from None
    if encoded.decode("utf-8", errors="strict") != value:
        raise _invalid(item, "does not survive a UTF-8 round trip")
    if max_chars is not None and len(value) > max_chars:
        raise _invalid(item, f"exceeds {max_chars} characters (got {len(value)})")
    if max_bytes is not None and len(encoded) > max_bytes:
        raise _invalid(item, f"exceeds {max_bytes} bytes (got {len(encoded)})")
    return value


def check_identifier(value: Any, *, item: str, max_chars: int = limits.MAX_REF_ID_CHARS) -> str:
    text = check_text(value, item=item, max_chars=max_chars)
    if not text or limits._ID_RE.match(text) is None:
        raise _invalid(item, "must be a bare identifier of letters, digits and . _ - :")
    return text


def is_path_shaped(value: str) -> bool:
    """A reference is never a filesystem path, URL or home-relative locator."""
    return (
        "/" in value
        or "\\" in value
        or value.startswith(".")
        or value.startswith("~")
        or "://" in value
    )


# -- field groups ----------------------------------------------------------


def _check_scalar_mapping(
    value: Any,
    *,
    item: str,
    max_keys: int,
    positive_ints: bool,
) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _invalid(item, "expected an object of scalar entries")
    if len(value) > max_keys:
        raise _invalid(item, f"exceeds {max_keys} entries (got {len(value)})")
    checked: dict[str, Any] = {}
    for key, entry in value.items():
        name = check_text(key, item=f"{item}.key", max_chars=limits.MAX_REF_ID_CHARS)
        target = f"{item}.{name}"
        if isinstance(entry, bool) or not isinstance(entry, (str, int)):
            raise _invalid(target, "only scalar string or integer entries are declared")
        if isinstance(entry, int):
            if positive_ints and entry <= 0:
                raise _invalid(target, "must be a positive integer")
            checked[name] = entry
        elif positive_ints:
            raise _invalid(target, "expected an integer budget")
        else:
            checked[name] = check_text(entry, item=target, max_chars=limits.MAX_REF_ID_CHARS)
    check_credential_free(checked, item=item)
    return checked


def _check_ref(value: Any, *, item: str, expected_kind: type) -> Any:
    if isinstance(value, expected_kind):
        owner_id, revision = value.owner_id, value.revision
    elif isinstance(value, Mapping):
        unknown = sorted(set(value) - {"owner_id", "revision"})
        if unknown:
            raise _invalid(item, f"a reference carries only owner_id and revision, not {unknown}")
        owner_id, revision = value.get("owner_id"), value.get("revision")
    else:
        raise _invalid(item, f"expected a {expected_kind.__name__} declaration")
    owner_id = check_identifier(owner_id, item=f"{item}.owner_id")
    if is_path_shaped(owner_id):
        raise _invalid(item, "a resource reference is never a filesystem path or URL")
    if revision is not None:
        revision = check_text(revision, item=f"{item}.revision",
                              max_chars=limits.MAX_REF_ID_CHARS)
        if _REF_REVISION_RE.match(revision) is None or is_path_shaped(revision):
            raise _invalid(item, "a reference revision is a pinned version token")
    if is_credential_named(owner_id) or (revision and is_credential_named(revision)):
        raise _exceeds(item, "a resource reference never names a credential")
    return expected_kind(owner_id=owner_id, revision=revision)


def _check_refs(
    value: Any,
    *,
    item: str,
    expected_kind: type,
    max_entries: int,
) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, expected_kind):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise _invalid(item, "expected a list of resource references")
    if len(value) > max_entries:
        raise _invalid(item, f"exceeds {max_entries} references (got {len(value)})")
    refs = tuple(
        _check_ref(entry, item=f"{item}[{index}]", expected_kind=expected_kind)
        for index, entry in enumerate(value)
    )
    seen: set[tuple[str, str | None]] = set()
    for ref in refs:
        pair = (ref.owner_id, ref.revision)
        if pair in seen:
            raise _invalid(item, f"duplicate reference {ref.owner_id}")
        seen.add(pair)
    return refs


def _check_source(value: Any, *, item: str) -> SourceApproval:
    if isinstance(value, SourceApproval):
        source = value
    elif isinstance(value, Mapping):
        unknown = sorted(set(value) - {
            "origin", "origin_ref", "content_digest", "approved_by_principal", "approved_at",
        })
        if unknown:
            raise _invalid(item, f"a source approval has no {unknown} field")
        source = SourceApproval(
            origin=value.get("origin"), origin_ref=value.get("origin_ref"),
            content_digest=value.get("content_digest"),
            approved_by_principal=value.get("approved_by_principal"),
            approved_at=value.get("approved_at"),
        )
    else:
        raise _invalid(item, "expected a source approval object")
    if source.origin not in SOURCE_ORIGINS:
        raise _invalid(item, f"origin is one of {'/'.join(SOURCE_ORIGINS)}")
    origin_ref = check_text(source.origin_ref, item=f"{item}.origin_ref",
                            max_chars=limits.MAX_SOURCE_REF_CHARS)
    if origin_ref.startswith("/") or origin_ref.startswith("~") or origin_ref.startswith(".."):
        raise _invalid(item, "origin_ref is a relative provenance label, never a host path")
    if source.origin == "git-revision" and limits._GIT_PIN_RE.match(
        origin_ref.rsplit("@", 1)[-1].split("#", 1)[0]
    ) is None:
        raise _invalid(
            item,
            "a git-revision source pins a full 40-hex commit id; a floating "
            "branch is never a source",
        )
    digest = check_text(source.content_digest, item=f"{item}.content_digest",
                        max_chars=_DIGEST_MAX)
    if DIGEST_RE.match(digest) is None:
        raise _invalid(item, "content_digest must be sha256:<64 lowercase hex>")
    principal = check_text(source.approved_by_principal, item=f"{item}.approved_by_principal",
                           max_chars=limits.MAX_PRINCIPAL_CHARS)
    if _PRINCIPAL_RE.match(principal) is None:
        raise _invalid(item, "approved_by_principal is a namespaced principal id")
    approved_at = check_text(source.approved_at, item=f"{item}.approved_at", max_chars=64)
    if _TIMESTAMP_RE.match(approved_at) is None:
        raise _invalid(item, "approved_at must be an ISO-8601 timestamp")
    check_credential_free(
        {"origin_ref": origin_ref, "approved_by_principal": principal, "approved_at": approved_at},
        item=item,
    )
    return SourceApproval(
        origin=source.origin, origin_ref=origin_ref, content_digest=digest,
        approved_by_principal=principal, approved_at=approved_at,
    )


def _check_retained(value: Any, *, item: str) -> dict[str, Any]:
    """Unknown provider/brand fragments stay verbatim, JSON-shaped and sized."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise _invalid(item, "expected an object of retained native fields")
    if len(value) > limits.MAX_RETAINED_NATIVE_FIELDS:
        raise _invalid(item, f"exceeds {limits.MAX_RETAINED_NATIVE_FIELDS} retained fields")
    retained: dict[str, Any] = {}
    for key, entry in value.items():
        name = check_text(key, item=item, max_chars=limits.MAX_REF_ID_CHARS)
        target = f"{item}.{name}"
        if is_credential_named(name):
            raise _exceeds(target, "a native field named like a credential is never kept")
        try:
            encoded = json.dumps(
                entry, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True,
            )
        except (TypeError, ValueError):
            raise _invalid(target, "is not JSON-shaped, so it cannot be retained") from None
        if len(encoded.encode("utf-8")) > limits.MAX_RETAINED_NATIVE_BYTES:
            raise _invalid(target, f"exceeds {limits.MAX_RETAINED_NATIVE_BYTES} retained bytes")
        check_credential_free(entry, item=target)
        for text in _iter_strings(entry):
            check_text(text, item=target, max_bytes=limits.MAX_RETAINED_NATIVE_BYTES)
        retained[name] = entry
    return retained


# -- DTO validation (enforced on any caller-built object, before a write) --


def validate_definition(definition: AgentDefinition) -> AgentDefinition:
    if not isinstance(definition, AgentDefinition):
        raise _invalid("definition", "expected an AgentDefinition")
    check_identifier(definition.server_scope, item="server_scope")
    definition_id = check_identifier(definition.definition_id, item="definition_id",
                                     max_chars=limits.MAX_DEFINITION_ID_CHARS)
    if definition.slug and definition.slug in definition_id:
        raise _invalid("definition_id", "an opaque id is never derived from the slug")
    slug = check_text(definition.slug, item="slug", max_chars=limits.MAX_SLUG_CHARS)
    if _SLUG_RE.match(slug) is None:
        raise _invalid("slug", "must match [a-z0-9][a-z0-9._-]* and may not be empty")
    display_name = check_text(definition.display_name, item="display_name",
                              max_chars=limits.MAX_DISPLAY_NAME_CHARS)
    if not display_name.strip():
        raise _invalid("display_name", "must not be blank")
    check_text(definition.description, item="description",
               max_chars=limits.MAX_DESCRIPTION_CHARS)
    origin_owner = check_identifier(definition.origin_owner, item="origin_owner")
    if definition.origin_scope not in ORIGIN_SCOPES:
        raise _invalid("origin_scope", "must be public, project or profile")
    _check_int(definition.latest_revision, item="latest_revision", minimum=0)
    if not isinstance(definition.archived, bool):
        raise _invalid("archived", "expected a boolean")
    _check_int(definition.row_version, item="row_version", minimum=0)
    check_credential_free(asdict(definition), item="definition")
    return definition


def validate_revision(revision: DefinitionRevision) -> DefinitionRevision:
    """Check every field and hand back a normalized, fully typed revision."""
    if not isinstance(revision, DefinitionRevision):
        raise _invalid("revision", "expected a DefinitionRevision")
    definition_id = check_identifier(revision.definition_id, item="definition_id",
                                     max_chars=limits.MAX_DEFINITION_ID_CHARS)
    _check_int(revision.revision, item="revision", minimum=1)
    digest = check_text(revision.content_digest, item="content_digest", max_chars=_DIGEST_MAX)
    if DIGEST_RE.match(digest) is None:
        raise _invalid("content_digest", "must be sha256:<64 lowercase hex>")
    if not isinstance(revision.role_body, str) or not revision.role_body.strip():
        raise _invalid("role_body", "must not be blank")
    role_body = check_text(revision.role_body, item="role_body",
                           max_bytes=limits.MAX_ROLE_BODY_BYTES)
    model = None
    if revision.declared_model_ref is not None:
        model = _check_ref(revision.declared_model_ref, item="declared_model_ref",
                           expected_kind=ModelRef)
    tool_refs = _check_refs(revision.tool_refs, item="tool_refs", expected_kind=ToolRef,
                            max_entries=limits.MAX_TOOL_REFS)
    mcp_refs = _check_refs(revision.mcp_refs, item="mcp_refs", expected_kind=McpRef,
                           max_entries=limits.MAX_MCP_REFS)
    skill_refs = _check_refs(revision.skill_refs, item="skill_refs", expected_kind=SkillRef,
                             max_entries=limits.MAX_SKILL_REFS)
    permission = revision.requested_permission
    if permission is not None:
        permission = check_identifier(permission, item="requested_permission")
    isolation = _check_scalar_mapping(revision.isolation, item="isolation",
                                      max_keys=limits.MAX_ISOLATION_KEYS, positive_ints=False)
    budgets = _check_scalar_mapping(revision.limits, item="limits",
                                    max_keys=limits.MAX_LIMIT_KEYS, positive_ints=True)
    if revision.source is None:
        raise _invalid("source", "content without an approved source is never stored")
    source = _check_source(revision.source, item="source")
    retained = _check_retained(revision.retained_native_fields, item="retained_native_fields")
    check_credential_free(role_body, item="role_body")
    try:
        expected = revision_digest(revision)
    except TypeError as exc:
        raise _invalid("revision", f"content is not canonicalisable ({exc})") from None
    if digest != expected:
        raise _invalid("content_digest", "does not match the canonical digest of this content")
    return DefinitionRevision(
        definition_id=definition_id, revision=revision.revision, content_digest=digest,
        role_body=role_body, declared_model_ref=model, tool_refs=tool_refs, mcp_refs=mcp_refs,
        skill_refs=skill_refs, requested_permission=permission, isolation=isolation,
        limits=budgets, source=source, retained_native_fields=retained,
    )


def _check_int(value: Any, *, item: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(item, f"expected an integer, got {type(value).__name__}")
    if value < minimum:
        raise _invalid(item, f"must be at least {minimum}")
    return value


def is_compilable(revision: DefinitionRevision) -> bool:
    """False while anything is retained: an unmapped field is never "applied"."""
    return not revision.retained_native_fields and revision.source is not None


def definition_mapping(definition: AgentDefinition) -> dict[str, Any]:
    """The stored shape of a metadata row (round-trips through the decoder)."""
    return _plain(asdict(definition))


def revision_mapping(revision: DefinitionRevision) -> dict[str, Any]:
    """The stored shape of one immutable revision."""
    return _plain(asdict(revision))


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain(entry) for key, entry in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(entry) for entry in value]
    return value


# -- decoders --------------------------------------------------------------

_REVISION_REQUIRED = ("definition_id", "revision", "content_digest", "role_body")
_REVISION_KNOWN = frozenset(_REVISION_REQUIRED + (
    "declared_model_ref", "tool_refs", "mcp_refs", "skill_refs", "requested_permission",
    "isolation", "limits", "source", "retained_native_fields",
))
_DEFINITION_REQUIRED = (
    "server_scope", "definition_id", "slug", "display_name", "description",
    "origin_scope", "origin_owner",
)
_DEFINITION_KNOWN = frozenset(_DEFINITION_REQUIRED + (
    "latest_revision", "archived", "row_version",
))


def decode_revision(mapping: Mapping[str, Any]) -> DefinitionRevision:
    """One stored or imported revision shape, or a typed refusal naming an item."""
    if not isinstance(mapping, Mapping):
        raise _invalid("revision", "expected an object")
    for key in _REVISION_REQUIRED:
        if key not in mapping:
            raise _invalid(key, "required field is missing")
    retained = _check_retained(mapping.get("retained_native_fields"),
                               item="retained_native_fields")
    for key in sorted(set(mapping) - _REVISION_KNOWN):
        retained[check_text(key, item="retained_native_fields",
                            max_chars=limits.MAX_REF_ID_CHARS)] = mapping[key]
    model = mapping.get("declared_model_ref")
    revision = DefinitionRevision(
        definition_id=mapping["definition_id"],
        revision=mapping["revision"],
        content_digest=mapping["content_digest"],
        role_body=mapping["role_body"],
        declared_model_ref=None if model is None else _check_ref(
            model, item="declared_model_ref", expected_kind=ModelRef,
        ),
        tool_refs=_check_refs(mapping.get("tool_refs"), item="tool_refs",
                              expected_kind=ToolRef, max_entries=limits.MAX_TOOL_REFS),
        mcp_refs=_check_refs(mapping.get("mcp_refs"), item="mcp_refs",
                             expected_kind=McpRef, max_entries=limits.MAX_MCP_REFS),
        skill_refs=_check_refs(mapping.get("skill_refs"), item="skill_refs",
                               expected_kind=SkillRef, max_entries=limits.MAX_SKILL_REFS),
        requested_permission=mapping.get("requested_permission"),
        isolation=_check_scalar_mapping(mapping.get("isolation"), item="isolation",
                                        max_keys=limits.MAX_ISOLATION_KEYS, positive_ints=False),
        limits=_check_scalar_mapping(mapping.get("limits"), item="limits",
                                     max_keys=limits.MAX_LIMIT_KEYS, positive_ints=True),
        source=None if mapping.get("source") is None else _check_source(
            mapping["source"], item="source",
        ),
        retained_native_fields=retained,
    )
    return validate_revision(revision)


def decode_definition(mapping: Mapping[str, Any]) -> AgentDefinition:
    """The mutable metadata row: it has no content fields and no extras."""
    if not isinstance(mapping, Mapping):
        raise _invalid("definition", "expected an object")
    for key in _DEFINITION_REQUIRED:
        if key not in mapping:
            raise _invalid(key, "required field is missing")
    unknown = sorted(key for key in mapping if key not in _DEFINITION_KNOWN)
    if unknown:
        raise _invalid("definition", f"unknown field(s): {', '.join(unknown)}")
    definition = AgentDefinition(
        server_scope=mapping["server_scope"],
        definition_id=mapping["definition_id"],
        slug=mapping["slug"],
        display_name=mapping["display_name"],
        description=mapping["description"],
        origin_scope=mapping["origin_scope"],
        origin_owner=mapping["origin_owner"],
        latest_revision=mapping.get("latest_revision", 0),
        archived=mapping.get("archived", False),
        row_version=mapping.get("row_version", 0),
    )
    return validate_definition(definition)


# -- the imported document format -----------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_FRONTMATTER_FIELD_RE = re.compile(r"\A([A-Za-z][A-Za-z0-9_-]*)[ \t]*:[ \t]*(.*)\Z")
#: Frontmatter keys this domain understands; anything else is retained verbatim.
_IMPORT_KEYS = {
    "name": "slug",
    "description": "description",
    "model": "declared_model_ref",
    "tools": "tool_refs",
    "permission": "requested_permission",
}
_REQUIRED_IMPORT_KEYS = ("slug", "description")


def decode_import_document(text: str, *, item: str = "document") -> dict[str, Any]:
    """A frontmatter definition document as a partial revision mapping.

    Recognised keys become declarations; every other key lands in
    `retained_native_fields` so the compiled view can never claim an unmapped
    field was applied. Nothing here is executed, resolved or fetched.
    """
    check_text(text, item=item, max_bytes=limits.MAX_IMPORT_FILE_BYTES)
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise _invalid(item, "the document has no --- frontmatter block")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entry = _FRONTMATTER_FIELD_RE.match(stripped)
        if entry is None:
            raise _invalid("frontmatter", f"line is not a scalar entry: {stripped[:32]!r}")
        key, raw = entry.group(1), entry.group(2).strip()
        if raw[:1] in {"[", "{", "|", ">", "&", "*", "!", "%", "@", "`"}:
            raise _invalid(key, "only scalar frontmatter entries are understood")
        if not raw:
            raise _invalid(key, "must carry a value")
        if key in fields:
            raise _invalid(key, "duplicate frontmatter key")
        fields[key] = raw.strip("\"'")
    mapping: dict[str, Any] = {"role_body": text[match.end():], "retained_native_fields": {}}
    for key, value in fields.items():
        target = _IMPORT_KEYS.get(key)
        if target is None:
            mapping["retained_native_fields"][key] = value
        elif target == "declared_model_ref":
            mapping[target] = {"owner_id": value, "revision": None}
        elif target == "tool_refs":
            names = [name for name in re.split(r"[,\s]+", value) if name]
            mapping[target] = [{"owner_id": name, "revision": None} for name in names]
        else:
            mapping[target] = value
    for required in _REQUIRED_IMPORT_KEYS:
        if required not in mapping:
            raise _invalid(item, f"the document does not declare {required}")
    return mapping
