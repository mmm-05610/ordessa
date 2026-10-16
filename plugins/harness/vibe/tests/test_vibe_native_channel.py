"""N011 vibe driver tests — pure planning/compile (no real process)."""

from __future__ import annotations

import pytest

from ordessa_harness_vibe import native_channel


def test_plan_launch_redirects_shared_home(tmp_path) -> None:
    # G12 counter-example: user ~/.vibe (shared credentials home) must be redirected
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    env = plan["env"]
    assert env["VIBE_HOME"] == str(tmp_path / "home" / "vibe")
    assert env["HOME"] == str(tmp_path / "home")
    for key in env:
        upper = key.upper()
        for banned in ("TOKEN", "KEY", "SECRET", "PASSWORD", "APIKEY"):
            assert banned not in upper


def test_plan_launch_is_pure_and_entry_is_caller_supplied(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work", entry="custom-vibe")
    assert plan["executable"] == "custom-vibe"
    assert plan["argv"][0] == "custom-vibe"


def test_compile_config_maps_session_params() -> None:
    compiled = native_channel.compile_config({"model": "m", "profile": "p", "skills": ["s"]})
    assert compiled["session_params"]["profile"] == "p"


@pytest.mark.parametrize("bad_key", ["mistralApiKey", "hotModelSwitch", "mystery"])
def test_compile_config_refuses_credentials_and_unknown(bad_key) -> None:
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.compile_config({bad_key: 1})


def test_report_and_matrix_are_honest() -> None:
    report = native_channel.channel_report()
    assert "runtimeReady" not in repr(report)
    assert "unpinned" in report["release"]["version"]
    assert "never read" in report["isolation"]["shared_home_hazard"]
    matrix = native_channel.capability_matrix()
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
        assert row["observed"] != "yes", name
    assert matrix["acpExtensions"]["declared"] == "unknown"
