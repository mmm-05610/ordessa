"""Validate published references; never infer current native runtime state."""
import json

from .client import profile_ref_valid
from .configuration import node_ref_valid
from .providers import definition_ref_valid


def _same(left, right):
    return json.dumps(left, sort_keys=True, separators=(',', ':')) == json.dumps(right, sort_keys=True, separators=(',', ':'))


def _safe(value, depth=0):
    if depth > 32:
        return False
    if isinstance(value, dict):
        denied = {'token', 'password', 'secret', 'apikey', 'authorization', 'credentials',
                  'endpoint', 'url', 'stdout', 'stderr', 'config', 'configuration', 'value', 'payload'}
        return all(key.lower().replace('_', '').replace('-', '') not in denied and _safe(item, depth + 1)
                   for key, item in value.items())
    if isinstance(value, list):
        return all(_safe(item, depth + 1) for item in value)
    return True


def _scoped(value, environment):
    return isinstance(value, dict) and len(value) >= 2 and value.get('environmentNamespace') == environment


def node_record_valid(record, environment, schema, requested=None):
    if (not isinstance(record, dict) or set(record) != set(schema['results']['nodeRecord']['required'])
            or not _safe(record) or not node_ref_valid(record['nodeRef'], environment)
            or (requested is not None and not _same(record['nodeRef'], requested))
            or type(record['publicationRevision']) is not int or record['publicationRevision'] < 1):
        return False
    binding = record['binding']
    if (not isinstance(binding, dict) or set(binding) != set(schema['results']['nodeBinding']['required'])
            or not _same(binding['nodeRef'], record['nodeRef'])
            or not _scoped(binding['harnessProviderRef'], environment)
            or not definition_ref_valid(binding['harnessDefinitionRef'], environment)
            or not profile_ref_valid(binding['profileSnapshotRef'])
            or binding['profileSnapshotRef']['environmentNamespace'] != environment
            or not _scoped(binding['preparationContextRef'], environment)
            or not isinstance(binding['operationRef'], str) or not binding['operationRef']):
        return False
    def owner(value):
        return (_scoped(value, environment) and len(value) >= 4
                and _same(value.get('ownerProviderRef'), binding['harnessProviderRef'])
                and isinstance(value.get('sourceRevision'), str) and bool(value['sourceRevision']))
    if not owner(binding['harnessUnitRef']) or not owner(binding['configurationTargetRef']):
        return False
    sessions = binding['nativeSessionRefs']
    if not isinstance(sessions, list) or len(sessions) > 1 or not all(owner(item) for item in sessions):
        return False
    lineage = record['lineage']
    if (not isinstance(lineage, dict) or set(lineage) != {'profileSnapshotRef', 'preparationContextRef'}
            or any(not _same(lineage[key], binding[key]) for key in lineage)):
        return False
    usages = record['resourceUsageRefs']
    surfaces = record['managementSurfaceRefs']
    access = record['accessSurfaceRefs']
    if (not isinstance(usages, list) or not usages or any(
            not isinstance(item, dict) or set(item) != {'environmentNamespace', 'usageId'}
            or item['environmentNamespace'] != environment or not isinstance(item['usageId'], str)
            or not item['usageId'] for item in usages)):
        return False
    if (not isinstance(surfaces, list) or not surfaces or any(
            not isinstance(item, dict) or set(item) != {'environmentNamespace', 'surfaceId', 'nodeRef'}
            or item['environmentNamespace'] != environment or item['surfaceId'] != 'pacthold.agents'
            or not _same(item['nodeRef'], record['nodeRef']) for item in surfaces)):
        return False
    return isinstance(access, list) and bool(access) and all(owner(item) for item in access)


def node_result_valid(action, result, environment, schema, requested=None):
    key = 'nodes' if action == 'list' else 'node'
    if not isinstance(result, dict) or set(result) != {key}:
        return False
    if action == 'inspect':
        return result['node'] is None or node_record_valid(result['node'], environment, schema, requested)
    if not isinstance(result['nodes'], list) or not all(node_record_valid(item, environment, schema) for item in result['nodes']):
        return False
    identities = [json.dumps(item['nodeRef'], sort_keys=True) for item in result['nodes']]
    return len(identities) == len(set(identities))
