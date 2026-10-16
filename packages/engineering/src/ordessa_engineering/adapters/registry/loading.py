"""Packaged canonical operation-registry resource and runtime loader.

The canonical resource lives at ``adapters/registry/resources/operation_registry.v1.json``
and is read via ``importlib.resources`` so the installed wheel path works too.
The loader keeps the runtime closure verification (via ``source_integrity``).
"""
from __future__ import annotations

import importlib.resources
import json
from typing import Any, Mapping

from ordessa_engineering.domain.artifacts.library_material_codec import content_digest
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from .source_integrity import REGISTRY_ID, verify_implementation


def _manifest() -> dict[str, Any]:
    try:
        resource = importlib.resources.files('ordessa_engineering').joinpath(
            'adapters', 'registry', 'resources', 'operation_registry.v1.json')
        value = json.loads(resource.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, ModuleNotFoundError) as exc:
        raise EngineeringError('operation_registry_unavailable') from exc
    if not isinstance(value, dict):
        raise EngineeringError('operation_registry_shape')
    return value


def load_registry() -> dict[str, Any]:
    """Load and verify the exact manifest and source closure before execution."""
    registry = _manifest()
    expected_keys = {'schema_version', 'registry_id', 'revision', 'operations', 'implementation', 'implementation_digest', 'registry_digest'}
    if set(registry) != expected_keys:
        raise EngineeringError('operation_registry_shape')
    unsigned = {key: value for key, value in registry.items() if key != 'registry_digest'}
    if registry['schema_version'] != 'engineering-operation-registry/1' or registry['registry_id'] != REGISTRY_ID or type(registry['revision']) is not int or (registry['revision'] < 1) or (registry['registry_digest'] != content_digest(unsigned)) or (registry['implementation_digest'] != content_digest(registry['implementation'])):
        raise EngineeringError('operation_registry_digest_mismatch')
    verify_implementation(registry)
    operations = registry['operations']
    if not isinstance(operations, Mapping) or not operations:
        raise EngineeringError('operation_registry_operations_shape')
    for name, contract in operations.items():
        if type(name) is not str or not isinstance(contract, Mapping) or set(contract) != {'version', 'inputs', 'results'} or (type(contract['version']) is not str) or (not contract['version']) or (not isinstance(contract['inputs'], Mapping)) or (not isinstance(contract['results'], list)) or any((type(item) is not str or not item for item in contract['results'])):
            raise EngineeringError('operation_registry_operation_shape')
    return registry


__all__ = ['load_registry']
