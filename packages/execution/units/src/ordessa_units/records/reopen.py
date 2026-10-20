"""Validate an existing journal for new Units; never recover an old capability.

The trusted host retains its exclusive root lock and supplies a live validator.
This module validates existing bytes only. It creates no schema, owner manifest,
ticket, session, process or permission, and cannot release a historical Use.
"""
import json
import sqlite3
from types import SimpleNamespace

from ordessa_infrastructure.encoding.immutable_json import safe_json


def validate_existing_journal(path, namespace, *, managed_turn_opt_in, acp_turn_opt_in):
    from .operation_journal import BASE_SCHEMA_SQL, JournalError
    from .unit_records import UNIT_SCHEMA_SQL, MANAGED_SCHEMA_SQL, UnitReservation, _digest
    from .acp_turns import ACP_SCHEMA_SQL, _check

    expected = sqlite3.connect(':memory:')
    actual = None
    try:
        expected.executescript(';\n'.join((BASE_SCHEMA_SQL, UNIT_SCHEMA_SQL,
            MANAGED_SCHEMA_SQL if managed_turn_opt_in else '',
            ACP_SCHEMA_SQL if acp_turn_opt_in else '')))
        actual = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
        actual.row_factory = sqlite3.Row
        actual.execute('PRAGMA query_only=ON')
        actual.execute('BEGIN')
        def schema(connection):
            return tuple(tuple(row) for row in connection.execute(
                'SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name'))
        if (schema(actual) != schema(expected)
                or tuple(tuple(r) for r in actual.execute('PRAGMA integrity_check')) != (('ok',),)
                or actual.execute('PRAGMA foreign_key_check').fetchone() is not None):
            raise JournalError('existing journal schema or integrity differs')
        units = {}
        for row in actual.execute('SELECT * FROM harness_unit_reservations'):
            unit = UnitReservation(row['unit_ref'], row['intent_json'], row['scope_json'])
            facts = unit.facts
            if (row['intent_digest'] != _digest(row['intent_json'])
                    or safe_json(facts) != row['intent_json']
                    or safe_json(unit.scope_ref.to_dict()) != row['scope_json']
                    or unit.scope_ref.environment_namespace != namespace
                    or facts['providerRef']['environmentNamespace'] != namespace
                    or facts['nodeRef']['environmentNamespace'] != namespace
                    or row['correlation'] != facts['correlation']
                    or row['scope_key'] != safe_json({'environmentNamespace':namespace,
                                                       'scopeId':unit.scope_ref.scope_id})):
                raise JournalError('existing journal Unit identity differs')
            units[unit.unit_ref] = unit
        # Native facts stay historical. Validate their hashes, not their current
        # live owner: no native handle or original verifier is manufactured here.
        for table, pairs in (
            ('harness_unit_sessions', (('native_json','native_digest'),)),
            ('harness_unit_confirmations', (('native_json','native_digest'),)),
            ('harness_unit_configuration_attempts', (('identity_json','identity_digest'),
                ('native_request_json','native_request_digest'), ('confirmation_json','confirmation_digest'))),
            ('harness_unit_terminations', (('identity_json','identity_digest'), ('outcome_json','outcome_digest')))):
            for row in actual.execute('SELECT * FROM ' + table):
                if row['unit_ref'] not in units:
                    raise JournalError('existing journal native Unit differs')
                for value, digest in pairs:
                    raw = row[value]
                    if ((raw is None) != (row[digest] is None)
                            or raw is not None and (safe_json(json.loads(raw)) != raw
                                                    or _digest(raw) != row[digest])):
                        raise JournalError('existing journal native content differs')
        if acp_turn_opt_in:
            readonly = SimpleNamespace(_unit=lambda db, unit_id: units[unit_id])
            for row in actual.execute('SELECT * FROM harness_acp_turn_attempts'):
                _check(readonly, actual, row)
        if managed_turn_opt_in:
            # This narrow admission currently supports original ACP generation,
            # not resumption/adoption of managed-input capture/Workspace claims.
            if actual.execute('SELECT 1 FROM harness_managed_turn_attempts LIMIT 1').fetchone():
                raise JournalError('historical managed-input claims require their original owner')
        # Legacy operations are retained/readable but cannot obtain new claims
        # through this new-Units-only admission.
        for row in actual.execute('SELECT * FROM plans'):
            if _digest(row['plan_json']) != row['fingerprint']:
                raise JournalError('existing journal plan integrity differs')
        return frozenset(units)
    except Exception as error:
        if isinstance(error, JournalError):
            raise
        raise JournalError('existing journal validation refused') from error
    finally:
        if actual is not None:
            actual.close()
        expected.close()
