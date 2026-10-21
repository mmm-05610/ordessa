"""Harness native locators, not governance references or grants."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


class NativeRefInvalid(ValueError):
    """A native locator violates the preserved identity or metadata bounds."""


def _validate_native_locator(value) -> None:
    if not isinstance(value.provider, str) or not value.provider:
        raise NativeRefInvalid("provider and native_id are required")
    if not isinstance(value.native_id, str) or not value.native_id:
        raise NativeRefInvalid("provider and native_id are required")
    if value.uri is not None and not isinstance(value.uri, str):
        raise NativeRefInvalid("uri must be a string or None")
    try:
        metadata = dict(value.metadata)
    except (TypeError, ValueError) as error:
        raise NativeRefInvalid("metadata must be a flat string-to-string map") from error
    if len(metadata) > 16:
        raise NativeRefInvalid("metadata has more than 16 items")
    for key, item in metadata.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise NativeRefInvalid("metadata must be a flat string-to-string map")
        if len(key) > 64 or len(item) > 256:
            raise NativeRefInvalid("metadata item exceeds bounded size")
    object.__setattr__(value, "metadata", metadata)


@dataclass(frozen=True)
class NativeProfileRef:
    """Exact native Profile locator; revision/digest remain explicit metadata."""
    provider: str
    native_id: str
    uri: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_native_locator(self)


@dataclass(frozen=True)
class NativeContinuationRef:
    """A provider-owned native continuation locator, never a new session grant."""
    provider: str
    native_id: str
    uri: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_native_locator(self)


@dataclass(frozen=True)
class NativeCredentialRef:
    """A credential locator containing no credential content."""
    provider: str
    native_id: str
    uri: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_native_locator(self)
