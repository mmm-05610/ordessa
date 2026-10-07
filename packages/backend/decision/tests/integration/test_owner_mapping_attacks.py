"""Independent host mapping check; controlled owner, no actual agent operations."""
from dataclasses import replace
import pytest
from test_core_read_seam import setup, DEF
from pacthold.agents.public import OwnerProposalInput
from ordessa_decision.contracts import ContractError
from ordessa_decision.offline import offline_case
from ordessa_decision.integrations.ordessa import OwnerProposalValidator
from ordessa_decision.runtime import run_decision


def native_input(api, draft, ratio):
    return OwnerProposalInput(DEF, api.providers.describe(DEF)['providerRef'], '1',
        {'configurationKind': 'brand.new', 'payload': ratio}, (),
        tuple({'obligationId': o.obligation_id, 'requirement': o.requirement,
            'checkerId': o.validator_kind, 'checkerVersion': o.version_constraint}
            for o in draft.required_validation_obligations))


async def test_T61_builder_without_reviewed_mapping_cannot_return_ready(setup):
    env, policy, owner, api = setup
    request, flow, services = offline_case(action='create')
    validator = OwnerProposalValidator(api.providers,
        input_builder=lambda draft, basis: native_input(api, draft, 0.1),
        read_context=services.read_context)
    result = await run_decision(request, flow=flow, services=replace(services, validator=validator))
    assert not (result.status == 'completed' and result.outcome.disposition == 'ready')
    assert owner.calls == [] and owner.effects == []


@pytest.mark.parametrize('ratio', [0.1, 0.9])
async def test_T61_T62_builder_wrong_field_rejected_before_owner(setup, ratio):
    env, policy, owner, api = setup
    request, flow, services = offline_case(action='create')
    def verify(draft, basis, value):
        return (value.proposal_data['configurationKind'] == 'brand.new'
            and draft.payload['configuration_kind'] == 'controlled.new.kind'
            and draft.payload['action'] == 'create'
            and value.proposal_data['payload'] == draft.payload['configuration']['ratio'])
    validator = OwnerProposalValidator(api.providers,
        input_builder=lambda draft, basis: native_input(api, draft, ratio),
        input_verifier=verify, read_context=services.read_context)
    result = await run_decision(request, flow=flow, services=replace(services, validator=validator))
    assert not (result.status == 'completed' and result.outcome.disposition == 'ready')
    assert owner.calls == [] and owner.effects == []
