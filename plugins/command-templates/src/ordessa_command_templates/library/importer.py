"""Read-only native-file import preview/commit (T07, FR-05, gate G21).

Only bytes a user explicitly selected are ever examined; there is no HOME or
project-directory scan here (the caller passes the bytes). A native prompt file
is converted to an Ordessa revision **only** when the mapping is provably
lossless. Anything that carries command execution, a dynamic include, a
permission field, or a parameter form we cannot represent is refused rather than
partially imported, and the source file is never written back.

This module is pure over ``bytes``/``str`` — it opens no files itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..api import schema
from ..api.dto import ParameterSpec
from ..api.errors import InvalidDocumentError, ProjectionRefusedError
from ..expansion.parser import Placeholder, parse

#: A native Markdown prompt may name arguments with $1/$ARGUMENTS/$FILE or embed
#: dynamic context. None of those have a lossless Ordessa v1 equivalent, so their
#: presence refuses the import outright (spec "含动态 include/命令执行… 必须拒绝").
_DYNAMIC_MARKERS = (
    re.compile(r"\$ARGUMENTS\b"),
    re.compile(r"\$\d"),
    re.compile(r"\$FILE\b"),
    re.compile(r"!`"),                       # Claude inline bash execution
    re.compile(r"@\S"),                      # Claude file/@mention include
    re.compile(r"```(bash|sh|shell|python)\b", re.IGNORECASE),  # fenced exec blocks
)
#: A YAML frontmatter permission/model/tool key is outside the message contract.
_PERMISSION_KEYS = re.compile(
    r"^\s*(allowed-tools|permission[s]?|model|tools|env)\s*:", re.IGNORECASE | re.MULTILINE)


@dataclass(frozen=True)
class ImportPreview:
    ok: bool
    display_name: str
    body: str
    parameters: "tuple[ParameterSpec, ...]"
    reason: Optional[str] = None
    detail: Optional[str] = None


def _split_frontmatter(text: str) -> "tuple[str, str]":
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            header = text[4:end]
            nl = text.find("\n", end + 1)
            body = text[nl + 1:] if nl != -1 else ""
            return header, body
    return "", text


def _frontmatter_name(header: str) -> Optional[str]:
    for line in header.splitlines():
        m = re.match(r"\s*name\s*:\s*(.+?)\s*\Z", line)
        if m:
            return m.group(1).strip("'\"")
    return None


def preview_import(*, raw: bytes, source_label: str) -> ImportPreview:
    """Decide, from the selected bytes only, whether the import is lossless.

    ``source_label`` is the user-facing name they chose the file by; it is never
    treated as a path and nothing is opened from it.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise InvalidDocumentError("import input must be raw bytes the user selected")
    if len(raw) > schema.MAX_BODY_BYTES:
        return ImportPreview(False, "", "", (), reason="SIZE",
                             detail="the source exceeds the template size bound")
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        return ImportPreview(False, "", "", (), reason="ENCODING",
                             detail="the source is not valid UTF-8")
    header, body = _split_frontmatter(text)
    if _PERMISSION_KEYS.search(header):
        return ImportPreview(False, "", "", (), reason="PERMISSION_FIELD",
                             detail="a native permission/model/tool field has no lossless mapping")
    for marker in _DYNAMIC_MARKERS:
        if marker.search(body):
            return ImportPreview(False, "", "", (), reason="DYNAMIC_INCLUDE_OR_EXEC",
                                 detail="the source carries command execution or a dynamic include")
    display = _frontmatter_name(header) or source_label
    # A native file that already uses $1-style positional arguments was rejected
    # above. Anything left is treated as a literal body unless it happens to use
    # {{name}}, which is our own syntax and imports cleanly.
    try:
        parsed = parse(body)
    except InvalidDocumentError as exc:
        return ImportPreview(False, display, body, (), reason="MALFORMED", detail=str(exc))
    names = [seg.name for seg in parsed.segments if isinstance(seg, Placeholder)]
    parameters = tuple(ParameterSpec(name=n, kind="string", required=True) for n in sorted(set(names)))
    try:
        slug = _slugify(display)
    except InvalidDocumentError as exc:
        return ImportPreview(False, display, body, parameters, reason="NAME_UNMAPPABLE",
                             detail=str(exc))
    return ImportPreview(True, display, body, parameters, detail=slug)


def _slugify(display: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", display.strip().lower()).strip("-")[:64]
    if not slug:
        raise InvalidDocumentError("the source name cannot map to a display slug")
    return slug


def commit_from_preview(preview: ImportPreview) -> "dict[str, object]":
    """Turn an approved preview into the create+save_revision arguments.

    Commit does not touch the original bytes; it only hands the caller the plain
    domain inputs to store as an ``imported`` revision.
    """
    if not preview.ok:
        raise ProjectionRefusedError(
            f"import was refused ({preview.reason})", detail=preview.detail)
    return {
        "origin": "imported",
        "display_name": preview.display_name,
        "slug": preview.detail,
        "body": preview.body,
        "parameters": preview.parameters,
    }
