"""Native composition's fixed ACP peer opt-in; no model or peer launch."""
from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from ordessa_server_compat import composition


ROOT = Path(__file__).resolve().parents[3]
PLUGIN = ROOT / "plugins" / "harness"
FIXTURE = ROOT / "tests" / "integration" / "acp_orchestration" / "fixtures" / "bidirectional_acp_peer.mjs"


def _build(tmp_path, *, controlled_test_peer=False, adapter_command=None, adapter_args=None,
           harness_id="pi"):
    return composition.build_runtime_from_native_adapter(
        tmp_path / "data", plugin_root=PLUGIN, harness_id=harness_id,
        adapter_command=adapter_command or shutil.which("node"),
        adapter_args=adapter_args if adapter_args is not None else (str(FIXTURE),),
        controlled_test_peer=controlled_test_peer,
    )


@pytest.mark.parametrize("changes", [
    {"adapter_command": "/bin/echo"},
    {"adapter_args": ("/tmp/other-peer.mjs",)},
    {"adapter_args": (str(FIXTURE), "--extra")},
    {"harness_id": "codex"},
])
def test_controlled_opt_in_refuses_other_commands_and_paths(tmp_path, changes):
    with pytest.raises(RuntimeError, match="NATIVE_CONTROLLED_PEER_INVALID"):
        _build(tmp_path, controlled_test_peer=True, **changes)


def test_controlled_opt_in_requires_boolean_and_exact_fixture_path(tmp_path):
    with pytest.raises(RuntimeError, match="NATIVE_CONTROLLED_PEER_INVALID"):
        _build(tmp_path, controlled_test_peer=1)
    alias = tmp_path / "peer-alias.mjs"
    alias.symlink_to(FIXTURE)
    with pytest.raises(RuntimeError, match="NATIVE_CONTROLLED_PEER_INVALID"):
        _build(tmp_path, controlled_test_peer=True, adapter_args=(str(alias),))


def test_default_composition_keeps_existing_adapter_selection(tmp_path):
    runtime = _build(tmp_path, adapter_command="/bin/echo", adapter_args=("plain-adapter",))
    runtime.stop()


@pytest.mark.parametrize("controlled", [False, True])
def test_only_explicit_opt_in_forwards_fixed_test_mode(tmp_path, monkeypatch, controlled):
    from ordessa_harness.server_acp import plugin as acp_plugin

    captured = {}
    original = acp_plugin.AcpChannelServerPlugin

    def capture_plugin(*, launch, native_identity):
        captured["launch"] = launch
        return original(launch=launch, native_identity=native_identity)

    class CapturedTransport:
        def __init__(self, **kwargs):
            captured["transport"] = kwargs

        def start(self):
            return self

    monkeypatch.setattr(acp_plugin, "AcpChannelServerPlugin", capture_plugin)
    monkeypatch.setattr(composition, "AccessEntryTransport", CapturedTransport)
    monkeypatch.setenv("AGENTBOX_ACCESS_TEST_MODE", "untrusted-ambient-value")
    runtime = _build(tmp_path, controlled_test_peer=controlled)
    try:
        captured["launch"](harness_id="pi", cwd=str(tmp_path),
                           on_line=lambda line: None, on_exit=lambda status: None)
        arguments = captured["transport"]
        assert arguments["adapter"] == {"command": shutil.which("node"),
                                         "args": [str(FIXTURE)]}
        assert arguments["environment"].get("AGENTBOX_ACCESS_TEST_MODE") == (
            "controlled-peer-v1" if controlled else None)
        assert arguments.get("controlled_test_peer", False) is controlled
    finally:
        runtime.stop()


def test_tampered_peer_content_is_refused(tmp_path):
    """019 digest discipline: same name, one byte changed -> refused."""
    tampered = tmp_path / "bidirectional_acp_peer.mjs"
    tampered.write_bytes(FIXTURE.read_bytes() + b"\n")
    with pytest.raises(RuntimeError, match="NATIVE_CONTROLLED_PEER_INVALID"):
        _build(tmp_path, controlled_test_peer=True, adapter_args=(str(tampered),))
