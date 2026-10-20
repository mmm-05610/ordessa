"""Declarative display projections; the host never inspects domain types.

``render.kind`` is ``json`` (default), ``table``, ``fields`` or ``process``.
``fields`` names result keys; ``process`` names JSON paths for exit/stdout/
stderr. Unknown hints refuse instead of guessing.
"""
from __future__ import annotations

from collections.abc import Mapping

from ordessa_interfaces_contracts import ContractError


def _path(data, dotted: str):
    value = data
    for segment in dotted.split('.'):
        if not isinstance(value, Mapping) or segment not in value:
            return None
        value = value[segment]
    return value


def project(descriptor, data):
    """Project ``data`` according to the operation's declarative render hint."""
    render = None if descriptor.cli is None else descriptor.cli.get('render')
    if render is None:
        return data
    kind = render.get('kind')
    if kind == 'json':
        return data
    if kind == 'table':
        if isinstance(data, Mapping):
            data = data.get('rows', data.get('items', data))
        if not isinstance(data, (list, tuple)):
            raise ContractError('INVALID_INPUT', 'table projection requires a list result')
        return [dict(row) if isinstance(row, Mapping) else row for row in data]
    if kind == 'fields':
        if not isinstance(data, Mapping):
            raise ContractError('INVALID_INPUT', 'fields projection requires an object result')
        return {field: _path(data, field) for field in render.get('fields', ())}
    if kind == 'process':
        if not isinstance(data, Mapping):
            raise ContractError('INVALID_INPUT', 'process projection requires an object result')
        paths = render.get('paths')
        if isinstance(paths, Mapping):
            return {name: _path(data, path) for name, path in paths.items()}
        if isinstance(paths, (list, tuple)) and paths and all(
                type(item) is str and item for item in paths):
            return {name: _path(data, name) for name in paths}
        raise ContractError('INVALID_INPUT', 'process projection requires named JSON paths')
    raise ContractError('INVALID_INPUT', f'unsupported render kind: {kind}')


__all__ = ['project']
