"""Thin preparation request/result checks; no native plan or retry mechanism."""
import re

from .client import profile_ref_valid
from .nodes import _same, _safe, node_record_valid


def request_valid(value, environment=None):
    if (not isinstance(value, dict) or set(value) != {'requestId', 'profileRef', 'context', 'options'}
            or not isinstance(value['requestId'], str)
            or not re.fullmatch(r'[a-z][a-z0-9._-]{0,63}', value['requestId'])
            or not profile_ref_valid(value['profileRef'])
            or (environment is not None and value['profileRef']['environmentNamespace'] != environment)
            or not isinstance(value['context'], dict) or not isinstance(value['options'], dict)
            or not _safe(value)):
        return False
    denied = {'cwd', 'path', 'normalizedpath', 'executable', 'privaterootfacts',
              'argv', 'command', 'runtimeroot', 'userroot'}
    def public(item):
        if isinstance(item, dict):
            return (all(key.lower().replace('_', '').replace('-', '') not in denied and public(child)
                        for key, child in item.items())
                    and (environment is None or 'environmentNamespace' not in item
                         or item['environmentNamespace'] == environment))
        if isinstance(item, list):
            return all(public(child) for child in item)
        return True
    return public(value)


def result_valid(result, request, environment, schema):
    contract = schema['results']['preparationOperation']
    if (not isinstance(result, dict) or set(result) != set(contract['required'])
            or not isinstance(result['operationRef'], str) or not result['operationRef']
            or len(result['operationRef']) > 256
            or type(result['revision']) is not int or result['revision'] < 1
            or result['status'] not in contract['statuses'] or not _safe(result)):
        return False
    if result['status'] != 'published':
        return result['node'] is None
    node = result['node']
    return (node_record_valid(node, environment, schema)
            and node['publicationRevision'] == result['revision']
            and node['binding']['operationRef'] == result['operationRef']
            and _same(node['lineage']['profileSnapshotRef'], request['profileRef'])
            and _same(node['lineage']['preparationContextRef'].get('preparationRequest'),
                      {key: request[key] for key in ('profileRef', 'context', 'options')}))
