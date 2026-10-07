"""N003 pi driver tests — pure planning/compile behaviour (no real process).

Gate mapping: G2 (no parallel registry), G3 (unsupported config refused before
launch), G9/G12 (isolation env, no credential keys), G1/EVIDENCE (no
runtimeReady claim, no all-true capability matrix).
"""

from __future__ import annotations

import pytest

from ordessa_harness_pi import native_channel


def test_plan_launch_shapes_isolated_rpc_argv(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    argv = plan["argv"]
    assert "--mode" in argv and argv[argv.index("--mode") + 1] == "rpc"
    assert "--no-session" in argv
    assert "--offline" in argv
    for flag in ("--no-extensions", "--no-skills", "--no-context-files", "--no-prompt-templates", "--no-approve"):
        assert flag in argv


def test_plan_launch_env_pins_home_and_drops_tokens(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    env = plan["env"]
    assert env["HOME"] == str(tmp_path / "home")
    assert env["XDG_CONFIG_HOME"].startswith(str(tmp_path / "home"))
    assert env["PI_TELEMETRY"] == "0"
    assert env["PI_OFFLINE"] == "1"
    assert env["LANG"] == "C.UTF-8"
    for key in env:
        assert "TOKEN" not in key.upper() and "KEY" not in key.upper() and "SECRET" not in key.upper()


def test_plan_launch_pure_no_subprocess(tmp_path, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("plan_launch must not spawn or resolve processes")

    monkeypatch.setattr(native_channel.os, "system", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert isinstance(plan["argv"], list) and plan["executable"] == "pi"


def test_plan_launch_session_dir_replaces_no_session(tmp_path) -> None:
    plan = native_channel.plan_launch(
        home=tmp_path / "home", workspace=tmp_path / "work", session_dir=tmp_path / "sessions"
    )
    argv = plan["argv"]
    assert "--session-dir" in argv and "--no-session" not in argv
    assert argv[argv.index("--session-dir") + 1] == str(tmp_path / "sessions")


def test_compile_config_maps_supported_keys(tmp_path) -> None:
    compiled = native_channel.compile_config(
        {
            "provider": "anthropic",
            "model": "claude-sonnet",
            "thinking": "high",
            "session_dir": "/tmp/s",
            "offline": True,
        }
    )
    args = compiled["args"]
    assert args[args.index("--provider") + 1] == "anthropic"
    assert args[args.index("--model") + 1] == "claude-sonnet"
    assert args[args.index("--thinking") + 1] == "high"
    assert compiled["session_dir"] == "/tmp/s"
    assert compiled["offline"] is True


def test_compile_config_extensions_false_maps_no_extensions() -> None:
    compiled = native_channel.compile_config({"extensions": False})
    assert "--no-extensions" in compiled["args"]


@pytest.mark.parametrize("bad_key", ["mcpServers", "sandbox", "hotModelSwitch", "someUnknownKey"])
def test_compile_config_refuses_unsupported_keys(bad_key) -> None:
    # G3 counter-example: refused before any launch, never silently swallowed
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({bad_key: {"anything": 1}})
    assert excinfo.value.key == bad_key


def test_channel_report_has_no_runtime_ready_claim() -> None:
    report = native_channel.channel_report()
    text = repr(report)
    assert "runtimeReady" not in text
    assert report["release"]["version"] == native_channel.PINNED_RELEASE
    assert report["session"]["resume"].startswith("unknown")


def test_capability_matrix_is_honest() -> None:
    matrix = native_channel.capability_matrix()
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
    # counter-example gate: nothing observed beyond the N001 probe evidence
    observed_yes = {name for name, row in matrix.items() if row["observed"].startswith("yes")}
    assert observed_yes <= {"unknownExtensions", "requestReconciliation"}
    assert matrix["transportFence"]["observed"] == "no"
    assert matrix["resume"]["implemented"] == "no"


def test_identity_matches_registered_family() -> None:
    # G2: family identity is the already-registered one; no second identity
    assert native_channel.FAMILY_ID == "pi"
    assert native_channel.COMPILE_SUPPORTED_KEYS.isdisjoint(native_channel.COMPILE_REFUSAL_KEYS)
