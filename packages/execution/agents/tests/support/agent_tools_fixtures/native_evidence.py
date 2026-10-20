"""Controlled evidence owners shared by Agents tests and provider tests. No SDK or process IO."""
from __future__ import annotations

import json
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.records.unit_records import (
    INPUT_SESSION_ASSOCIATION_VERSION, UNIT_CONFIRMATION_VERSION, UnitRecordsRefused,
)
from agent_tools_fixtures.unit_records import ROOT


def source(unit, name):
    return {'environmentNamespace': 'env', 'ownerProviderRef': unit.facts['providerRef'],
            'sourceRevision': 'controlled-source-1', 'ref': name}


class UnitEvidence:
    valid = True
    damage = None

    def verify_unit_binding(self, unit, correlation, evidence):
        if not self.valid or evidence != self.reference(unit, 'receipt'):
            raise UnitRecordsRefused('original process/pipe proof unavailable')
        assert unit.facts['privateRootFacts'] == ROOT
        proof = {'contractVersion': UNIT_CONFIRMATION_VERSION, 'unitRef': dict(unit.public_ref),
                 'creationCorrelation': correlation, 'evidenceRef': evidence,
                 'processRef': self.reference(unit, 'owned-process'),
                 'transportRef': self.reference(unit, 'same-pipe'),
                 'initializationRef': self.reference(unit, 'original-initialize-success')}
        if self.damage == 'unit': proof['unitRef']['unitId'] = 'other'
        elif self.damage == 'correlation': proof['creationCorrelation'] = 'other'
        elif self.damage == 'version': proof['contractVersion'] = 'unknown'
        elif self.damage == 'session': proof['sessionId'] = 'default'
        elif self.damage == 'ack': proof.pop('initializationRef')
        elif self.damage == 'owner': proof['processRef']['ownerProviderRef'] = {'environmentNamespace': 'env', 'providerId': 'other'}
        elif self.damage == 'boolean': proof['processRef']['ownerProviderRef'] = dict(unit.facts['providerRef'], generation=True)
        elif self.damage == 'source': proof['transportRef']['sourceRevision'] = ''
        elif self.damage == 'sourceChanged': proof['transportRef']['sourceRevision'] = 'controlled-source-2'
        return proof

    def reference(self, unit, name):
        return {'environmentNamespace': 'env', 'ownerProviderRef': unit.facts['providerRef'],
                'sourceRevision': 'controlled-source-1', 'ref': name}


class AssociationEvidence:
    """Controlled original persisted owner receipt, never SDK IO or real proof."""
    def __init__(self, unit, expected):
        self.expected, self.unit, self.valid, self.damage = expected, unit, True, None
        self.receipt = source(unit, 'original-input-receipt')
        self.after_verify = lambda: None
        self.calls = 0
        self.fail_on = None

    def verify_association(self, unit, identity, evidence):
        self.calls += 1
        if (not self.valid or self.calls == self.fail_on or unit != self.unit or safe_json(identity) != safe_json(self.expected)
                or evidence != self.receipt):
            raise UnitRecordsRefused('original input Session receipt unavailable')
        proof = {'contractVersion': INPUT_SESSION_ASSOCIATION_VERSION, 'identity': json.loads(safe_json(identity)),
                 'nativeBinding': {'nativeRealm': 'controlled-owned-native', 'sessionId': 'observed-native-session',
                                   'evidenceRef': 'original-input-native-receipt'},
                 'evidenceRef': dict(self.receipt), 'associationRef': source(unit, 'original-session-association')}
        if self.damage == 'version': proof['contractVersion'] = 'unpublished/999'
        elif self.damage == 'extra': proof['secret'] = 'must-not-persist'
        elif self.damage == 'ack': proof['nativeBinding'] = {'accepted': True}
        elif self.damage == 'default': proof['nativeBinding']['sessionId'] = 'default'
        elif self.damage == 'session': proof['nativeBinding']['sessionId'] = 'substituted-session'
        elif self.damage == 'digest': proof['identity']['inputDigest'] = 'different-input'
        elif self.damage == 'correlation': proof['identity']['nativeCorrelation']['requestId'] = True
        elif self.damage == 'capture': proof['identity']['capturedInputRef']['captureRevision'] = True
        elif self.damage == 'boolean-owner': proof['associationRef']['ownerProviderRef'] = dict(self.expected['providerRef'], generation=True)
        elif self.damage == 'source': proof['associationRef']['sourceRevision'] = ''
        self.after_verify()
        return proof
