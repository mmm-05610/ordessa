"""Validate the sealed six-field operation metadata projection.

The core guarantees the whitelist; this module only re-checks the frozen
shape before the CLI may present a read receipt. A receipt never proves
task completion: hasResult only states that a result record exists.
"""
from __future__ import annotations

import re


OPERATION_STATUSES = ('reserved', 'running', 'unknown', 'published', 'refused', 'cancelled')
METADATA_FIELDS = frozenset({'operationRef', 'kind', 'revision', 'status', 'nodeRef', 'hasResult'})


def operation_read_result_valid(result, environment_namespace, request_operation_ref):
    """True only for the exact sealed projection of the requested operation."""
    if (not isinstance(result, dict) or set(result) != METADATA_FIELDS
            or result['operationRef'] != request_operation_ref
            or result['status'] not in OPERATION_STATUSES
            or type(result['hasResult']) is not bool):
        return False
    node_ref = result['nodeRef']
    if node_ref is None:
        return True
    return (isinstance(node_ref, dict)
            and set(node_ref) == {'environmentNamespace', 'instanceId', 'generation'}
            and all(isinstance(node_ref[key], str)
                    and re.fullmatch(r'[a-z][a-z0-9._-]{0,63}', node_ref[key])
                    for key in ('environmentNamespace', 'instanceId'))
            and type(node_ref['generation']) is int and node_ref['generation'] > 0
            and node_ref['environmentNamespace'] == environment_namespace)
