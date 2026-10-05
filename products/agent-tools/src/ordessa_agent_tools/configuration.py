"""Validate the public configuration observation DTOs, without native adapters."""
import re
import json
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


def change_request_valid(value, environment=None):
    if (not isinstance(value, dict) or set(value) != {'requestId', 'expectedConfigurationRevision', 'declarations', 'applicationPolicy'}
            or not _name(value['requestId']) or not _name(value['expectedConfigurationRevision'])
            or not isinstance(value['applicationPolicy'], dict) or set(value['applicationPolicy']) != {'allowDeferred', 'allowRestart'}
            or not all(type(item) is bool for item in value['applicationPolicy'].values())
            or not isinstance(value['declarations'], list) or not 1 <= len(value['declarations']) <= 256
            or not _safe_tree(value)):
        return False
    ids = []
    for item in value['declarations']:
        fields = {'declarationId', 'configurationKind', 'schemaVersion', 'action', 'requirement'}
        if (not isinstance(item, dict) or not fields <= item.keys() or item.keys() - fields - {'payload', 'resourceRefs'}
                or not all(isinstance(item[key], str) and bool(item[key]) for key in ('declarationId', 'configurationKind', 'schemaVersion'))
                or item['action'] not in ('value', 'reset', 'disabled') or item['requirement'] not in ('required', 'optional')):
            return False
        refs = item.get('resourceRefs', [])
        if not isinstance(refs, list) or any(not isinstance(ref, dict) or len(ref) < 2 or not _name(ref.get('environmentNamespace')) for ref in refs):
            return False
        if environment is not None and any(ref['environmentNamespace'] != environment for ref in refs):
            return False
        if item['action'] != 'value' and ('payload' in item or refs):
            return False
        if item['action'] == 'value' and 'payload' not in item and not refs:
            return False
        ids.append(item['declarationId'])
    return len(ids) == len(set(ids))


def operation_result_valid(value, environment, requested_operation=None, change=None):
    if (not isinstance(value, dict) or set(value) != {'operationRef', 'revision', 'status', 'configurationResult'}
            or not _name(value['operationRef']) or type(value['revision']) is not int or value['revision'] < 1
            or value['status'] not in ('reserved', 'running', 'unknown', 'published', 'refused', 'cancelled')
            or (requested_operation is not None and value['operationRef'] != requested_operation)):
        return False
    result = value['configurationResult']
    if result is None:
        return value['status'] != 'published'
    if (not isinstance(result, dict) or set(result) != {'operationRef', 'overallOutcome', 'itemResults', 'confirmedSnapshot'}
            or result['operationRef'] != value['operationRef'] or not isinstance(result['itemResults'], list) or not result['itemResults']):
        return False
    snapshot = result['confirmedSnapshot']
    if snapshot is not None and not snapshot_result_valid(snapshot, environment):
        return False
    ids, outcomes = [], []
    for item in result['itemResults']:
        if (not isinstance(item, dict) or set(item) != {'declarationId', 'outcome', 'confirmation'} or not _name(item['declarationId'])
                or item['outcome'] not in ('applied', 'deferred', 'restartRequired', 'rejected', 'conflict', 'unknown')):
            return False
        confirmation = item['confirmation']
        if item['outcome'] == 'applied' and confirmation is None:
            return False
        if confirmation is not None:
            if (not isinstance(confirmation, dict) or set(confirmation) != {'operationRef', 'unitRef', 'scopeRef', 'requestDigest', 'evidenceRef'}
                    or confirmation['operationRef'] != value['operationRef'] or not _name(confirmation['requestDigest'])
                    or not all(_scoped_ref(confirmation[key], environment) for key in ('unitRef', 'scopeRef', 'evidenceRef'))):
                return False
            if item['outcome'] == 'applied' and snapshot is not None and any(json.dumps(confirmation[key], sort_keys=True, separators=(',', ':')) != json.dumps(snapshot[key], sort_keys=True, separators=(',', ':')) for key in ('unitRef', 'scopeRef')):
                return False
        ids.append(item['declarationId']); outcomes.append(item['outcome'])
    if len(ids) != len(set(ids)):
        return False
    if change is not None:
        if set(ids) != {item['declarationId'] for item in change['declarations']}:
            return False
        if 'deferred' in outcomes and not change['applicationPolicy']['allowDeferred']:
            return False
    overall = outcomes[0] if len(set(outcomes)) == 1 else 'partial'
    return result['overallOutcome'] == overall and not (value['status'] == 'published' and any(item in ('unknown', 'deferred') for item in outcomes))


def operation_disposition(value):
    """Envelope status/exit describes observed outcome, never native readiness."""
    result = value['configurationResult']
    overall = result['overallOutcome'] if result is not None else None
    if overall == 'partial':
        return 'partial', 6, 'CONFIGURATION_PARTIAL'
    if value['status'] in ('unknown', 'running') or overall == 'unknown':
        return 'unknown', 6, 'OUTCOME_UNKNOWN'
    if value['status'] in ('refused', 'cancelled') or overall in ('rejected', 'conflict'):
        return 'refused', 5 if overall == 'conflict' else 4, 'PRECONDITION_CONFLICT' if overall == 'conflict' else 'CONFIGURATION_REFUSED'
    if value['status'] == 'reserved' or overall in ('deferred', 'restartRequired'):
        return 'pending', 0, None
    return 'confirmed', 0, None
