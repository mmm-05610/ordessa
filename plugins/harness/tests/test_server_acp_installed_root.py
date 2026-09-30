"""An installed artifact root is a startup binding, never a connect field."""
import pytest

from ordessa_harness.server_acp.access_entry import AccessEntryTransport


def transport(**kwargs):
    return AccessEntryTransport(node="/usr/bin/node", entry="/opt/ordessa/access-entry.mjs",
                               harness_id="pi", cwd="/tmp", adapter={"command": "/usr/bin/node", "args": []},
                               on_line=lambda _: None, on_exit=lambda _: None, **kwargs)


def test_installed_root_only_enters_startup_argv():
    selected = transport(installed_artifact_root="/opt/ordessa/harness-artifacts")
    assert selected._inner._argv == ["/usr/bin/node", "/opt/ordessa/access-entry.mjs", "--native",
                                     "--installed-artifact-root", "/opt/ordessa/harness-artifacts"]
    assert "installed_artifact_root" not in selected._adapter
    assert transport()._inner._argv == ["/usr/bin/node", "/opt/ordessa/access-entry.mjs", "--native"]


@pytest.mark.parametrize("root", ["relative", "/opt/../elsewhere", "//opt/ordessa", "/opt/with\x00nul", 1])
def test_installed_root_rejects_invalid_binding(root):
    with pytest.raises(ValueError):
        transport(installed_artifact_root=root)


def test_installed_root_cannot_enable_controlled_peer():
    with pytest.raises(ValueError):
        transport(installed_artifact_root="/opt/ordessa", controlled_test_peer=True)
