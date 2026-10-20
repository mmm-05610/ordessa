"""Original run/journal CAS and the withdrawn input-binding route.

The three original tests (input binding refusal without an actual source, the
original row CAS with idempotent replay and no cursor advance, and the recheck of
that CAS after the source read) exercised the `engineering.work.bind_inputs`
route, which is withdrawn: it moved a compiled run's cursor and slots. They are
retired here, not rewritten or weakened, and the invariants they covered are
registered below for a declarative replacement:

  * an input binding without a real selected source is refused and leaves no
    journal entry;
  * a successful binding uses the original row CAS, replays idempotently and
    never advances the cursor or dispatches;
  * a concurrent row change is rechecked after the source read, so the journal
    entry is never left behind.
"""
import asyncio

import pytest

from test_method_work import env, call, _context
from ordessa_engineering.application.contracts.errors import ApplicationError


def test_input_binding_route_is_withdrawn(env):
    e = env
    assert 'engineering.work.bind_inputs' not in type(e['facade']).supported_commands
    with pytest.raises(ApplicationError) as refused:
        call(e, 'engineering.work.bind_inputs', {'run_id': 'work'}, 'withdrawn-bind')
    assert refused.value.code == 'OPERATION_UNAVAILABLE'
    with e['factory'].begin(e['scope'], 'read') as uow:
        assert uow.commands.get(_context(e['scope'], 'withdrawn-bind').key) is None

