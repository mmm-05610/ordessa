"""Real resource endpoints persist bindings without transferring Use to agents."""
import asyncio
import hashlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from ordessa_environments import EnvironmentManager, EnvironmentRefused, EnvironmentUseOperations, EnvironmentEndpoints, OwnerScope, ProcessRequest, SQLiteEnvironmentStore
from ordessa_environments_local import LocalEnvironmentResourceProvider


class EndpointBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ordessa-endpoint-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.provider = LocalEnvironmentResourceProvider(default_root=str(self.root/'work'))
        self.manager = EnvironmentManager(store=SQLiteEnvironmentStore(self.root/'env.sqlite'), providers={'local': self.provider})
        self.instance = self.manager.create('local', {'root': str(self.root/'work')})
        self.scope = OwnerScope('principal', 'existing-subject')
        self.invocation = SimpleNamespace(owner_scope=self.scope)
        self.denied = set()
        self.authorize = lambda scope, action, target, invocation: scope == self.scope and invocation is self.invocation and action not in self.denied
        self.uses = EnvironmentUseOperations(self.manager, authorize=self.authorize)
        self.service = EnvironmentEndpoints(self.uses)
        self.use = self.uses.acquire(self.instance.identity, self.scope, request_id='acquire', sharing=False, invocation=self.invocation)['useIdentity']

    def export(self, capabilities, request='export', **kwargs):
        return self.service.export(self.use, self.scope, capabilities=capabilities, request_id=request,
                                   invocation=self.invocation, **kwargs)

    def request(self, argv):
        return ProcessRequest.build(argv, cwd=str(self.root/'work'), env={})

    def cleanup_process(self, data):
        async def cleanup():
            process = self.uses.process(self.use, data['processIdentity'], self.scope, invocation=self.invocation)
            if process.observe().state != 'exited': await process.terminate(request_id='cleanup-stop')
            await process.wait_exit(timeout=3)
            process.detach(request_id='cleanup-detach')
            self.uses.release(self.use, self.scope, request_id='cleanup-release', invocation=self.invocation)
        asyncio.run(cleanup())

    def test_launcher_does_not_implicitly_grant_observe_or_terminate(self):
        exported = self.export(['launcher'])
        self.assertEqual(self.export(['launcher']), exported)
        self.assertNotIn('use', str(exported['endpointRef']).lower())
        data = self.service.launch(exported['endpointRef'], self.scope, self.request(['/bin/cat']), request_id='launch', invocation=self.invocation)
        try:
            _, descriptor = self.service.resolve(data['processEndpointRef'], self.scope, invocation=self.invocation)
            self.assertEqual(descriptor['capabilities'], [])
            process = self.service.process(data['processEndpointRef'], self.scope, invocation=self.invocation)
            with self.assertRaises(EnvironmentRefused): process.observe()
            with self.assertRaises(EnvironmentRefused): asyncio.run(process.terminate(request_id='unauthorized'))
            self.assertEqual(self.uses.release(self.use, self.scope, request_id='busy', invocation=self.invocation)['status'], 'pending')
        finally: self.cleanup_process(data)

    def test_positive_original_process_communication_and_explicit_lifecycle(self):
        async def scenario():
            ref = self.export(['launcher','observe','communicate','terminate','detach'])['endpointRef']
            data = self.service.launch(ref, self.scope, self.request(['/bin/cat']), request_id='launch', invocation=self.invocation)
            self.assertEqual(self.service.launch(ref, self.scope, self.request(['/bin/cat']), request_id='launch', invocation=self.invocation), data)
            process = self.service.process(data['processEndpointRef'], self.scope, invocation=self.invocation)
            try:
                self.assertEqual(await process.write_stdin(b'endpoint-positive\n', timeout=2), 18)
                self.assertEqual(await process.read_stdout(timeout=2), b'endpoint-positive\n')
                self.denied.add('terminate')
                with self.assertRaises(EnvironmentRefused): await process.terminate(request_id='denied')
            finally:
                self.denied.discard('terminate')
                result = await process.terminate(request_id='stop')
                self.assertEqual(result['status'], 'completed')
                await process.wait_exit(timeout=3)
                process.detach(request_id='detach')
                self.assertEqual(self.uses.release(self.use, self.scope, request_id='release', invocation=self.invocation)['status'], 'completed')
        asyncio.run(scenario())

    def test_cold_resolver_never_reopens_use_or_rebinds_endpoint(self):
        ref = self.export(['launcher'])['endpointRef']
        cold = EnvironmentManager(store=SQLiteEnvironmentStore(self.root/'env.sqlite'), providers={'local': self.provider})
        cold_service = EnvironmentEndpoints(EnvironmentUseOperations(cold, authorize=self.authorize))
        self.provider.open_use = lambda *a, **k: self.fail('cold resolver must not reopen Use')
        with self.assertRaisesRegex(EnvironmentRefused, 'original endpoint unavailable'):
            cold_service.resolve(ref, self.scope, invocation=self.invocation)
        self.assertEqual(cold.get(self.instance.identity).snapshot.active_uses, 1)
        self.uses.release(self.use, self.scope, request_id='release', invocation=self.invocation)

    def test_digest_tampering_and_traversal_refuse(self):
        ref = self.export(['launcher'])['endpointRef']
        with self.assertRaises(EnvironmentRefused):
            self.service.resolve({**ref,'descriptorDigest':'sha256:'+'0'*64}, self.scope, invocation=self.invocation)
        with self.assertRaises(EnvironmentRefused):
            self.service.directory(ref, self.scope, {'schemaVersion':'bound-path/1','rootKey':'work','relativePath':'../escape'}, invocation=self.invocation)
        self.uses.release(self.use, self.scope, request_id='release', invocation=self.invocation)

    def test_atomic_configuration_and_prepared_no_file_endpoint(self):
        ref = self.export(['files'], request='files')['endpointRef']
        body = 'prepared-positive'
        digest = 'sha256:'+hashlib.sha256(body.encode()).hexdigest()
        location = {'schemaVersion':'bound-path/1','rootKey':'work','relativePath':'config.txt'}
        artifact = {'schemaVersion':'configuration-artifact/1','target':location,'mediaType':'text/plain','textUtf8':body,'digest':digest,'mode':384}
        first = self.service.materialize(ref, self.scope, artifact, request_id='write', invocation=self.invocation)
        self.assertEqual(first['status'], 'completed')
        self.assertEqual(self.service.materialize(ref, self.scope, artifact, request_id='write', invocation=self.invocation), first)
        self.assertEqual((self.root/'work/config.txt').read_text(), body)
        self.assertEqual((self.root/'work/config.txt').stat().st_mode & 0o777, 0o600)
        self.assertFalse(list((self.root/'work').glob('.ordessa-config-*')))
        prepared = {'schemaVersion':'prepared-configuration-ref/1','issuer':'existing-config-authority',
            'configurationId':'configuration','revision':'1','digest':digest,'mediaType':'text/plain','byteLength':len(body),'location':location}
        self.assertTrue(self.service.verify(ref,self.scope,prepared,invocation=self.invocation)['verified'])
        launch_ref = self.export(['launcher','observe','communicate','detach'], request='prepared', prepared_configurations=[prepared])['endpointRef']
        data = self.service.launch(launch_ref,self.scope,self.request(['/bin/cat','config.txt']),request_id='prepared-launch',invocation=self.invocation,prepared_configurations=[prepared])
        self.cleanup_process(data)

    def test_detached_exited_process_does_not_destroy_reusable_use(self):
        async def scenario():
            ref=self.export(['launcher','observe','communicate','detach'])['endpointRef']
            observed=[]
            for number in range(2):
                launched=self.service.launch(ref,self.scope,self.request(['/bin/echo',str(number)]),request_id='reuse/'+str(number),invocation=self.invocation)
                process=self.service.process(launched['processEndpointRef'],self.scope,invocation=self.invocation)
                observed.append(await process.read_stdout(timeout=2))
                await process.wait_exit(timeout=2)
                process.detach(request_id='detach/'+str(number))
                self.assertEqual(self.instance.snapshot.active_uses,1)
            self.assertEqual(observed,[b'0\n',b'1\n'])
            self.assertEqual(len(self.manager._owned_process_handles),2)
            self.assertEqual(self.uses.release(self.use,self.scope,request_id='caller-release',invocation=self.invocation)['status'],'completed')
            self.assertEqual(self.instance.snapshot.active_uses,0)
        asyncio.run(scenario())

    def test_observe_revocation_does_not_remove_communicate_permission(self):
        async def scenario():
            ref=self.export(['launcher','observe','communicate','terminate','detach'])['endpointRef']
            launched=self.service.launch(ref,self.scope,self.request(['/bin/cat']),request_id='launch',invocation=self.invocation)
            process=self.service.process(launched['processEndpointRef'],self.scope,invocation=self.invocation)
            self.denied.add('observe')
            try:
                with self.assertRaises(EnvironmentRefused):process.observe()
                self.assertEqual(await process.write_stdin(b'communication-only\n',timeout=2),19)
                self.assertEqual(await process.read_stdout(timeout=2),b'communication-only\n')
            finally:
                self.denied.clear()
                await process.terminate(request_id='cleanup')
                await process.wait_exit(timeout=2)
                process.detach(request_id='detach')
                self.uses.release(self.use,self.scope,request_id='release',invocation=self.invocation)
        asyncio.run(scenario())

    def test_forged_subject_or_caller_cannot_resolve_locator(self):
        ref=self.export(['observe'])['endpointRef']
        with self.assertRaises(EnvironmentRefused):
            self.service.resolve(ref,OwnerScope('principal','different-subject'),invocation=self.invocation)
        with self.assertRaises(EnvironmentRefused):
            self.service.resolve(ref,self.scope,invocation=SimpleNamespace(owner_scope=self.scope))
        self.assertEqual(self.instance.snapshot.active_uses,1)
        self.uses.release(self.use,self.scope,request_id='release',invocation=self.invocation)

    def test_same_unknown_launch_request_never_dispatches_twice(self):
        use=self.manager._owned_use_handles[self.use]
        original=use._backend.execution.start
        calls=[]
        def uncertain(request):
            from ordessa_environments import EnvironmentOperationUnknown
            # No real process is needed to model unknown delivery here; all
            # storage/fencing is real and the invocation count is asserted.
            calls.append(request.argv)
            raise EnvironmentOperationUnknown('controlled lost launch response',identity=self.use)
        use._backend.execution.start=uncertain
        ref=self.export(['launcher'])['endpointRef']
        first=self.service.launch(ref,self.scope,self.request(['/bin/echo','never-retry']),request_id='uncertain-launch',invocation=self.invocation)
        self.assertEqual(first['status'],'unknown')
        second=self.service.launch(ref,self.scope,self.request(['/bin/echo','never-retry']),request_id='uncertain-launch',invocation=self.invocation)
        self.assertEqual(second,first)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.instance.snapshot.active_uses,1)
        self.assertEqual(self.uses.release(self.use,self.scope,request_id='release',invocation=self.invocation)['status'],'pending')
        use._backend.execution.start=original


if __name__ == '__main__': unittest.main()
