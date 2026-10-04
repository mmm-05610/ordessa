"""N005 claude driver tests — pure planning/compile (no real process).

Gates: G2 (both identities recorded, neither renamed), G3 (refuse before
launch), G12 (no token keys, no subscription token), EVIDENCE honesty.
"""

from __future__ import annotations

import pytest

from ordessa_harness.claude import native_channel


def test_plan_launch_shapes_headless_stream(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work", prompt="hi")
    argv = plan["argv"]
    assert argv[:2] == ["claude", "-p"]
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "stream-json"
    assert "hi" in argv


def test_plan_launch_env_pins_home_without_credentials(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    env = plan["env"]
    assert env["HOME"] == str(tmp_path / "home")
    for key in env:
        upper = key.upper()
        for banned in ("TOKEN", "KEY", "SECRET", "PASSWORD"):
            assert banned not in upper


def test_plan_launch_is_pure(tmp_path, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("plan_launch must not spawn processes")

    monkeypatch.setattr("subprocess.Popen", explode)
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert plan["executable"] == "claude"


def test_compile_config_maps_documented_flags() -> None:
    compiled = native_channel.compile_config(
        {
            "model": "claude-x",
            "permission_mode": "acceptEdits",
            "allowed_tools": "Read,Edit",
            "system_prompt": "be brief",
            "mcp_config": "/tmp/mcp.json",
            "resume": "sess-1",
            "continue_": True,
        }
    )
    args = compiled["args"]
    assert args[args.index("--model") + 1] == "claude-x"
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    assert args[args.index("--resume") + 1] == "sess-1"
    assert "--continue" in args


@pytest.mark.parametrize("bad_key", ["subscriptionToken", "hotModelSwitch", "sandboxInstancePool", "mystery"])
def test_compile_config_refuses_before_launch(bad_key) -> None:
    # G3/G12 counter-example: subscription tokens are never accepted
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({bad_key: "x"})
    assert excinfo.value.key == bad_key


def test_channel_report_records_terms_and_gaps() -> None:
    report = native_channel.channel_report()
    assert "runtimeReady" not in repr(report)
    terms = report["license_terms"]
    assert "Commercial Terms" in terms["commercial"]
    assert "must not be offered to third parties" in terms["auth_terms"]
    assert "unknown" in report["protocol"]["stdin_side"]


def test_capability_matrix_has_no_observed_yes() -> None:
    matrix = native_channel.capability_matrix()
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
        assert row["observed"] != "yes", name


def test_identity_keeps_both_names_without_rename() -> None:
    assert native_channel.FAMILY_ID == "claude"
    assert native_channel.COMMAND_CATALOG_ID == "claude-code"
