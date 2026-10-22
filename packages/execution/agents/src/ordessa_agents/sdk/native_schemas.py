"""Data-only JSON Schema for the ``agent-native/1`` public envelopes.

The typed values in ``native_envelope`` (and the provider codecs) remain the
authority; these schemas are the published shape for discovery and negative
conformance checks. They describe envelopes only: the provider-shaped
``nativeMessage``/``response`` payloads are open objects whose unknown fields
must be preserved.
"""
from copy import deepcopy

TEXT = {'type': 'string', 'minLength': 1, 'maxLength': 512}
DIGEST = {'type': 'string', 'pattern': '^sha256:[0-9a-f]{64}$'}
OPEN = {'type': 'object'}
NULLABLE_DIGEST = {'anyOf': [DIGEST, {'type': 'null'}]}
CURSOR = {'type': ['string', 'null'], 'pattern': '^s[0-9]{1,18}$'}

KINDS = ('DescribeRequest', 'RequestSubmit', 'NotifySubmit', 'QueryRequest',
         'EventsRequest', 'RespondRequest', 'Description', 'Acceptance',
         'Observation', 'Event', 'EventPage', 'Reply')

DEFS = {
    'Instance': {'type': 'object', 'required': ['schemaVersion', 'namespace', 'instanceId'],
                 'properties': {'schemaVersion': {'const': 'agent-instance/1'},
                                'namespace': TEXT, 'instanceId': TEXT, 'bindingDigest': DIGEST},
                 'additionalProperties': True},
    'OperationRef': {'type': 'object',
                     'required': ['schemaVersion', 'instanceRef', 'requestKey'],
                     'properties': {'schemaVersion': {'const': 'agent-native-operation-ref/2'},
                                    'instanceRef': {'$ref': '#/$defs/Instance'},
                                    'requestKey': DIGEST},
                     'additionalProperties': False},
    'PendingRequestRef': {'type': 'object',
                          'required': ['schemaVersion', 'instanceRef', 'connectionGeneration',
                                       'nativeRequestId', 'protocolId'],
                          'properties': {'schemaVersion': {'const': 'agent-native-pending-ref/1'},
                                         'instanceRef': {'$ref': '#/$defs/Instance'},
                                         'connectionGeneration': {'type': 'integer', 'minimum': 0},
                                         'nativeRequestId': TEXT, 'protocolId': TEXT},
                          'additionalProperties': False},
    'DescribeRequest': {'type': 'object', 'required': ['instanceRef'],
                        'properties': {'instanceRef': {'$ref': '#/$defs/Instance'}},
                        'additionalProperties': False},
    'RequestSubmit': {'type': 'object', 'required': ['instanceRef', 'requestId', 'nativeMessage'],
                      'properties': {'instanceRef': {'$ref': '#/$defs/Instance'},
                                     'requestId': TEXT, 'nativeMessage': OPEN},
                      'additionalProperties': False},
    'NotifySubmit': {'type': 'object', 'required': ['instanceRef', 'requestId', 'nativeMessage'],
                     'properties': {'instanceRef': {'$ref': '#/$defs/Instance'},
                                    'requestId': TEXT, 'nativeMessage': OPEN},
                     'additionalProperties': False},
    'QueryRequest': {'type': 'object', 'required': ['operationRef'],
                     'properties': {'operationRef': {'$ref': '#/$defs/OperationRef'},
                                    'expectedInputDigest': NULLABLE_DIGEST},
                     'additionalProperties': False},
    'EventsRequest': {'type': 'object', 'required': ['instanceRef'],
                      'properties': {'instanceRef': {'$ref': '#/$defs/Instance'},
                                     'cursor': CURSOR,
                                     'limit': {'anyOf': [{'type': 'integer', 'minimum': 1,
                                                          'maximum': 256}, {'type': 'null'}]}},
                      'additionalProperties': False},
    'RespondRequest': {'type': 'object',
                       'required': ['pendingRequestRef', 'requestId', 'response'],
                       'properties': {'pendingRequestRef': {'$ref': '#/$defs/PendingRequestRef'},
                                      'requestId': TEXT, 'response': OPEN},
                       'additionalProperties': False},
    'Description': {'type': 'object',
                    'required': ['schemaVersion', 'instanceRef', 'protocolId',
                                 'protocolVersion', 'sessionId', 'categories',
                                 'availability', 'reason'],
                    'properties': {'schemaVersion': {'const': 'agent-native-description/1'},
                                   'instanceRef': {'$ref': '#/$defs/Instance'},
                                   'protocolId': TEXT,
                                   'protocolVersion': {'type': 'integer', 'minimum': 0},
                                   'sessionId': {'anyOf': [TEXT, {'type': 'null'}]},
                                   'categories': {'type': 'object'},
                                   'availability': {'enum': ['available', 'unavailable']},
                                   'reason': {'anyOf': [TEXT, {'type': 'null'}]}},
                    'additionalProperties': False},
    'Acceptance': {'type': 'object',
                   'required': ['schemaVersion', 'operationRef', 'kind', 'state',
                                'inputDigest', 'acceptedAt'],
                   'properties': {'schemaVersion': {'const': 'agent-native-acceptance/1'},
                                  'operationRef': {'$ref': '#/$defs/OperationRef'},
                                  'kind': {'enum': ['request', 'notify']},
                                  'state': {'enum': ['accepted', 'sent', 'completed', 'failed',
                                                     'cancelled', 'refused', 'unknown']},
                                  'inputDigest': DIGEST, 'acceptedAt': TEXT},
                   'additionalProperties': False},
    'Observation': {'type': 'object',
                    'required': ['schemaVersion', 'operationRef', 'kind', 'state',
                                 'protocolId', 'sessionId', 'inputDigest',
                                 'acceptedAt', 'updatedAt'],
                    'properties': {'schemaVersion': {'const': 'agent-native-observation/1'},
                                   'operationRef': {'$ref': '#/$defs/OperationRef'},
                                   'kind': {'enum': ['request', 'notify']},
                                   'state': {'enum': ['accepted', 'sent', 'completed', 'failed',
                                                      'cancelled', 'refused', 'unknown']},
                                   'protocolId': TEXT, 'sessionId': TEXT,
                                   'inputDigest': DIGEST, 'acceptedAt': TEXT, 'updatedAt': TEXT,
                                   'response': OPEN, 'error': OPEN, 'delivery': OPEN},
                    'additionalProperties': False},
    'Event': {'type': 'object',
              'required': ['schemaVersion', 'seq', 'kind', 'payload', 'payloadDigest',
                           'operationRef', 'observedAt'],
              'properties': {'schemaVersion': {'const': 'agent-native-event/1'},
                             'seq': {'type': 'integer', 'minimum': 1},
                             'kind': {'enum': ['response', 'notification', 'reverse_request',
                                               'lifecycle', 'oversize', 'gap', 'malformed']},
                             'payload': OPEN, 'payloadDigest': DIGEST,
                             'operationRef': {'anyOf': [{'$ref': '#/$defs/OperationRef'},
                                                        {'type': 'null'}]},
                             'observedAt': TEXT},
              'additionalProperties': False},
    'EventPage': {'type': 'object',
                  'required': ['schemaVersion', 'instanceRef', 'events', 'nextCursor',
                               'hasMore', 'completeness'],
                  'properties': {'schemaVersion': {'const': 'agent-native-event-page/1'},
                                 'instanceRef': {'$ref': '#/$defs/Instance'},
                                 'events': {'type': 'array', 'maxItems': 256,
                                            'items': {'$ref': '#/$defs/Event'}},
                                 'nextCursor': CURSOR, 'hasMore': {'type': 'boolean'},
                                 'completeness': {'type': 'object'}},
                  'additionalProperties': False},
    'Reply': {'type': 'object',
              'required': ['schemaVersion', 'pendingRequestRef', 'state', 'inputDigest',
                           'acceptedAt'],
              'properties': {'schemaVersion': {'const': 'agent-native-reply/1'},
                             'pendingRequestRef': {'$ref': '#/$defs/PendingRequestRef'},
                             'state': {'enum': ['accepted', 'sent', 'refused', 'unknown']},
                             'inputDigest': DIGEST, 'acceptedAt': TEXT},
              'additionalProperties': False},
}


def native_schema(kind='Observation'):
    if kind not in KINDS:
        raise ValueError('unknown native envelope')
    return deepcopy({'$schema': 'https://json-schema.org/draft/2020-12/schema',
                     '$id': 'urn:ordessa:agent-native-envelope:1',
                     '$ref': '#/$defs/' + kind, '$defs': DEFS})


__all__ = ['KINDS', 'DEFS', 'native_schema']
