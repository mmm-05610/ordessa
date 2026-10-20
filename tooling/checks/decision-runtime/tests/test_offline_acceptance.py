"""The controlled offline fixture still completes through both graph variants."""
import asyncio

from assignment_source.offline import run_offline


def test_default_and_alternate_offline_assignment_complete():
    for alternate in (False, True):
        result = asyncio.run(run_offline(alternate=alternate))
        assert result.outcome.disposition == 'ready'
