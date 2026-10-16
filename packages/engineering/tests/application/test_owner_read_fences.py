"""Real original SQLite reads rechecked inside the original write transaction."""
from dataclasses import asdict
import pytest
from test_proposal_usecases import environment, _artifact_graph, _create, _proposal_ref, _ctx, SCOPE
from ordessa_engineering.application.contracts.commands import ReadSet, ReadVersion
from ordessa_engineering.application.contracts.errors import ApplicationError


def test_proposal_control_and_change_read_fences_resolve_original_records(environment):
    lib,factory,access,method=environment
    base,proposed,claim=_artifact_graph(factory)
    result=_create(factory,access,method,base,proposed,claim,'proposal')
    ref=_proposal_ref(result.result['proposal_ref'])
    with factory.begin(SCOPE,'read') as uow:
        control=uow.proposals.get_control(ref)
        change=uow.proposals.get_change(ref.change_id)
    reads=ReadSet(SCOPE,(ReadVersion('proposal_control',ref.digest.hex,control.version),
                         ReadVersion('change',change.change_id,change.version)))
    with factory.guard_read_set(reads):
        with factory.begin(SCOPE) as uow:
            assert uow.proposals.control_by_digest(ref.digest.hex)==control
            uow.commit()
    # This mutation occurs outside the guard, before a fresh original write.
    from ordessa_engineering.application.usecases.changes.proposals import ProposalUseCases
    from test_proposal_usecases import SyntheticControlAdmission
    cases=ProposalUseCases(factory,access,SyntheticControlAdmission(lib))
    cases.withdraw({'proposal_ref':asdict(ref),'expected_version':control.version,
                    'reason':'explicit test revocation'},_ctx(request_id='withdraw'))
    with factory.guard_read_set(reads):
        with pytest.raises(ApplicationError,match='READ_SET_CHANGED'):
            with factory.begin(SCOPE): pass
    # Cleanup must restore the original thread-local guard stack after refusal.
    with factory.begin(SCOPE,'read') as uow:
        assert uow.proposals.get_control(ref).version==control.version+1


def test_foreign_scope_and_unknown_read_kind_cannot_bypass_owner_fence(environment):
    _,factory,_,_=environment
    reads=ReadSet(SCOPE,(ReadVersion('made_up_kind','id',0),))
    with factory.guard_read_set(reads):
        with pytest.raises(ApplicationError,match='UNSUPPORTED_READ_KIND'):
            with factory.begin(SCOPE): pass
