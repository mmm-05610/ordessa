"""Environment capability through real generic registry, local provider/SQLite."""
import asyncio
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from ordessa_interfaces_contracts import validate_capability
from ordessa_interfaces.system_access import (
    CapabilityHost, RequestContext, build_registry,
)
from ordessa_environments import (
    EnvironmentManager, EnvironmentOperationUnknown, OwnerScope, SQLiteEnvironmentStore,
)
from ordessa_environments.capability import EnvironmentCapabilityService, factory
from ordessa_environments_local import LocalEnvironmentResourceProvider


class EnvironmentCapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ordessa-env-capability-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manager = EnvironmentManager(store=SQLiteEnvironmentStore(self.root/'env.sqlite'), providers={
            'local': LocalEnvironmentResourceProvider(default_root=str(self.root/'work'))})
        self.scope = OwnerScope('principal', 'local-test-subject')
        self.invocation = SimpleNamespace(owner_scope=self.scope)
        self.denied = set()
        self.services = EnvironmentCapabilityService(self.manager,
            authorize=lambda scope, action, target, invocation: (
                scope == self.scope and invocation is self.invocation and action not in self.denied),
            provider_catalog=[{'id': 'local', 'available': True, 'isolation': 'none'},
                              {'id': 'openshell', 'available': False, 'status': 'UNAVAILABLE'}],
            aliases_path=self.root/'aliases.json')
        capability = factory.build({'services': self.services,
                                    'invocation_resolver': lambda context: self.invocation})
        self.capability = capability
        validate_capability(capability)
        self.host = CapabilityHost(build_registry([capability]), ('environments',))
        self.count = 0

    def call(self, action, data=None, request_id=None):
        self.count += 1
        context = RequestContext({'id': 'local-test-subject'}, request_id or str(self.count))
        return asyncio.run(self.host.call('environments.'+action, data or {}, context))

    def create(self, request_id='create'):
        result = self.call('create', {'provider': 'local', 'root': str(self.root/'work'), 'alias': 'work'}, request_id)
        self.assertEqual(result.status, 'completed', result)
        return result

    def test_registry_descriptors_and_real_resource_queries(self):
        self.assertEqual(self.call('providers').data['providers'][1]['status'], 'UNAVAILABLE')
        result = self.create()
        self.assertEqual(self.create(), result)
        self.assertEqual(len(self.call('list').data['resources']), 1)
        view = self.call('inspect', {'reference': 'work'}).data
        self.assertEqual(view['identity'], result.data['identity'])
        self.assertEqual(view['activeUses'], 0)
        self.assertFalse(view['capabilities']['assurance']['isolationIsSecurityBoundary'])

    def test_positive_exec_echo_pipe_nonzero_exit_and_cleanup(self):
        self.create()
        # A one-shot exec must not retain its process transport: otherwise a
        # foreground session would refuse to exit forever.
        result = self.call('exec', {'reference': 'work', 'argv': ['/bin/echo', 'hello']})
        self.assertEqual(result.status, 'completed', result.error)
        facts = self.services.session_facts()
        self.assertEqual(facts['processes'], [])
        self.assertEqual([use for use in facts['uses'] if use['phase'] == 'active'], [])
        echo = self.call('exec', {'reference': 'work', 'argv': ['/bin/echo', 'registry-positive']})
        self.assertEqual(echo.status, 'completed', echo)
        self.assertEqual(echo.data['stdout'], 'registry-positive\n')
        pipe = self.call('exec', {'reference': 'work', 'argv': ['/bin/cat'], 'stdin': 'pipe-positive\n'})
        self.assertEqual(pipe.status, 'completed', pipe)
        self.assertEqual(pipe.data['stdout'], 'pipe-positive\n')
        child = self.call('exec', {'reference': 'work', 'argv': ['/bin/false']})
        self.assertEqual(child.status, 'completed', child)
        self.assertEqual(child.data['exitCode'], 1)
        self.assertEqual(self.call('inspect', {'reference': 'work'}).data['activeUses'], 0)

    def test_file_roundtrip_and_local_lifecycle_preserves_user_files(self):
        self.create()
        write = self.call('files', {'reference': 'work', 'verb': 'write', 'path': 'kept.txt', 'content': 'kept'})
        self.assertEqual(write.status, 'completed', write)
        self.assertEqual(self.call('files', {'reference': 'work', 'verb': 'cat', 'path': 'kept.txt'}).data['content'], 'kept')
        self.assertIn('kept.txt', self.call('files', {'reference': 'work', 'verb': 'ls'}).data['entries'])
        for action in ('stop', 'delete'):
            self.assertEqual(self.call(action, {'reference': 'work'}).status, 'refused')
        self.assertEqual((self.root/'work/kept.txt').read_text(), 'kept')

    def test_invalid_input_and_denied_authority_before_effect(self):
        self.create()
        invalid = self.call('exec', {'reference': 'work', 'argv': []})
        self.assertEqual(invalid.status, 'refused')
        self.assertEqual(invalid.error.code, 'INVALID_INPUT')
        self.denied.add('acquire')
        refused = self.call('acquire', {'reference': 'work', 'sharing': False})
        self.assertEqual(refused.status, 'refused')
        self.assertEqual(self.call('inspect', {'reference': 'work'}).data['activeUses'], 0)

    def test_explicit_use_release_and_cold_retention(self):
        self.create()
        acquired = self.call('acquire', {'reference': 'work', 'sharing': False})
        self.assertEqual(acquired.status, 'completed', acquired)
        use = acquired.data['useIdentity']
        view = self.call('use-inspect', {'useIdentity': use})
        self.assertEqual(view.data['ownerScope'], self.scope.to_dict())
        released = self.call('release', {'useIdentity': use})
        self.assertEqual(released.status, 'completed')
        self.assertEqual(self.call('inspect', {'reference': 'work'}).data['activeUses'], 0)

    def test_alias_conflict_and_unknown_after_resource_create_do_not_recreate(self):
        first = self.create()
        conflict = self.call('create', {'provider': 'local', 'root': str(self.root/'other'), 'alias': 'work'})
        self.assertEqual(conflict.status, 'refused')
        self.assertEqual(conflict.error.code, 'CONFLICT')
        self.services._alias = lambda *args: (_ for _ in ()).throw(OSError('controlled publication failure'))
        request = {'provider': 'local', 'root': str(self.root/'third'), 'alias': 'third'}
        unknown = self.call('create', request, 'uncertain-create')
        self.assertEqual(unknown.status, 'unknown')
        self.assertEqual(self.call('create', request, 'uncertain-create'), unknown)
        self.assertEqual(len(self.manager.list()), 2)

    def test_reconcile_is_published_and_never_creates_a_second_resource(self):
        published = {operation.id for operation in self.capability.descriptor.operations}
        self.assertIn('environments.reconcile', published)
        # An uncertain creation becomes a fact to verify, never a second create.
        provider = self.manager.providers['local']
        original = provider.create
        calls = []
        def uncertain(reference, **kwargs):
            calls.append(reference)
            raise EnvironmentOperationUnknown('controlled uncertain creation', identity='controlled')
        provider.create = uncertain
        unknown = self.call('create', {'provider': 'local', 'root': str(self.root/'work'),
                                       'alias': 'work'}, 'uncertain-create')
        self.assertEqual(unknown.status, 'unknown')
        identity = unknown.data['identity']
        provider.create = original
        reconciled = self.call('reconcile', {'reference': identity}, 'uncertain-reconcile')
        # The local provider owns no creation-correlation authority: it refuses
        # instead of guessing, and no second resource is created either way.
        self.assertEqual(reconciled.status, 'refused')
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.manager.list()), 1)
        self.assertEqual(self.manager.list()[0].phase, 'unknown')
        # A settled resource has nothing to reconcile.
        settled_create = self.call('create', {'provider': 'local', 'root': str(self.root/'other'),
                                              'alias': 'other'}, 'settled-create')
        self.assertEqual(settled_create.status, 'completed')
        settled = self.call('reconcile', {'reference': 'other'}, 'settled-reconcile')
        self.assertEqual(settled.status, 'refused')
        self.assertEqual(settled.error.code, 'INVALID_INPUT')

    def test_timeout_is_unknown_without_retry_and_releases_own_process(self):
        self.create()
        result = self.call('exec', {'reference': 'work', 'argv': ['/bin/sleep', '3'], 'timeout': 0.05}, 'timeout')
        self.assertEqual(result.status, 'unknown', result)
        self.assertEqual(result.error.code, 'OBSERVATION_TIMEOUT')
        self.assertEqual(self.call('exec', {'reference': 'work', 'argv': ['/bin/sleep', '3'], 'timeout': 0.05}, 'timeout'), result)
        self.assertEqual(self.call('inspect', {'reference': 'work'}).data['activeUses'], 0)

    def test_same_alias_concurrent_managers_reserve_before_effect(self):
        import threading
        entered, proceed = threading.Event(), threading.Event()
        provider = self.manager.providers['local']
        original = provider.create
        calls = []
        def delayed(reference, **kwargs):
            calls.append(reference['root'])
            entered.set()
            if not proceed.wait(3): raise RuntimeError('test scheduling timeout')
            return original(reference, **kwargs)
        provider.create = delayed
        second_manager = EnvironmentManager(store=SQLiteEnvironmentStore(self.root/'env.sqlite'), providers={'local': provider})
        second = EnvironmentCapabilityService(second_manager, authorize=self.services.uses.authorize,
            provider_catalog=[], aliases_path=self.root/'aliases.json')
        results, failures = [], []
        def first():
            try: results.append(self.call('create', {'provider':'local','root':str(self.root/'work'),'alias':'race'}, 'race-first'))
            except Exception as error: failures.append(error)
        thread = threading.Thread(target=first)
        thread.start()
        try:
            self.assertTrue(entered.wait(3))
            rejected = asyncio.run(second.invoke('create', {'provider':'local','root':str(self.root/'other'),'alias':'race'}, self.invocation, 'race-second'))
            self.assertEqual(rejected.status, 'refused')
            self.assertEqual(rejected.error.code, 'CONFLICT')
        finally:
            proceed.set(); thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(results[0].status, 'completed')
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.manager.list()), 1)
        self.assertEqual(second._identity('race'), results[0].data['identity'])

    def test_file_effect_then_revoked_cleanup_is_unknown_not_refused(self):
        self.create()
        original_release = self.services.uses.release
        calls = []
        def revoked(*args, **kwargs):
            calls.append(args[0])
            from ordessa_environments import EnvironmentRefused
            raise EnvironmentRefused('controlled cleanup revocation')
        self.services.uses.release = revoked
        request = {'reference':'work','verb':'write','path':'already-written.txt','content':'effect-confirmed'}
        result = self.call('files', request, 'write-then-revoke')
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.error.code, 'EFFECT_UNKNOWN')
        self.assertEqual((self.root/'work/already-written.txt').read_text(), 'effect-confirmed')
        self.assertEqual(self.call('files', request, 'write-then-revoke'), result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.manager.list()[0].active_uses, 1)
        self.services.uses.release = original_release
        self.assertEqual(original_release(calls[0], self.scope, request_id='explicit-cleanup', invocation=self.invocation)['status'], 'completed')


    def test_native_entry_is_published_and_names_every_provider(self):
        published = {operation.id for operation in self.capability.descriptor.operations}
        for identifier in ('environments.native.describe', 'environments.native.request',
                           'environments.native.query', 'environments.native.events'):
            self.assertIn(identifier, published)
        described = self.call('native.describe')
        self.assertEqual(described.status, 'completed', described)
        entries = {entry['id']: entry for entry in described.data['providers']}
        self.assertEqual(set(entries), {'local', 'openshell'})
        # The local provider owns no native management port: it is named, and
        # the fact that it has no such port is stated rather than invented.
        self.assertIsNone(entries['local']['management'])
        self.assertFalse(entries['openshell']['available'])

    def test_native_request_to_a_provider_without_the_port_is_refused(self):
        for provider in ('local', 'openshell'):
            result = self.call('native.request', {'provider': provider, 'action': 'list',
                                                  'requestId': 'native-' + provider})
            self.assertEqual(result.status, 'refused', result)
            self.assertEqual(result.error.code, 'CAPABILITY_UNSUPPORTED')

    def test_native_query_of_an_unknown_request_is_refused(self):
        result = self.call('native.query', {'requestId': 'native-absent'})
        self.assertEqual(result.status, 'refused', result)
        self.assertEqual(result.error.code, 'INVALID_INPUT')

    def test_native_events_of_an_empty_owner_is_a_complete_empty_page(self):
        page = self.call('native.events')
        self.assertEqual(page.status, 'completed', page)
        self.assertEqual(page.data['events'], [])
        self.assertTrue(page.data['complete'])


