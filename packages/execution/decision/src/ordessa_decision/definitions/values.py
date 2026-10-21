"""Canonical finite-JSON helpers shared by the decision definitions."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

MAX_VALUE_BYTES = 512 * 1024
MAX_JOB_DOCUMENT_BYTES = 8 * (512 * 1024) + 65536


def job_document_bound(value=None):
    """Explicit host document allocation; unrelated to model/output budgets."""
    if value is None:
        return MAX_VALUE_BYTES
    if type(value) is not int or not 0 < value <= MAX_JOB_DOCUMENT_BYTES:
        raise DecisionError("invalid_job_document_limit")
    return value
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class DecisionError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and _ID.fullmatch(code) else "invalid_error_code"
        super().__init__(self.code)


def name(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise DecisionError("invalid_identifier")
    return value


def plain(value, *, depth: int = 0):
    if depth > 32:
        raise DecisionError("value_too_deep")
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise DecisionError("nonfinite_number")
        return value
    if isinstance(value, Mapping):
        out = {}
        for key, item in value.items():
            if type(key) is not str:
                raise DecisionError("nonstring_key")
            out[key] = plain(item, depth=depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [plain(item, depth=depth + 1) for item in value]
    raise DecisionError("non_json_value")


def canonical_bytes(value, *, maximum: int = MAX_VALUE_BYTES) -> bytes:
    body = json.dumps(plain(value), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(body) > maximum:
        raise DecisionError("value_too_large")
    return body


def decode_json(raw: bytes):
    try:
        value = json.loads(raw.decode("utf-8"), parse_constant=_reject)
    except (UnicodeDecodeError, ValueError) as exc:
        raise DecisionError("invalid_json") from exc
    if canonical_bytes(value) != raw:
        raise DecisionError("noncanonical_json")
    return value


def digest_hex(value, *, maximum: int = MAX_VALUE_BYTES):
    return hashlib.sha256(canonical_bytes(value, maximum=maximum)).hexdigest()


def _reject(text):
    raise DecisionError("nonfinite_number")


class ContractError(DecisionError):
    """Legacy-name refusal used by the decision provider adapters."""


def canonical(value, *, max_string=65536, max_bytes=262144):
    return canonical_bytes(value, maximum=max_bytes)


def decode(data, *, max_bytes=262144):
    if type(data) is not bytes:
        raise ContractError("json_invalid")
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_constant=_reject)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ContractError("json_invalid") from exc
    if canonical_bytes(value, maximum=max_bytes) != data:
        raise ContractError("json_invalid")
    return value


def _pairs(items):
    out = {}
    for key, value in items:
        if key in out:
            raise ContractError("duplicate_key")
        out[key] = value
    return out


def digest(domain, value, *, max_string=65536, max_bytes=2097152):
    if domain not in {"descriptor", "question", "answer", "policy", "event", "feedback"}:
        raise ContractError("digest_domain")
    body = canonical_bytes({"domain": domain, "value": plain(value)}, maximum=max_bytes)
    return "sha256:" + hashlib.sha256(body).hexdigest()


def revision(value):
    if value is not None:
        name(value)
    return value
