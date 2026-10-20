"""Explicit Host effect selection, without opening a store or keyring."""
from ordessa_server_product.composition import ProductCompositionUnavailable
import pytest

from ordessa_server_product.composition import ServerProductComposition
from ordessa_units.public import (
    AgentOwnerUnavailable, validate_agent_owner_selection,
)
from ordessa_server.composition.product_unit_admission import (
    create_product_unit_admission, create_owned_product_unit_admission,
)
from ordessa_server.bootstrap.security.secret_service import product_secret_store


def _bind(product):
    product.bind_host_environment_ports(environment_factory=create_product_unit_admission,
        owned_environment_factory=create_owned_product_unit_admission,
        secret_store_factory=product_secret_store)


def test_same_actual_host_ports_rebind_without_replacement():
    product = ServerProductComposition()
    _bind(product)
    _bind(product)
    assert product._host_environment_factory is create_product_unit_admission
    assert product._host_owned_environment_factory is create_owned_product_unit_admission
    assert product._host_secret_store_factory is product_secret_store


@pytest.mark.parametrize("member", ["environment_factory", "owned_environment_factory", "secret_store_factory"])
def test_foreign_member_cannot_replace_any_actual_host_port(member):
    product = ServerProductComposition()
    _bind(product)
    selected = dict(environment_factory=create_product_unit_admission,
                    owned_environment_factory=create_owned_product_unit_admission,
                    secret_store_factory=product_secret_store)
    selected[member] = lambda *args, **kwargs: None
    with pytest.raises(ProductCompositionUnavailable):
        product.bind_host_environment_ports(**selected)
    assert product._host_environment_factory is create_product_unit_admission
    assert product._host_owned_environment_factory is create_owned_product_unit_admission
    assert product._host_secret_store_factory is product_secret_store


@pytest.mark.parametrize("member", ["environment_factory", "owned_environment_factory", "secret_store_factory"])
def test_invalid_member_does_not_partially_bind(member):
    product = ServerProductComposition()
    selected = dict(environment_factory=create_product_unit_admission,
                    owned_environment_factory=create_owned_product_unit_admission,
                    secret_store_factory=product_secret_store)
    selected[member] = None
    with pytest.raises(TypeError):
        product.bind_host_environment_ports(**selected)
    assert product._host_environment_factory is None
    assert product._host_owned_environment_factory is None
    assert product._host_secret_store_factory is None


def test_unbound_environment_entrypoints_reject_without_creating_path(tmp_path):
    product = ServerProductComposition()
    store = tmp_path / "uncreated" / "state" / "core.sqlite"
    with pytest.raises(ProductCompositionUnavailable, match="explicit host Environment"):
        product.environment_factory(store)
    with pytest.raises(ProductCompositionUnavailable, match="explicit host owned Environment"):
        product.owned_environment_factory(store, object())
    assert not store.parent.parent.exists()


def test_owner_opt_in_runs_mandatory_pure_check_and_retains_actual_refusal():
    with pytest.raises(AgentOwnerUnavailable, match="protected fingerprint port"):
        ServerProductComposition(fingerprint_port=object(), agent_owner_inputs=object())
    with pytest.raises(AgentOwnerUnavailable, match="protected fingerprint port"):
        ServerProductComposition(fingerprint_port=object(), agent_owner_inputs=object(),
                                 agent_owner_validator=validate_agent_owner_selection)
