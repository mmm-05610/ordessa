"""Process transport release is separate from exit and from Use release."""
from __future__ import annotations

import asyncio

import pytest

from ordessa_environments import (
    EnvironmentManager, EnvironmentRefused, ProcessRequest, SQLiteEnvironmentStore,
)
from ordessa_environments.management.ownership import EnvironmentUseOperations, OwnerScope
from ordessa_environments_local import LocalEnvironmentResourceProvider


def test_process_release_requires_observed_exit_and_use_release_is_separate(tmp_path):
    work = tmp_path / 'work'
    work.mkdir()
    manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(tmp_path / 'environments.sqlite'),
        providers={'local': LocalEnvironmentResourceProvider(default_root=str(work))})
    scope = OwnerScope('principal', 'os-user:test')
    invocation = object()
    uses = EnvironmentUseOperations(manager,
        authorize=lambda s, a, t, i: i is invocation and s == scope)
    environment = manager.create('local', {'root': str(work)})
    use = uses.acquire(environment.identity, scope, request_id='acquire',
                       sharing=False, invocation=invocation)
    use_id = use['useIdentity']

    def launch(argv):
        return uses.launch(use_id, scope, ProcessRequest.build(argv, cwd=str(work), env={}),
                           request_id='launch-' + argv[-1], invocation=invocation)

    async def scenario():
        # A running process is refused: release is not termination.
        running = launch(['/bin/sh', '-c', 'sleep 1'])
        running_process = uses.process(use_id, running['processIdentity'], scope,
                                       invocation=invocation)
        refused = uses.process_release(use_id, running['processIdentity'], scope,
                                       request_id='release-running', invocation=invocation)
        assert refused['status'] == 'refused'
        assert refused['code'] == 'ENVIRONMENTS_PROCESS_NOT_EXITED'
        assert running_process.observe().state == 'running'
        # The Use cannot be released while the original transport is unreleased.
        busy = uses.release(use_id, scope, request_id='release-busy', invocation=invocation)
        assert busy['status'] == 'pending' and busy['code'] == 'ENVIRONMENTS_USE_BUSY'
        await running_process.terminate(request_id='terminate-running')
        await running_process.wait_exit(timeout=5)

        completed = uses.process_release(use_id, running['processIdentity'], scope,
                                         request_id='release-exited', invocation=invocation)
        assert completed['status'] == 'completed'
        assert completed['exitClaimed'] is False
        assert completed['receipt']['transportReleased'] is True
        assert completed['receipt']['processState'] == 'exited'
        # Replay reads the original receipt; it does not repeat the effect.
        assert uses.process_release(use_id, running['processIdentity'], scope,
                                    request_id='release-exited',
                                    invocation=invocation) == completed
        # A foreign owner is refused before any effect.
        with pytest.raises(EnvironmentRefused):
            uses.process_release(use_id, running['processIdentity'],
                                 OwnerScope('principal', 'os-user:other'),
                                 request_id='foreign', invocation=invocation)

        released = uses.release(use_id, scope, request_id='release-use', invocation=invocation)
        assert released['status'] == 'completed'
        assert released['resourcePreserved'] is True
        assert work.is_dir()

    asyncio.run(scenario())
