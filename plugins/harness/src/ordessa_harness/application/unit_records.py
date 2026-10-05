"""Harness-owned facts in the *existing* OperationJournal SQLite transaction.

reserve_unit(context, provider_ref, node_ref, input_digest, private_root_facts)
consumes a prepare InvocationContext and returns (UnitReservation, created).
begin_session(unit_ref, context, input_digest) consumes a start context and
durably fixes its creation correlation before returning an opaque RecordTicket.
record_session(ticket, expected_source_revision, state, evidence=None) only
records opening -> unknown/confirmed evidence; it cannot dispatch native work.
read_unit/read_session require a current issue_query context. All owner ports
are explicit trusted deployment injections, never inferred from caller paths.

Tickets are process-local identities, not serializable permissions. They bind
the exact journal instance, unit, core operation/step, input, provider, action
and management epoch. Native effects still require the original RuntimeProvider
invocation. After restart only authorized reads/native reconciliation can occur;
begin_session never issues a replacement start ticket for an existing binding.

This is a persistence foundation, not a production scope fence: the old Session
entry must call can_admit_legacy under its same BEGIN IMMEDIATE admission cut.
No old table/codec is migrated here. No process/filesystem/model effects occur.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping, Protocol
from uuid import uuid4

from ordessa_environment_api.operations import safe_json, sealed_mapping
from ordessa_harness_api import ApplicationTarget, Unknown
from .operation_journal import OperationJournal, JournalError


class UnitRecordsRefused(JournalError):
    pass


@dataclass(frozen=True)
class CanonicalConfigurationScopeRef:
    environment_namespace: str
    scope_id: str
    revision: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not v or len(v) > 256
               or any(ord(c) < 32 for c in v)
               for v in (self.environment_namespace, self.scope_id, self.revision)):
            raise UnitRecordsRefused("invalid canonical scope reference")

    def to_dict(self):
        return {"environmentNamespace": self.environment_namespace,
                "scopeId": self.scope_id, "revision": self.revision}

    def owner_ref(self, provider_ref):
        """Provenance projection of this SAME canonical scope identity."""
        if (not isinstance(provider_ref, Mapping)
                or provider_ref.get('environmentNamespace') != self.environment_namespace):
            raise UnitRecordsRefused('canonical scope owner environment differs')
        source = safe_json({'scopeRef': self.to_dict(), 'ownerProviderRef': provider_ref})
        return sealed_mapping({**self.to_dict(), 'ownerProviderRef': provider_ref,
                               'sourceRevision': 'sha256:' + _digest(source)})


class ScopeAuthorityPort(Protocol):
    def issue_scope(self, provider_ref, node_ref, private_root_facts) -> CanonicalConfigurationScopeRef: ...
    def verify_scope(self, scope_ref, private_root_facts) -> bool: ...
    def map_legacy_scope(self, legacy_target: ApplicationTarget) -> CanonicalConfigurationScopeRef | None: ...


class NativeSessionEvidencePort(Protocol):
    def verify_binding(self, unit, creation_correlation, evidence) -> Mapping: ...


class NativeConfigurationEvidencePort(Protocol):
    """Original native receipt provenance, never a current-value equality test."""
    def verify_configuration(self, unit, identity, native_request_id,
                             native_request_digest, evidence) -> Mapping: ...


class ManagementEpochPort(Protocol):
    def current_epoch(self, node_ref) -> int: ...


@dataclass(frozen=True)
class UnitReservation:
    unit_ref: str
    intent_json: str
    scope_json: str

    @property
    def facts(self):
        return sealed_mapping(json.loads(self.intent_json))

    @property
    def scope_ref(self):
        value = json.loads(self.scope_json)
        return CanonicalConfigurationScopeRef(value['environmentNamespace'], value['scopeId'], value['revision'])

    @property
    def public_ref(self):
        """Immutable source identity, never a native configuration version.

        Callers must obtain this reservation through authorized owner reads.
        Only references/digests leave the existing private journal record.
        """
        provider = self.facts['providerRef']
        source = safe_json({'unitId': self.unit_ref, 'intentDigest': _digest(self.intent_json),
                            'scopeDigest': _digest(self.scope_json)})
        return sealed_mapping({'environmentNamespace': provider['environmentNamespace'],
                               'unitId': self.unit_ref, 'ownerProviderRef': provider,
                               'sourceRevision': 'sha256:' + _digest(source)})

    @property
    def configuration_target_ref(self):
        return self.scope_ref.owner_ref(self.facts['providerRef'])


@dataclass(frozen=True)
class NativeSessionBinding:
    unit_ref: str
    state: str
    source_revision: int
    creation_correlation: str | None
    native_json: str | None

    @property
    def native_facts(self):
        return None if self.native_json is None else sealed_mapping(json.loads(self.native_json))


class RecordTicket:
    __slots__ = ()

    def __init__(self):
        raise TypeError("record tickets are issued by UnitRecords")

    def __copy__(self):
        raise TypeError("record tickets cannot be copied")

    __deepcopy__ = lambda self, memo: self.__copy__()

    def __reduce__(self):
        raise TypeError("record tickets cannot be serialized")


class ConfigurationRecordTicket(RecordTicket):
    """Original configuration dispatch capability; never reissued on replay."""


@dataclass(frozen=True)
class NativeConfigurationAttempt:
    attempt_ref: str
    identity_json: str
    state: str
    source_revision: int
    native_request_id: str | int | None
    native_request_digest: str | None
    confirmation_json: str | None

    @property
    def identity(self):
        return sealed_mapping(json.loads(self.identity_json))

    @property
    def confirmation(self):
        return None if self.confirmation_json is None else sealed_mapping(json.loads(self.confirmation_json))


def _digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _correlation(facts):
    return safe_json({"request": facts['request'], "operationRef": facts['operationRef'],
                      "stepId": facts['stepId']})


class UnitRecords:
    def __init__(self, journal, *, scope_authority, native_evidence, verifier, epoch_port,
                 configuration_evidence=None):
        if (not isinstance(journal, OperationJournal) or any(p is None for p in
                (scope_authority, native_evidence, verifier, epoch_port))):
            raise UnitRecordsRefused("existing journal and explicit authority ports required")
        self.journal = journal
        self.scope_authority, self.native_evidence = scope_authority, native_evidence
        self.verifier, self.epoch_port = verifier, epoch_port
        self.configuration_evidence = configuration_evidence
        self._tickets = {}
        self._configuration_tickets = {}
        authority = getattr(journal, '_unit_records_scope_authority', None)
        if authority is not None and authority is not scope_authority:
            raise UnitRecordsRefused("journal already has a different scope authority")
        with journal._connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS harness_unit_reservations (
                    unit_ref TEXT PRIMARY KEY, correlation TEXT NOT NULL UNIQUE,
                    intent_json TEXT NOT NULL, intent_digest TEXT NOT NULL,
                    scope_json TEXT NOT NULL, scope_key TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS harness_unit_sessions (
                    unit_ref TEXT PRIMARY KEY REFERENCES harness_unit_reservations(unit_ref),
                    state TEXT NOT NULL, source_revision INTEGER NOT NULL,
                    creation_correlation TEXT UNIQUE, native_json TEXT,
                    native_digest TEXT);
                CREATE TABLE IF NOT EXISTS harness_unit_configuration_attempts (
                    attempt_ref TEXT PRIMARY KEY,
                    unit_ref TEXT NOT NULL REFERENCES harness_unit_reservations(unit_ref),
                    correlation TEXT NOT NULL UNIQUE,
                    identity_json TEXT NOT NULL, identity_digest TEXT NOT NULL,
                    state TEXT NOT NULL, source_revision INTEGER NOT NULL,
                    native_request_json TEXT, native_request_digest TEXT,
                    confirmation_json TEXT, confirmation_digest TEXT);
            ''')
        # Retain one owner and one bound gate per journal object. The journal
        # owns the actual transactional admission cut; importing UnitRecords
        # into OperationJournal would create a circular dependency.
        if authority is None:
            journal._unit_records_scope_authority = scope_authority
            journal._unit_records_admission_guard = self
        installer = getattr(journal, 'install_admission_guard', None)
        if callable(installer):
            installer(journal._unit_records_admission_guard)

    def _authorize(self, context, action, provider, node, digest, *, query=False, epoch_target=None):
        facts = self.verifier.verify_and_consume(context, action, provider, node, digest)
        if (not isinstance(facts, Mapping) or facts.get('query') is not query
                or not isinstance(facts.get('providerRef'), Mapping) or not isinstance(facts.get('targetRef'), Mapping)
                or facts.get('action') != action or safe_json(facts.get('providerRef')) != safe_json(provider)
                or safe_json(facts.get('targetRef')) != safe_json(node) or facts.get('inputDigest') != digest
                or type(facts.get('managementEpoch')) is not int
                or facts['managementEpoch'] < 0):
            raise UnitRecordsRefused("verified invocation facts differ")
        if self._epoch(node if epoch_target is None else epoch_target) != facts['managementEpoch']:
            raise UnitRecordsRefused("management epoch changed")
        return facts

    def _epoch(self, node):
        value = self.epoch_port.current_epoch(node)
        if type(value) is not int or value < 0:
            raise UnitRecordsRefused("current management epoch evidence unavailable")
        return value

    def _unit(self, db, unit_ref):
        row = db.execute('SELECT * FROM harness_unit_reservations WHERE unit_ref=?', (unit_ref,)).fetchone()
        if row is None or row['intent_digest'] != _digest(row['intent_json']):
            raise UnitRecordsRefused("unit missing or immutable facts damaged")
        unit = UnitReservation(row['unit_ref'], row['intent_json'], row['scope_json'])
        if row['correlation'] != unit.facts['correlation']:
            raise UnitRecordsRefused("unit correlation damaged")
        if self.scope_authority.verify_scope(unit.scope_ref, unit.facts['privateRootFacts']) is not True:
            raise UnitRecordsRefused("scope authority unavailable or mapping changed")
        expected_key = safe_json({'environmentNamespace': unit.scope_ref.environment_namespace,
                                  'scopeId': unit.scope_ref.scope_id})
        if expected_key != row['scope_key']:
            raise UnitRecordsRefused("scope identity damaged")
        return unit

    def _binding(self, db, unit_ref):
        row = db.execute('SELECT * FROM harness_unit_sessions WHERE unit_ref=?', (unit_ref,)).fetchone()
        if row is None or row['state'] not in ('notCreated', 'opening', 'unknown', 'confirmed'):
            raise UnitRecordsRefused("session binding missing or damaged")
        if type(row['source_revision']) is not int or row['source_revision'] < 1:
            raise UnitRecordsRefused("binding revision damaged")
        if ((row['state'] == 'notCreated') != (row['creation_correlation'] is None)
                or (row['state'] == 'confirmed') != (row['native_json'] is not None)
                or (row['native_json'] is not None and row['native_digest'] != _digest(row['native_json']))):
            raise UnitRecordsRefused("binding identity or evidence damaged")
        if row['state'] == 'confirmed':
            native = json.loads(row['native_json'])
            if not isinstance(native, dict) or not isinstance(native.get('evidenceRef'), str):
                raise UnitRecordsRefused("binding native evidence damaged")
            verified = self.native_evidence.verify_binding(self._unit(db, unit_ref),
                        row['creation_correlation'], native['evidenceRef'])
            if safe_json(verified) != row['native_json']:
                raise UnitRecordsRefused("binding differs from native owner evidence")
        return NativeSessionBinding(unit_ref, row['state'], row['source_revision'],
                                    row['creation_correlation'], row['native_json'])

    def _legacy_busy(self, db, scope):
        for row in db.execute("SELECT * FROM operations WHERE state IN ('applying','verifying','unknown','confirmed')"):
            if row['state'] == 'confirmed' and not isinstance(self.journal._result(db, row), Unknown):
                continue
            target = ApplicationTarget(row['server_id'], row['session_id'],
                                       row['channel_id'], row['runtime_generation'])
            mapped = self.scope_authority.map_legacy_scope(target)
            if (not isinstance(mapped, CanonicalConfigurationScopeRef)
                    or (mapped.environment_namespace, mapped.scope_id) == (scope.environment_namespace, scope.scope_id)):
                raise UnitRecordsRefused("legacy unresolved operation retains configuration fence")

    def reserve_unit(self, context, *, provider_ref, node_ref, input_digest, private_root_facts):
        facts = self._authorize(context, 'prepare', provider_ref, node_ref, input_digest)
        environment = facts['request']['environmentNamespace']
        if (provider_ref.get('environmentNamespace') != environment
                or node_ref.get('environmentNamespace') != environment
                or not isinstance(private_root_facts, Mapping) or not private_root_facts):
            raise UnitRecordsRefused("complete scoped unit facts required")
        intent = safe_json({'correlation': _correlation(facts), 'inputDigest': input_digest,
                           'providerRef': provider_ref, 'nodeRef': node_ref,
                           'managementEpoch': facts['managementEpoch'], 'privateRootFacts': private_root_facts})
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            existing = db.execute('SELECT unit_ref,intent_json FROM harness_unit_reservations WHERE correlation=?',
                                  (_correlation(facts),)).fetchone()
            if existing is not None:
                if existing['intent_json'] != intent:
                    raise UnitRecordsRefused("correlation bound to different input or unit")
                return self._unit(db, existing['unit_ref']), False
            scope = self.scope_authority.issue_scope(provider_ref, node_ref, private_root_facts)
            if (not isinstance(scope, CanonicalConfigurationScopeRef)
                    or scope.environment_namespace != environment
                    or self.scope_authority.verify_scope(scope, private_root_facts) is not True):
                raise UnitRecordsRefused("owner-issued canonical scope required")
            self._legacy_busy(db, scope)
            key = safe_json({'environmentNamespace': environment, 'scopeId': scope.scope_id})
            if db.execute('SELECT 1 FROM harness_unit_reservations WHERE scope_key=?', (key,)).fetchone():
                raise UnitRecordsRefused("configuration scope already reserved")
            unit = UnitReservation('unit-' + uuid4().hex, intent, safe_json(scope.to_dict()))
            db.execute('INSERT INTO harness_unit_reservations VALUES (?,?,?,?,?,?)',
                       (unit.unit_ref, _correlation(facts), intent, _digest(intent), unit.scope_json, key))
            db.execute('INSERT INTO harness_unit_sessions VALUES (?,?,?,?,?,?)',
                       (unit.unit_ref, 'notCreated', 1, None, None, None))
            db.commit()
            return unit, True

    def begin_session(self, unit_ref, context, *, input_digest):
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            unit = self._unit(db, unit_ref)
            facts = self._authorize(context, 'start', unit.facts['providerRef'], unit.facts['nodeRef'], input_digest)
            if facts['managementEpoch'] != unit.facts['managementEpoch']:
                raise UnitRecordsRefused("unit management epoch changed")
            binding = self._binding(db, unit_ref)
            if binding.state != 'notCreated':
                raise UnitRecordsRefused("existing native creation cannot be dispatched again")
            correlation = _correlation(facts)
            db.execute("UPDATE harness_unit_sessions SET state='opening',source_revision=2,creation_correlation=? WHERE unit_ref=?",
                       (correlation, unit_ref))
            db.commit()
        ticket = object.__new__(RecordTicket)
        self._tickets[id(ticket)] = (ticket, unit, correlation, input_digest, facts['managementEpoch'])
        return ticket

    def record_session(self, ticket, *, expected_source_revision, state, evidence=None):
        entry = self._tickets.get(id(ticket))
        if type(ticket) is not RecordTicket or entry is None or entry[0] is not ticket:
            raise UnitRecordsRefused("record ticket is not owned by this journal instance")
        _, unit, correlation, digest, epoch = entry
        if self._epoch(unit.facts['nodeRef']) != epoch:
            raise UnitRecordsRefused("record ticket epoch expired")
        if state not in ('unknown', 'confirmed'):
            raise UnitRecordsRefused("ticket cannot restart or replace native creation")
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._unit(db, unit.unit_ref) != unit:
                raise UnitRecordsRefused("unit changed after ticket issuance")
            binding = self._binding(db, unit.unit_ref)
            if (type(expected_source_revision) is not int or binding.source_revision != expected_source_revision
                    or binding.creation_correlation != correlation or binding.state not in ('opening', 'unknown')):
                raise UnitRecordsRefused("binding terminal, changed, or revision conflict")
            native = None
            if state == 'confirmed':
                native = self.native_evidence.verify_binding(unit, correlation, evidence)
                if (not isinstance(native, Mapping) or set(native) != {'nativeRealm', 'sessionId', 'evidenceRef'}
                        or any(not isinstance(native[k], str) or not native[k] for k in native)):
                    raise UnitRecordsRefused("real native session evidence required")
                native = safe_json(native)
            elif evidence is not None:
                raise UnitRecordsRefused("unknown cannot claim native confirmation")
            db.execute('UPDATE harness_unit_sessions SET state=?,source_revision=?,native_json=?,native_digest=? WHERE unit_ref=?',
                       (state, binding.source_revision + 1, native, None if native is None else _digest(native), unit.unit_ref))
            db.commit()
            result = self._binding(db, unit.unit_ref)
        if state == 'confirmed':
            del self._tickets[id(ticket)]
        return result

    def read_unit(self, unit_ref, context, *, input_digest):
        with self.journal._connect() as db:
            unit = self._unit(db, unit_ref)
            self._authorize(context, 'query', unit.facts['providerRef'], unit.facts['nodeRef'], input_digest, query=True)
            return unit

    def resolve_unit_reference(self, unit_ref, context, *, input_digest):
        """Authorized original-owner read, checking every public identity field."""
        if (not isinstance(unit_ref, Mapping)
                or set(unit_ref) != {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
                or not isinstance(unit_ref['unitId'], str) or not unit_ref['unitId']):
            raise UnitRecordsRefused('complete owner-bound Unit reference required')
        unit = self.read_unit(unit_ref['unitId'], context, input_digest=input_digest)
        if safe_json(unit_ref) != safe_json(unit.public_ref):
            raise UnitRecordsRefused('Unit reference differs from original owner source')
        return unit

    def read_session(self, unit_ref, context, *, input_digest):
        self.read_unit(unit_ref, context, input_digest=input_digest)
        with self.journal._connect() as db:
            return self._binding(db, unit_ref)

    def _configuration_attempt(self, db, attempt_ref):
        row = db.execute('SELECT * FROM harness_unit_configuration_attempts WHERE attempt_ref=?',
                         (attempt_ref,)).fetchone()
        if (row is None or row['identity_digest'] != _digest(row['identity_json'])
                or row['state'] not in ('opening', 'unknown', 'confirmed')
                or type(row['source_revision']) is not int or row['source_revision'] < 1):
            raise UnitRecordsRefused('configuration attempt missing or damaged')
        identity = json.loads(row['identity_json'])
        if (row['unit_ref'] != identity['unitRef']['unitId'] or row['correlation'] != identity['correlation']
                or (row['native_request_json'] is None) != (row['native_request_digest'] is None)
                or (row['confirmation_json'] is not None) != (row['state'] == 'confirmed')):
            raise UnitRecordsRefused('configuration attempt binding damaged')
        unit = self._unit(db, row['unit_ref'])
        if (safe_json(identity['scopeRef']) != safe_json(unit.configuration_target_ref)
                or safe_json(identity['unitRef']) != safe_json(unit.public_ref)
                or safe_json(identity['providerRef']) != safe_json(unit.facts['providerRef'])):
            raise UnitRecordsRefused('configuration scope or owner changed')
        native_id = None
        if row['native_request_json'] is not None:
            captured = json.loads(row['native_request_json'])
            native_id = captured.get('requestId') if isinstance(captured, dict) else None
            native_digest = row['native_request_digest']
            if (not isinstance(captured, dict) or set(captured) != {'requestId'}
                    or type(native_id) not in (str, int)
                    or isinstance(native_id, str) and (not native_id or len(native_id) > 256)
                    or not isinstance(native_digest, str) or len(native_digest) != 71
                    or not native_digest.startswith('sha256:')
                    or any(c not in '0123456789abcdef' for c in native_digest[7:])):
                raise UnitRecordsRefused('native configuration request binding damaged')
        if row['state'] == 'confirmed':
            if row['confirmation_digest'] != _digest(row['confirmation_json']):
                raise UnitRecordsRefused('configuration confirmation damaged')
            self._verify_configuration_confirmation(unit, identity, native_id,
                row['native_request_digest'], json.loads(row['confirmation_json'])['evidenceRef'],
                expected=row['confirmation_json'])
        return NativeConfigurationAttempt(row['attempt_ref'], row['identity_json'], row['state'],
            row['source_revision'], native_id, row['native_request_digest'], row['confirmation_json'])

    def begin_configuration_change(self, unit_ref, context, *, input_digest, expected_revision):
        """Persist original batch intent before any native write; no plaintext payload.

        This does not compare the actual native revision: the provider must do
        so under its canonical owner lock immediately before dispatch. One batch
        has one native write ID; individual setters need distinct captured steps.
        An existing attempt can only be queried, never receive a new ticket.
        """
        if not callable(getattr(self.configuration_evidence, 'verify_configuration', None)):
            raise UnitRecordsRefused('native configuration evidence port unavailable')
        if not isinstance(expected_revision, str) or not expected_revision or len(expected_revision) > 512:
            raise UnitRecordsRefused('native expected revision required')
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            unit = self._unit(db, unit_ref)
            if self._binding(db, unit_ref).state != 'confirmed':
                raise UnitRecordsRefused('confirmed native unit required')
            facts = self._authorize(context, 'applyConfiguration', unit.facts['providerRef'],
                unit.configuration_target_ref, input_digest, epoch_target=unit.facts['nodeRef'])
            if facts['managementEpoch'] != unit.facts['managementEpoch']:
                raise UnitRecordsRefused('unit management epoch changed')
            correlation = _correlation(facts)
            if db.execute('SELECT 1 FROM harness_unit_configuration_attempts WHERE correlation=?',
                          (correlation,)).fetchone():
                raise UnitRecordsRefused('existing configuration attempt cannot dispatch again')
            if db.execute("SELECT 1 FROM harness_unit_configuration_attempts WHERE unit_ref=? AND state IN ('opening','unknown')",
                          (unit_ref,)).fetchone():
                raise UnitRecordsRefused('unknown configuration attempt retains scope fence')
            identity = safe_json({'unitRef': unit.public_ref,
                'scopeRef': unit.configuration_target_ref, 'providerRef': unit.facts['providerRef'],
                'correlation': correlation, 'operationRef': facts['operationRef'], 'requestDigest': input_digest,
                'expectedRevision': expected_revision, 'managementEpoch': facts['managementEpoch']})
            attempt_ref = 'configuration-' + uuid4().hex
            db.execute('INSERT INTO harness_unit_configuration_attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (attempt_ref, unit_ref, correlation, identity, _digest(identity), 'opening', 1, None, None, None, None))
            db.commit()
        ticket = object.__new__(ConfigurationRecordTicket)
        self._configuration_tickets[id(ticket)] = (ticket, unit, attempt_ref, facts['managementEpoch'])
        return ticket

    def _configuration_ticket(self, ticket):
        entry = self._configuration_tickets.get(id(ticket))
        if type(ticket) is not ConfigurationRecordTicket or entry is None or entry[0] is not ticket:
            raise UnitRecordsRefused('configuration ticket is not owned by this journal instance')
        if self._epoch(entry[1].facts['nodeRef']) != entry[3]:
            raise UnitRecordsRefused('configuration ticket epoch expired')
        return entry

    def bind_configuration_dispatch(self, ticket, *, native_request_id, native_request_digest):
        """Must finish in the transport pre-send hook, before its actual write.

        No replacement binding even if the first write failed or timed out.
        Current invocation authority still needs a separate per-write barrier.
        """
        _, unit, attempt_ref, _ = self._configuration_ticket(ticket)
        if (type(native_request_id) not in (str, int) or isinstance(native_request_id, str)
                and (not native_request_id or len(native_request_id) > 256)
                or not isinstance(native_request_digest, str) or not native_request_digest.startswith('sha256:')
                or len(native_request_digest) != 71
                or any(c not in '0123456789abcdef' for c in native_request_digest[7:])):
            raise UnitRecordsRefused('exact native request identity and digest required')
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            attempt = self._configuration_attempt(db, attempt_ref)
            if self._unit(db, unit.unit_ref) != unit or attempt.state != 'opening' or attempt.native_request_id is not None:
                raise UnitRecordsRefused('native configuration dispatch already bound or terminal')
            db.execute('UPDATE harness_unit_configuration_attempts SET native_request_json=?,native_request_digest=?,source_revision=source_revision+1 WHERE attempt_ref=?',
                (safe_json({'requestId': native_request_id}), native_request_digest, attempt_ref))
            db.commit()
            return self._configuration_attempt(db, attempt_ref)

    def _verify_configuration_confirmation(self, unit, identity, native_id, native_digest, evidence, *, expected=None):
        verifier = getattr(self.configuration_evidence, 'verify_configuration', None)
        if not callable(verifier) or native_id is None:
            raise UnitRecordsRefused('original native configuration confirmation unavailable')
        proof = verifier(unit, sealed_mapping(identity), native_id, native_digest, evidence)
        required = {'operationRef', 'unitRef', 'scopeRef', 'requestDigest',
                    'nativeRequestId', 'nativeRequestDigest', 'evidenceRef'}
        if (not isinstance(proof, Mapping) or set(proof) != required
                or any(proof[key] != identity[key] for key in ('operationRef','unitRef','scopeRef','requestDigest'))
                or proof['nativeRequestId'] != native_id or type(proof['nativeRequestId']) is not type(native_id)
                or proof['nativeRequestDigest'] != native_digest
                or not isinstance(proof['evidenceRef'], str) or not proof['evidenceRef']):
            raise UnitRecordsRefused('configuration confirmation identity differs')
        encoded = safe_json(proof)
        if expected is not None and expected != encoded:
            raise UnitRecordsRefused('configuration native owner evidence changed')
        return encoded

    def record_configuration_change(self, ticket, *, expected_source_revision, state, evidence=None):
        _, unit, attempt_ref, _ = self._configuration_ticket(ticket)
        if state not in ('unknown', 'confirmed') or state == 'unknown' and evidence is not None:
            raise UnitRecordsRefused('unknown cannot claim configuration confirmation')
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            attempt = self._configuration_attempt(db, attempt_ref)
            if (self._unit(db, unit.unit_ref) != unit or type(expected_source_revision) is not int
                    or attempt.source_revision != expected_source_revision or attempt.state == 'confirmed'):
                raise UnitRecordsRefused('configuration attempt terminal or revision conflict')
            proof = None if state == 'unknown' else self._verify_configuration_confirmation(unit,
                attempt.identity, attempt.native_request_id, attempt.native_request_digest, evidence)
            db.execute('UPDATE harness_unit_configuration_attempts SET state=?,source_revision=source_revision+1,confirmation_json=?,confirmation_digest=? WHERE attempt_ref=?',
                (state, proof, None if proof is None else _digest(proof), attempt_ref))
            db.commit()
            result = self._configuration_attempt(db, attempt_ref)
        if state == 'confirmed':
            del self._configuration_tickets[id(ticket)]
        return result

    def query_configuration_change(self, unit_ref, operation_ref, context, *, input_digest):
        """Read the original attempt under query authority; never infer from current config."""
        with self.journal._connect() as db:
            unit = self._unit(db, unit_ref)
            facts = self._authorize(context, 'query', unit.facts['providerRef'], unit.configuration_target_ref,
                input_digest, query=True, epoch_target=unit.facts['nodeRef'])
            if facts['operationRef'] != operation_ref:
                raise UnitRecordsRefused('query operation identity differs')
            row = db.execute('SELECT attempt_ref FROM harness_unit_configuration_attempts WHERE correlation=? AND unit_ref=?',
                (_correlation(facts), unit_ref)).fetchone()
            if row is None:
                raise UnitRecordsRefused('original configuration attempt unavailable')
            attempt = self._configuration_attempt(db, row['attempt_ref'])
            if attempt.identity['requestDigest'] != input_digest:
                raise UnitRecordsRefused('query configuration digest differs')
            return attempt

    def can_admit_legacy(self, db, legacy_target):
        """Pure gate for old reserve_new's existing BEGIN IMMEDIATE transaction.

        Mapping absence with any reserved unit refuses admission. This helper
        never grants a scope or clears a reservation and must be called by ALL
        old native/configuration write paths before they reserve/dispatch.
        """
        if not isinstance(legacy_target, ApplicationTarget):
            return False
        mapped = self.scope_authority.map_legacy_scope(legacy_target)
        if not isinstance(mapped, CanonicalConfigurationScopeRef):
            # An unmapped target cannot evade any retained unit OR legacy
            # active/unknown reservation. No scope is inferred from its codec.
            if db.execute('SELECT 1 FROM harness_unit_reservations LIMIT 1').fetchone():
                return False
            for row in db.execute("SELECT * FROM operations WHERE state IN ('applying','verifying','unknown','confirmed')"):
                if row['state'] != 'confirmed' or isinstance(self.journal._result(db, row), Unknown):
                    return False
            return mapped is None
        for row in db.execute('SELECT unit_ref FROM harness_unit_reservations'):
            try:
                unit = self._unit(db, row['unit_ref'])
            except (UnitRecordsRefused, KeyError, TypeError, ValueError):
                return False
            if ((unit.scope_ref.environment_namespace, unit.scope_ref.scope_id)
                    == (mapped.environment_namespace, mapped.scope_id)):
                return False
        try:
            self._legacy_busy(db, mapped)
        except UnitRecordsRefused:
            return False
        return True
