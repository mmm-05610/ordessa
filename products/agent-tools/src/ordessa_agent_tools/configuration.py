"""Validate the public configuration description DTO, without native adapters."""
import re


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
