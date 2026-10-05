"""Validate the public configuration observation DTOs, without native adapters."""
import re
from datetime import datetime


def node_ref_valid(value, environment=None):
    return (isinstance(value, dict) and set(value) == {'environmentNamespace', 'instanceId', 'generation'}
            and all(isinstance(value[key], str) and re.fullmatch(r'[a-z][a-z0-9._-]{0,63}', value[key])
                    for key in ('environmentNamespace', 'instanceId'))
            and type(value['generation']) is int and value['generation'] > 0
            and (environment is None or value['environmentNamespace'] == environment))


def _name(value):
    return (isinstance(value, str) and bool(value) and value.strip() == value and len(value) <= 256
            and not any(ord(c) < 32 for c in value))


def _enum_list(value, choices):
    return (isinstance(value, list) and all(isinstance(item, str) and item in choices for item in value)
            and len(value) == len(set(value)))


def description_result_valid(result):
    if not isinstance(result, dict) or set(result) != {'descriptions'} or not isinstance(result['descriptions'], list):
        return False
    identities = []
    for item in result['descriptions']:
        if (not isinstance(item, dict) or set(item) != {'configurationKind', 'schemaVersion', 'inputSchema',
                'supportedActions', 'scope', 'applicationModes', 'confirmation', 'supportStatus'}
                or not _name(item['configurationKind']) or not _name(item['schemaVersion'])
                or not isinstance(item['inputSchema'], dict)
                or not _enum_list(item['supportedActions'], {'value', 'reset', 'disabled'})
                or not _enum_list(item['applicationModes'], {'live', 'deferred', 'restart'})
                or item['scope'] not in ('instance', 'session', 'nextInput', None)
                or item['confirmation'] not in ('readback', 'operationReceipt', 'none')
                or item['supportStatus'] not in ('supported', 'unsupported', 'unknown')):
            return False
        if item['supportStatus'] == 'supported' and (not item['supportedActions'] or not item['applicationModes'] or item['scope'] is None):
            return False
        identities.append((item['configurationKind'], item['schemaVersion']))
    return len(identities) == len(set(identities))


def _secret_ref_valid(value):
    if not isinstance(value, dict) or set(value) != {'ref', 'revision', 'owner_namespace', 'access_purpose'}:
        return False
    patterns = {'ref': r'[A-Za-z0-9][A-Za-z0-9._:-]{0,191}',
                'revision': r'[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}',
                'owner_namespace': r'[a-z][a-z0-9._-]{0,95}',
                'access_purpose': r'[a-z][a-z0-9._-]{0,95}'}
    return all(isinstance(value[key], str) and re.fullmatch(pattern, value[key]) for key, pattern in patterns.items())


def _safe_tree(value, depth=0):
    if depth > 32:
        return False
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'secretRef' and not _secret_ref_valid(item):
                return False
            if key.lower().replace('_', '').replace('-', '') in {
                'token', 'accesstoken', 'apikey', 'password', 'secret', 'privatekey', 'authorization', 'credential', 'credentials'} and item is not None:
                if not isinstance(item, dict) or set(item) != {'secretRef'} or not _secret_ref_valid(item['secretRef']):
                    return False
            if not _safe_tree(item, depth + 1):
                return False
    elif isinstance(value, list):
        return all(_safe_tree(item, depth + 1) for item in value)
    return True


def _scoped_ref(value, environment):
    # Owner leaf schemas stay opaque. Environment and credential shape alone
    # do not grant authority or prove native owner identity.
    return (isinstance(value, dict) and len(value) >= 2
            and value.get('environmentNamespace') == environment and _safe_tree(value))


def snapshot_result_valid(result, environment):
    fields = {'unitRef', 'scopeRef', 'sourceRevision', 'observedAt', 'configuration',
              'unknownItems', 'confirmationEvidence', 'comparisonGuarantee'}
    if not isinstance(result, dict) or set(result) != fields:
        return False
    if (not all(_scoped_ref(result[key], environment) for key in ('unitRef', 'scopeRef', 'confirmationEvidence'))
            or not isinstance(result['configuration'], dict) or not _safe_tree(result['configuration'])
            or any(key in result['configuration'] for key in ('desired', 'pending'))
            or not isinstance(result['unknownItems'], list) or not all(_name(item) for item in result['unknownItems'])
            or len(result['unknownItems']) != len(set(result['unknownItems']))
            or any(item in result['configuration'] for item in result['unknownItems'])
            or result['comparisonGuarantee'] not in ('nativeAtomic', 'ownerSerialized', 'unavailable')
            or (result['sourceRevision'] is not None and not _name(result['sourceRevision']))
            or (result['sourceRevision'] is None and result['comparisonGuarantee'] != 'unavailable')
            or not _name(result['observedAt'])):
        return False
    try:
        return datetime.fromisoformat(result['observedAt'].replace('Z', '+00:00')).tzinfo is not None
    except ValueError:
        return False
