"""Real temporary SQLite; authority/native/verifier ports are controlled L1.

No native process/model, user directory, production admission or L2 claim.
The verifier fixture grants only objects explicitly issued in this test;
it does not establish production InvocationIssuer or native scope evidence.
"""
import copy
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from ordessa_agents.harness.definitions import ApplicationTarget, Plan, Confirmed
from ordessa_units.records.operation_journal import OperationJournal, FenceObservation, JournalError
from ordessa_units.records.unit_records import (
    UnitRecords, UnitRecordsRefused, CanonicalConfigurationScopeRef, RecordTicket,
    TERMINATION_VERSION,
)

PROVIDER = {'environmentNamespace': 'env', 'providerId': 'pi', 'generation': 1}
NODE = {'environmentNamespace': 'env', 'nodeId': 'node', 'generation': 1}
ROOT = {'host': 'controlled-host', 'filesystem': 1, 'parentObject': 42,
        'reservedChild': 'private-unit', 'isolationEvidence': 'controlled-proof'}


class Verifier:
    def __init__(self):
        self.issued = {}

    def issue(self, action='prepare', step='prepare', digest='input', epoch=0, node=NODE):
        context = object()
        facts = {'query': action == 'query', 'action': action, 'providerRef': PROVIDER,
                 'targetRef': node, 'inputDigest': digest, 'managementEpoch': epoch,
                 'request': {'environmentNamespace': 'env', 'principalScope': 'principal', 'requestId': 'request'},
                 'operationRef': 'operation', 'stepId': step}
        self.issued[context] = facts
        return context

    def verify_and_consume(self, context, action, provider, node, digest):
        if context not in self.issued:
            raise UnitRecordsRefused('unissued or consumed invocation')
        facts = self.issued[context]
        assert (action, provider, node, digest) == (facts['action'], facts['providerRef'], facts['targetRef'], facts['inputDigest'])
        if not facts['query']:
            del self.issued[context]
        return facts


class Scope:
    def __init__(self):
        self.valid = True
        self.scope = CanonicalConfigurationScopeRef('env', 'physical-shared-configuration', '1')
        self.legacy = None

    def issue_scope(self, provider, node, root):
        return self.scope

    def verify_scope(self, scope, root):
        return self.valid and scope == self.scope and root == ROOT

    def map_legacy_scope(self, target):
        assert isinstance(target, ApplicationTarget)
        return self.legacy


class Native:
    def __init__(self):
        self.valid = True

    def verify_binding(self, unit, correlation, evidence):
        if not self.valid or evidence != 'real-native-owner-evidence':
            raise UnitRecordsRefused('native evidence missing or forged')
        return {'nativeRealm': 'controlled-owned-pi', 'sessionId': 'native-observed-id',
                'evidenceRef': evidence}


class Epoch:
    value = 0

    def current_epoch(self, node):
        return self.value


def parts(tmp_path, *, termination=None, managed_turn_opt_in=False):
    journal_path = tmp_path / 'journal.sqlite'
    if managed_turn_opt_in:
        descriptor = os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    journal = OperationJournal(journal_path, managed_turn_opt_in=managed_turn_opt_in)
    verifier, scope, native, epoch = Verifier(), Scope(), Native(), Epoch()
    service = UnitRecords(journal, scope_authority=scope, native_evidence=native,
                          verifier=verifier, epoch_port=epoch,
                          termination_evidence=termination,
                          managed_turn_opt_in=managed_turn_opt_in)
    return service, journal, verifier, scope, native, epoch


class TermEvidence:
    def __init__(self, valid=True, refs=None):
        self.valid = valid
        self.refs = refs
        self.calls = []

    def verify_termination(self, unit, action, correlation, evidence):
        self.calls.append((action, correlation, evidence))
        if not self.valid:
            raise UnitRecordsRefused('termination evidence missing or forged')
        return self.refs if self.refs is not None else {
            'terminationEvidenceRef': 'sha256:' + action + '-owner-proof'}


def reserve(parts_, **changes):
    service, _, verifier, *_ = parts_
    values = {'provider_ref': PROVIDER, 'node_ref': NODE, 'input_digest': 'input', 'private_root_facts': ROOT}
    values.update(changes)
    return service.reserve_unit(verifier.issue(digest=values['input_digest'], node=values['node_ref']), **values)


def begin(parts_, unit):
    service, _, verifier, *_ = parts_
    return service.begin_session(unit.unit_ref, verifier.issue('start', 'start', 'start-input'), input_digest='start-input')


def read(parts_, unit):
    service, _, verifier, *_ = parts_
    return service.read_session(unit.unit_ref, verifier.issue('query', 'query', 'query-input'), input_digest='query-input')


