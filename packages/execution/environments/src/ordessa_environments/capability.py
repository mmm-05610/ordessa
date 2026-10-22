"""Environment-owned capability boundary; no interface-host or plugin imports."""
from dataclasses import replace
from pathlib import Path
import asyncio
import hashlib
import json
import os
import math
import re
import uuid

from ordessa_interfaces_contracts import (
    Capability, CapabilityDescriptor, CapabilityError, OperationDescriptor,
    OperationResult, compute_descriptor_digest,
)
from .definitions.contracts import ProcessRequest
from .definitions.errors import EnvironmentOperationUnknown, EnvironmentRefused, ProcessWaitTimeout
from .definitions.native import (
    NATIVE_ACTIONS, NATIVE_DESCRIPTION_VERSION, NATIVE_EVENTS_VERSION,
    NATIVE_MANAGEMENT_VERSION, NATIVE_OBSERVATION_VERSION, NATIVE_QUERY_VERSION,
    NativeEvent, NativeObservation, description_projection, events_projection,
    format_cursor, validate_action, validate_cursor, validate_page_limit,
    validate_request_id,
)
from .management.ownership import EnvironmentUseOperations, OwnerScope, _json
from .management.endpoints import EnvironmentEndpoints


class InvalidEnvironmentInput(EnvironmentRefused):
    pass


class EnvironmentProviderUnavailable(EnvironmentRefused):
    pass


class EnvironmentCommandConflict(EnvironmentRefused):
    pass


class EnvironmentLifecycleRefused(EnvironmentRefused):
    pass


def _validate_input(action, request):
    if action not in SPECS or not isinstance(request, dict):
        raise InvalidEnvironmentInput('unknown command or invalid request')
    properties, required = SPECS[action]
    if set(request) - set(properties) or set(required) - set(request):
        raise InvalidEnvironmentInput('invalid command fields')
    for key, value in request.items():
        schema = properties[key]
        kind = schema.get('type')
        if kind == 'string' and (type(value) is not str or not schema.get('minLength', 0) <= len(value) <= schema.get('maxLength', 8192) or '\x00' in value):
            raise InvalidEnvironmentInput('invalid string input')
        if kind == 'boolean' and type(value) is not bool:
            raise InvalidEnvironmentInput('invalid boolean input')
        if kind == 'number' and (type(value) not in (int, float) or not math.isfinite(value) or value <= 0 or value > 300):
            raise InvalidEnvironmentInput('invalid timeout')
        if kind == 'array' and schema.get('valueKind') == 'structured':
            if (type(value) is not list or len(value) > 32
                    or any(type(item) is not dict or not item for item in value)):
                raise InvalidEnvironmentInput('structured array input required')
        elif kind == 'array' and (type(value) is not list or not 1 <= len(value) <= 256 or any(type(x) is not str or not x or len(x) > 8192 or '\x00' in x for x in value)):
            raise InvalidEnvironmentInput('invalid argv')
        if (kind == 'object' and key != 'endpointRef'
                and schema.get('valueKind') != 'structured'
                and (type(value) is not dict or len(value) > 128 or any(type(k) is not str or type(v) is not str or '\x00' in k or '\x00' in v for k, v in value.items()))):
            raise InvalidEnvironmentInput('invalid environment values')
        if schema.get('valueKind') == 'structured' and kind != 'array' and type(value) is not dict:
            raise InvalidEnvironmentInput('structured provider reference required')
        if 'enum' in schema and value not in schema['enum']:
            raise InvalidEnvironmentInput('invalid command enum')


