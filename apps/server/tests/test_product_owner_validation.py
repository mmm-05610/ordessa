"""The original owner admission cannot be bypassed by an injected callback."""
from ordessa_units.public import AgentOwnerUnavailable
import pytest

from ordessa_server_product.composition import ServerProductComposition
from ordessa_server.composition.configuration.product_selection import create_host_product_composition


def test_product_owner_constructor_cannot_accept_forged_inputs_via_noop_validator():
    with pytest.raises(AgentOwnerUnavailable):
        ServerProductComposition(fingerprint_port=object(), agent_owner_inputs=object(),
                                 agent_owner_validator=lambda *_args: None)


def test_host_selector_cannot_replace_owner_admission_with_noop_validator():
    with pytest.raises(AgentOwnerUnavailable):
        create_host_product_composition(fingerprint_port=object(), agent_owner_inputs=object(),
                                        agent_owner_validator=lambda *_args: None)
