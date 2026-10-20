"""AgentManager against the real test-caller endpoint fixture (no mocking).

The fixture owns the resources; the Agent receives only the strict F1 endpoint,
its resolver and the invocation — no Use, no environment object.
"""
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / 'tests/integration/packages_convergence'))

from endpoint_fixture import LocalEndpointFixture  # noqa: E402

from ordessa_execution_agents.sdk.manager import AgentManager, ManagerRefused, Records  # noqa: E402


def test_manager_starts_replays_and_releases_a_real_local_process(tmp_path):
    outcome = {}

    async def scenario():
        fixture = LocalEndpointFixture(tmp_path)
        try:
            endpoint = await fixture.endpoint()
            manager = AgentManager(fixture.resolver, Records(tmp_path / 'records.jsonl'))
            plan = fixture.plan(['/bin/echo', 'real-agent-manager'])
            first = await manager._launch_once('test/manager-start', plan, endpoint.ref, fixture.invocation)
            assert first.status in ('accepted', 'completed'), first.status
            assert first.process_endpoint_ref is not None
            result = await fixture.wait_exit(first.process_endpoint_ref)
            assert result.exit_code == 0, result.exit_code
            # The recorded start is replayed: no second process is launched.
            replay = await manager._launch_once('test/manager-start', plan, endpoint.ref,
                                         fixture.invocation)
            assert replay.operation_ref == first.operation_ref
            assert manager.records.operation('test/manager-start', 'start').status == first.status
            outcome['process'] = first.process_endpoint_ref
            # A member that was not exported is refused before any effect.
            bare = endpoint.__class__(endpoint.ref, {})
            manager_bare = AgentManager(type('R', (), {'resolve': staticmethod(
                lambda ref, invocation: _resolved(bare))})(),
                Records(tmp_path / 'r2.jsonl'))
            try:
                await manager_bare._launch_once('test/bare', plan, endpoint.ref, fixture.invocation)
                raise AssertionError('a bare endpoint must not launch')
            except ManagerRefused as error:
                assert error.code == 'LAUNCHER_NOT_GRANTED'
        finally:
            await fixture.cleanup()

    async def _resolved(bound):
        return bound

    asyncio.run(scenario())
