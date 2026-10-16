"""Explicit Python entry-point discovery and metadata, without admission policy.

Import performs no discovery or loading. Enumeration preserves metadata's order
and duplicates; callers own selection and sorting. Loading imports executable
Python code, so the caller must authorize it before calling load_entry_point.
The loaded object is returned unchanged, never invoked or validated here.

Source facts are metadata observations, not proof of the loaded module's origin
or trust. No provider descriptor, factory, registry, context or activation lives
in this module. Python >=3.12 is the distribution's existing runtime boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata

__all__ = [
    "EntryPointSource",
    "enumerate_entry_points",
    "entry_point_source",
    "load_entry_point",
]


@dataclass(frozen=True)
class EntryPointSource:
    """Optional source metadata; errors never imply admission or rejection.

    group/name/value identify the declared entry point. Distribution name and
    version describe its attached distribution, not the object imported under
    the current sys.path. Missing attributes stay None. Failed or non-text
    attributes stay None and are identified in metadata_errors; independent
    available fields are retained. Error strings contain field and error type,
    without invoking arbitrary exception formatting.
    """

    group: str | None
    name: str | None
    value: str | None
    distribution_name: str | None = None
    distribution_version: str | None = None
    metadata_errors: tuple[str, ...] = ()


def enumerate_entry_points(group: str) -> tuple[metadata.EntryPoint, ...]:
    """Enumerate exactly group, without loading, normalizing or sorting it.

    Metadata discovery exceptions propagate unchanged. The caller may supply
    already-selected entry points to its own loader instead of enumerating.
    """
    if not isinstance(group, str):
        raise TypeError("entry-point group must be a string")
    if not group:
        raise ValueError("entry-point group must be non-empty")
    return tuple(metadata.entry_points().select(group=group))


def _optional_text(owner, attribute: str, label: str, errors: list[str]) -> str | None:
    try:
        value = getattr(owner, attribute, None)
    except Exception as exc:
        errors.append(f"{label}: {type(exc).__name__}")
        return None
    if value is None or isinstance(value, str):
        return value
    errors.append(f"{label}: TypeError")
    return None


def entry_point_source(entry_point: metadata.EntryPoint) -> EntryPointSource:
    """Observe one entry point's optional metadata without loading its target."""
    errors: list[str] = []
    group = _optional_text(entry_point, "group", "group", errors)
    name = _optional_text(entry_point, "name", "name", errors)
    value = _optional_text(entry_point, "value", "value", errors)
    try:
        distribution = getattr(entry_point, "dist", None)
    except Exception as exc:
        errors.append(f"distribution: {type(exc).__name__}")
        distribution = None
    distribution_name = _optional_text(distribution, "name", "distribution_name", errors)
    distribution_version = _optional_text(distribution, "version", "distribution_version", errors)
    return EntryPointSource(
        group, name, value, distribution_name, distribution_version, tuple(errors)
    )


def load_entry_point(entry_point: metadata.EntryPoint) -> object:
    """Explicitly load once, return unchanged; native errors propagate.

    This does not call factories, descriptor/build methods or provider runtime,
    and neither enumerates nor retries an alternative entry point on failure.
    """
    return entry_point.load()
