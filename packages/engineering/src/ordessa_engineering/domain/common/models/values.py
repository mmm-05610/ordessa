"""Foundational IDs, digests, times, paths and value rules; no resolution or authority."""
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Literal, NewType
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)

# Static distinctions retain the existing string wire and persisted identities.
RealmId = NewType("RealmId", str)
ProjectId = NewType("ProjectId", str)
ActorId = NewType("ActorId", str)
RelativePath = NewType("RelativePath", str)
UtcInstant = NewType("UtcInstant", str)

def validate_id(value: str) -> None:
    """Validate an opaque ID without Unicode normalization or resolution."""
    if type(value) is not str or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ReferenceError("INVALID_SCHEMA")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ReferenceError("INVALID_SCHEMA") from None


@dataclass(frozen=True)
class Digest:
    algorithm: Literal["sha256"]
    hex: str

    def __post_init__(self):
        if self.algorithm != "sha256" or type(self.hex) is not str or not re.fullmatch(r"[0-9a-f]{64}", self.hex):
            raise ReferenceError("INVALID_SCHEMA")


def utc_instant(value: str) -> None:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value):
        raise ReferenceError("INVALID_TIME")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        raise ReferenceError("INVALID_TIME") from None


MAX_VERSION = (1 << 53) - 1

def validate_version(value, *, positive=False):
    if type(value) is not int or not (1 if positive else 0) <= value <= MAX_VERSION:
        raise ReferenceError("INVALID_VERSION")


def validate_text(value):
    if type(value) is not str or not value or len(value) > 16384 or "\x00" in value:
        raise ReferenceError("INVALID_SCHEMA")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ReferenceError("INVALID_SCHEMA") from None


def normalized_path(value: RelativePath) -> None:
    """Require an already normalized relative path; never rewrite user bytes."""
    validate_id(value)
    if (value.startswith('/') or '\\' in value or ':' in value
            or any(part in {'', '.', '..'} for part in value.split('/'))):
        raise ReferenceError('INVALID_PATH')


def validate_items(value, kind, *, nonempty=False):
    if (type(value) is not tuple or len(value) > 4096 or (nonempty and not value)
            or any(type(item) is not kind for item in value)):
        raise ReferenceError("INVALID_SCHEMA")


def ordered_unique(value, key, *, code):
    keys = [key(item) for item in value]
    if len(keys) != len(set(keys)):
        raise ReferenceError(code)
    return tuple(item for _, item in sorted(zip(keys, value), key=lambda row: row[0]))
