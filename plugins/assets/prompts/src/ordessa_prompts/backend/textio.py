"""UTF-8 import/export discipline (contracts.md §1 importText/exportText).

Import receives bytes the client already selected and uploaded — the
service never dereferences a path (G04). Rules:

* strict UTF-8 only: an invalid encoding or NUL refuses the whole item,
  nothing is truncated or patched;
* a leading BOM may be stripped *only* at the very start, and the result
  says so (``bom_stripped``) — interior BOMs stay an encoding error;
* pure whitespace / empty bodies refuse;
* one body ≤ 128 KiB checked *before* anything is applied;
* export proposes a safe filename derived from the title — no host
  paths, no separators, no traversal (G05).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..api import (
    BODY_MAX_BYTES,
    IMPORT_MAX_BYTES,
    InvalidContentError,
    LimitExceededError,
)

_BOM = "\ufeff"
_UNSAFE_FILENAME = re.compile(r"[^A-Za-z0-9._ -]+")


@dataclass(frozen=True)
class ImportedText:
    body: bytes
    #: True when a leading UTF-8 BOM was removed; the saved digest is
    #: computed over the final saved bytes (data-model).
    bom_stripped: bool
    suggested_title: str


def decode_import_bytes(content: bytes, *, filename_hint: "str | None" = None) -> ImportedText:
    if not isinstance(content, bytes):
        raise InvalidContentError("importText needs raw bytes, not a decoded string")
    if len(content) > IMPORT_MAX_BYTES:
        # Refuse before applying: an over-capacity import is never truncated.
        raise LimitExceededError(
            f"import exceeds {IMPORT_MAX_BYTES} bytes; split the document first",
            size=len(content), limit=IMPORT_MAX_BYTES)
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InvalidContentError(
            "import is not valid UTF-8", start=exc.start, end=exc.end) from exc
    bom_stripped = text.startswith(_BOM)
    if bom_stripped:
        text = text[1:]
    if "\x00" in text:
        raise InvalidContentError("import contains NUL characters")
    if not text.strip():
        raise InvalidContentError("import is empty or only whitespace")
    body = text.encode("utf-8")
    if len(body) > BODY_MAX_BYTES:
        raise LimitExceededError(
            f"import exceeds {BODY_MAX_BYTES} bytes after BOM processing",
            size=len(body), limit=BODY_MAX_BYTES)
    return ImportedText(body=body, bom_stripped=bom_stripped,
                        suggested_title=suggested_title_from_hint(filename_hint))


def suggested_title_from_hint(filename_hint: "str | None") -> str:
    """A display title from a *name hint* only — never a path read."""
    if not filename_hint:
        return "Imported prompt"
    name = str(filename_hint).replace("\\", "/").rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name and not name.startswith(".") else name
    cleaned = sanitize_filename(stem)
    return cleaned or "Imported prompt"


def sanitize_filename(name: str) -> str:
    """A safe suggestion for the client's existing save dialog.

    Strips separators and traversal, keeps it short; the Server never
    writes this path itself (FR15/G05).
    """
    text = unicodedata.normalize("NFKC", str(name))
    text = text.replace("/", " ").replace("\\", " ").replace("\x00", "")
    text = _UNSAFE_FILENAME.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text in ("", ".", ".."):
        text = "prompt"
    return text[:80]


def export_filename(kind: str, title: str, revision: int) -> str:
    safe = sanitize_filename(title) or "prompt"
    return f"{safe}.prompt{int(revision)}.md"