if __name__ == '__main__':
    unittest.main()


class _StructuredProvider:
    """Minimal non-local provider: records the forwarded creation reference."""

    operations = frozenset({'start', 'stop', 'delete'})

    def __init__(self):
        self.references = []
        self.identity = 'structured'
        self.binding_id = 'structured-binding'

    def create(self, reference, *, operation_id):
        from ordessa_environments import BackendObservation, CapabilityReport
        self.references.append((dict(reference), operation_id))
        return BackendObservation('backend-1', 'running',
            CapabilityReport({}, 'structured', 'provider_self_report', '', {}),
            '2026-10-20T00:00:00+00:00', None)

    def inspect(self, backend_id):
        from ordessa_environments import BackendObservation, CapabilityReport
        return BackendObservation(backend_id, 'running',
            CapabilityReport({}, 'structured', 'provider_self_report', '', {}),
            '2026-10-20T00:00:00+00:00', None)

    def start(self, backend_id):
        return self.inspect(backend_id)

    def stop(self, backend_id):
        return self.inspect(backend_id)

    def delete(self, backend_id):
        return None


class StructuredReferenceCreateTests(unittest.TestCase):
    """A remote provider receives one closed structured reference, not a path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ordessa-env-structured-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.provider = _StructuredProvider()
        self.manager = EnvironmentManager(
            store=SQLiteEnvironmentStore(self.root/'env.sqlite'),
            providers={'local': LocalEnvironmentResourceProvider(default_root=str(self.root/'work')),
                       'structured': self.provider})
        self.scope = OwnerScope('principal', 'local-test-subject')
        self.invocation = SimpleNamespace(owner_scope=self.scope)
        self.services = EnvironmentCapabilityService(self.manager,
            authorize=lambda scope, action, target, invocation: True,
            provider_catalog=[{'id': 'local', 'available': True},
                              {'id': 'structured', 'available': True}],
            aliases_path=self.root/'aliases.json')
        self.capability = factory.build({'services': self.services,
                                         'invocation_resolver': lambda context: self.invocation})
        self.host = CapabilityHost(build_registry([self.capability]), ('environments',))
        self.count = 0

    def call(self, action, data=None, request_id=None):
        self.count += 1
        context = RequestContext({'id': 'local-test-subject'}, request_id or str(self.count))
        return asyncio.run(self.host.call('environments.'+action, data or {}, context))

    REFERENCE = {'image': 'image:1', 'policy': {'version': 1}, 'main_command': ['sleep', 'infinity']}

    def test_structured_reference_is_forwarded_to_the_selected_provider(self):
        result = self.call('create', {'provider': 'structured', 'reference': self.REFERENCE,
                                      'alias': 'remote'}, 'structured-create')
        self.assertEqual(result.status, 'completed', result)
        reference, operation_id = self.provider.references[0]
        self.assertEqual(reference, self.REFERENCE)
        self.assertRegex(operation_id, r'^[0-9a-f]{32}$')
        view = self.call('inspect', {'reference': 'remote'}).data
        self.assertEqual(view['backendId'], 'backend-1')

    def test_replayed_request_derives_the_same_operation_identity(self):
        request = {'provider': 'structured', 'reference': self.REFERENCE, 'alias': 'remote'}
        first = self.call('create', request, 'structured-replay')
        second = self.call('create', request, 'structured-replay')
        self.assertEqual(first.data, second.data)
        self.assertEqual(len(self.provider.references), 1)

    def test_missing_structured_reference_is_refused_before_any_effect(self):
        result = self.call('create', {'provider': 'structured'}, 'structured-missing')
        self.assertEqual(result.status, 'refused')
        self.assertEqual(result.error.code, 'INVALID_INPUT')
        self.assertEqual(self.provider.references, [])

    def test_local_provider_still_requires_an_absolute_root(self):
        for payload in ({'provider': 'local'}, {'provider': 'local', 'root': 'relative'}):
            result = self.call('create', payload, 'local-' + str(self.count))
            self.assertEqual(result.status, 'refused')
            self.assertEqual(result.error.code, 'INVALID_INPUT')
