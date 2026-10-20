"""Externally bound resource endpoint locators; no Agent state or acquisition.

Locators are persisted capability bindings, not bearer grants or business owners.
Resolving always requires the existing subject's current authority and ORIGINAL
live Use; a cold manager never reopens/reacquires a replacement.
"""
import hashlib
import asyncio
from contextlib import contextmanager
import threading
import json
import os
import re
import uuid

from ..definitions.contracts import ProcessRequest
from ..definitions.errors import EnvironmentRefused
from .ownership import _json

RIGHTS = {'launcher': 'launch', 'observe': 'observe', 'communicate': 'communicate',
          'terminate': 'terminate', 'detach': 'detach', 'files': 'files'}


class EnvironmentEndpoints:
    def __init__(self, uses):
        self.uses = uses
        self.manager = uses.manager
        self.issuer = 'environment-endpoints:' + hashlib.sha256(self.manager.store.path.encode()).hexdigest()[:24]
        with self.manager.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS environment_endpoint_bindings (
                endpoint_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL UNIQUE,
                owner_scope TEXT NOT NULL, use_id TEXT NOT NULL,
                process_identity TEXT, descriptor TEXT NOT NULL,
                descriptor_digest TEXT NOT NULL, roots TEXT NOT NULL)''')

    def _live(self, scope, use_id):
        self.uses._owned(scope, use_id)
        with self.manager._view_lock:
            use = self.manager._owned_use_handles.get(use_id)
        if use is None:
            raise EnvironmentRefused('original endpoint unavailable; reacquisition is not recovery')
        use.check(use.environment_id, use.generation, allow_unknown=True)
        return use

    def export(self, use_id, scope, *, capabilities, request_id, invocation,
               roots=None, process_identity=None, prepared_configurations=()):
        self.uses._authorize(scope, 'export', use_id, invocation)
        self.uses._owned(scope, use_id)
        if (type(capabilities) not in (tuple, list) or len(set(capabilities)) != len(capabilities)
                or not set(capabilities) <= set(RIGHTS)):
            raise EnvironmentRefused('invalid independent endpoint capability list')
        roots = dict(roots or {'work': '.'})
        if not roots or len(roots) > 32:
            raise EnvironmentRefused('bounded approved roots required')
        use = self._live(scope, use_id)
        for key, relative in roots.items():
            if type(key) is not str or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', key):
                raise EnvironmentRefused('invalid approved root key')
            self._relative(relative)
            use.files.path(relative)
        for capability in capabilities:
            self.uses._authorize(scope, RIGHTS[capability], use_id, invocation)
        prepared = [dict(ref) for ref in prepared_configurations]
        for ref in prepared:
            self.uses._authorize(scope, 'files', use_id, invocation)
            self._verify_configuration(use, roots, ref)
        if 'files' in capabilities and not callable(getattr(use.files, 'write_text_atomic', None)):
            raise EnvironmentRefused('atomic file capability unavailable')
        if process_identity is not None:
            with self.manager._view_lock:
                if (use_id, process_identity) not in self.manager._owned_process_handles:
                    raise EnvironmentRefused('original process endpoint unavailable')
        inputs = {'capabilities': list(capabilities), 'roots': roots,
                  'processIdentity': process_identity, 'preparedConfigurations': prepared}
        row, first = self.uses._begin(scope, request_id, 'export', use_id, inputs, use_id=use_id)
        if not first:
            return self.uses._replay(row)
        endpoint_id = 'endpoint/' + uuid.uuid4().hex
        # The consumer needs to know whether these paths are host paths or a
        # remote file area (for example an OpenShell sandbox), because harness
        # command resolution and directory checks differ between the two.
        snapshot = self.manager.get(use.environment_id).snapshot
        observation = snapshot.observation
        endpoint_kind = ('local-directory' if observation is not None
                         and observation.endpoint_kind == 'local' else 'remote-gateway')
        descriptor = {'schemaVersion': 'environment-endpoint-descriptor/2',
                      'endpointId': endpoint_id, 'revision': '1',
                      'capabilities': sorted(capabilities), 'rootKeys': sorted(roots),
                      'preparedConfigurations': prepared, 'reconnect': 'unsupported',
                      'providerId': snapshot.provider_id, 'endpointKind': endpoint_kind}
        digest = 'sha256:' + hashlib.sha256(_json(descriptor).encode()).hexdigest()
        with self.manager.store.transaction() as db:
            db.execute('INSERT INTO environment_endpoint_bindings VALUES (?,?,?,?,?,?,?,?)',
                (endpoint_id, row['operation_id'], scope.storage_key, use_id,
                 process_identity, _json(descriptor), digest, _json(roots)))
        ref = {'schemaVersion': 'agent-endpoint/1', 'issuer': self.issuer,
               'endpointId': endpoint_id, 'revision': '1', 'descriptorDigest': digest}
        return self.uses._finish(row, 'completed', endpointRef=ref, descriptor=descriptor)

    def resolve(self, ref, scope, *, invocation, capability=None, require_live=True):
        required = {'schemaVersion','issuer','endpointId','revision','descriptorDigest'}
        if (not isinstance(ref, dict) or set(ref) != required or ref['schemaVersion'] != 'agent-endpoint/1'
                or ref['issuer'] != self.issuer or ref['revision'] != '1'):
            raise EnvironmentRefused('endpoint locator belongs to another binding')
        with self.manager.store.transaction() as db:
            row = db.execute('SELECT * FROM environment_endpoint_bindings WHERE endpoint_id=?',
                             (ref['endpointId'],)).fetchone()
        if row is None or row['owner_scope'] != scope.storage_key or row['descriptor_digest'] != ref['descriptorDigest']:
            raise EnvironmentRefused('endpoint binding differs from its original subject/content')
        descriptor = json.loads(row['descriptor'])
        expected = 'sha256:' + hashlib.sha256(_json(descriptor).encode()).hexdigest()
        if expected != row['descriptor_digest']:
            raise EnvironmentRefused('endpoint descriptor integrity differs')
        self.uses._authorize(scope, 'resolve', row['use_id'], invocation)
        if capability is not None:
            if capability not in descriptor['capabilities']:
                raise EnvironmentRefused('endpoint did not export this independent permission')
            self.uses._authorize(scope, RIGHTS[capability], row['use_id'], invocation)
        if require_live:
            self._live(scope, row['use_id'])
        return dict(row), descriptor

    async def send_guarded(self, ref, scope, frame, *, request_id, invocation,
                           correlation, write_guard, timeout=None):
        """Own one physical frame effect; never own an Agent protocol turn.

        The neutral synchronous guard is passed to the original provider writer.
        Replay reads this original child result and cannot reopen or resend.
        """
        if (type(frame) is not bytes or not 0 < len(frame) <= 1048576
                or type(correlation) is not dict or not callable(write_guard)):
            raise EnvironmentRefused('bounded frame, correlation and physical guard required')
        from ..definitions.io import validate_timeout
        timeout = validate_timeout(timeout)
        inputs = {'frameDigest': 'sha256:' + hashlib.sha256(frame).hexdigest(),
                  'byteLength': len(frame), 'correlation': correlation}
        # JSON validity/bounds before any claim; never persist frame contents.
        if len(_json(inputs).encode()) > 16384:
            raise EnvironmentRefused('bounded child effect correlation required')
        # Resolve identity/owner without requiring a replacement live handle.
        binding, _ = self.resolve(ref, scope, invocation=invocation, require_live=False)
        from .ownership import _text
        _text(request_id, 'endpoint request id')
        with self.manager.store.transaction() as db:
            existing = db.execute('SELECT * FROM environment_use_requests WHERE owner_scope=? AND request_id=?',
                                  (scope.storage_key, request_id)).fetchone()
        if existing is not None:
            self.resolve(ref, scope, invocation=invocation, capability='observe', require_live=False)
            row, _ = self.uses._begin(scope, request_id, 'send-frame', binding['endpoint_id'], inputs,
                                      use_id=binding['use_id'])
            return self.uses._replay(row)
        binding, _ = self.resolve(ref, scope, invocation=invocation, capability='communicate')
        if binding['process_identity'] is None:
            raise EnvironmentRefused('original process endpoint required')
        view = self.uses.process(binding['use_id'], binding['process_identity'], scope, invocation=invocation)
        native = self.uses._process(view, 'communicate')
        if not getattr(native, 'guarded_write_supported', False):
            raise EnvironmentRefused('original provider has no physical guarded writer')
        row, first = self.uses._begin(scope, request_id, 'send-frame', binding['endpoint_id'], inputs,
                                      use_id=binding['use_id'])
        if not first:
            self.resolve(ref, scope, invocation=invocation, capability='observe', require_live=False)
            return self.uses._replay(row)
        origin_task, origin_thread = asyncio.current_task(), threading.get_ident()
        entered = False
        dispatched = False
        @contextmanager
        def actual_writer_guard():
            nonlocal entered, dispatched
            if entered or asyncio.current_task() is not origin_task or threading.get_ident() != origin_thread:
                raise EnvironmentRefused('guarded child write target or single-use cut differs')
            entered = True
            self.resolve(ref, scope, invocation=invocation, capability='communicate')
            with write_guard():
                # External engineering/current-send guard has admitted THIS cut.
                self.resolve(ref, scope, invocation=invocation, capability='communicate')
                dispatched = True
                yield
        try:
            count = await native.write_stdin_guarded(frame, timeout=timeout, write_guard=actual_writer_guard)
            if not dispatched or type(count) is not int or count != len(frame):
                raise EnvironmentRefused('provider did not confirm the guarded write cut')
        except BaseException as error:
            result = self.uses._finish(row, 'unknown' if dispatched else 'refused',
                delivery='possibly_sent' if dispatched else 'not_sent',
                bytesObserved=None if dispatched else 0,
                code='ENVIRONMENTS_SEND_UNKNOWN' if dispatched else 'ENVIRONMENTS_SEND_NOT_SENT')
            if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            return result
        return self.uses._finish(row, 'completed', delivery='confirmed', bytesObserved=count)

    def send_result(self, ref, scope, *, request_id, invocation):
        """Original read-authorized child facts, including cold unknown; no live reopen."""
        binding, _ = self.resolve(ref, scope, invocation=invocation, capability='observe', require_live=False)
        with self.manager.store.transaction() as db:
            row = db.execute('SELECT * FROM environment_use_requests WHERE owner_scope=? AND request_id=?',
                             (scope.storage_key, request_id)).fetchone()
        if row is None or row['action'] != 'send-frame' or row['target'] != binding['endpoint_id']:
            raise EnvironmentRefused('original child send result unavailable')
        return self.uses._replay(row)

    @staticmethod
    def _relative(relative):
        if (type(relative) is not str or not relative or len(relative) > 512
                or '\\' in relative or '\x00' in relative or os.path.isabs(relative)
                or relative != '.' and any(p in ('', '.', '..') for p in relative.split('/'))):
            raise EnvironmentRefused('canonical relative bound path required')
        return relative

    def _path(self, use, roots, bound):
        if (not isinstance(bound, dict) or set(bound) != {'schemaVersion','rootKey','relativePath'}
                or bound['schemaVersion'] != 'bound-path/1' or bound['rootKey'] not in roots):
            raise EnvironmentRefused('path is not in the externally approved root binding')
        relative = self._relative(bound['relativePath'])
        joined = os.path.normpath(os.path.join(roots[bound['rootKey']], relative))
        return use.files.path(joined)

    def directory(self, ref, scope, bound, *, invocation):
        row, _ = self.resolve(ref, scope, invocation=invocation, capability='launcher')
        return self._path(self._live(scope, row['use_id']), json.loads(row['roots']), bound)

    def directory_ready(self, ref, scope, bound, *, invocation, create=False):
        """Private-directory fact through the backend's own file area.

        The host filesystem is not the authority for a remote provider: existence
        and creation go through the environment's files capability, which for a
        local provider is the host directory and for a remote provider is the
        sandbox file area.
        """
        row, _ = self.resolve(ref, scope, invocation=invocation, capability='launcher')
        use = self._live(scope, row['use_id'])
        path = self._path(use, json.loads(row['roots']), bound)
        relative = os.path.relpath(path, use.files.root())
        if relative == os.curdir:
            return path
        if create:
            use.files.ensure(relative)
        elif not use.files.exists(relative):
            raise EnvironmentRefused('approved root is absent: ' + bound['rootKey'])
        return path

    def _verify_configuration(self, use, roots, ref):
        required = {'schemaVersion','issuer','configurationId','revision','digest','mediaType','byteLength','location'}
        if not isinstance(ref, dict) or set(ref) != required or ref['schemaVersion'] != 'prepared-configuration-ref/1':
            raise EnvironmentRefused('prepared configuration reference is invalid')
        path = self._path(use, roots, ref['location'])
        relative = os.path.relpath(path, use.files.root())
        body = use.files.read_text(relative).encode('utf-8')
        if len(body) > 262144 or len(body) != ref['byteLength'] or 'sha256:'+hashlib.sha256(body).hexdigest() != ref['digest']:
            raise EnvironmentRefused('prepared configuration bytes differ from pinned reference')

    def verify(self, ref, scope, prepared_ref, *, invocation):
        row, _ = self.resolve(ref, scope, invocation=invocation, capability='files')
        self._verify_configuration(self._live(scope, row['use_id']), json.loads(row['roots']), prepared_ref)
        return {'verified': True, 'digest': prepared_ref['digest']}

    def materialize(self, ref, scope, artifact, *, request_id, invocation):
        binding, _ = self.resolve(ref, scope, invocation=invocation, capability='files')
        if (not isinstance(artifact, dict) or set(artifact) != {'schemaVersion','target','mediaType','textUtf8','digest','mode'}
                or artifact['schemaVersion'] != 'configuration-artifact/1'
                or type(artifact['textUtf8']) is not str or type(artifact['mode']) is not int
                or artifact['mode'] not in (384, 420)):
            raise EnvironmentRefused('invalid bounded configuration artifact')
        body = artifact['textUtf8'].encode('utf-8')
        if len(body) > 262144 or 'sha256:'+hashlib.sha256(body).hexdigest() != artifact['digest']:
            raise EnvironmentRefused('configuration artifact digest/size differs')
        use = self._live(scope, binding['use_id'])
        path = self._path(use, json.loads(binding['roots']), artifact['target'])
        relative = os.path.relpath(path, use.files.root())
        row, first = self.uses._begin(scope, request_id, 'materialize', ref['endpointId'],
            {'target': artifact['target'], 'digest': artifact['digest'], 'mode': artifact['mode'], 'mediaType': artifact['mediaType']}, use_id=binding['use_id'])
        if not first: return self.uses._replay(row)
        try:
            self.resolve(ref, scope, invocation=invocation, capability='files')
            use.files.write_text_atomic(relative, artifact['textUtf8'], mode=artifact['mode'])
        except EnvironmentRefused:
            return self.uses._finish(row, 'refused', code='ENVIRONMENTS_FILE_REFUSED')
        except Exception:
            return self.uses._finish(row, 'unknown', code='ENVIRONMENTS_FILE_UNKNOWN')
        return self.uses._finish(row, 'completed', digest=artifact['digest'], byteLength=len(body))

    def verify_materialized(self, ref, scope, artifact, *, invocation):
        binding, _ = self.resolve(ref, scope, invocation=invocation, capability='files')
        use = self._live(scope, binding['use_id'])
        path = self._path(use, json.loads(binding['roots']), artifact['target'])
        body = use.files.read_text(os.path.relpath(path, use.files.root())).encode('utf-8')
        if len(body) > 262144 or 'sha256:'+hashlib.sha256(body).hexdigest() != artifact['digest']:
            raise EnvironmentRefused('materialized artifact bytes differ from pinned launch plan')
        return {'verified': True, 'digest': artifact['digest']}

    def launch(self, ref, scope, request, *, request_id, invocation, prepared_configurations=()):
        row, descriptor = self.resolve(ref, scope, invocation=invocation, capability='launcher')
        for prepared in prepared_configurations:
            if prepared not in descriptor['preparedConfigurations']:
                raise EnvironmentRefused('prepared configuration was not externally admitted')
            self._verify_configuration(self._live(scope, row['use_id']), json.loads(row['roots']), prepared)
        result = self.uses.launch(row['use_id'], scope, request, request_id=request_id, invocation=invocation)
        if result['status'] != 'completed': return result
        # A process gets only independently exported rights; launch grants none.
        rights = tuple(c for c in descriptor['capabilities'] if c != 'launcher')
        try:
            exported = self.export(row['use_id'], scope, capabilities=rights,
                request_id=result['operationRef']+'/endpoint', invocation=invocation,
                roots=json.loads(row['roots']), process_identity=result['processIdentity'])
        except Exception:
            return {**result, 'status': 'unknown', 'code': 'ENVIRONMENTS_ENDPOINT_PUBLICATION_UNKNOWN'}
        if exported['status'] != 'completed':
            return {**result, 'status': 'unknown', 'code': 'ENVIRONMENTS_ENDPOINT_PUBLICATION_UNKNOWN'}
        return {**result, 'processEndpointRef': exported['endpointRef']}

    def process(self, ref, scope, *, invocation):
        row, _ = self.resolve(ref, scope, invocation=invocation)
        if row['process_identity'] is None:
            raise EnvironmentRefused('endpoint has no confirmed original process')
        return EndpointProcess(self, ref, scope, invocation)


class EndpointProcess:
    def __init__(self, service, ref, scope, invocation):
        self._service, self._ref, self._scope, self._invocation = service, ref, scope, invocation

    def _view(self, capability):
        row, _ = self._service.resolve(self._ref, self._scope, invocation=self._invocation, capability=capability)
        return self._service.uses.process(row['use_id'], row['process_identity'], self._scope, invocation=self._invocation)

    def observe(self): return self._view('observe').observe()
    async def wait_exit(self, *, timeout=None): return await self._view('observe').wait_exit(timeout=timeout)
    async def read_stdout(self, max_bytes=65536, *, timeout=None): return await self._view('communicate').read_stdout(max_bytes, timeout=timeout)
    async def read_stderr(self, max_bytes=65536, *, timeout=None): return await self._view('communicate').read_stderr(max_bytes, timeout=timeout)
    async def write_stdin(self, data, *, timeout=None): return await self._view('communicate').write_stdin(data, timeout=timeout)
    async def close_stdin(self): return await self._view('communicate').close_stdin()
    async def terminate(self, *, request_id, force=False): return await self._view('terminate').terminate(request_id=request_id, force=force)
    def detach(self, *, request_id): return self._view('detach').detach(request_id=request_id)


    async def terminate_guarded(self, *, request_id, force=False, guard_effect):
        return await self._view('terminate').terminate_guarded(request_id=request_id,force=force,guard_effect=guard_effect)

    def detach_guarded(self, *, request_id, guard_effect):
        return self._view('detach').detach_guarded(request_id=request_id,guard_effect=guard_effect)
