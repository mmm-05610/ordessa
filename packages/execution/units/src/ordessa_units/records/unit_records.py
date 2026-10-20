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
import re
from threading import RLock
from typing import Mapping, Protocol
from uuid import uuid4

from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_execution_agents.harness.definitions import ApplicationTarget, Unknown
from .operation_journal import OperationJournal, JournalError


UNIT_SCHEMA_SQL = """
                CREATE TABLE IF NOT EXISTS harness_unit_reservations (
                    unit_ref TEXT PRIMARY KEY, correlation TEXT NOT NULL UNIQUE,
                    intent_json TEXT NOT NULL, intent_digest TEXT NOT NULL,
                    scope_json TEXT NOT NULL, scope_key TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS harness_unit_sessions (
                    unit_ref TEXT PRIMARY KEY REFERENCES harness_unit_reservations(unit_ref),
                    state TEXT NOT NULL, source_revision INTEGER NOT NULL,
                    creation_correlation TEXT UNIQUE, native_json TEXT,
                    native_digest TEXT);
                CREATE TABLE IF NOT EXISTS harness_unit_confirmations (
                    unit_ref TEXT PRIMARY KEY REFERENCES harness_unit_reservations(unit_ref),
                    state TEXT NOT NULL, source_revision INTEGER NOT NULL,
                    creation_correlation TEXT UNIQUE, native_json TEXT,
                    native_digest TEXT, input_digest TEXT);
                CREATE TABLE IF NOT EXISTS harness_unit_configuration_attempts (
                    attempt_ref TEXT PRIMARY KEY,
                    unit_ref TEXT NOT NULL REFERENCES harness_unit_reservations(unit_ref),
                    correlation TEXT NOT NULL UNIQUE,
                    identity_json TEXT NOT NULL, identity_digest TEXT NOT NULL,
                    state TEXT NOT NULL, source_revision INTEGER NOT NULL,
                    native_request_json TEXT, native_request_digest TEXT,
                    confirmation_json TEXT, confirmation_digest TEXT);
                CREATE TABLE IF NOT EXISTS harness_unit_terminations (
                    unit_ref TEXT NOT NULL REFERENCES harness_unit_reservations(unit_ref),
                    action TEXT NOT NULL,
                    correlation TEXT NOT NULL UNIQUE,
                    identity_json TEXT NOT NULL, identity_digest TEXT NOT NULL,
                    state TEXT NOT NULL, source_revision INTEGER NOT NULL,
                    outcome_json TEXT, outcome_digest TEXT,
                    PRIMARY KEY (unit_ref, action));
            """

MANAGED_SCHEMA_SQL = """CREATE TABLE harness_managed_turn_attempts (
                    operation_ref TEXT PRIMARY KEY,
                    request_key TEXT NOT NULL UNIQUE,
                    unit_ref TEXT NOT NULL REFERENCES harness_unit_reservations(unit_ref),
                    input_digest TEXT NOT NULL,
                    binding_json TEXT NOT NULL, binding_digest TEXT NOT NULL,
                    execution_json TEXT NOT NULL, execution_digest TEXT NOT NULL,
                    state TEXT NOT NULL, revision INTEGER NOT NULL,
                    receipt_json TEXT, terminal_json TEXT)"""

class UnitRecordsRefused(JournalError):
    pass


class AcpEvidenceCapacityRefused(UnitRecordsRefused):
    """The complete original ACP evidence cannot fit its finite owner budget."""
    code = 'ACP_EVIDENCE_CAPACITY_EXCEEDED'


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


UNIT_CONFIRMATION_VERSION = 'harness-unit-confirmation/1'
INPUT_SESSION_ASSOCIATION_VERSION = 'harness-input-session-association/1'
SESSIONLESS_INPUT_VERSION = 'harness-sessionless-input/1'
TERMINATION_VERSION = 'harness-unit-termination/1'
TERMINATION_ACTIONS = ('stop', 'release')
MANAGED_TURN_VERSION = 'harness-managed-codex-turn/1'
MANAGED_TURN_STATES = frozenset({'reserved', 'possibly-written', 'accepted', 'completed',
                                 'failed', 'interrupted', 'unknown'})


class NativeInputAssociationEvidencePort(Protocol):
    """Original input receipt and Session identity, not input effect completion.

    Reverify original persisted input/Unit/process/transport/native correlation,
    fixed roots and installation, original Session absence observation, actual
    returned Session and current owner liveness. ACK/latest Session is no proof.
    This port observes only; it must never start or submit an input.
    """
    def verify_association(self, unit, identity, evidence) -> Mapping: ...


class NativeUnitEvidencePort(Protocol):
    """Original owned process + same-pipe initialize evidence, not an ACK.

    The owner verifies fixed installation/root, process and transport identity,
    original start correlation, successful initialization and current liveness.
    It returns only versioned provenance refs; no PID, command, secret or session
    selector is substituted for an independently verified native Unit.
    """
    def verify_unit_binding(self, unit, creation_correlation, evidence) -> Mapping: ...


class NativeConfigurationEvidencePort(Protocol):
    """Original native receipt provenance, never a current-value equality test."""
    def verify_configuration(self, unit, identity, native_request_id,
                             native_request_digest, evidence) -> Mapping: ...


class ManagementEpochPort(Protocol):
    def current_epoch(self, node_ref) -> int: ...


class NativeTerminationEvidencePort(Protocol):
    """Original stop/release effect proof, never an ACK or a caller string.

    The owner verifies the fixed installation/root, the original unit and
    correlation, and the actual termination effect; it returns only
    versioned provenance refs. Confirmed termination stores the owner's
    returned refs — caller-supplied evidence is never stored as proof.
    """
    def verify_termination(self, unit, action, correlation, evidence) -> Mapping: ...


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
class ManagedTurnRecord:
    operation_ref: str
    request_key: str
    unit_ref: str
    input_digest: str
    binding_json: str
    execution_json: str
    state: str
    revision: int
    receipt_json: str | None = None
    terminal_json: str | None = None

    @property
    def binding(self):
        return sealed_mapping(json.loads(self.binding_json))

    @property
    def execution_evidence(self):
        return sealed_mapping(json.loads(self.execution_json))

    @property
    def receipt(self):
        return None if self.receipt_json is None else sealed_mapping(json.loads(self.receipt_json))

    @property
    def terminal(self):
        return None if self.terminal_json is None else sealed_mapping(json.loads(self.terminal_json))


@dataclass(frozen=True)
class NativeSessionBinding:
    unit_ref: str
    state: str
    source_revision: int
    creation_correlation: str | None
    native_json: str | None

    @property
    def native_facts(self):
        if self.native_json is None:
            return None
        proof = json.loads(self.native_json)
        if proof.get('contractVersion') == INPUT_SESSION_ASSOCIATION_VERSION:
            return sealed_mapping(proof['nativeBinding'])
        return sealed_mapping(proof)

    @property
    def association_facts(self):
        if self.native_json is None:
            return None
        proof = json.loads(self.native_json)
        return sealed_mapping(proof) if proof.get('contractVersion') == INPUT_SESSION_ASSOCIATION_VERSION else None


@dataclass(frozen=True)
class NativeUnitBinding:
    unit_ref: str
    state: str
    source_revision: int
    creation_correlation: str | None
    native_json: str | None
    input_digest: str | None = None

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


class UnitRecordTicket(RecordTicket):
    """Native Unit creation; separate from the strict session ticket."""


