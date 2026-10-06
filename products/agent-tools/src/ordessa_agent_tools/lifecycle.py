"""Validate the frozen Node lifecycle request and receipt DTOs.

The wire methods agents.nodes.stop/release/recover take a fixed request
(requestId, complete NodeRef, whitelisted preconditions) and return the
original lifecycleOperation projection. agents.nodes.applyProfile takes
requestId/profileRef/expectedConfigurationRevision/applicationPolicy; its
declarations are derived by the core from the referenced Profile, never
carried in the request body. Nothing here observes native runtime state and
no unknown receipt is promoted to an operation identity.
"""
from .client import profile_ref_valid
from .configuration import node_ref_valid, _name
from .nodes import _safe
from .preparation import request_id_valid

ACTIONS = ('stop', 'release', 'recover')
_PRECONDITION_KEYS = frozenset({'expectedPublicationRevision'})


def preconditions_valid(value):
    """Only whitelisted precondition keys are understood; values are checked types."""
    if not isinstance(value, dict) or not set(value) <= _PRECONDITION_KEYS:
        return False
    if 'expectedPublicationRevision' not in value:
        return True
    return type(value['expectedPublicationRevision']) is int and value['expectedPublicationRevision'] >= 1


def request_valid(value, environment=None):
    """Complete fixed stop/release/recover request file."""
    if (not isinstance(value, dict) or set(value) != {'requestId', 'nodeRef', 'preconditions'}
            or not request_id_valid(value['requestId'])
            or not node_ref_valid(value['nodeRef'])
            or (environment is not None and value['nodeRef']['environmentNamespace'] != environment)
            or not preconditions_valid(value['preconditions'])
            or not _safe(value)):
        return False
    return True


def application_request_valid(value, environment=None):
    """Complete fixed applyProfile request file (no declarations in the body)."""
    if (not isinstance(value, dict) or set(value) != {'requestId', 'profileRef', 'expectedConfigurationRevision', 'applicationPolicy'}
            or not request_id_valid(value['requestId'])
            or not profile_ref_valid(value['profileRef'])
            or (environment is not None and value['profileRef']['environmentNamespace'] != environment)
            or not _name(value['expectedConfigurationRevision'])
            or not _policy_valid(value['applicationPolicy'])
            or not _safe(value)):
        return False
    return True


def _policy_valid(value):
    return (isinstance(value, dict) and set(value) == {'allowDeferred', 'allowRestart'}
            and type(value['allowDeferred']) is bool and type(value['allowRestart']) is bool)


def view_valid(value, action, schema):
    """The original lifecycleOperation projection; unknown extras never pass."""
    contract = schema['results']['lifecycleOperation']
    if (not isinstance(value, dict) or set(value) - {'node'} != set(contract['required'])
            or not isinstance(value['operationRef'], str) or not value['operationRef']
            or len(value['operationRef']) > 256
            or type(value['revision']) is not int or value['revision'] < 1
            or value['status'] not in contract['statuses']
            or value['action'] != action
            or ('node' in value and value['node'] is not None)
            or not _safe(value)):
        return False
    return True


def disposition(value):
    """Envelope status/exit describes the observed receipt, never native readiness.

    The core leaves a lifecycle operation at 'running' once its single step
    concluded; 'reserved' or 'unknown' cannot confirm any effect.
    """
    if value['status'] in ('running', 'published'):
        return 'confirmed', 0, None
    if value['status'] in ('refused', 'cancelled'):
        return 'refused', 4, 'LIFECYCLE_REFUSED'
    return 'unknown', 6, 'OUTCOME_UNKNOWN'
