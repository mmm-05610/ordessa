"""Content digests: single-file addressing with a frozen normalization.

The domain borrows the content-address *pattern* from
``plugins/server-compat/.../assets/records.py`` (a ``sha256:`` prefix, digest
required before a revision is publishable) but never the Skill asset kind or its
tree store. Standard library only (research-and-reuse.md).
"""
from __future__ import annotations

import hashlib
import json
from typing import Sequence

from ..api import schema
from ..api.dto import ParameterSpec


def body_digest(body: str) -> str:
    """Digest of the normalized body bytes (NFC, LF) — the visible text."""
    normalized = schema.normalize_body(body)
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _canonical_parameters(parameters: Sequence[ParameterSpec]) -> list[dict[str, object]]:
    """A stable, key-sorted projection of the parameter schema for hashing."""
    projected: list[dict[str, object]] = []
    for spec in sorted(parameters, key=lambda s: s.name):
        entry: dict[str, object] = {
            "name": spec.name,
            "kind": spec.kind,
            "required": spec.required,
        }
        if spec.default is not None:
            entry["default"] = spec.default
        if spec.max_length is not None:
            entry["max_length"] = spec.max_length
        if spec.minimum is not None:
            entry["minimum"] = spec.minimum
        if spec.maximum is not None:
            entry["maximum"] = spec.maximum
        if spec.choices is not None:
            entry["choices"] = list(spec.choices)
        projected.append(entry)
    return projected


def revision_digest(body: str, parameters: Sequence[ParameterSpec]) -> str:
    """Digest binding the normalized body *and* the canonical schema (FR-01)."""
    payload = json.dumps(
        {"body": schema.normalize_body(body), "parameters": _canonical_parameters(parameters)},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def arguments_digest(values: "dict[str, object]") -> str:
    """Digest of the supplied arguments — stored on a receipt, never the values.

    Values are normalized the same way the renderer treats them so the digest
    is reproducible, but the digest is the only thing that leaves the domain.
    """
    canonical = json.dumps(
        {k: _stable(v) for k, v in sorted(values.items())},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _stable(value: object) -> object:
    if hasattr(value, "stable_id"):  # a resolved ProjectRef — hash identity only
        return {"ref": str(value.stable_id)}
    return value


def rendered_digest(rendered: str) -> str:
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()
