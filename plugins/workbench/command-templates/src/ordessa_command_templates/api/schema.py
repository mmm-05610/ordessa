"""Validation primitives shared by the API DTOs and the library.

Pure functions over stdlib types only — no host import, no I/O. The bounds here
are the frozen size/encoding rules the domain refuses around (FR-01, FR-05):
they are intentionally conservative and constant so digests are reproducible.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .errors import InvalidDocumentError, InvalidIdentifierError

#: A stable template id: a lowercase namespaced slug. Kept compatible with the
#: repository's existing id vocabularies (``_PLUGIN_ID``/``_ASSET_ID``) without
#: importing them — the pattern is restated, the values are our own.
_TEMPLATE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}\Z")
#: A display slug used for menu naming; distinct ids may collide on a slug and
#: that collision must be *detected* (FR-07), so the slug itself stays simple.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")
#: A restricted ASCII parameter identifier inside ``{{name}}``.
_PARAM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
#: A namespaced slash-route id the Chat menu contributes as, e.g.
#: ``template:review``. This never claims a bare ``/review`` (FR-07).
_NAMESPACED_ROUTE = re.compile(r"^template:[a-z0-9][a-z0-9_-]{0,63}\Z")

#: Frozen document bounds (bytes of UTF-8 body / metadata lengths).
MAX_BODY_BYTES = 64 * 1024
MAX_DESCRIPTION_CHARS = 512
MAX_DISPLAY_NAME_CHARS = 120
#: Frozen bound on rendered output (FR-05 "输出大小受限").
MAX_RENDERED_BYTES = 128 * 1024

#: The single normalization the domain commits to for digests: NFC. CRLF and
#: lone CR are normalised to LF before hashing so the same logical text always
#: yields the same digest regardless of the author's editor.
def normalize_body(text: str) -> str:
    """Return the canonical form whose digest is stored (NFC + LF line ends)."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFC", normalised)


def validate_template_id(value: object) -> str:
    if not isinstance(value, str) or _TEMPLATE_ID.fullmatch(value) is None:
        raise InvalidIdentifierError(f"template id must be a lowercase slug, got {value!r}")
    return value


def validate_slug(value: object) -> str:
    if not isinstance(value, str) or _SLUG.fullmatch(value) is None:
        raise InvalidIdentifierError(f"slug must be a lowercase display token, got {value!r}")
    return value


def validate_param_name(value: object) -> str:
    if not isinstance(value, str) or _PARAM_NAME.fullmatch(value) is None:
        raise InvalidIdentifierError(f"parameter name must be a restricted ASCII id, got {value!r}")
    return value


def validate_namespaced_route(value: object) -> str:
    if not isinstance(value, str) or _NAMESPACED_ROUTE.fullmatch(value) is None:
        raise InvalidIdentifierError(f"namespaced route must be 'template:<slug>', got {value!r}")
    return value


def validate_body(text: object) -> str:
    """Reject non-str, over-long and surrogates/invalid UTF-8 before hashing."""
    if not isinstance(text, str):
        raise InvalidDocumentError("template body must be a string")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogates
        raise InvalidDocumentError("template body is not valid UTF-8") from exc
    if len(encoded) > MAX_BODY_BYTES:
        raise InvalidDocumentError(
            f"template body exceeds {MAX_BODY_BYTES} bytes (got {len(encoded)})")
    return text


def validate_text_field(value: object, field: str, max_chars: int, *, required: bool = True) -> str:
    if value is None:
        if required:
            raise InvalidDocumentError(f"{field} is required")
        return ""
    if not isinstance(value, str):
        raise InvalidDocumentError(f"{field} must be a string")
    if required and not value.strip():
        raise InvalidDocumentError(f"{field} must not be blank")
    if len(value) > max_chars:
        raise InvalidDocumentError(f"{field} exceeds {max_chars} characters")
    return value


def require_unique(names: Iterable[str], kind: str) -> None:
    seen: set[str] = set()
    for name in names:
        if name in seen:
            raise InvalidDocumentError(f"duplicate {kind} {name!r}")
        seen.add(name)
