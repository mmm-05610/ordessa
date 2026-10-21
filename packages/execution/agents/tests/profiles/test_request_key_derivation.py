"""The external request id is opaque; the durable RequestKey has its own grammar."""
import re

import pytest

from ordessa_agents.capability.profiles import _request_key_id
from ordessa_infrastructure.identifiers import RequestKey

LOCAL_ID = re.compile(r'^[a-z][a-z0-9._-]{0,63}$')


@pytest.mark.parametrize('external', ['96dc2aa31a5143b2b0f1ca80b9aea4c1',
                                      'f0da2cc265764d6fa70cdac05bdd7a26',
                                      'req-1', 'A-uppercase', '0'])
def test_opaque_request_ids_map_to_a_valid_request_key(external):
    derived = _request_key_id(external)
    assert LOCAL_ID.match(derived), derived
    # The durable key must actually construct.
    key = RequestKey('local-abc', 'principal:alice', derived)
    assert key.request_id == derived


def test_derivation_is_stable_and_collision_free_for_distinct_ids():
    first = _request_key_id('96dc2aa31a5143b2b0f1ca80b9aea4c1')
    assert first == _request_key_id('96dc2aa31a5143b2b0f1ca80b9aea4c1')
    assert first != _request_key_id('f0da2cc265764d6fa70cdac05bdd7a26')


@pytest.mark.parametrize('value', ['', None, 7])
def test_invalid_external_ids_are_refused(value):
    with pytest.raises(ValueError):
        _request_key_id(value)
