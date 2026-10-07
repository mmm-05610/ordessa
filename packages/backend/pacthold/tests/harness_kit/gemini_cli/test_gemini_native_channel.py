"""N008 gemini driver tests — pure planning/compile (no real process)."""

from __future__ import annotations

import pytest

from ordessa_harness_gemini_cli import native_channel


def test_plan_launch_shapes_acp_argv(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert plan["argv"][:2] == ["gemini", "--acp"]


def test_plan_launch_pins_home_and_disables_telemetry(tmp_path) -> None:
    env = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")["env"]
    assert env["HOME"] == str(tmp_path / "home")
    assert env["GEMINI_TELEMETRY_ENABLED"] == "false"
    for key in env:
        upper = key.upper()
        for banned in ("TOKEN", "KEY", "SECRET", "PASSWORD"):
            assert banned not in upper


def test_plan_launch_is_pure(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert plan["executable"] == "gemini"


def test_compile_config_maps_and_defers() -> None:
    compiled = native_channel.compile_config({"model": "gemini-2", "approval_mode": "default", "debug": True})
    assert "--debug" in compiled["args"]
    assert compiled["session_params"]["model"] == "gemini-2"
    assert compiled["telemetry"] == "off"


@pytest.mark.parametrize("bad_key", ["oauthToken", "hotModelSwitch", "mystery"])
def test_compile_config_refuses(bad_key) -> None:
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.compile_config({bad_key: 1})


def test_report_and_matrix_are_honest() -> None:
    report = native_channel.channel_report()
    assert "runtimeReady" not in repr(report)
    matrix = native_channel.capability_matrix()
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
        assert row["observed"] != "yes", name
    assert matrix["modelConfig"]["declared"] == "unstable"
