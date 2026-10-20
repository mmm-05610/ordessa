"""Finite recording transport; no synthetic human answer authenticates a user."""
import pytest
from ordessa_server.composition.engineering import DEFAULT_MACHINE_CAPABILITIES
from ordessa_server.composition.engineering_human_review import human_review_ports_factory
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from apps.server.tests.test_engineering_slice import runtime, call, SCOPE

OP = 'engineering.reviews.record'
PARAMS = dict(review_id='missing', request_version=0, fence=1, raw_response_utf8='{}')


def test_record_is_available_but_never_a_default_machine_grant(runtime):
    assert OP not in DEFAULT_MACHINE_CAPABILITIES
    caps = call(runtime, 'engineering.capabilities')['result']
    assert OP in caps['supported_methods']
    assert call(runtime, OP, PARAMS)['error']['code'] == 'FORBIDDEN'


@pytest.mark.parametrize('extra', ['plan', 'verdict', 'reviewer_evidence'])
def test_explicit_capability_cannot_supply_review_trust(runtime, extra):
    runtime.wire.identity_authority.replace_grants((AccessGrant(SCOPE, (OP,)),))
    result = call(runtime, OP, dict(PARAMS, **{extra:{}}))
    assert 'error' in result and 'result' not in result


def test_missing_original_review_authority_refuses(runtime):
    runtime.wire.identity_authority.replace_grants((AccessGrant(SCOPE, (OP,)),))
    result = call(runtime, OP, PARAMS)
    assert 'error' in result and 'result' not in result


@pytest.mark.parametrize('source', [None, 'wire-callable'])
def test_human_source_is_not_created_from_bearer_or_wire(source):
    with pytest.raises(ApplicationError):
        human_review_ports_factory(bindings=object(), manual_authority_factory=source)
