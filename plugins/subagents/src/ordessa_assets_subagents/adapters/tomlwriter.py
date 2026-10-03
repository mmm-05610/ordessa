"""A minimal, self-verifying TOML writer (Codex agent documents, G12/L1).

There is no TOML *writer* in the standard library, and this package may not
add a dependency, so this module hand-renders the narrow schema it needs —
tables, string / string-array / integer / boolean values — and then *every*
document is re-parsed with stdlib :mod:`tomllib` and compared to the intended
structure. That round-trip equality is the L1 evidence that the emitted
format is right without needing the Codex CLI (which is not installed).

Refusals, not approximations: NUL and other non-representable control bytes,
floats/None/nested tables (outside the schema), dotted or spaced keys, and
anything whose re-parse would disagree with the input.
"""
from __future__ import annotations

import re
import tomllib
from typing import Any, Mapping, Sequence

from .. import errors

BARE_KEY_RE = re.compile(r"\A[A-Za-z0-9_-]+\Z")
TABLE_NAME_RE = re.compile(r"\A[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*\Z")

_SHORT_ESCAPES = {"\b": "b", "\t": "t", "\n": "n", "\f": "f", "\r": "r"}
_MAX_INT = 2 ** 63 - 1
_MIN_INT = -(2 ** 63)


class TomlRefusal(errors.DomainError):
    """A typed refusal of a TOML document this writer will not emit."""

    def __init__(self, detail: str, *, item: str | None = None) -> None:
        super().__init__(errors.DEFINITION_INVALID, item_id=item,
                         detail=f"toml: {detail}")


def quote_string(value: Any, *, item: str) -> str:
    """One TOML basic string, escaped so the re-parse is the identity."""
    if not isinstance(value, str):
        raise TomlRefusal("only strings are emitable as string values", item=item)
    if "\x00" in value:
        # TOML \u0000 is not a Unicode scalar value: NUL cannot be written at
        # all, so it is refused rather than silently dropped.
        raise TomlRefusal("NUL (U+0000) has no TOML representation", item=item)
    out = ['"']
    for ch in value:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch in _SHORT_ESCAPES:
            out.append("\\" + _SHORT_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    out.append('"')
    text = "".join(out)
    try:
        text.encode("utf-8")  # lone surrogates die here
    except UnicodeEncodeError as exc:
        raise TomlRefusal("value is not utf-8 encodable", item=item) from exc
    return text


def _format_value(value: Any, *, item: str) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if not _MIN_INT <= value <= _MAX_INT:
            raise TomlRefusal("integer outside the TOML 64-bit range", item=item)
        return str(value)
    if isinstance(value, str):
        return quote_string(value, item=item)
    if isinstance(value, (list, tuple)):
        if not value:
            raise TomlRefusal("empty arrays are refused (schema has none)", item=item)
        return "[" + ", ".join(quote_string(v, item=f"{item}[]") for v in value) + "]"
    raise TomlRefusal(
        f"value type {type(value).__name__} is outside this writer's schema "
        "(str / list[str] / int / bool only)", item=item)


def _is_table(value: Any) -> bool:
    return isinstance(value, Mapping)


def render_document(document: Mapping[str, Any]) -> str:
    """Render `{key: scalar | {subkey: scalar}}` and verify by re-parse.

    The verification is not optional: whatever comes out of this function has
    already been re-parsed with `tomllib` and compared to the input.
    """
    if not isinstance(document, Mapping) or not document:
        raise TomlRefusal("a document must be a non-empty mapping")
    flat: list[tuple[str, str]] = []
    tables: list[tuple[str, list[tuple[str, str]]]] = []
    for key, value in document.items():
        if not isinstance(key, str) or BARE_KEY_RE.fullmatch(key) is None:
            raise TomlRefusal(
                f"key {key!r} is not a bare TOML key ([A-Za-z0-9_-]+); dotted "
                "and spaced keys are refused, not quoted around", item=str(key))
        if _is_table(value):
            rendered_inner: list[tuple[str, str]] = []
            if not value:
                raise TomlRefusal(f"table {key!r} is empty", item=key)
            for sub_key, sub_value in value.items():
                if not isinstance(sub_key, str) or BARE_KEY_RE.fullmatch(sub_key) is None:
                    raise TomlRefusal(f"table key {sub_key!r} is not bare", item=key)
                if _is_table(sub_value):
                    raise TomlRefusal("nested tables deeper than one level are refused",
                                      item=f"{key}.{sub_key}")
                rendered_inner.append((sub_key, _format_value(sub_value, item=f"{key}.{sub_key}")))
            tables.append((key, rendered_inner))
        else:
            flat.append((key, _format_value(value, item=key)))

    lines: list[str] = [f"{k} = {v}" for k, v in flat]
    for name, entries in tables:
        if TABLE_NAME_RE.fullmatch(name) is None:  # bare-key rule already covers it
            raise TomlRefusal(f"table name {name!r} is not expressible", item=name)
        lines.append("")
        lines.append(f"[{name}]")
        lines.extend(f"{k} = {v}" for k, v in entries)
    text = "\n".join(lines) + "\n"
    verify_roundtrip(document, text)
    return text


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _normalise(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_normalise(v) for v in value]
    if isinstance(value, list):
        return [_normalise(v) for v in value]
    return value


def verify_roundtrip(document: Mapping[str, Any], text: str) -> Mapping[str, Any]:
    """Re-parse `text` with stdlib `tomllib` and demand equality with `document`.

    A mismatch means the emitter lied; that is a refusal, never a shrug — the
    validator is what lets L1 tests stand as format evidence for G12.
    """
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise TomlRefusal(
            f"emitted document does not parse ({exc.__class__.__name__}: {exc})") from exc
    if parsed != _normalise(document):
        raise TomlRefusal(
            "re-parsed document differs from the intended structure "
            "(the writer would have silently altered a value)")
    return parsed


def render_and_verify(document: Mapping[str, Any]) -> str:
    """Alias kept explicit for call sites that want the intent in the name."""
    return render_document(document)