class EnvironmentCapabilityService:
    """One owner service; composition supplies manager/catalog/authorization.

    Request rows are idempotent command outcomes; resource/use rows remain the
    authority for resource ownership. No registry, credentials or host objects.
    """
    def __init__(self, manager, *, authorize, provider_catalog, aliases_path=None):
        self.manager = manager
        self.uses = EnvironmentUseOperations(manager, authorize=authorize)
        self.endpoints = EnvironmentEndpoints(self.uses)
        self.provider_catalog = tuple(dict(p) for p in provider_catalog)
        self.aliases_path = Path(aliases_path) if aliases_path is not None else None
        with manager.store.transaction() as db:
            existing_alias_table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='environment_alias_bindings'").fetchone()
            db.execute('''CREATE TABLE IF NOT EXISTS environment_alias_bindings (
                alias TEXT PRIMARY KEY, identity TEXT NOT NULL, phase TEXT NOT NULL)''')
            if existing_alias_table is None:
                for alias, identity in self._read_alias_file().items():
                    db.execute("INSERT INTO environment_alias_bindings VALUES (?,?,'bound')", (alias, identity))
            db.execute('''CREATE TABLE IF NOT EXISTS environment_command_requests (
                owner_scope TEXT NOT NULL, request_id TEXT NOT NULL,
                operation_id TEXT NOT NULL UNIQUE, action TEXT NOT NULL,
                input_digest TEXT NOT NULL, identity TEXT NOT NULL,
                state TEXT NOT NULL, result TEXT,
                PRIMARY KEY(owner_scope,request_id))''')

    def _scope(self, invocation):
        scope = getattr(invocation, 'owner_scope', None)
        if type(scope) is not OwnerScope:
            raise EnvironmentRefused('trusted ownerScope invocation required')
        return scope

    def _read_alias_file(self):
        if self.aliases_path is None or not self.aliases_path.exists():
            return {}
        value = json.loads(self.aliases_path.read_text())
        aliases = value.get('aliases')
        if not isinstance(aliases, dict) or any(
                type(k) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', k)
                or type(v) is not str or not v.startswith('environment/') for k, v in aliases.items()):
            raise EnvironmentRefused('alias map is invalid')
        return aliases

    def _identity(self, reference):
        if type(reference) is not str or not reference:
            raise InvalidEnvironmentInput('environment reference required')
        if any(p['id'] == reference and not p.get('available') for p in self.provider_catalog):
            raise EnvironmentProviderUnavailable('provider unavailable')
        identity = self._aliases().get(reference, reference)
        if identity not in self.manager.store.identities():
            raise InvalidEnvironmentInput('unknown alias or identity')
        self.manager.get(identity)
        return identity

    def _aliases(self):
        with self.manager.store.transaction() as db:
            return {r['alias']: r['identity'] for r in db.execute(
                "SELECT alias,identity FROM environment_alias_bindings WHERE phase='bound'")}

    def _reserve_alias(self, alias, identity):
        if alias is None: return
        if (self.aliases_path is None or type(alias) is not str
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', alias)):
            raise EnvironmentRefused('alias storage or name unavailable')
        with self.manager.store.transaction() as db:
            row = db.execute('SELECT identity FROM environment_alias_bindings WHERE alias=?', (alias,)).fetchone()
            if row is not None and row['identity'] != identity:
                raise EnvironmentCommandConflict('alias already reserved')
            db.execute("INSERT OR IGNORE INTO environment_alias_bindings VALUES (?,?,'reserved')", (alias, identity))

    def _alias(self, alias, identity):
        if alias is None: return
        # SQLite serializes alias reservation/publication across processes. JSON
        # remains a derived legacy-format view, not a second mutation authority.
        with self.manager.store.transaction() as db:
            row = db.execute('SELECT identity FROM environment_alias_bindings WHERE alias=?', (alias,)).fetchone()
            if row is None or row['identity'] != identity:
                raise EnvironmentCommandConflict('alias reservation differs')
            db.execute("UPDATE environment_alias_bindings SET phase='bound' WHERE alias=?", (alias,))
            aliases = {r['alias']:r['identity'] for r in db.execute(
                "SELECT alias,identity FROM environment_alias_bindings WHERE phase='bound'")}
            self._write_alias_file(aliases)

    def _write_alias_file(self, aliases):
        # JSON stays a derived legacy-format view; SQLite is the single authority.
        if self.aliases_path is None:
            return
        self.aliases_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.aliases_path.with_name(self.aliases_path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(_json({'apiVersion': 'agent-tools/1', 'aliases': aliases}))
            temporary.replace(self.aliases_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _release_aliases(self, identity):
        """A deleted resource must not keep its name reserved.

        The alias binding is released only after the provider confirmed the
        delete; the name may then be reserved by a replacement resource. This
        never rebinds an existing name silently: the released name is free, not
        redirected.
        """
        with self.manager.store.transaction() as db:
            db.execute("DELETE FROM environment_alias_bindings WHERE identity=?", (identity,))
            aliases = {r['alias']: r['identity'] for r in db.execute(
                "SELECT alias,identity FROM environment_alias_bindings WHERE phase='bound'")}
        self._write_alias_file(aliases)

    def _project(self, snapshot):
        observation = snapshot.observation
        report = observation.capabilities if observation else None
        statuses = {k: v.value for k, v in report.values.items()} if report else {}
        aliases = sorted(k for k, v in self._aliases().items() if v == snapshot.identity)
        # A deleted resource keeps its last stored observation for audit, but that
        # observation is historical: presenting ``state=running`` for a resource
        # that is gone would be a false claim, so those fields are not re-stated.
        deleted = snapshot.phase == 'deleted'
        return {'identity': snapshot.identity, 'alias': aliases[0] if aliases else None,
                'aliases': aliases, 'provider': snapshot.provider_id, 'backendId': snapshot.backend_id,
                'phase': snapshot.phase, 'generation': snapshot.generation,
                'state': 'deleted' if deleted else (observation.state if observation else None),
                'observationStale': deleted,
                'observedAt': observation.observed_at if observation else None,
                'operationStatus': {'phase': snapshot.phase, 'operation': snapshot.operation},
                'activeUses': snapshot.active_uses, 'isolation': report.isolation if report else None,
                'endpointKind': 'local-directory' if observation and observation.endpoint_kind == 'local' else 'remote-gateway',
                'health': ('unknown' if deleted else
                    (observation.health if observation.health != 'unknown'
                     else 'ready' if snapshot.phase == 'ready' and observation.state == 'running'
                     else 'unknown')) if observation else 'unknown',
                'capabilities': None if (report is None or deleted) else {
                    'isolation': report.isolation, 'statuses': statuses,
                    'provides': sorted(report.provides), 'values': dict(report.details),
                    'assurance': {'isolation': report.isolation, 'isolationIsSecurityBoundary': False,
                                  'localDevelopmentOnly': report.isolation == 'none',
                                  'providerAssurance': report.assurance,
                                  'statement': 'provider-reported isolation; it is not a permission, lease or hold'}}}

    # -- the thin native management entry ------------------------------------
    #
    # A native request is a bounded, read-only question about the provider's own
    # control plane. It shares this service, this manager, this store and this
    # authority with the normal lifecycle: an inspected resource is the same
    # ``environment_resources`` row with the same immutable backend id, and the
    # recorded outcome is the same command-request row every other command
    # uses. There is no second state store and no second authority.

    def _native_provider(self, provider_id):
        provider = self.manager.providers.get(provider_id)
        if provider is None:
            raise EnvironmentProviderUnavailable('provider unavailable')
        return provider

    def _native_describe(self, request):
        """Availability plus the provider's own gateway/binding facts."""
        selected = request.get('provider')
        entries = []
        for catalog in self.provider_catalog:
            if selected is not None and catalog['id'] != selected:
                continue
            entry = {'id': catalog['id'], 'available': bool(catalog.get('available')),
                     'reason': catalog.get('reason'), 'management': None}
            provider = self.manager.providers.get(catalog['id'])
            describe = getattr(provider, 'native_describe', None)
            if callable(describe):
                try:
                    entry['management'] = describe()
                except EnvironmentRefused as error:
                    entry['management'] = {
                        'schemaVersion': NATIVE_MANAGEMENT_VERSION,
                        'provider': catalog['id'], 'available': False,
                        'reason': error.detail, 'actions': []}
            entries.append(entry)
        if not entries:
            raise InvalidEnvironmentInput('unknown provider')
        return description_projection(entries)

    def _native_command_row(self, scope, request_id):
        with self.manager.store.transaction() as db:
            row = db.execute('SELECT * FROM environment_command_requests '
                             'WHERE owner_scope=? AND request_id=? AND action=?',
                             (scope.storage_key, request_id, 'native.request')).fetchone()
        return None if row is None else dict(row)

    def _native_query(self, scope, request):
        """Read the stored fact of one native request; never dispatch again."""
        request_id = request['requestId']
        try:
            validate_request_id(request_id)
        except EnvironmentRefused as error:
            raise InvalidEnvironmentInput(error.detail) from None
        row = self._native_command_row(scope, request_id)
        if row is None:
            raise InvalidEnvironmentInput('native request is unknown')
        replayed = self._replay(row)
        data = {'schemaVersion': NATIVE_QUERY_VERSION, 'requestId': request_id,
                'status': replayed.status, 'operationRef': replayed.operation_ref,
                'observation': replayed.data,
                'error': None if replayed.error is None else
                    {'code': replayed.error.code, 'message': replayed.error.message}}
        return OperationResult(replayed.status, data, replayed.error, replayed.operation_ref)

    def _native_events(self, scope, request):
        """One page of the owner's native events, with the page's completeness."""
        try:
            start = validate_cursor(request.get('cursor'))
            limit = validate_page_limit(request.get('limit'))
        except EnvironmentRefused as error:
            raise InvalidEnvironmentInput(error.detail) from None
        with self.manager.store.transaction() as db:
            rows = db.execute('SELECT rowid AS seq,* FROM environment_command_requests '
                              'WHERE owner_scope=? AND action=? AND rowid>? ORDER BY rowid LIMIT ?',
                              (scope.storage_key, 'native.request', start, limit + 1)).fetchall()
        events = []
        for row in rows[:limit]:
            stored = json.loads(row['result']) if row['result'] else None
            facts = (stored or {}).get('data') or {}
            events.append(NativeEvent(
                sequence=row['seq'], request_id=row['request_id'], state=row['state'],
                operation_ref=row['operation_id'], provider=facts.get('provider'),
                action=facts.get('action'), backend_id=facts.get('backendId'),
                status=(stored or {}).get('status')))
        complete = len(rows) <= limit
        next_cursor = format_cursor(rows[limit - 1]['seq']) if (not complete and events) else None
        return events_projection(events, cursor=request.get('cursor'), next_cursor=next_cursor,
                                 complete=complete, limit=limit)

    def _native_unknown(self, request, error):
        """The stored fact of an uncertain native request."""
        correlation = error.identity
        if type(correlation) is not str or not correlation:
            correlation = request['requestId']
        observation = NativeObservation(
            request_id=request['requestId'], provider=request['provider'], action=request['action'],
            state='unknown', correlation_id=correlation, backend_id=error.backend_id)
        return observation.projection()

    async def _native_effect(self, request, scope, invocation, row):
        """Dispatch one bounded native read and record it in the same store."""
        provider_id = request['provider']
        provider = self._native_provider(provider_id)
        native = getattr(provider, 'native_request', None)
        if not callable(native):
            raise EnvironmentRefused('provider exposes no native management port')
        action = request['action']
        target = None
        identity = None
        backend_id = None
        if action == 'inspect':
            reference = request.get('reference')
            if reference is None:
                raise InvalidEnvironmentInput('native inspect requires an environment reference')
            identity = self._identity(reference)
            snapshot = self.manager.get(identity).snapshot
            if snapshot.provider_id != provider_id:
                raise InvalidEnvironmentInput('environment is not owned by the selected provider')
            if not snapshot.backend_id:
                raise InvalidEnvironmentInput('environment has no immutable backend identity')
            target = backend_id = snapshot.backend_id
        request_id = request['requestId']
        try:
            facts = native(action, target=target, request_id=request_id)
        except (EnvironmentRefused, EnvironmentOperationUnknown):
            raise
        except Exception as error:
            # An uncertain outcome keeps its correlation id and is stored as
            # ``unknown``; it is never dispatched a second time.
            raise EnvironmentOperationUnknown('native request outcome is unknown',
                                              identity=request_id, backend_id=backend_id) from error
        observation = NativeObservation(
            request_id=request_id, provider=provider_id, action=action, state='completed',
            correlation_id=request_id, backend_id=backend_id,
            environment_identity=identity, result=facts)
        return observation.projection()

    def _reserve(self, scope, request_id, action, request):
        if type(request_id) is not str or not 0 < len(request_id) <= 512:
            raise EnvironmentRefused('bounded request id required')
        digest = hashlib.sha256(_json(request).encode()).hexdigest()
        with self.manager.store.transaction() as db:
            row = db.execute('SELECT * FROM environment_command_requests WHERE owner_scope=? AND request_id=?',
                             (scope.storage_key, request_id)).fetchone()
            if row:
                if (row['action'], row['input_digest']) != (action, digest):
                    raise EnvironmentCommandConflict('requestId conflicts with fixed command input')
                return dict(row), False
            operation = 'environment-command/' + uuid.uuid4().hex
            identity = 'environment/' + uuid.uuid4().hex
            db.execute('INSERT INTO environment_command_requests VALUES (?,?,?,?,?,?,?,NULL)',
                       (scope.storage_key, request_id, operation, action, digest, identity, 'reserved'))
            return dict(db.execute('SELECT * FROM environment_command_requests WHERE operation_id=?', (operation,)).fetchone()), True

    def _finish(self, row, result):
        body = {'status': result.status, 'data': result.data,
                'error': None if result.error is None else {'code': result.error.code, 'message': result.error.message},
                'operation_ref': result.operation_ref, 'evidence_refs': list(result.evidence_refs)}
        with self.manager.store.transaction() as db:
            db.execute('UPDATE environment_command_requests SET state=?,result=? WHERE operation_id=?',
                       (result.status, _json(body), row['operation_id']))
        return result

    def session_facts(self):
        """Local foreground facts: live Use/process handles and pending effects."""
        with self.manager.store.transaction() as db:
            uses=[{'useIdentity':row['identity'],'environmentIdentity':row['environment_id'],
                   'generation':row['generation'],'phase':row['phase'],'pendingEffects':row['pending']}
                  for row in db.execute('SELECT identity,environment_id,generation,phase,pending'
                                        ' FROM environment_uses ORDER BY identity')]
        released={use['useIdentity'] for use in uses if use['phase'] in ('released','invalid')}
        with self.manager._view_lock:
            live_uses=tuple(sorted(use for use in self.manager._owned_use_handles
                                   if use not in released))
            processes=tuple(sorted(self.manager._owned_process_handles))
        return {'uses':uses,'liveUseHandles':list(live_uses),
                'processes':[{'useIdentity':use_id,'processIdentity':process_id}
                             for use_id,process_id in processes]}

    @staticmethod
    def _replay(row):
        if row['result'] is None:
            return OperationResult('unknown', {'identity': row['identity']},
                CapabilityError('EFFECT_UNKNOWN', 'Original command outcome requires inspection'), row['operation_id'])
        data = json.loads(row['result'])
        error = CapabilityError(**data['error']) if data['error'] else None
        return OperationResult(data['status'], data['data'], error, data['operation_ref'], tuple(data['evidence_refs']))

    async def invoke(self, action, request, invocation, request_id):
        _validate_input(action, request)
        scope = self._scope(invocation)
        target = request.get('reference') or request.get('useIdentity') or 'environments'
        if action in ('create', 'register'):
            # The pre-effect target of a creation is the selected provider, not
            # the provider-specific reference value (which may be a structure).
            target = request['provider']
        self.uses._authorize(scope, action, target, invocation)
        if action == 'providers':
            return OperationResult('completed', {'providers': list(self.provider_catalog)})
        if action == 'native.describe':
            return OperationResult('completed', self._native_describe(request))
        if action == 'native.query':
            return self._native_query(scope, request)
        if action == 'native.events':
            return OperationResult('completed', self._native_events(scope, request))
        if action == 'list':
            return OperationResult('completed', {'resources': [self._project(s) for s in self.manager.list()], 'orphanAliases': []})
        if action == 'inspect':
            return OperationResult('completed', self._project(self.manager.get(self._identity(request['reference'])).inspect()))
        if action == 'use-inspect':
            return OperationResult('completed', self.uses.inspect(request['useIdentity'], scope, invocation=invocation))
        if action == 'export-endpoint':
            data = self.endpoints.export(request['useIdentity'], scope, request_id=request_id,
                capabilities=request['capabilities'], invocation=invocation,
                roots=request.get('roots'),
                prepared_configurations=tuple(request.get('preparedConfigurations', ())))
            return _owned_result(data)
        if action == 'endpoint-inspect':
            _, descriptor = self.endpoints.resolve(request['endpointRef'], scope, invocation=invocation)
            return OperationResult('completed', {'endpointRef': request['endpointRef'], 'descriptor': descriptor})
        if action in ('acquire', 'release', 'launch', 'process-release'):
            if action == 'acquire':
                data = self.uses.acquire(self._identity(request['reference']), scope,
                    request_id=request_id, sharing=request['sharing'], invocation=invocation)
            elif action == 'release':
                data = self.uses.release(request['useIdentity'], scope, request_id=request_id, invocation=invocation)
            elif action == 'process-release':
                binding, _descriptor = self.endpoints.resolve(request['endpointRef'], scope, invocation=invocation)
                process_identity = binding.get('process_identity')
                if type(process_identity) is not str or not process_identity:
                    raise EnvironmentRefused('endpoint has no confirmed original process')
                data = self.uses.process_release(binding['use_id'], process_identity, scope,
                    request_id=request_id, invocation=invocation)
            else:
                process_request = ProcessRequest.build(request['argv'], cwd=request['cwd'], env=request.get('env', {}))
                data = self.uses.launch(request['useIdentity'], scope, process_request,
                    request_id=request_id, invocation=invocation)
            return _owned_result(data)
        if action == 'native.request':
            # The native request id is the idempotency key: the same id with the
            # same canonical input replays the stored result, a different input
            # conflicts, and an uncertain outcome is stored once and never
            # dispatched again.
            try:
                validate_request_id(request['requestId'])
                validate_action(request['action'])
            except EnvironmentRefused as error:
                raise InvalidEnvironmentInput(error.detail) from None
            reserve_key = request['requestId']
        else:
            reserve_key = request_id
        row, first = self._reserve(scope, reserve_key, action, request)
        if not first:
            return self._replay(row)
        try:
            self.uses._authorize(scope, action, target, invocation)
            data = await self._effect(action, request, scope, invocation, row)
            result = OperationResult('completed', data, operation_ref=row['operation_id'])
        except InvalidEnvironmentInput:
            result = OperationResult('refused', None, CapabilityError('INVALID_INPUT', 'Environment input is invalid'), row['operation_id'])
        except EnvironmentProviderUnavailable:
            result = OperationResult('refused', None, CapabilityError('CAPABILITY_UNSUPPORTED', 'Environment provider unavailable'), row['operation_id'])
        except EnvironmentLifecycleRefused:
            result = OperationResult('refused', None, CapabilityError('INVALID_INPUT', 'Resource lifecycle refused; user files preserved'), row['operation_id'])
        except EnvironmentCommandConflict:
            result = OperationResult('refused', None, CapabilityError('CONFLICT', 'Environment resource or alias already exists'), row['operation_id'])
        except EnvironmentRefused:
            result = OperationResult('refused', None, CapabilityError('CAPABILITY_UNSUPPORTED', 'Environment command refused before its effect'), row['operation_id'])
        except EnvironmentOperationUnknown as error:
            if action == 'native.request':
                # An uncertain native outcome is a stored fact: it keeps its
                # correlation id and is never dispatched a second time.
                result = OperationResult('unknown', self._native_unknown(request, error),
                    CapabilityError('EFFECT_UNKNOWN', 'Environment native request outcome is unknown; not re-dispatched'),
                    row['operation_id'])
            else:
                result = OperationResult('unknown', {'identity': row['identity']} if action in ('create', 'register') else None, CapabilityError('EFFECT_UNKNOWN', 'Environment command requires explicit inspection'), row['operation_id'])
        except ProcessWaitTimeout:
            result = OperationResult('unknown', None, CapabilityError('OBSERVATION_TIMEOUT', 'Process observation timed out'), row['operation_id'])
        except Exception:
            result = OperationResult('unknown', {'identity': row['identity']} if action in ('create', 'register') else None, CapabilityError('EFFECT_UNKNOWN', 'Environment command requires explicit inspection'), row['operation_id'])
        return self._finish(row, result)

    async def _effect(self, action, request, scope, invocation, row):
        if action == 'native.request':
            return await self._native_effect(request, scope, invocation, row)
        if action in ('create', 'register'):
            provider = request['provider']
            if provider not in self.manager.providers:
                raise EnvironmentProviderUnavailable('provider unavailable')
            alias = request.get('alias')
            if alias is not None and alias in self._aliases():
                raise EnvironmentCommandConflict('alias already exists')
            # Providers differ in what identifies a resource before it exists: a
            # local resource is an absolute root directory, while a remote
            # provider takes one closed structured reference. The capability
            # only validates and forwards; provider semantics stay in the owner.
            if provider == 'local':
                root = request.get('root') if action == 'create' else request.get('backend')
                if type(root) is not str or not os.path.isabs(root):
                    raise InvalidEnvironmentInput('absolute resource root required')
                if any(s.provider_id == provider and s.backend_id == os.path.realpath(root) for s in self.manager.list()):
                    raise EnvironmentCommandConflict('backend already registered')
                reference = {'root': root} if action == 'create' else root
            elif action == 'create':
                reference = request.get('reference')
                if not isinstance(reference, dict) or not reference:
                    raise InvalidEnvironmentInput('structured provider reference required')
            else:
                reference = request.get('backend')
                if type(reference) is not str or not reference:
                    raise InvalidEnvironmentInput('provider backend identity required')
            self._reserve_alias(alias, row['identity'])
            try:
                if action == 'create':
                    # A remote provider names its backend from the operation
                    # identity. The command's own operation id is namespaced
                    # ('environment-command/<uuid>'), so derive one stable
                    # 32-character lowercase digest from the reserved command
                    # identity: a replay of the same request row therefore
                    # derives the same backend name and never adopts a stranger.
                    creation_operation = (row['operation_id'] if provider == 'local'
                        else hashlib.sha256(('environment-create:' + row['identity']).encode()).hexdigest()[:32])
                    instance = self.manager._create(provider, reference, identity=row['identity'], operation_id=creation_operation)
                else:
                    instance = self.manager._register(provider, reference, identity=row['identity'])
            except EnvironmentRefused:
                # Provider refusal is the established pre-effect contract.
                # Only this command's still-reserved alias may be discharged.
                with self.manager.store.transaction() as db:
                    db.execute("DELETE FROM environment_alias_bindings WHERE identity=? AND phase='reserved'", (row['identity'],))
                raise
            try:
                self._alias(alias, instance.identity)
            except Exception as error:
                raise EnvironmentOperationUnknown('resource exists; alias publication requires inspection', identity=instance.identity) from error
            return self._project(instance.snapshot)
        identity = self._identity(request['reference'])
        instance = self.manager.get(identity)
        # A row whose resource is already gone or failed is a settled refusal:
        # nothing is dispatched and no effect can be unknown.
        if action not in ('delete',) and instance.snapshot.phase in ('deleted', 'failed'):
            raise InvalidEnvironmentInput('environment resource is ' + instance.snapshot.phase)
        self.uses._authorize(scope, action, identity, invocation)
        if action == 'reconcile':
            # An uncertain creation is *verified*, never repeated. The provider's
            # recovery is a read-only correlation lookup over the persisted
            # operation identity; this command never creates a second resource.
            snapshot = instance.snapshot
            if snapshot.operation != 'create' or snapshot.phase not in ('creating', 'unknown'):
                raise InvalidEnvironmentInput('environment has no uncertain creation to reconcile')
            self.manager.reconcile_creation(identity, backend_id=None)
            return self._project(instance.snapshot)
        if action in ('stop', 'delete'):
            provider = self.manager._provider(instance.snapshot.provider_id)
            if action not in provider.operations:
                raise EnvironmentLifecycleRefused('provider does not own this resource lifecycle operation')
            receipt = getattr(instance, action)()
            if action == 'delete' and receipt.confirmed:
                try:
                    self._release_aliases(identity)
                except Exception as error:
                    raise EnvironmentOperationUnknown(
                        'resource deleted; alias release requires inspection',
                        identity=identity) from error
            return {'identity': identity, 'operation': action, 'confirmed': receipt.confirmed}
        if action == 'exec':
            argv = request['argv']
            if not argv:
                raise EnvironmentRefused('terminal sessions unavailable; pass a command')
            for permission in ('acquire', 'launch', 'communicate', 'observe', 'detach', 'release'):
                self.uses._authorize(scope, permission, identity, invocation)
            acquired = self.uses.acquire(identity, scope, request_id=row['operation_id']+'/acquire',
                sharing=False, invocation=invocation)
            if acquired['status'] == 'refused':
                # A busy exclusive Use is a settled pre-effect refusal.
                raise EnvironmentCommandConflict('environment is held by another exclusive Use')
            if acquired['status'] != 'completed':
                raise EnvironmentOperationUnknown('execution Use unavailable', identity=identity)
            use_id = acquired['useIdentity']
            with self.manager._view_lock:
                use = self.manager._owned_use_handles[use_id]
            process = None
            try:
                launch = self.uses.launch(use_id, scope, ProcessRequest.build(argv, cwd=use.files.root(), env=request.get('env', {})),
                    request_id=row['operation_id']+'/launch', invocation=invocation)
                if launch['status'] != 'completed':
                    raise EnvironmentOperationUnknown('execution launch unresolved', identity=identity)
                process = self.uses.process(use_id, launch['processIdentity'], scope, invocation=invocation)
                data = request.get('stdin', '').encode('utf-8')
                if data:
                    await process.write_stdin(data, timeout=request.get('timeout', 60))
                await process.close_stdin()
                async def drain(reader):
                    chunks = []; size = 0
                    while True:
                        chunk = await reader(65536, timeout=request.get('timeout', 60))
                        if not chunk: break
                        size += len(chunk)
                        if size > 262144:
                            raise EnvironmentOperationUnknown('captured process output exceeded bound after launch', identity=identity)
                        chunks.append(chunk)
                    return b''.join(chunks).decode('utf-8', errors='replace')
                tasks = [asyncio.create_task(drain(process.read_stdout)), asyncio.create_task(drain(process.read_stderr)),
                         asyncio.create_task(process.wait_exit(timeout=request.get('timeout', 60)))]
                try:
                    stdout, stderr, observation = await asyncio.gather(*tasks)
                finally:
                    for task in tasks:
                        if not task.done(): task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                return {'exitCode': observation.exit_code, 'stdout': stdout, 'stderr': stderr, 'useReleased': True, 'truncated': {'stdout': False, 'stderr': False}}
            except EnvironmentRefused as error:
                raise EnvironmentOperationUnknown('execution or communication permission changed after resource acquisition', identity=identity) from error
            finally:
                try:
                    if process is not None:
                        if process.observe().state != 'exited':
                            termination = await process.terminate(request_id=row['operation_id']+'/terminate')
                            if termination['status'] != 'completed':
                                raise EnvironmentOperationUnknown('termination outcome unresolved', identity=identity)
                            await process.wait_exit(timeout=5)
                        detached = process.detach(request_id=row['operation_id']+'/detach')
                        if detached['status'] != 'completed':
                            raise EnvironmentOperationUnknown('detach outcome unresolved', identity=identity)
                        # A one-shot exec owns no exported endpoint, and the exit was
                        # already observed by this command, so its handle is dropped
                        # here. process-release is not applicable: it re-observes
                        # per-process state, which exec-only providers do not report.
                        self.uses.drop_exited_process(use_id, process.process_id)
                    released = self.uses.release(use_id, scope, request_id=row['operation_id']+'/release', invocation=invocation)
                    if released['status'] != 'completed':
                        raise EnvironmentOperationUnknown('execution cleanup pending', identity=identity)
                except EnvironmentRefused as error:
                    raise EnvironmentOperationUnknown('execution cleanup authority unavailable; resource retained', identity=identity) from error
        if action == 'files':
            acquired = self.uses.acquire(identity, scope, request_id=row['operation_id']+'/acquire', sharing=False, invocation=invocation)
            if acquired['status'] != 'completed':
                raise EnvironmentOperationUnknown('file Use unavailable', identity=identity)
            use_id = acquired['useIdentity']
            use = self.manager._owned_use_handles[use_id]
            try:
                self.uses._authorize(scope, 'files', identity, invocation)
                verb, path = request['verb'], request.get('path', '.')
                if verb == 'ls':
                    return {'entries': list(use.files.list())}
                if verb == 'cat':
                    return {'content': use.files.read_text(path)}
                if verb == 'write':
                    content = request.get('content', '').encode('utf-8')
                    use.files.write_text(path, content.decode('utf-8'))
                    return {'operation': 'write', 'path': path, 'bytes': len(content), 'byteLength': len(content)}
                raise EnvironmentRefused('unknown file operation')
            finally:
                try:
                    released = self.uses.release(use_id, scope, request_id=row['operation_id']+'/release', invocation=invocation)
                    if released['status'] != 'completed':
                        raise EnvironmentOperationUnknown('file cleanup pending after possible effect', identity=identity)
                except EnvironmentRefused as error:
                    raise EnvironmentOperationUnknown('file cleanup permission changed after possible effect', identity=identity) from error
        raise EnvironmentRefused('unsupported environment command')


def _owned_result(data):
    status = data['status']
    if status == 'completed':
        return OperationResult('completed', data, operation_ref=data['operationRef'])
    if status == 'refused':
        return OperationResult('refused', data, CapabilityError('CAPABILITY_UNSUPPORTED', 'Resource operation refused'), data['operationRef'])
    if status == 'pending':
        return OperationResult('accepted', data, operation_ref=data['operationRef'])
    return OperationResult('unknown', data, CapabilityError('EFFECT_UNKNOWN', 'Resource outcome requires inspection'), data['operationRef'])


def _schema(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


STR = {'type': 'string', 'minLength': 1, 'maxLength': 8192}
ARGV = {'type': 'array', 'items': STR, 'minItems': 1, 'maxItems': 256}
ENV = {'type': 'object', 'additionalProperties': {'type': 'string'}, 'maxProperties': 128}
SPECS = {
    'providers': ({}, ()), 'list': ({}, ()),
    'inspect': ({'reference': STR}, ('reference',)),
    # ``root`` stays the local provider's input; a remote provider supplies one
    # closed structured ``reference`` object instead. The handler enforces which
    # one the selected provider requires, before any effect.
    'create': ({'provider': STR, 'root': STR, 'alias': STR,
                'reference': {'type': 'object', 'valueKind': 'structured'}}, ('provider',)),
    'register': ({'provider': STR, 'backend': STR, 'alias': STR}, ('provider', 'backend')),
    'stop': ({'reference': STR}, ('reference',)), 'delete': ({'reference': STR}, ('reference',)),
    # An uncertain creation becomes a verifiable fact through this command. It
    # binds the evidence of an existing creation; it never creates a new one.
    'reconcile': ({'reference': STR}, ('reference',)),
    'exec': ({'reference': STR, 'argv': ARGV, 'env': ENV, 'stdin': {'type': 'string', 'maxLength': 262144},
              'timeout': {'type': 'number', 'exclusiveMinimum': 0, 'maximum': 300}}, ('reference', 'argv')),
    'files': ({'reference': STR, 'verb': {'enum': ['ls', 'cat', 'write']}, 'path': STR,
               'content': {'type': 'string', 'maxLength': 262144}}, ('reference', 'verb')),
    'acquire': ({'reference': STR, 'sharing': {'type': 'boolean'}}, ('reference', 'sharing')),
    'release': ({'useIdentity': STR}, ('useIdentity',)),
    'process-release': ({'endpointRef': {'type': 'object'}}, ('endpointRef',)),
    'export-endpoint': ({'useIdentity': STR, 'capabilities': {'type': 'array', 'minItems': 1, 'maxItems': 6,
        'items': {'enum': ['launcher','observe','communicate','terminate','detach','files']}}, 'roots': ENV,
        # One closed list of already-materialized configuration references. They
        # are verified against the real bytes at export time, never trusted from
        # the request.
        'preparedConfigurations': {'type': 'array', 'maxItems': 32, 'valueKind': 'structured'}},
        ('useIdentity', 'capabilities')),
    'endpoint-inspect': ({'endpointRef': {'type': 'object'}}, ('endpointRef',)),
    'use-inspect': ({'useIdentity': STR}, ('useIdentity',)),
    'launch': ({'useIdentity': STR, 'argv': ARGV, 'cwd': STR, 'env': ENV}, ('useIdentity', 'argv', 'cwd')),
    # The thin native management entry. It is a bounded, read-only view over
    # the provider's own control plane: the same store, the same authority and
    # the same immutable backend identity as the normal lifecycle.
    'native.describe': ({'provider': STR}, ()),
    'native.request': ({'provider': STR, 'action': {'enum': list(NATIVE_ACTIONS)},
                        'reference': STR, 'requestId': STR},
                       ('provider', 'action', 'requestId')),
    'native.query': ({'requestId': STR}, ('requestId',)),
    'native.events': ({'cursor': {'type': ['string', 'null'], 'maxLength': 32},
                       'limit': {'type': ['integer', 'null'], 'minimum': 1, 'maximum': 256}}, ()),
}


# Entity commands whose identifiers are opaque values use explicit JSON field
# references (``FILE#/pointer``) instead of hand-copied literals.
_EXPLICIT_ENTITY_ARGS = {
    'release': ({'name': 'useIdentity', 'flags': ('--use-identity',), 'type': 'json-file'},),
    'use-inspect': ({'name': 'useIdentity', 'flags': ('--use-identity',), 'type': 'json-file'},),
    'export-endpoint': ({'name': 'useIdentity', 'flags': ('--use-identity',), 'type': 'json-file'},
                        {'name': 'capabilities', 'type': 'string', 'nargs': '+'},
                        {'name': 'roots', 'flags': ('--roots',), 'type': 'json-file'},
                        {'name': 'preparedConfigurations', 'flags': ('--prepared-configurations',),
                         'type': 'json-file'}),
    'endpoint-inspect': ({'name': 'endpointRef', 'flags': ('--endpoint-ref',), 'type': 'json-file'},),
    'process-release': ({'name': 'endpointRef', 'flags': ('--endpoint-ref',), 'type': 'json-file'},),
}


def _cli_arguments(action, properties, required):
    if action in _EXPLICIT_ENTITY_ARGS:
        return list(_EXPLICIT_ENTITY_ARGS[action])
    args = []
    for name in required:
        argument = {'name': name, 'type': 'boolean' if name == 'sharing' else 'string', 'jsonPath': name}
        if name == 'capabilities':
            argument.update(type='string', nargs='+')
        if name == 'endpointRef':
            argument.update(type='json-file')
        if name == 'argv':
            argument.update(type='string', nargs='REMAINDER')
        args.append(argument)
    for name in properties:
        if name not in required and name in ('root','alias','timeout','path','content','roots','reference'):
            kind = 'number' if name == 'timeout' else 'json-file' if name in ('roots','reference') else 'string'
            args.append({'name': name, 'flags': ['--'+name], 'type': kind, 'jsonPath': name})
    # ``create`` keeps the established ``--root`` grammar for the local
    # provider, but root is no longer universally required: a remote provider
    # supplies ``--reference`` instead. The handler refuses whichever input the
    # selected provider needs but did not receive, before any effect.
    if action == 'create':
        args = [a for a in args if a['name'] != 'root'] + [
            {'name': 'root', 'flags': ['--root'], 'type': 'string', 'jsonPath': 'root'}]
    if action == 'files':
        args = [{'name': 'reference', 'type': 'string', 'jsonPath': 'reference'},
            {'name': 'verb', 'type': 'string', 'jsonPath': 'verb'},
            {'name': 'path', 'type': 'string', 'jsonPath': 'path', 'nargs': '?', 'default': '.'},
            {'name': 'content', 'type': 'string', 'jsonPath': 'content', 'nargs': '?', 'default': ''}]
    return args


#: The native management entry has its own command path, so the thin native
#: surface never collides with the ordinary ``environments <action>`` grammar.
_NATIVE_CLI = {
    'native.describe': ('describe', (('provider', '--provider', 'string'),)),
    'native.request': ('request', (('provider', '--provider', 'string'),
                                   ('action', '--action', 'string'),
                                   ('reference', '--reference', 'string'),
                                   ('requestId', '--request-id-value', 'string'))),
    'native.query': ('query', (('requestId', '--request-id-value', 'string'),)),
    'native.events': ('events', (('cursor', '--cursor', 'string'),
                                 ('limit', '--limit', 'integer'))),
}


def descriptor():
    """Static command/metadata surface; constructing it opens no store."""
    descriptors = []
    for action, (properties, required) in SPECS.items():
        if action in _NATIVE_CLI:
            operation, arguments = _NATIVE_CLI[action]
            cli = {'command': 'environments native', 'operation': operation,
                   'args': [{'name': name, 'flags': (flag,), 'type': kind}
                            for name, flag, kind in arguments],
                   'render': {'kind': 'json'}}
        else:
            cli = {'command': 'environments', 'operation': action,
                   'args': _cli_arguments(action, properties, required),
                   'render': {'kind': 'process', 'paths': ['exitCode', 'stdout', 'stderr']} if action == 'exec' else {'kind': 'json'}}
        descriptors.append(OperationDescriptor('environments.'+action, _schema(properties, required), {'type': 'object'},
            ('environments.'+action,), cli,
            {'tool': 'environments_' + action.replace('-', '_').replace('.', '_')}))
    base = CapabilityDescriptor('environments', '1', tuple(descriptors), '')
    return CapabilityDescriptor('environments', '1', tuple(descriptors),
                                compute_descriptor_digest(base))


class EnvironmentsCapabilityFactory:
    def build(self, bindings):
        services = bindings.get('services')
        resolver = bindings.get('invocation_resolver')
        if type(services) is not EnvironmentCapabilityService or not callable(resolver):
            raise EnvironmentRefused('prebuilt environment services and invocation resolver required')
        declared = descriptor()
        declared_ids = {operation.id for operation in declared.operations}
        handlers = {}
        for action in SPECS:
            operation_id = 'environments.'+action
            if operation_id not in declared_ids:
                continue
            def make_handler(action):
                async def handler(request, context):
                    try:
                        invocation = resolver(context)
                        return await services.invoke(action, request, invocation, context.request_id)
                    except EnvironmentProviderUnavailable:
                        return OperationResult('refused', None, CapabilityError('CAPABILITY_UNSUPPORTED', 'Environment provider unavailable'))
                    except InvalidEnvironmentInput:
                        return OperationResult('refused', None, CapabilityError('INVALID_INPUT', 'Environment input is invalid'))
                    except EnvironmentCommandConflict:
                        return OperationResult('refused', None, CapabilityError('CONFLICT', 'Environment request conflicts'))
                    except EnvironmentRefused:
                        return OperationResult('refused', None, CapabilityError('PERMISSION_DENIED', 'Environment invocation refused'))
                return handler
            handlers[operation_id] = make_handler(action)
        return Capability(declared, handlers)


factory = EnvironmentsCapabilityFactory()