class TerminationRecordTicket(RecordTicket):
    """Original stop/release attempt; one live ticket per Unit and action."""


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
    @property
    def acp_turn_evidence_max_bytes(self):
        from .acp_turns import MAX_EVIDENCE_BYTES
        return MAX_EVIDENCE_BYTES

    def __init__(self, journal, *, scope_authority, native_evidence, verifier, epoch_port,
                 configuration_evidence=None, native_unit_evidence=None, input_association_evidence=None,
                 termination_evidence=None, managed_turn_opt_in=False, acp_turn_opt_in=False):
        if (not isinstance(journal, OperationJournal) or any(p is None for p in
                (scope_authority, native_evidence, verifier, epoch_port))):
            raise UnitRecordsRefused("existing journal and explicit authority ports required")
        self.journal = journal
        self.scope_authority, self.native_evidence = scope_authority, native_evidence
        self.verifier, self.epoch_port = verifier, epoch_port
        self.configuration_evidence = configuration_evidence
        self.native_unit_evidence = native_unit_evidence
        self.input_association_evidence = input_association_evidence
        self.termination_evidence = termination_evidence
        if type(managed_turn_opt_in) is not bool:
            raise UnitRecordsRefused("managed turn schema opt-in must be explicit")
        if managed_turn_opt_in and not journal.managed_turn_opt_in:
            raise UnitRecordsRefused("managed turn schema requires an explicitly opted-in pristine journal")
        self.managed_turn_available = managed_turn_opt_in
        if type(acp_turn_opt_in) is not bool or acp_turn_opt_in and not journal.acp_turn_opt_in:
            raise UnitRecordsRefused('ACP turn schema requires original pristine journal opt-in')
        self.acp_turn_available = acp_turn_opt_in
        # One private, bounded observation snapshot per original owner. The
        # lock covers its SQLite transaction and post-COMMIT publication.
        self._acp_observation_lock = RLock()
        self._acp_observation_cache = None
        self._tickets = {}
        self._configuration_tickets = {}
        self._termination_tickets = {}
        authority = getattr(journal, '_unit_records_scope_authority', None)
        if authority is not None and authority is not scope_authority:
            raise UnitRecordsRefused("journal already has a different scope authority")
        if not journal.reopened_for_new_units:
            with journal._connect() as db:
                db.executescript(UNIT_SCHEMA_SQL)
        if self.managed_turn_available and not journal.reopened_for_new_units:
            with journal._connect() as db:
                db.execute(MANAGED_SCHEMA_SQL)
        if self.acp_turn_available and not journal.reopened_for_new_units:
            from .acp_turns import initialize
            initialize(self)
        # Retain one owner and one bound gate per journal object. The journal
        # owns the actual transactional admission cut; importing UnitRecords
        # into OperationJournal would create a circular dependency.
        if authority is None:
            journal._unit_records_scope_authority = scope_authority
            journal._unit_records_admission_guard = self
        installer = getattr(journal, 'install_admission_guard', None)
        if callable(installer):
            installer(journal._unit_records_admission_guard)

    @staticmethod
    def _managed_turn_record(row):
        if row is None:
            return None
        record = ManagedTurnRecord(row['operation_ref'], row['request_key'], row['unit_ref'],
            row['input_digest'], row['binding_json'], row['execution_json'], row['state'],
            row['revision'], row['receipt_json'], row['terminal_json'])
        if (record.state not in MANAGED_TURN_STATES or type(record.revision) is not int
                or record.revision < 1
                or _digest(record.binding_json) != row['binding_digest']
                or _digest(record.execution_json) != row['execution_digest']):
            raise UnitRecordsRefused('managed turn record identity is damaged')
        return record

    def _require_managed_turn(self):
        if not self.managed_turn_available:
            raise UnitRecordsRefused("managed turn records are unavailable without fresh-journal opt-in")

    def reserve_managed_turn(self, *, operation_ref, request_key, unit_ref, input_digest,
                             binding, execution_evidence):
        """Persist the one frozen prepared frame in the existing UnitRecords DB."""
        self._require_managed_turn()
        if (not isinstance(operation_ref, str) or not operation_ref
                or not isinstance(request_key, str) or not request_key
                or not isinstance(unit_ref, str) or not unit_ref
                or not isinstance(input_digest, str) or not input_digest
                or not isinstance(binding, Mapping) or not isinstance(execution_evidence, Mapping)):
            raise UnitRecordsRefused('complete managed turn reservation required')
        expected_binding = {'contractVersion', 'operationRef', 'unitRef', 'providerRef',
            'managementEpoch', 'protocol', 'nativeRequestId', 'frameDigest', 'method',
            'nativeThreadId', 'capturedInputRef', 'contentDigest'}
        if (set(binding) != expected_binding or binding['contractVersion'] != MANAGED_TURN_VERSION
                or binding['operationRef'] != operation_ref or not isinstance(binding['unitRef'], Mapping)
                or set(binding['unitRef']) != {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
                or binding['unitRef'].get('unitId') != unit_ref
                or not isinstance(binding['providerRef'], Mapping)
                or not isinstance(binding['capturedInputRef'], Mapping)
                or binding['capturedInputRef'].get('environmentNamespace') != binding['providerRef'].get('environmentNamespace')
                or binding['method'] != 'turn/start' or binding['protocol'] != 'codex-app-server/1'
                or type(binding['managementEpoch']) is not int or binding['managementEpoch'] < 0
                or not isinstance(binding['nativeRequestId'], (str, int))
                or isinstance(binding['nativeRequestId'], bool)
                or not isinstance(binding['nativeThreadId'], str) or not binding['nativeThreadId']
                or not isinstance(binding['frameDigest'], str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', binding['frameDigest'])
                or not isinstance(binding['contentDigest'], str)
                or not re.fullmatch(r'sha256:[0-9a-f]{64}', binding['contentDigest'])):
            raise UnitRecordsRefused('managed turn frame binding is invalid')
        expected_execution = {'contractVersion', 'operationRef', 'environmentNamespace',
            'principalScope', 'nodeRef', 'unitRef', 'captureRef', 'contentDigest',
            'managementEpoch', 'evidenceRef'}
        if (set(execution_evidence) != expected_execution
                or execution_evidence['operationRef'] != operation_ref
                or not isinstance(execution_evidence['nodeRef'], Mapping)
                or not isinstance(execution_evidence['unitRef'], Mapping)
                or execution_evidence['unitRef'] != binding['unitRef']
                or execution_evidence['captureRef'] != binding['capturedInputRef']
                or execution_evidence['contentDigest'] != binding['contentDigest']
                or execution_evidence['managementEpoch'] != binding['managementEpoch']
                or execution_evidence['environmentNamespace'] != binding['providerRef'].get('environmentNamespace')
                or execution_evidence['nodeRef'].get('environmentNamespace') != execution_evidence['environmentNamespace']
                or not isinstance(execution_evidence['evidenceRef'], str) or not execution_evidence['evidenceRef']):
            raise UnitRecordsRefused('Workspace execution evidence differs from the frozen turn')
        binding_json, execution_json = safe_json(binding), safe_json(execution_evidence)
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            unit = self._unit(db, unit_ref)
            if (unit.facts['providerRef'] != binding['providerRef']
                    or unit.facts['managementEpoch'] != binding['managementEpoch']):
                raise UnitRecordsRefused('managed turn differs from its original Unit owner or epoch')
            native = self._binding(db, unit_ref)
            if (native.state != 'confirmed' or native.native_facts is None
                    or native.native_facts.get('sessionId') != binding['nativeThreadId']):
                raise UnitRecordsRefused('managed turn requires the original confirmed Session')
            row = db.execute('SELECT * FROM harness_managed_turn_attempts WHERE operation_ref=?',
                             (operation_ref,)).fetchone()
            if row is not None:
                record = self._managed_turn_record(row)
                if (record.request_key != request_key or record.unit_ref != unit_ref
                        or record.input_digest != input_digest or record.binding_json != binding_json
                        or record.execution_json != execution_json):
                    raise UnitRecordsRefused('operation already binds a different native frame')
                db.commit()
                return record, False
            if db.execute('SELECT 1 FROM harness_managed_turn_attempts WHERE request_key=?',
                          (request_key,)).fetchone():
                raise UnitRecordsRefused('request key already belongs to another managed operation')
            db.execute("INSERT INTO harness_managed_turn_attempts VALUES (?,?,?,?,?,?,?,?,'reserved',1,NULL,NULL)",
                (operation_ref, request_key, unit_ref, input_digest, binding_json,
                 _digest(binding_json), execution_json, _digest(execution_json)))
            record = self._managed_turn_record(db.execute(
                'SELECT * FROM harness_managed_turn_attempts WHERE operation_ref=?', (operation_ref,)).fetchone())
            db.commit()
            return record, True

    def transition_managed_turn(self, operation_ref, *, expected_revision, state,
                                receipt=None, terminal=None):
        self._require_managed_turn()
        if state not in MANAGED_TURN_STATES - {'reserved'}:
            raise UnitRecordsRefused('invalid managed turn transition')
        receipt_json = None if receipt is None else safe_json(receipt)
        terminal_json = None if terminal is None else safe_json(terminal)
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM harness_managed_turn_attempts WHERE operation_ref=?',
                             (operation_ref,)).fetchone()
            current = self._managed_turn_record(row)
            if current is None:
                raise UnitRecordsRefused('managed turn reservation is unavailable')
            if current.state == state and current.receipt_json == receipt_json and current.terminal_json == terminal_json:
                db.commit()
                return current
            allowed = {
                'reserved': {'possibly-written', 'unknown'},
                'possibly-written': {'accepted', 'unknown'},
                'accepted': {'completed', 'failed', 'interrupted', 'unknown'},
                'unknown': set(), 'completed': set(), 'failed': set(), 'interrupted': set(),
            }
            if (type(expected_revision) is not int or current.revision != expected_revision
                    or state not in allowed[current.state]):
                raise UnitRecordsRefused('managed turn is terminal, unknown or revision-conflicted')
            if state == 'accepted':
                if current.state != 'possibly-written' or receipt is None or terminal is not None:
                    raise UnitRecordsRefused('accepted state requires its original native receipt')
                binding = current.binding
                if (set(receipt) != {'contractVersion', 'nativeRequestId', 'frameDigest',
                        'nativeThreadId', 'nativeTurnId', 'status', 'receiptDigest'}
                        or receipt['contractVersion'] != 'codex-turn-receipt/1'
                        or receipt['nativeRequestId'] != binding['nativeRequestId']
                        or receipt['frameDigest'] != binding['frameDigest']
                        or receipt['nativeThreadId'] != binding['nativeThreadId']
                        or not isinstance(receipt['nativeTurnId'], str) or not receipt['nativeTurnId']
                        or receipt['status'] != 'inProgress'):
                    raise UnitRecordsRefused('native turn receipt differs from the frozen frame')
            elif state in {'completed', 'failed', 'interrupted'}:
                if current.state != 'accepted' or terminal is None or receipt is not None:
                    raise UnitRecordsRefused('terminal requires the accepted original receipt')
                binding = current.binding
                accepted = current.receipt
                if (set(terminal) != {'contractVersion', 'nativeThreadId', 'nativeTurnId',
                        'status', 'eventDigest', 'evidenceRef'}
                        or terminal['contractVersion'] != 'codex-turn-terminal/1'
                        or terminal['nativeThreadId'] != binding['nativeThreadId']
                        or terminal['nativeTurnId'] != accepted['nativeTurnId']
                        or terminal['status'] != state or not str(terminal['eventDigest']).startswith('sha256:')
                        or not isinstance(terminal['evidenceRef'], str) or not terminal['evidenceRef']):
                    raise UnitRecordsRefused('native terminal differs from the original accepted turn')
            elif state == 'possibly-written' and (receipt is not None or terminal is not None):
                raise UnitRecordsRefused('pre-write transition cannot carry a later receipt')
            elif state == 'unknown' and terminal is not None:
                raise UnitRecordsRefused('unknown is not a native terminal fact')
            db.execute('UPDATE harness_managed_turn_attempts SET state=?,revision=?,receipt_json=?,terminal_json=? WHERE operation_ref=?',
                (state, current.revision + 1,
                 receipt_json if receipt_json is not None else current.receipt_json,
                 terminal_json if terminal_json is not None else current.terminal_json,
                 operation_ref))
            result = self._managed_turn_record(db.execute(
                'SELECT * FROM harness_managed_turn_attempts WHERE operation_ref=?', (operation_ref,)).fetchone())
            db.commit()
            return result

    def read_managed_turn(self, operation_ref, *, input_digest):
        self._require_managed_turn()
        with self.journal._connect() as db:
            row = db.execute('SELECT * FROM harness_managed_turn_attempts WHERE operation_ref=?',
                             (operation_ref,)).fetchone()
            record = self._managed_turn_record(row)
            if record is not None and record.input_digest != input_digest:
                raise UnitRecordsRefused('managed turn query digest differs from its original operation')
            return record

    @staticmethod
    def acp_prompt_input_digest(unit_ref, params):
        """Public content identity only; never grants query/write authority."""
        from .acp_turns import digest
        return digest({'unitRef':dict(unit_ref), 'params':params})

    def validate_acp_prompt_capacity(self, unit_ref, params):
        """Read-only capacity check on the original confirmed Unit/session."""
        from .acp_turns import validate_prompt_capacity
        validate_prompt_capacity(self, unit_ref, params)

    @staticmethod
    def acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_input_digest):
        from .acp_turns import digest
        return digest({'action':'query-acp-turn', 'unitRef':dict(unit_ref),
                       'operationRef':operation_ref, 'expectedPromptInputDigest':expected_prompt_input_digest})

    def query_acp_turn(self, unit_ref, operation_ref, context, *, input_digest, expected_prompt_input_digest):
        """Authorized durable read; never opens a channel or retries a turn."""
        from .acp_turns import query
        return query(self, unit_ref, operation_ref, context, input_digest=input_digest,
                     expected_prompt_input_digest=expected_prompt_input_digest)

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
        if unit_ref in self.journal.historical_unit_ids:
            raise UnitRecordsRefused('historical Unit stays fenced; reopen permits only fresh Units')
        return self._reservation(db, unit_ref)

    def _reservation(self, db, unit_ref):
        """Recheck one stored reservation; the caller decides on the fence.

        Execution paths reach this only through ``_unit`` (fenced). The one
        historical read-only projection uses it directly and never unfences the
        Unit: no live Unit object is returned and no execution path is enabled.
        """
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

    def _historical_reservation(self, db, unit_id):
        """Immutable identity of one *historical* Unit on a reopened journal.

        A reopened journal is admitted only through the verified owner/root
        reopen, which pins the namespace, file identity and schema and pins the
        canonical reservation bytes; the live scope index is deliberately not
        restored. This read therefore rechecks the persisted facts themselves
        (canonical bytes, digests, correlation, scope key and namespaces) and
        returns the immutable reservation - never a live Unit, never an
        execution path, and never a re-verified live scope mapping.
        """
        if self.journal.reopened_for_new_units is not True:
            raise UnitRecordsRefused('historical read requires the verified reopened journal')
        if unit_id not in self.journal.historical_unit_ids:
            raise UnitRecordsRefused('historical read requires a historical Unit')
        row = db.execute('SELECT * FROM harness_unit_reservations WHERE unit_ref=?',
                         (unit_id,)).fetchone()
        if row is None or row['intent_digest'] != _digest(row['intent_json']):
            raise UnitRecordsRefused("unit missing or immutable facts damaged")
        unit = UnitReservation(row['unit_ref'], row['intent_json'], row['scope_json'])
        facts = unit.facts
        if (row['correlation'] != facts['correlation']
                or safe_json(facts) != row['intent_json']
                or safe_json(unit.scope_ref.to_dict()) != row['scope_json']):
            raise UnitRecordsRefused("unit correlation or canonical facts damaged")
        namespace = unit.scope_ref.environment_namespace
        if (namespace != facts['providerRef'].get('environmentNamespace')
                or namespace != facts['nodeRef'].get('environmentNamespace')
                or not namespace):
            raise UnitRecordsRefused("unit scope namespace damaged")
        if row['scope_key'] != safe_json({'environmentNamespace': namespace,
                                          'scopeId': unit.scope_ref.scope_id}):
            raise UnitRecordsRefused("scope identity damaged")
        return unit

    def _binding(self, db, unit_ref):
        row = db.execute('SELECT * FROM harness_unit_sessions WHERE unit_ref=?', (unit_ref,)).fetchone()
        if row is None or row['state'] not in ('notCreated', 'opening', 'unknown', 'confirmed'):
            raise UnitRecordsRefused("session binding missing or damaged")
        if type(row['source_revision']) is not int or row['source_revision'] < 1:
            raise UnitRecordsRefused("binding revision damaged")
        try:
            native = None if row['native_json'] is None else json.loads(row['native_json'])
        except (TypeError, ValueError):
            raise UnitRecordsRefused('binding native evidence damaged') from None
        association = isinstance(native, Mapping) and native.get('contractVersion') == INPUT_SESSION_ASSOCIATION_VERSION
        if (native is not None and (not isinstance(native, Mapping)
                or not association and set(native) != {'nativeRealm', 'sessionId', 'evidenceRef'})):
            raise UnitRecordsRefused('binding native evidence version or fields damaged')
        if ((row['state'] == 'notCreated' and row['source_revision'] != 1)
                or (row['state'] == 'opening' and row['source_revision'] != 2)
                or (row['state'] == 'unknown' and row['source_revision'] < 3)
                or (row['state'] == 'confirmed' and row['source_revision'] != 2 and association)
                or (row['state'] == 'confirmed' and row['source_revision'] < 3 and not association)):
            raise UnitRecordsRefused('binding state and revision damaged')
        if ((row['state'] == 'notCreated') != (row['creation_correlation'] is None)
                or (row['state'] == 'confirmed') != (row['native_json'] is not None)
                or ((row['native_json'] is None) != (row['native_digest'] is None))
                or (row['native_json'] is not None and row['native_digest'] != _digest(row['native_json']))):
            raise UnitRecordsRefused("binding identity or evidence damaged")
        if row['state'] == 'confirmed':
            unit = self._unit(db, unit_ref)
            if association:
                if (set(native) != {'contractVersion', 'identity', 'nativeBinding', 'evidenceRef', 'associationRef'}
                        or not isinstance(native['identity'], Mapping)):
                    raise UnitRecordsRefused('Session association envelope damaged')
                self._check_association_identity(unit, native['identity'])
                if _correlation(native['identity']) != row['creation_correlation']:
                    raise UnitRecordsRefused('Session association correlation damaged')
                confirmed_unit = self._unit_confirmation(db, unit_ref)
                if (confirmed_unit.state != 'confirmed'
                        or safe_json(confirmed_unit.native_facts['evidenceRef']) != safe_json(native['identity']['unitConfirmationRef'])):
                    raise UnitRecordsRefused('Session association original Unit confirmation changed')
                verified = self._association_proof(unit, native['identity'], native['evidenceRef'])
            else:
                if not isinstance(native, dict) or not isinstance(native.get('evidenceRef'), str):
                    raise UnitRecordsRefused("binding native evidence damaged")
                verified = safe_json(self.native_evidence.verify_binding(unit, row['creation_correlation'], native['evidenceRef']))
            if verified != row['native_json']:
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
            db.execute('INSERT INTO harness_unit_confirmations VALUES (?,?,?,?,?,?,?)',
                       (unit.unit_ref, 'notCreated', 1, None, None, None, None))
            db.commit()
            return unit, True

    def begin_session(self, unit_ref, context, *, input_digest):
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            unit = self._unit(db, unit_ref)
            confirmation = db.execute('SELECT state FROM harness_unit_confirmations WHERE unit_ref=?', (unit_ref,)).fetchone()
            if confirmation is not None and self._unit_confirmation(db, unit_ref).state != 'notCreated':
                raise UnitRecordsRefused('original native Unit creation retains the start fence')
            binding = self._binding(db, unit_ref)
            if binding.state != 'notCreated':
                raise UnitRecordsRefused("existing native creation cannot be dispatched again")
            facts = self._authorize(context, 'start', unit.facts['providerRef'], unit.facts['nodeRef'], input_digest)
            if facts['managementEpoch'] != unit.facts['managementEpoch']:
                raise UnitRecordsRefused("unit management epoch changed")
            correlation = _correlation(facts)
            db.execute("UPDATE harness_unit_sessions SET state='opening',source_revision=2,creation_correlation=? WHERE unit_ref=?",
                       (correlation, unit_ref))
            db.commit()
        ticket = object.__new__(RecordTicket)
        self._tickets[id(ticket)] = (ticket, unit, correlation, input_digest, facts['managementEpoch'])
        return ticket

    def _unit_proof(self, unit, correlation, evidence):
        port = self.native_unit_evidence
        if not callable(getattr(port, 'verify_unit_binding', None)):
            raise UnitRecordsRefused('native Unit evidence owner is absent')
        proof = port.verify_unit_binding(unit, correlation, evidence)
        fields = {'contractVersion', 'unitRef', 'creationCorrelation', 'processRef',
                  'transportRef', 'initializationRef', 'evidenceRef'}
        if (not isinstance(proof, Mapping) or set(proof) != fields
                or proof['contractVersion'] != UNIT_CONFIRMATION_VERSION
                or not isinstance(proof['unitRef'], Mapping)
                or safe_json(proof['unitRef']) != safe_json(unit.public_ref)
                or proof['creationCorrelation'] != correlation):
            raise UnitRecordsRefused('native Unit proof identity differs')
        for name in ('processRef', 'transportRef', 'initializationRef', 'evidenceRef'):
            ref = proof[name]
            if (not isinstance(ref, Mapping)
                    or set(ref) != {'environmentNamespace', 'ownerProviderRef', 'sourceRevision', 'ref'}
                    or ref['environmentNamespace'] != unit.scope_ref.environment_namespace
                    or not isinstance(ref['ownerProviderRef'], Mapping)
                    or safe_json(ref['ownerProviderRef']) != safe_json(unit.facts['providerRef'])
                    or any(not isinstance(ref[key], str) or not ref[key] or len(ref[key]) > 256
                           or any(ord(c) < 32 for c in ref[key]) for key in ('sourceRevision', 'ref'))):
                raise UnitRecordsRefused('native Unit proof provenance differs')
        return safe_json(proof)

    def _unit_confirmation(self, db, unit_ref):
        row = db.execute('SELECT * FROM harness_unit_confirmations WHERE unit_ref=?', (unit_ref,)).fetchone()
        if (row is None or row['state'] not in ('notCreated', 'opening', 'unknown', 'confirmed')
                or type(row['source_revision']) is not int or row['source_revision'] < 1
                or (row['state'] == 'notCreated' and row['source_revision'] != 1)
                or (row['state'] == 'opening' and row['source_revision'] != 2)
                or (row['state'] in ('unknown', 'confirmed') and row['source_revision'] < 3)
                or ((row['state'] == 'notCreated') != (row['creation_correlation'] is None))
                or ((row['state'] == 'notCreated') != (row['input_digest'] is None))
                or (row['input_digest'] is not None and (not isinstance(row['input_digest'], str) or not row['input_digest']))
                or ((row['state'] == 'confirmed') != (row['native_json'] is not None))
                or ((row['native_json'] is None) != (row['native_digest'] is None))):
            raise UnitRecordsRefused('native Unit confirmation missing or damaged')
        if row['native_json'] is not None:
            if row['native_digest'] != _digest(row['native_json']):
                raise UnitRecordsRefused('native Unit confirmation digest differs')
            proof = json.loads(row['native_json'])
            if self._unit_proof(self._unit(db, unit_ref), row['creation_correlation'], proof['evidenceRef']) != row['native_json']:
                raise UnitRecordsRefused('native Unit confirmation differs from owner evidence')
        return NativeUnitBinding(unit_ref, row['state'], row['source_revision'],
                                    row['creation_correlation'], row['native_json'], row['input_digest'])

    def begin_unit(self, unit_ref, context, *, input_digest):
        """Consume the original start once without creating a fake session."""
        if not callable(getattr(self.native_unit_evidence, 'verify_unit_binding', None)):
            raise UnitRecordsRefused('native Unit evidence owner is absent')
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            unit = self._unit(db, unit_ref)
            binding = self._unit_confirmation(db, unit_ref)
            if binding.state != 'notCreated' or self._binding(db, unit_ref).state != 'notCreated':
                raise UnitRecordsRefused('original native creation retains the start fence')
            facts = self._authorize(context, 'start', unit.facts['providerRef'], unit.facts['nodeRef'], input_digest)
            if facts['managementEpoch'] != unit.facts['managementEpoch']:
                raise UnitRecordsRefused('unit management epoch changed')
            correlation = _correlation(facts)
            db.execute("UPDATE harness_unit_confirmations SET state='opening',source_revision=2,creation_correlation=?,input_digest=? WHERE unit_ref=?", (correlation, input_digest, unit_ref))
            db.commit()
        ticket = object.__new__(UnitRecordTicket)
        self._tickets[id(ticket)] = (ticket, unit, correlation, input_digest, facts['managementEpoch'])
        return ticket

    def record_unit(self, ticket, *, expected_source_revision, state, evidence=None):
        entry = self._tickets.get(id(ticket))
        if type(ticket) is not UnitRecordTicket or entry is None or entry[0] is not ticket:
            raise UnitRecordsRefused('native Unit ticket is not owned by this journal instance')
        _, unit, correlation, input_digest, epoch = entry
        if self._epoch(unit.facts['nodeRef']) != epoch:
            raise UnitRecordsRefused('native Unit ticket epoch expired')
        if state not in ('unknown', 'confirmed') or (state == 'unknown' and evidence is not None):
            raise UnitRecordsRefused('native Unit ticket cannot restart or invent confirmation')
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._unit(db, unit.unit_ref) != unit:
                raise UnitRecordsRefused('native Unit changed after ticket issuance')
            binding = self._unit_confirmation(db, unit.unit_ref)
            if (type(expected_source_revision) is not int or binding.source_revision != expected_source_revision
                    or binding.creation_correlation != correlation or binding.state not in ('opening', 'unknown')):
                raise UnitRecordsRefused('native Unit terminal, changed, or revision conflict')
            if binding.input_digest != input_digest:
                raise UnitRecordsRefused('native Unit original input digest differs')
            native = self._unit_proof(unit, correlation, evidence) if state == 'confirmed' else None
            db.execute('UPDATE harness_unit_confirmations SET state=?,source_revision=?,native_json=?,native_digest=? WHERE unit_ref=?',
                       (state, binding.source_revision + 1, native, None if native is None else _digest(native), unit.unit_ref))
            db.commit()
            result = self._unit_confirmation(db, unit.unit_ref)
        if state == 'confirmed':
            del self._tickets[id(ticket)]
        return result

    def read_unit_confirmation(self, unit_ref, context, *, input_digest):
        self.read_unit(unit_ref, context, input_digest=input_digest)
        with self.journal._connect() as db:
            return self._unit_confirmation(db, unit_ref)

    def reconcile_unit_confirmation(self, unit_ref, context, *, input_digest,
                                    expected_source_revision, evidence):
        """Read original owner evidence under query authority; never restart.

        Cold reconciliation updates only this journal's original observation,
        issues no creation ticket and cannot substitute another start step.
        """
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            unit = self._unit(db, unit_ref)
            facts = self._authorize(context, 'query', unit.facts['providerRef'],
                                    unit.facts['nodeRef'], input_digest, query=True)
            binding = self._unit_confirmation(db, unit_ref)
            if binding.creation_correlation != _correlation(facts):
                raise UnitRecordsRefused('query is not the original native Unit start')
            if binding.input_digest != input_digest:
                raise UnitRecordsRefused('query is not the original native Unit input')
            if (type(expected_source_revision) is not int
                    or binding.source_revision != expected_source_revision):
                raise UnitRecordsRefused('native Unit observation revision conflict')
            if binding.state == 'confirmed':
                return binding  # Original proof already reverified; no replacement.
            if binding.state not in ('opening', 'unknown'):
                raise UnitRecordsRefused('native Unit start has not been claimed')
            native = self._unit_proof(unit, binding.creation_correlation, evidence)
            db.execute("UPDATE harness_unit_confirmations SET state='confirmed',source_revision=?,native_json=?,native_digest=? WHERE unit_ref=?",
                       (binding.source_revision + 1, native, _digest(native), unit_ref))
            db.commit()
            return self._unit_confirmation(db, unit_ref)

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

    def owner_read_unit(self, unit_ref):
        """Owner-trusted unit projection; consumes no invocation.

        The single records owner reads its own immutable journal facts for the
        provider's trusted projection. This issues no claim, ticket or effect
        permission and never substitutes for an authorized read.
        """
        with self.journal._connect() as db:
            return self._unit(db, unit_ref)

    def owner_read_unit_for_query(self, unit_ref):
        """Pure identity read of one reservation, for historical ACP queries.

        The caller names the complete public UnitRef; it must be exactly the
        reservation's own immutable reference. This reuses the historical
        read-only checks (canonical bytes, digests, correlation, scope and the
        full UnitRef) without the execution fence - and without clearing it:
        the return value is the immutable ``UnitReservation`` (identity only),
        never a live Unit, a permission or an execution path.
        """
        if (not isinstance(unit_ref, Mapping)
                or set(unit_ref) != {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
                or not isinstance(unit_ref['unitId'], str) or not unit_ref['unitId']):
            raise UnitRecordsRefused('complete owner-bound Unit reference required')
        with self.journal._connect() as db:
            unit_id = unit_ref['unitId']
            if unit_id in self.journal.historical_unit_ids:
                unit = self._historical_reservation(db, unit_id)
            else:
                unit = self._unit(db, unit_id)
        if safe_json(unit_ref) != safe_json(unit.public_ref):
            raise UnitRecordsRefused('Unit reference differs from original owner source')
        return unit

    def owner_read_session(self, unit_ref):
        """Owner-trusted session projection; consumes no invocation."""
        with self.journal._connect() as db:
            self._unit(db, unit_ref)
            return self._binding(db, unit_ref)

    def owner_read_unit_confirmation(self, unit_ref):
        """Owner-trusted Unit confirmation projection; consumes no invocation."""
        with self.journal._connect() as db:
            self._unit(db, unit_ref)
            return self._unit_confirmation(db, unit_ref)

    def _termination_identity(self, unit, action, correlation, input_digest):
        return safe_json({'action': action, 'correlation': correlation,
                          'inputDigest': input_digest, 'unitRef': unit.public_ref})

    def _termination_proof(self, unit, action, correlation, evidence):
        if not callable(getattr(self.termination_evidence, 'verify_termination', None)):
            raise UnitRecordsRefused('termination evidence owner is absent')
        try:
            refs = self.termination_evidence.verify_termination(unit, action, correlation, evidence)
        except UnitRecordsRefused:
            raise
        except Exception:
            raise UnitRecordsRefused('termination evidence missing or forged') from None
        if (not isinstance(refs, Mapping) or not refs
                or any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
                       for key, value in refs.items())):
            raise UnitRecordsRefused('termination evidence owner must return provenance refs')
        return safe_json(dict(refs))

    def begin_termination(self, unit_ref, context, *, input_digest, action):
        """Claim the one original stop/release attempt for this Unit.

        The unified termination face for every family: one live ticket per
        Unit and action, ever. Unknown outcomes keep the attempt and its
        hold; nothing is released automatically and no family may grow a
        second termination ledger.
        """
        if action not in TERMINATION_ACTIONS:
            raise UnitRecordsRefused('termination action must be stop or release')
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            unit = self._unit(db, unit_ref)
            facts = self._authorize(context, action, unit.facts['providerRef'],
                                    unit.facts['nodeRef'], input_digest)
            if facts['managementEpoch'] != unit.facts['managementEpoch']:
                raise UnitRecordsRefused('unit management epoch changed')
            correlation = _correlation(facts)
            identity = self._termination_identity(unit, action, correlation, input_digest)
            existing = db.execute(
                'SELECT * FROM harness_unit_terminations WHERE (unit_ref=? AND action=?) OR correlation=?',
                (unit.unit_ref, action, correlation)).fetchall()
            for row in existing:
                if (row['identity_digest'] != _digest(row['identity_json'])
                        or safe_json(json.loads(row['identity_json'])) != identity):
                    raise UnitRecordsRefused('different termination attempt is already recorded')
                raise UnitRecordsRefused('termination attempt already claimed')
            try:
                db.execute(
                    'INSERT INTO harness_unit_terminations(unit_ref, action, correlation, '
                    'identity_json, identity_digest, state, source_revision) VALUES(?,?,?,?,?,\'opening\',1)',
                    (unit.unit_ref, action, correlation, identity, _digest(identity)))
            except Exception:
                raise UnitRecordsRefused('termination attempt collides with another record') from None
            db.commit()
        ticket = object.__new__(TerminationRecordTicket)
        self._termination_tickets[id(ticket)] = (
            ticket, unit, action, correlation, input_digest, facts['managementEpoch'])
        return ticket

    def record_termination(self, ticket, *, expected_source_revision, state, evidence=None):
        """Record the original stop/release outcome: confirmed or unknown.

        Confirmed stores the owner evidence port's returned provenance refs,
        never caller-supplied strings. Unknown keeps the attempt, its hold
        and its live ticket; nothing here releases Usages or kills
        processes — the caller owns those effects and their proof.
        """
        entry = self._termination_tickets.get(id(ticket))
        if type(ticket) is not TerminationRecordTicket or entry is None or entry[0] is not ticket:
            raise UnitRecordsRefused('termination ticket is not owned by this journal instance')
        _, unit, action, correlation, input_digest, epoch = entry
        if state not in ('unknown', 'confirmed') or (state == 'unknown' and evidence is not None):
            raise UnitRecordsRefused('termination ticket cannot invent or replace its outcome')
        supplied = None if evidence is None else dict(evidence)
        if state == 'confirmed' and (
                not isinstance(evidence, Mapping) or not supplied
                or any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
                       for key, value in supplied.items())):
            raise UnitRecordsRefused('confirmed termination requires owner evidence refs')
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if self._epoch(unit.facts['nodeRef']) != epoch:
                raise UnitRecordsRefused('termination ticket epoch expired')
            if self._unit(db, unit.unit_ref) != unit:
                raise UnitRecordsRefused('unit changed after termination ticket issuance')
            row = db.execute(
                'SELECT * FROM harness_unit_terminations WHERE unit_ref=? AND action=?',
                (unit.unit_ref, action)).fetchone()
            if (row is None or type(expected_source_revision) is not int
                    or row['source_revision'] != expected_source_revision
                    or row['correlation'] != correlation
                    or row['state'] not in ('opening', 'unknown')):
                raise UnitRecordsRefused('termination terminal, changed, or revision conflict')
            # Re-bind the stored identity to these exact ticket facts and
            # validate the row before any write, so a refused call can never
            # leave an already-committed outcome behind.
            expected_identity = self._termination_identity(unit, action, correlation, input_digest)
            self._check_termination_row(db, unit, action, expected_identity, row)
            outcome = (None if state == 'unknown'
                       else self._termination_proof(unit, action, correlation, supplied))
            db.execute(
                'UPDATE harness_unit_terminations SET state=?, source_revision=?, outcome_json=?, '
                'outcome_digest=? WHERE unit_ref=? AND action=?',
                (state, row['source_revision'] + 1, outcome,
                 None if outcome is None else _digest(outcome), unit.unit_ref, action))
            db.commit()
            result = self._termination_record(db, unit.unit_ref, action, expected_identity)
        if state == 'confirmed':
            del self._termination_tickets[id(ticket)]
        return result

    def reconcile_termination(self, unit_ref, context, *, input_digest, action,
                              expected_source_revision, state, evidence=None):
        """Cold recovery: authorized query reconciliation, never a new claim.

        After a restart the original ticket is gone; this revalidates the
        original correlation under query authority and may conclude the
        retained attempt with owner evidence. It never re-arms a dispatch,
        never fabricates an opening and never releases anything.
        """
        if action not in TERMINATION_ACTIONS:
            raise UnitRecordsRefused('termination action must be stop or release')
        if state not in ('unknown', 'confirmed') or (state == 'unknown' and evidence is not None):
            raise UnitRecordsRefused('termination reconciliation cannot invent an outcome')
        supplied = None if evidence is None else dict(evidence)
        if state == 'confirmed' and (
                not isinstance(evidence, Mapping) or not supplied
                or any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
                       for key, value in supplied.items())):
            raise UnitRecordsRefused('confirmed termination requires owner evidence refs')
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            unit = self._unit(db, unit_ref)
            facts = self._authorize(context, 'query', unit.facts['providerRef'],
                                    unit.facts['nodeRef'], input_digest, query=True)
            correlation = _correlation(facts)
            row = db.execute(
                'SELECT * FROM harness_unit_terminations WHERE unit_ref=? AND action=?',
                (unit.unit_ref, action)).fetchone()
            if row is None:
                raise UnitRecordsRefused('termination attempt was never claimed')
            if correlation != row['correlation']:
                raise UnitRecordsRefused('query is not the original termination attempt')
            expected_identity = self._termination_identity(unit, action, correlation, input_digest)
            self._check_termination_row(db, unit, action, expected_identity, row)
            if (type(expected_source_revision) is not int
                    or row['source_revision'] != expected_source_revision
                    or row['state'] not in ('opening', 'unknown')):
                raise UnitRecordsRefused('termination terminal, changed, or revision conflict')
            outcome = (None if state == 'unknown'
                       else self._termination_proof(unit, action, correlation, supplied))
            db.execute(
                'UPDATE harness_unit_terminations SET state=?, source_revision=?, outcome_json=?, '
                'outcome_digest=? WHERE unit_ref=? AND action=?',
                (state, row['source_revision'] + 1, outcome,
                 None if outcome is None else _digest(outcome), unit.unit_ref, action))
            db.commit()
            return self._termination_record(db, unit.unit_ref, action, expected_identity)

    def owner_read_termination(self, unit_ref, action):
        """Owner-trusted termination projection; consumes no invocation."""
        if action not in TERMINATION_ACTIONS:
            raise UnitRecordsRefused('termination action must be stop or release')
        with self.journal._connect() as db:
            if unit_ref in self.journal.historical_unit_ids:
                # A reopened journal keeps every historical Unit fenced for
                # execution; the stop/release proof itself is still the owner's
                # own record, so it is projected read-only from that record.
                return self._historical_termination(db, unit_ref, action)
            unit = self._unit(db, unit_ref)
            row = db.execute(
                'SELECT * FROM harness_unit_terminations WHERE unit_ref=? AND action=?',
                (unit.unit_ref, action)).fetchone()
            if row is None:
                return None
            return self._termination_record(db, unit.unit_ref, action, row=row)

    def _historical_termination(self, db, unit_ref, action):
        """Read-only termination projection for one historical (fenced) Unit.

        The reservation is rechecked exactly as ``_unit`` does (canonical bytes,
        digests, correlation, scope key and the complete UnitRef), but the
        historical fence is deliberately not cleared: this branch returns no
        live Unit, enables no execution path, calls no termination validator and
        writes nothing. The stored identity must be the same identity those
        facts imply, and a ``confirmed`` action must still carry the original
        persisted, non-empty proof.
        """
        unit = self._historical_reservation(db, unit_ref)
        row = db.execute(
            'SELECT * FROM harness_unit_terminations WHERE unit_ref=? AND action=?',
            (unit.unit_ref, action)).fetchone()
        if row is None:
            return None
        try:
            stored = json.loads(row['identity_json'])
        except Exception:
            raise UnitRecordsRefused('termination record is damaged') from None
        if (not isinstance(stored, Mapping)
                or set(stored) != {'action', 'correlation', 'inputDigest', 'unitRef'}
                or row['identity_digest'] != _digest(row['identity_json'])
                or row['state'] not in ('opening', 'unknown', 'confirmed')
                or type(row['source_revision']) is not int
                or (row['state'] == 'opening') != (row['source_revision'] == 1)
                or row['source_revision'] < 1
                or row['action'] != action
                or stored.get('action') != action
                or stored.get('correlation') != row['correlation']
                or not isinstance(stored.get('inputDigest'), str) or not stored['inputDigest']
                or not isinstance(stored.get('unitRef'), Mapping)
                or safe_json(stored['unitRef']) != safe_json(unit.public_ref)):
            raise UnitRecordsRefused('termination record is damaged')
        # The stored identity must be exactly the one these reservation facts
        # imply: same action, same correlation, the same input digest and the
        # complete UnitRef. A rewritten identity is damage, not a new attempt.
        expected_identity = safe_json({'action': action,
                                       'correlation': row['correlation'],
                                       'inputDigest': stored['inputDigest'],
                                       'unitRef': unit.public_ref})
        if safe_json(stored) != expected_identity:
            raise UnitRecordsRefused('termination record is damaged')
        if row['state'] == 'confirmed' and (
                row['outcome_json'] is None or row['outcome_digest'] is None
                or not row['outcome_json']):
            raise UnitRecordsRefused('confirmed termination lacks persisted proof')
        return self._termination_record(db, unit.unit_ref, action,
                                        expected_identity=expected_identity, row=row)

    def _check_termination_row(self, db, unit, action, expected_identity, row):
        try:
            stored = json.loads(row['identity_json'])
        except Exception:
            raise UnitRecordsRefused('termination record is damaged') from None
        if (row['identity_digest'] != _digest(row['identity_json'])
                or row['state'] not in ('opening', 'unknown', 'confirmed')
                or type(row['source_revision']) is not int or row['source_revision'] < 1
                or type(row['action']) is not str or row['action'] != action
                or not isinstance(stored, Mapping)
                or stored.get('correlation') != row['correlation']
                or stored.get('action') != row['action']
                or safe_json(stored) != expected_identity):
            raise UnitRecordsRefused('termination record is damaged')

    def _termination_record(self, db, unit_ref, action, expected_identity=None, row=None):
        if row is None:
            row = db.execute(
                'SELECT * FROM harness_unit_terminations WHERE unit_ref=? AND action=?',
                (unit_ref, action)).fetchone()
            if row is None:
                return None
        if expected_identity is None:
            try:
                expected_identity = safe_json(json.loads(row['identity_json']))
            except Exception:
                raise UnitRecordsRefused('termination record is damaged') from None
        self._check_termination_row(db, None, row['action'], expected_identity, row)
        if ((row['outcome_json'] is None) != (row['outcome_digest'] is None)
                or (row['outcome_json'] is not None
                    and row['outcome_digest'] != _digest(row['outcome_json']))):
            raise UnitRecordsRefused('termination record is damaged')
        outcome = None
        if row['outcome_json'] is not None:
            try:
                outcome = json.loads(row['outcome_json'])
            except Exception:
                raise UnitRecordsRefused('termination record is damaged') from None
            if (not isinstance(outcome, Mapping) or not outcome
                    or any(not isinstance(key, str) or not key or not isinstance(value, str) or not value
                           for key, value in outcome.items())):
                raise UnitRecordsRefused('termination record is damaged')
        return {'version': TERMINATION_VERSION, 'projection': 'owner-read',
                'action': row['action'], 'state': row['state'],
                'sourceRevision': row['source_revision'],
                'identity': sealed_mapping(json.loads(row['identity_json'])),
                'outcome': None if outcome is None else sealed_mapping(outcome)}

    def _check_association_identity(self, unit, identity):
        fields = {'request', 'operationRef', 'stepId', 'inputDigest', 'providerRef', 'unitRef',
                  'nodeRef', 'managementEpoch', 'nativeCorrelation', 'unitConfirmationRef', 'sessionAbsenceRef', 'capturedInputRef'}
        if (not isinstance(identity, Mapping) or set(identity) != fields
                or identity['stepId'] != 'native-input'
                or any(not isinstance(identity[key], str) or not identity[key] for key in ('operationRef', 'inputDigest'))
                or type(identity['managementEpoch']) is not int or identity['managementEpoch'] < 0
                or any(not isinstance(identity[key], Mapping) for key in ('unitRef', 'providerRef', 'nodeRef'))
                or safe_json(identity['unitRef']) != safe_json(unit.public_ref)
                or safe_json(identity['providerRef']) != safe_json(unit.facts['providerRef'])
                or safe_json(identity['nodeRef']) != safe_json(unit.facts['nodeRef'])):
            raise UnitRecordsRefused('original input association identity differs')
        request = identity['request']
        correlation = identity['nativeCorrelation']
        environment = unit.scope_ref.environment_namespace
        if (not isinstance(request, Mapping) or set(request) != {'environmentNamespace', 'principalScope', 'requestId'}
                or request['environmentNamespace'] != environment
                or any(not isinstance(request[key], str) or not request[key] for key in ('principalScope', 'requestId'))
                or not isinstance(correlation, Mapping)
                or set(correlation) != {'environmentNamespace', 'protocol', 'requestId'}
                or correlation['environmentNamespace'] != environment
                or not isinstance(correlation['protocol'], str) or not correlation['protocol']
                or type(correlation['requestId']) not in (str, int)
                or correlation['requestId'] == ''):
            raise UnitRecordsRefused('original input native correlation differs')
        for ref in (identity['unitConfirmationRef'], identity['sessionAbsenceRef']):
            self._association_source(unit, ref)
        captured = identity['capturedInputRef']
        if (not isinstance(captured, Mapping)
                or set(captured) != {'environmentNamespace', 'captureId', 'captureRevision', 'contentDigest'}
                or captured['environmentNamespace'] != environment
                or not isinstance(captured['captureId'], str) or not re.fullmatch(r'[a-z][a-z0-9._-]{0,63}', captured['captureId'])
                or type(captured['captureRevision']) is not int or captured['captureRevision'] < 1
                or not isinstance(captured['contentDigest'], str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', captured['contentDigest'])):
            raise UnitRecordsRefused('original captured input source differs')

    @staticmethod
    def _association_source(unit, ref):
        if (not isinstance(ref, Mapping)
                or set(ref) != {'environmentNamespace', 'ownerProviderRef', 'sourceRevision', 'ref'}
                or ref['environmentNamespace'] != unit.scope_ref.environment_namespace
                or not isinstance(ref['ownerProviderRef'], Mapping)
                or safe_json(ref['ownerProviderRef']) != safe_json(unit.facts['providerRef'])
                or any(not isinstance(ref[key], str) or not ref[key] or len(ref[key]) > 256
                       or any(ord(c) < 32 for c in ref[key]) for key in ('sourceRevision', 'ref'))):
            raise UnitRecordsRefused('input association owner source differs')

    def _association_proof(self, unit, identity, evidence):
        port = self.input_association_evidence
        if not callable(getattr(port, 'verify_association', None)):
            raise UnitRecordsRefused('original input association evidence owner unavailable')
        proof = port.verify_association(unit, identity, evidence)
        if (not isinstance(proof, Mapping)
                or set(proof) != {'contractVersion', 'identity', 'nativeBinding', 'evidenceRef', 'associationRef'}
                or proof['contractVersion'] != INPUT_SESSION_ASSOCIATION_VERSION
                or not isinstance(proof['identity'], Mapping)
                or safe_json(proof['identity']) != safe_json(identity)):
            raise UnitRecordsRefused('original input association proof identity differs')
        native = proof['nativeBinding']
        if (not isinstance(native, Mapping) or set(native) != {'nativeRealm', 'sessionId', 'evidenceRef'}
                or any(not isinstance(native[key], str) or not native[key] for key in native)
                or native['sessionId'] == 'default'):
            raise UnitRecordsRefused('actual input-associated Session proof required')
        self._association_source(unit, proof['evidenceRef'])
        self._association_source(unit, proof['associationRef'])
        return safe_json(proof)

    def _input_association_identity(self, db, unit, context, input_digest):
        if (not callable(getattr(self.input_association_evidence, 'verify_association', None))
                or not callable(getattr(self.verifier, 'verify_claimed_query', None))):
            raise UnitRecordsRefused('original input association/query owner unavailable')
        facts = self._authorize(context, 'query', unit.facts['providerRef'], unit.public_ref,
                                input_digest, query=True, epoch_target=unit.facts['nodeRef'])
        claimed = self.verifier.verify_claimed_query(context, unit.facts['providerRef'], unit.public_ref, input_digest,
                                                    operation_kind='managed-input')
        if safe_json(claimed) != safe_json(facts):
            raise UnitRecordsRefused('original claimed query facts differ')
        fixed = facts['contextRef']
        binding = fixed.get('sessionlessInputBinding')
        if (not {'nodeRef', 'nativeCorrelation', 'capturedInputRef'} <= set(fixed)
                or not isinstance(binding, Mapping)
                or set(binding) != {'contractVersion', 'unitRef', 'unitConfirmationRef', 'sessionAbsenceRef'}
                or binding['contractVersion'] != SESSIONLESS_INPUT_VERSION
                or not isinstance(binding['unitRef'], Mapping)
                or safe_json(binding['unitRef']) != safe_json(unit.public_ref)):
            raise UnitRecordsRefused('original sessionless input binding unavailable')
        invocations = fixed.get('invocationBindings')
        original_input = invocations.get('native-input') if isinstance(invocations, Mapping) else None
        expected_input = {'action': 'submitInput', 'targetRef': unit.public_ref, 'delegationRef': None, 'cleanup': False}
        if safe_json({'binding': original_input}) != safe_json({'binding': expected_input}):
            raise UnitRecordsRefused('claimed operation is not the original full Unit input')
        identity = {'request': facts['request'], 'operationRef': facts['operationRef'], 'stepId': facts['stepId'],
                    'inputDigest': input_digest, 'providerRef': facts['providerRef'], 'unitRef': binding['unitRef'],
                    'nodeRef': fixed['nodeRef'], 'managementEpoch': facts['managementEpoch'],
                    'nativeCorrelation': fixed['nativeCorrelation'], 'unitConfirmationRef': binding['unitConfirmationRef'],
                    'sessionAbsenceRef': binding['sessionAbsenceRef'], 'capturedInputRef': fixed['capturedInputRef']}
        self._check_association_identity(unit, identity)
        confirmation = self._unit_confirmation(db, unit.unit_ref)
        if (confirmation.state != 'confirmed'
                or safe_json(confirmation.native_facts['evidenceRef']) != safe_json(identity['unitConfirmationRef'])):
            raise UnitRecordsRefused('original confirmed Unit input source differs')
        return identity

    def query_input_session(self, unit_ref, context, *, input_digest):
        """Observe only the original claimed first-input association, no start."""
        with self.journal._connect() as db:
            unit = self._unit(db, unit_ref)
            identity = self._input_association_identity(db, unit, context, input_digest)
            binding = self._binding(db, unit_ref)
            if binding.state == 'notCreated':
                return binding
            if (binding.association_facts is None
                    or safe_json(binding.association_facts['identity']) != safe_json(identity)):
                raise UnitRecordsRefused('Session belongs to a different original input')
            self._input_association_identity(db, unit, context, input_digest)
            return binding

    def reconcile_input_session(self, unit_ref, context, *, input_digest, expected_source_revision, evidence):
        """Record original owner Session evidence; never create a dispatch ticket.

        A confirmed Session identity does not conclude the input effect, task or
        core operation. Its first-input hold remains until verified publication.
        """
        with self.journal._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            unit = self._unit(db, unit_ref)
            identity = self._input_association_identity(db, unit, context, input_digest)
            binding = self._binding(db, unit_ref)
            if type(expected_source_revision) is not int or binding.source_revision != expected_source_revision:
                raise UnitRecordsRefused('input Session association revision conflict')
            if binding.association_facts is not None:
                if safe_json(binding.association_facts['identity']) != safe_json(identity):
                    raise UnitRecordsRefused('Session belongs to a different original input')
                if self._association_proof(unit, identity, evidence) != binding.native_json:
                    raise UnitRecordsRefused('Session association proof cannot replace original evidence')
                self._input_association_identity(db, unit, context, input_digest)
                return binding  # Original owner proof reverified; never replace it.
            if binding.state != 'notCreated':
                raise UnitRecordsRefused('original Session creation retains its fence')
            native = self._association_proof(unit, identity, evidence)
            # Owner receipt verification can revoke authority; recheck the same
            # opaque query and original claim before the record-only write.
            if safe_json(self._input_association_identity(db, unit, context, input_digest)) != safe_json(identity):
                raise UnitRecordsRefused('input association authority changed during observation')
            db.execute("UPDATE harness_unit_sessions SET state='confirmed',source_revision=2,creation_correlation=?,native_json=?,native_digest=? WHERE unit_ref=?",
                       (_correlation(identity), native, _digest(native), unit_ref))
            db.commit()
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
