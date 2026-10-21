"""Consumer-facing test endpoint fixture proof; real short process, zero models."""
import asyncio
from endpoint_fixture import LocalEndpointFixture
from ordessa_agents.sdk.endpoint import BoundEndpoint


def test_worker_consumable_exact_endpoint_and_explicit_caller_cleanup(tmp_path):
    async def scenario():
        fixture=LocalEndpointFixture(tmp_path)
        try:
            endpoint=await fixture.endpoint()
            assert type(endpoint) is BoundEndpoint
            launched=await endpoint.launcher.launch(fixture.plan(['/bin/echo','fixture-positive']),
                                                      'consumer/start',fixture.invocation)
            assert launched.status=='completed'
            process=await fixture.resolver.resolve(launched.process_endpoint_ref,fixture.invocation)
            page=await process.communicate.receive(None,asyncio.get_running_loop().time()+2,fixture.invocation)
            assert b''.join(event.payload_bytes for event in page.events)==b'fixture-positive\n'
            assert (await fixture.wait_exit(launched.process_endpoint_ref)).exit_code==0
            await process.detach.detach('consumer/detach',fixture.invocation)
            assert fixture.retained_use_count==1
        finally:
            await fixture.cleanup()
        assert fixture.retained_use_count==0
    asyncio.run(scenario())
