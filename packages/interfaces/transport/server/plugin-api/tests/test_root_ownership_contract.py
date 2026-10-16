from pathlib import Path

import pytest

from server_plugin_api import (
    OwnedRootBinding, RootOwnershipError, ServerPluginSelection,
)


def test_public_root_binding_constructor_cannot_mint_authority(tmp_path):
    root = tmp_path / "data"
    store = root / "state" / "core.sqlite"
    child = root / "state" / "agent-owner" / "operations.sqlite"
    with pytest.raises(TypeError, match="issued by the Server host"):
        OwnedRootBinding(root, store, child, lambda: True)


def test_structural_binding_lookalike_cannot_claim_host_issuance(tmp_path):
    root = tmp_path / "data"
    store = root / "state" / "core.sqlite"
    child = root / "state" / "agent-owner" / "operations.sqlite"

    class ForgedBinding:
        root_path = root
        store_path = store
        child_path = child

        def validate_for(self, **_kwargs):
            return None

    with pytest.raises(RootOwnershipError, match="not issued by the Server host"):
        OwnedRootBinding.validate_for(ForgedBinding(), root_path=root,
                                      store_path=store, child_path=child)


def test_public_root_binding_constructor_is_unavailable_even_for_invalid_paths(tmp_path):
    root = tmp_path / "data"
    store = root / "state" / "core.sqlite"
    with pytest.raises(TypeError, match="issued by the Server host"):
        OwnedRootBinding(root, store, tmp_path / "outside.sqlite", lambda: True)
    with pytest.raises(TypeError, match="issued by the Server host"):
        OwnedRootBinding(root, store, store, lambda: True)


def test_selection_types_owned_factory_as_root_ownership_not_boolean():
    class Port:
        def bind_owned_root(self, **_kwargs):
            raise AssertionError

    seen = []
    selection = ServerPluginSelection((), owned_environment_factory=lambda _path, port: seen.append(port))
    port = Port()
    selection.owned_environment_factory(Path("/unused"), port)
    assert seen == [port]
    assert callable(port.bind_owned_root)
