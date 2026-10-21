"""Actual original Agent provenance and explicit external scope port, no send."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace
import pytest
from test_agent_guarded_bootstrap import setup
from ordessa_agents.public import InteractionService
from ordessa_engineering.adapters.native_records.agent_selection import OriginalAgentDispatchSelection
from ordessa_engineering.application.contracts.errors import ApplicationError


def test_original_profile_pin_read_refusal_and_explicit_scope_port(tmp_path):
    async def scenario():
        case=await setup(tmp_path)
        try:
            started=await case.manager.start(case.request,case.endpoint,case.fixture.invocation)
            source=InteractionService(case.records,case.authority,case.fixture.resolver)
            seen=[]
            @contextmanager
            def scope_guard(ctx,package,agent,scopes):
                seen.append((ctx,package,agent,scopes))
                yield
            selected=OriginalAgentDispatchSelection(source,case.request.profile_revision_ref,
                read_invocation_resolver=lambda ctx,agent:case.fixture.invocation,
                workspace_scope_guard=scope_guard)
            agent=started.instance_ref.projection();ctx=object()
            observed=selected._read(ctx,agent)
            assert observed.instance_ref==started.instance_ref
            assert observed.profile_ref==case.request.profile_revision_ref
            # Explicit external fence delegation only. This is not a package/
            # approval grant fixture or a positive business dispatch claim.
            package=SimpleNamespace(ref=object())
            scope=object();authorization=SimpleNamespace(scope_by_action=(('run_checks',scope),))
            with selected.guard_work_scope(ctx,package,agent,authorization,('run_checks',)):
                assert seen==[(ctx,package.ref,agent,(('run_checks',scope),))]
            assert case.fixture.retained_use_count==1
            wrong=replace(case.request.profile_revision_ref,profile_id='wrong-profile')
            other=OriginalAgentDispatchSelection(source,wrong,
                read_invocation_resolver=lambda ctx,agent:case.fixture.invocation,
                workspace_scope_guard=scope_guard)
            with pytest.raises(ApplicationError,match='DISPATCH_SELECTION_PROFILE_MISMATCH'):
                other._read(ctx,agent)
            case.authority.read=False
            with pytest.raises(ApplicationError,match='DISPATCH_SELECTION_BINDING_UNAVAILABLE'):
                selected._read(ctx,agent)
            with pytest.raises(ApplicationError,match='DISPATCH_WORK_SCOPE_AUTHORITY_UNAVAILABLE'):
                OriginalAgentDispatchSelection(source,case.request.profile_revision_ref,
                    read_invocation_resolver=lambda *_:case.fixture.invocation,workspace_scope_guard=None)
            assert case.records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]==0
        finally:
            case.owner.close();await case.fixture.cleanup()
    asyncio.run(scenario())
