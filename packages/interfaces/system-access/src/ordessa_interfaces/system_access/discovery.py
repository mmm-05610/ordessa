"""Allowlisted capability discovery from the ``ordessa.capabilities`` group.

Only entry points named in the explicit allowlist are imported. Each must
export ``factory`` with a callable ``build(bindings)``. The loader creates no
import-time effects: importing the module is the only import, and ``build`` is
called explicitly with trusted, process-local bindings.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib import metadata as importlib_metadata
from types import MappingProxyType

from ordessa_interfaces_contracts import (
    CAPABILITY_ENTRY_POINT_GROUP, CAPABILITY_FACTORY_ATTR, Capability,
    ContractError, validate_capability,
)


class DiscoveryError(ContractError):
    """A capability entry point cannot be loaded under the allowlist."""


def validate_bindings(bindings: Mapping[str, object]) -> Mapping[str, object]:
    """Every factory receives trusted bindings with the fixed contract keys."""
    if not isinstance(bindings, Mapping):
        raise DiscoveryError('INVALID_INPUT', 'bindings must be a mapping of process-local objects')
    for key in ('services', 'invocation_resolver'):
        if key not in bindings or bindings[key] is None:
            raise DiscoveryError('AUTHORITY_UNAVAILABLE', f'binding is missing: {key}')
    return MappingProxyType(dict(bindings))


def _entry_points(entry_points) -> tuple:
    if entry_points is None:
        found = importlib_metadata.entry_points()
        if hasattr(found, 'select'):
            return tuple(found.select(group=CAPABILITY_ENTRY_POINT_GROUP))
        return tuple(found.get(CAPABILITY_ENTRY_POINT_GROUP, ()))
    return tuple(entry_points)


def load_capabilities(allowlist: Iterable[str], bindings: Mapping[str, object],
                      *, entry_points=None) -> tuple[Capability, ...]:
    """Load exactly the allowlisted factories; any unknown name refuses."""
    names = tuple(allowlist)
    if not names or any(type(name) is not str or not name for name in names):
        raise DiscoveryError('INVALID_INPUT', 'allowlist must name at least one capability entry point')
    if len(set(names)) != len(names):
        raise DiscoveryError('INVALID_INPUT', 'allowlist names repeat')
    trusted = validate_bindings(bindings)
    available = {entry.name: entry for entry in _entry_points(entry_points)}
    unknown = [name for name in names if name not in available]
    if unknown:
        raise DiscoveryError('CAPABILITY_UNSUPPORTED',
                             'capability entry point is not installed: ' + ', '.join(sorted(unknown)))
    built: list[Capability] = []
    for name in names:
        entry = available[name]
        try:
            factory = _load_factory(entry)
        except ContractError:
            raise
        except Exception as error:  # import failure is an explicit unavailable
            raise DiscoveryError('CAPABILITY_UNSUPPORTED',
                                 f'capability factory cannot be imported: {name}') from error
        build = getattr(factory, 'build', None)
        if not callable(build):
            raise DiscoveryError('INVALID_INPUT', f'factory has no build(bindings): {name}')
        try:
            capability = build(trusted)
        except ContractError:
            raise
        except Exception as error:
            raise DiscoveryError('CAPABILITY_UNSUPPORTED',
                                 f'capability factory refused to build: {name}') from error
        validate_capability(capability)
        built.append(capability)
    return tuple(built)


def _load_factory(entry):
    module = getattr(entry, 'module', None)
    attribute = getattr(entry, 'attr', None)
    if module is not None and attribute is not None:
        loaded = __import__(module, fromlist=[attribute])
        factory = getattr(loaded, attribute)
    else:
        factory = entry.load()[CAPABILITY_FACTORY_ATTR]
    return factory


__all__ = ['DiscoveryError', 'validate_bindings', 'load_capabilities']
