"""Closed syntax v1 parser — ``{{name}}`` with ``\\{{`` / ``\\}}`` escapes.

Ordessa's own deterministic grammar (data-model.md). It deliberately does *not*
reproduce Pi ``$1``, Claude ``$ARGUMENTS`` or Codex ``$FILE``. The parser splits
a body into literal and placeholder segments; it recognises exactly two escapes
and no other syntax — no expressions, no shell, no URL/file include, no
recursion, no control flow.

A ``\\`` before ``{{`` or ``}}`` makes that brace pair literal and consumes the
backslash. A lone backslash (before anything else) is literal text. This keeps
the escape set closed and the mapping byte-exact.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from ..api.errors import InvalidDocumentError


@dataclass(frozen=True)
class Literal:
    text: str
    kind: str = "literal"


@dataclass(frozen=True)
class Placeholder:
    name: str
    kind: str = "placeholder"


Segment = Union[Literal, Placeholder]


@dataclass(frozen=True)
class ParsedBody:
    segments: "tuple[Segment, ...]"

    @property
    def declared_order(self) -> "tuple[str, ...]":
        """Placeholder names in first-appearance order (duplicates collapse)."""
        seen: set[str] = set()
        ordered: list[str] = []
        for segment in self.segments:
            if isinstance(segment, Placeholder) and segment.name not in seen:
                seen.add(segment.name)
                ordered.append(segment.name)
        return tuple(ordered)

    @property
    def placeholder_names(self) -> "frozenset[str]":
        return frozenset(
            segment.name for segment in self.segments if isinstance(segment, Placeholder))


def parse(body: str) -> ParsedBody:
    """Tokenise ``body`` into literal/placeholder segments.

    Rejects an unterminated ``{{`` (a placeholder that never closes) because a
    half-written token cannot be rendered deterministically.
    """
    if not isinstance(body, str):
        raise InvalidDocumentError("body must be a string to parse")
    segments: list[Segment] = []
    literal: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        # Escaped brace pair -> literal braces, backslash consumed.
        if ch == "\\" and i + 2 < n and body[i + 1:i + 3] in ("{{", "}}"):
            literal.append(body[i + 1:i + 3])
            i += 3
            continue
        if ch == "{" and i + 1 < n and body[i + 1] == "{":
            close = body.find("}}", i + 2)
            if close == -1:
                raise InvalidDocumentError(
                    f"unterminated placeholder starting at offset {i}")
            name = body[i + 2:close]
            if literal:
                segments.append(Literal("".join(literal)))
                literal = []
            # Name validity is checked by the caller against the schema; the
            # parser records the raw token so an undeclared name is reported as
            # a parameter error, not silently dropped.
            segments.append(Placeholder(name))
            i = close + 2
            continue
        literal.append(ch)
        i += 1
    if literal:
        segments.append(Literal("".join(literal)))
    return ParsedBody(tuple(segments))
