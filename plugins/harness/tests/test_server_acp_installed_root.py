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


def test_pi_profile_variant_is_startup_only_and_requires_private_instance(tmp_path):
    instance = tmp_path / "instance"
    instance.mkdir(mode=0o700)
    selected = transport(installed_artifact_root="/opt/ordessa", pi_profile_bridge=True,
                         instance_directory=str(instance), environment={"SAFE": "yes"})
    assert selected._inner._argv[-1] == "--pi-profile-bridge"
    assert selected._inner._environment["ORDESSA_PI_INSTANCE_DIR"] == str(instance)
    assert selected._inner._environment["SAFE"] == "yes"
    assert "instance_directory" not in selected._adapter


@pytest.mark.parametrize("kwargs", [
    {"pi_profile_bridge": True},
    {"installed_artifact_root": "/opt/ordessa", "pi_profile_bridge": True},
    {"installed_artifact_root": "/opt/ordessa", "pi_profile_bridge": "yes"},
    {"instance_directory": "/tmp"},
])
def test_profile_startup_rejects_incomplete_or_implicit_route(kwargs):
    with pytest.raises((ValueError, TypeError)):
        transport(**kwargs)


def test_profile_startup_rejects_shared_or_symlinked_instance(tmp_path):
    instance = tmp_path / "instance"
    instance.mkdir(mode=0o755)
    kwargs = {"installed_artifact_root": "/opt/ordessa", "pi_profile_bridge": True}
    with pytest.raises(ValueError):
        transport(instance_directory=str(instance), **kwargs)
    instance.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(instance, target_is_directory=True)
    with pytest.raises(ValueError):
        transport(instance_directory=str(link), **kwargs)
