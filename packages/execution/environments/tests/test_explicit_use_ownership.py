"""Real local processes/SQLite; callable policy controls independent permissions."""
import asyncio
from pathlib import Path
import tempfile
import unittest

from ordessa_environments import (
    EnvironmentManager, EnvironmentOperationUnknown, EnvironmentRefused,
    EnvironmentUseOperations, OwnerScope, ProcessRequest, SQLiteEnvironmentStore,
)
from ordessa_environments_local import LocalEnvironmentResourceProvider


class ExplicitOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ordessa-owner-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.provider = LocalEnvironmentResourceProvider(default_root=str(self.root/'work'))
        self.manager = EnvironmentManager(store=SQLiteEnvironmentStore(self.root/'env.sqlite'),
                                          providers={'local': self.provider})
        self.instance = self.manager.create('local', {'root': str(self.root/'work')})
        self.scope = OwnerScope('principal', 'existing-user')
        self.rights = {'acquire', 'release', 'observe', 'launch', 'communicate', 'terminate', 'detach'}
        self.invocation = object()
        self.authorize = lambda scope, action, target, invocation: (
            invocation is self.invocation and scope == self.scope and action in self.rights)
        self.ops = EnvironmentUseOperations(self.manager, authorize=self.authorize)

    def acquire(self, request='acquire'):
        return self.ops.acquire(self.instance.identity, self.scope,
                                request_id=request, sharing=False, invocation=self.invocation)

    def release(self, use, request='release'):
        return self.ops.release(use, self.scope, request_id=request, invocation=self.invocation)

    def launch(self, use, argv, request='launch'):
        return self.ops.launch(use, self.scope,
            ProcessRequest.build(argv, cwd=str(self.root/'work'), env={}),
            request_id=request, invocation=self.invocation)

    def test_acquire_replay_is_one_durable_use_and_conflict_refuses(self):
        first = self.acquire()
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(self.acquire(), first)
        self.assertEqual(self.instance.snapshot.active_uses, 1)
        with self.assertRaisesRegex(EnvironmentRefused, 'conflicts'):
            self.ops.acquire(self.instance.identity, self.scope, request_id='acquire',
                             sharing=True, invocation=self.invocation)
        facts = self.ops.inspect(first['useIdentity'], self.scope, invocation=self.invocation)
        self.assertEqual(facts['ownerScope'], self.scope.to_dict())
        self.assertFalse(facts['lease'])
        self.assertEqual(self.release(first['useIdentity'])['status'], 'completed')
        self.assertEqual(self.instance.snapshot.active_uses, 0)

    def test_completed_release_replay_survives_store_reopen(self):
        use = self.acquire()['useIdentity']
        receipt = self.release(use)
        cold = EnvironmentManager(store=SQLiteEnvironmentStore(self.root/'env.sqlite'),
                                  providers={'local': self.provider})
        ops = EnvironmentUseOperations(cold, authorize=self.authorize)
        self.assertEqual(ops.release(use, self.scope, request_id='release', invocation=self.invocation), receipt)

    def test_cold_manager_retains_use_and_never_infers_owner_death(self):
        use = self.acquire()['useIdentity']
        cold = EnvironmentManager(store=SQLiteEnvironmentStore(self.root/'env.sqlite'),
                                  providers={'local': self.provider})
        ops = EnvironmentUseOperations(cold, authorize=self.authorize)
        self.assertEqual(ops.acquire(self.instance.identity, self.scope, request_id='acquire',
                                    sharing=False, invocation=self.invocation)['useIdentity'], use)
        receipt = ops.release(use, self.scope, request_id='cold-release', invocation=self.invocation)
        self.assertEqual(receipt['status'], 'pending')
        self.assertEqual(cold.get(self.instance.identity).snapshot.active_uses, 1)
        self.assertEqual(self.release(use)['status'], 'completed')

    def test_authorization_not_forgeable_by_owner_ref(self):
        with self.assertRaises(EnvironmentRefused):
            self.ops.acquire(self.instance.identity, self.scope, request_id='forged',
                             sharing=False, invocation=object())
        self.assertEqual(self.instance.snapshot.active_uses, 0)
        with self.assertRaises(EnvironmentRefused):
            OwnerScope('agent-instance', 'invented-owner')

    def test_unknown_acquisition_is_never_reopened_or_released_on_restart(self):
        calls = []
        original = self.provider.open_use
        def uncertain(backend_id, **kwargs):
            calls.append(kwargs['use_id'])
            original(backend_id, **kwargs)
            raise EnvironmentOperationUnknown('controlled lost view', identity=kwargs['use_id'])
        self.provider.open_use = uncertain
        first = self.acquire()
        self.assertEqual(first['status'], 'unknown')
        self.assertEqual(self.acquire(), first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.instance.snapshot.active_uses, 1)
        self.assertEqual(self.release(first['useIdentity'])['status'], 'pending')

    def test_positive_real_process_and_explicit_release_order(self):
        async def scenario():
            use = self.acquire()['useIdentity']
            launch = self.launch(use, ['/bin/echo', 'positive-real-output'])
            self.assertEqual(launch['status'], 'completed')
            self.assertEqual(self.launch(use, ['/bin/echo', 'positive-real-output']), launch)
            view = self.ops.process(use, launch['processIdentity'], self.scope, invocation=self.invocation)
            output = await view.read_stdout(timeout=2)
            self.assertIn(b'positive-real-output', output)
            self.assertEqual((await view.wait_exit(timeout=2)).exit_code, 0)
            self.assertEqual(self.release(use, 'before-detach')['status'], 'pending')
            receipt = view.detach(request_id='detach')
            self.assertFalse(receipt['exitClaimed'])
            self.assertEqual(view.detach(request_id='detach'), receipt)
            self.assertEqual(self.release(use, 'after-detach')['status'], 'completed')
            self.assertEqual(self.instance.snapshot.active_uses, 0)
            self.assertTrue((self.root/'work').exists())
        asyncio.run(scenario())

    def test_observe_communicate_terminate_detach_are_independent_and_revocable(self):
        async def scenario():
            use = self.acquire()['useIdentity']
            launch = self.launch(use, ['/bin/cat'])
            view = self.ops.process(use, launch['processIdentity'], self.scope, invocation=self.invocation)
            try:
                self.rights.discard('terminate'); self.rights.discard('communicate'); self.rights.discard('detach')
                self.assertEqual(view.observe().state, 'running')
                with self.assertRaises(EnvironmentRefused):
                    await view.write_stdin(b'denied')
                with self.assertRaises(EnvironmentRefused):
                    await view.terminate(request_id='denied-stop')
                with self.assertRaises(EnvironmentRefused):
                    view.detach(request_id='denied-detach')
                self.assertEqual(self.release(use)['status'], 'pending')
                self.assertEqual(view.observe().state, 'running')
                self.rights.discard('observe')
                with self.assertRaises(EnvironmentRefused): view.observe()
                self.rights.add('communicate')
                self.assertEqual(await view.write_stdin(b'allowed\n', timeout=2), 8)
                self.assertEqual(await view.read_stdout(timeout=2), b'allowed\n')
            finally:
                self.rights.update({'terminate','observe','detach'})
                await view.terminate(request_id='test-cleanup')
                await view.wait_exit(timeout=3)
                view.detach(request_id='test-detach')
                self.release(use, 'test-release')
        asyncio.run(scenario())

    def test_reserved_request_after_crash_cannot_dispatch_effect(self):
        # Commit the same reservation boundary a crash can leave before dispatch.
        self.ops._begin(self.scope, 'acquire', 'acquire', self.instance.identity,
                        {'environment': self.instance.identity, 'sharing': False})
        result = self.acquire()
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(self.instance.snapshot.active_uses, 0)


if __name__ == '__main__':
    unittest.main()
