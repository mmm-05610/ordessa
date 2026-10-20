"""The narrow frontmatter-over-markdown codec (Claude agent documents, G11).

A hand-rolled strict subset — no PyYAML dependency exists for this package
and none may be added. What the codec understands, exactly:

* the fences: a first line `---`, a closing line `---` (LF only);
* top-level ``key: "quoted string"`` scalars;
* string lists in flow form ``key: ["a", "b"]`` or block form
  ``key:`` + one or more ``  - "item"`` lines.

Everything else is *refused on parse*, never approximated: tabs, CR/CRLF,
BOM, duplicate keys, tags (`!!python/object`), nested maps, block scalars
(`|`, `>`), flow maps, unquoted or single-quoted scalars, multi-line plain
values, comments and unbalanced quotes all raise :class:`FrontmatterRefusal`
(a typed `DEFINITION_INVALID` refusal naming the offending line/field).
The emitter always double-quotes and escapes, so ``emit -> parse`` is the
identity on everything the codec accepts (the L1 round-trip evidence).
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence, Union

from .. import errors

#: A field name as the frontmatter subset spells it.
KEY_RE = re.compile(r"\A[A-Za-z][A-Za-z0-9_-]*\Z")

_LINE_RE = re.compile(r"\A([A-Za-z][A-Za-z0-9_-]*):(?:[ ](.*))?\Z")
_BLOCK_ITEM_RE = re.compile(r"\A  - (.*)\Z")

#: One accepted scalar or one accepted flow/block list item.
Field = Union[str, tuple[str, ...]]

#: escape letter -> the character it stands for (parse direction)
_ESCAPES = {"\"": "\"", "\\": "\\", "/": "/", "b": "\b", "f": "\f",
            "n": "\n", "r": "\r", "t": "\t"}
#: character -> escape letter (emit direction); '/' needs no escape on output
_ESCAPE_OUTPUT = {ch: esc for esc, ch in _ESCAPES.items() if ch != "/"}


class FrontmatterRefusal(errors.DomainError):
    """A typed refusal of a frontmatter document; nothing is approximated."""

    def __init__(self, detail: str, *, item: str | None = None) -> None:
        super().__init__(errors.DEFINITION_INVALID, item_id=item,
                         detail=f"frontmatter: {detail}")


# -- emitter ----------------------------------------------------------------


def _quote(value: str, *, item: str) -> str:
    if not isinstance(value, str):
        raise FrontmatterRefusal("only strings are emitable", item=item)
    if "\x00" in value:
        raise FrontmatterRefusal("NUL cannot be represented", item=item)
    if value.startswith("\ufeff"):
        raise FrontmatterRefusal("a BOM inside a value is refused", item=item)
    out = ['"']
    for ch in value:
        if ch in _ESCAPE_OUTPUT:
            out.append("\\" + _ESCAPE_OUTPUT[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    out.append('"')
    try:
        "".join(out).encode("utf-8")
    except UnicodeEncodeError as exc:  # lone surrogates
        raise FrontmatterRefusal("value is not utf-8 encodable", item=item) from exc
    return "".join(out)


def emit_frontmatter(fields: Mapping[str, Union[str, Sequence[str]]], body: str) -> str:
    """Render one strict-subset document; refuses anything it cannot prove it
    can re-parse identically (no silent loss)."""
    if not isinstance(fields, Mapping) or not fields:
        raise FrontmatterRefusal("at least one field is required")
    if not isinstance(body, str):
        raise FrontmatterRefusal("body must be a string")
    if any(ord(ch) < 0x20 for ch in body if ch not in "\t\n\r") or "\x00" in body:
        raise FrontmatterRefusal("body control bytes are refused")
    if "\r" in body or body.startswith("\ufeff"):
        raise FrontmatterRefusal("body must be LF-only text without a BOM")
    if any(line == "---" for line in body.split("\n")):
        # A body line that is exactly the fence would truncate the parse; the
        # round-trip must be provable, so refuse it at emit time.
        raise FrontmatterRefusal("body may not contain a bare '---' fence line")
    lines: list[str] = []
    for key, value in fields.items():
        if not isinstance(key, str) or KEY_RE.fullmatch(key) is None:
            raise FrontmatterRefusal(f"key {key!r} is not a bare frontmatter key")
        if isinstance(value, str):
            lines.append(f"{key}: {_quote(value, item=key)}")
        elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            items = tuple(value)
            if not items:
                raise FrontmatterRefusal(f"key {key!r}: empty lists are refused")
            rendered = ", ".join(_quote(v, item=f"{key}[]") for v in items)
            lines.append(f"{key}: [{rendered}]")
        else:
            raise FrontmatterRefusal(f"key {key!r}: value must be a str or a list of str")
    text = "---\n" + "\n".join(lines) + "\n---\n" + body
    try:
        text.encode("utf-8")  # a lone surrogate anywhere (body included) dies here
    except UnicodeEncodeError as exc:
        raise FrontmatterRefusal("document is not utf-8 encodable") from exc
    return text


# -- parser ------------------------------------------------------------------


def _parse_quoted(text: str, *, where: str) -> str:
    """One complete double-quoted scalar consuming `text` entirely."""
    if not text.startswith('"'):
        raise FrontmatterRefusal(f"{where}: value must be a double-quoted scalar", item=where)
    out: list[str] = []
    i = 1
    n = len(text)
    while True:
        if i >= n:
            raise FrontmatterRefusal(f"{where}: unterminated quote", item=where)
        ch = text[i]
        if ch == '"':
            if i + 1 != n:
                raise FrontmatterRefusal(f"{where}: trailing content after the closing quote",
                                         item=where)
            return "".join(out)
        if ch == "\\":
            i += 1
            if i >= n:
                raise FrontmatterRefusal(f"{where}: unterminated escape", item=where)
            esc = text[i]
            if esc in _ESCAPES:
                out.append(_ESCAPES[esc])
                i += 1
                continue
            if esc == "u":
                digits = text[i + 1:i + 5]
                if len(digits) != 4 or re.fullmatch(r"[0-9a-fA-F]{4}", digits) is None:
                    raise FrontmatterRefusal(f"{where}: malformed \\u escape", item=where)
                code = int(digits, 16)
                if code < 0x20 and chr(code) not in "\b\f\n\r\t":
                    if code == 0:
                        raise FrontmatterRefusal(f"{where}: NUL is not representable", item=where)
                if 0xD800 <= code <= 0xDFFF:
                    raise FrontmatterRefusal(f"{where}: lone surrogates are refused", item=where)
                out.append(chr(code))
                i += 5
                continue
            raise FrontmatterRefusal(f"{where}: unknown escape \\{esc}", item=where)
        if ord(ch) < 0x20 and ch not in "\t":
            # A raw control byte in a scalar: multi-line and CRLF shapes are
            # exactly what this subset refuses to approximate.
            raise FrontmatterRefusal(f"{where}: raw control byte inside a scalar", item=where)
        if ch == "\t":
            raise FrontmatterRefusal(f"{where}: tabs are refused (use \\t)", item=where)
        out.append(ch)
        i += 1


def _parse_flow_list(text: str, *, where: str) -> tuple[str, ...]:
    if not text.startswith("["):
        raise FrontmatterRefusal(f"{where}: value form is not understood", item=where)
    if not text.endswith("]"):
        raise FrontmatterRefusal(f"{where}: unterminated flow list", item=where)
    inner = text[1:-1].strip()
    if not inner:
        raise FrontmatterRefusal(f"{where}: empty lists are refused", item=where)
    items: list[str] = []
    rest = inner
    while True:
        rest = rest.lstrip(" ")
        if not rest.startswith('"'):
            raise FrontmatterRefusal(
                f"{where}: flow list items must be double-quoted strings", item=where)
        # find the end of this quoted scalar, honouring escapes
        j = 1
        while True:
            if j >= len(rest):
                raise FrontmatterRefusal(f"{where}: unterminated quote in flow list", item=where)
            if rest[j] == "\\":
                j += 2
                continue
            if rest[j] == '"':
                break
            j += 1
        candidate = rest[:j + 1]
        items.append(_parse_quoted(candidate, where=f"{where}[]"))
        rest = rest[j + 1:]
        if rest == "":
            return tuple(items)
        if rest.startswith(", "):
            rest = rest[2:]
            continue
        raise FrontmatterRefusal(
            f"{where}: flow list must separate items with ', '", item=where)


def parse_frontmatter(text: str) -> tuple[dict[str, Field], str]:
    """Split one strict-subset document into (fields, body) or refuse."""
    if not isinstance(text, str):
        raise FrontmatterRefusal("document must be a string")
    if text.startswith("\ufeff"):
        raise FrontmatterRefusal("a leading BOM is refused")
    if "\r" in text:
        raise FrontmatterRefusal("CR is refused (this codec speaks LF only)")
    if "\x00" in text:
        raise FrontmatterRefusal("NUL is refused")
    lines = text.split("\n")
    if not lines or lines[0] != "---":
        raise FrontmatterRefusal("document must open with a '---' fence line")
    close = -1
    for index in range(1, len(lines)):
        if lines[index] == "---":
            close = index
            break
    if close < 0:
        raise FrontmatterRefusal("frontmatter fence is never closed")
    if close == 1:
        raise FrontmatterRefusal("frontmatter must carry at least one field")

    fields: dict[str, Field] = {}
    index = 1
    while index < close:
        line = lines[index]
        if "\t" in line:
            raise FrontmatterRefusal(f"line {index + 1}: tabs are refused in frontmatter")
        if not line.strip():
            raise FrontmatterRefusal(f"line {index + 1}: blank lines inside frontmatter are refused")
        if line.startswith("#"):
            raise FrontmatterRefusal(f"line {index + 1}: comments are outside the strict subset")
        if line.startswith(" "):
            raise FrontmatterRefusal(
                f"line {index + 1}: indented continuation/nested maps are refused")
        match = _LINE_RE.match(line)
        if match is None:
            raise FrontmatterRefusal(
                f"line {index + 1}: not a 'key: value' frontmatter line: {line[:64]!r}")
        key, raw_value = match.group(1), match.group(2)
        if key in fields:
            raise FrontmatterRefusal(f"duplicate key {key!r}", item=key)
        if raw_value is None or raw_value == "":
            # Block list form: one or more `  - "item"` lines must follow.
            items: list[str] = []
            index += 1
            while index < close:
                item_line = lines[index]
                item_match = _BLOCK_ITEM_RE.match(item_line)
                if item_match is None:
                    break
                items.append(_parse_quoted(item_match.group(1), where=f"{key}[]"))
                index += 1
            if not items:
                raise FrontmatterRefusal(
                    f"key {key!r} has no value: bare empty scalars and nested maps are refused",
                    item=key)
            fields[key] = tuple(items)
            continue
        if raw_value.startswith('"'):
            fields[key] = _parse_quoted(raw_value, where=key)
        elif raw_value.startswith("["):
            fields[key] = _parse_flow_list(raw_value, where=key)
        else:
            lead = raw_value[:1]
            named = {"|": "block scalar", ">": "folded scalar", "!": "tag (e.g. !!python/object)",
                     "{": "flow map", "'": "single-quoted scalar", "&": "anchor",
                     "*": "alias", "%": "directive"}.get(lead)
            raise FrontmatterRefusal(
                f"key {key!r}: {named or 'unquoted/multi-line scalar'} is outside the "
                "strict subset; nothing is approximated", item=key)
        index += 1

    body = "\n".join(lines[close + 1:])
    return fields, body
