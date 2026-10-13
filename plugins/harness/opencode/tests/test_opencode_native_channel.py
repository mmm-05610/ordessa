"""N004 opencode driver tests — pure planning/compile (no real process).

Gates: G2 (registered identity only), G3 (refuse before launch), G9/G12
(loopback plan, no credential keys), EVIDENCE (no runtimeReady, honest matrix).
"""

from __future__ import annotations

import pytest

from ordessa_harness_opencode import native_channel


def test_plan_launch_shapes_loopback_serve(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    argv = plan["argv"]
    assert argv[:2] == ["opencode", "serve"]
    assert "--hostname" in argv and argv[argv.index("--hostname") + 1] == "127.0.0.1"
    # port 0 = random free port discovered at run time, never guessed here
    assert "--port" not in argv


def test_plan_launch_env_pins_home_without_credentials(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    env = plan["env"]
    assert env["HOME"] == str(tmp_path / "home")
    for key in env:
        upper = key.upper()
        assert "TOKEN" not in upper and "KEY" not in upper and "SECRET" not in upper
        assert "PASSWORD" not in upper


def test_plan_launch_is_pure(tmp_path, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("plan_launch must not spawn processes")

    monkeypatch.setattr(native_channel.os, "system", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert plan["executable"] == "opencode"


def test_compile_config_maps_supported_keys() -> None:
    compiled = native_channel.compile_config(
        {"model": "gpt-x", "provider": "openai", "agent": "build", "project": "/w"}
    )
    fields = compiled["message_fields"]
    assert fields["model"] == "gpt-x" and fields["provider"] == "openai" and fields["agent"] == "build"
    assert compiled["project"] == "/w"


@pytest.mark.parametrize("bad_key", ["mcpServers", "sandbox", "hotModelSwitch", "unknownThing"])
def test_compile_config_refuses_before_launch(bad_key) -> None:
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({bad_key: 1})
    assert excinfo.value.key == bad_key


def test_channel_report_is_honest() -> None:
    report = native_channel.channel_report()
    assert "runtimeReady" not in repr(report)
    assert report["unknown_boundary"]["sse_disconnect"].startswith("NOT task completion")
    assert "unknown" in report["artifact"]["sha256"] or "unknown" in repr(report["artifact"])


def test_capability_matrix_has_no_observed_yes() -> None:
    matrix = native_channel.capability_matrix()
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
        assert row["observed"] != "yes", name
    assert matrix["resume"]["declared"] == "no"


def test_identity_is_registered_family() -> None:
    assert native_channel.FAMILY_ID == "opencode"
    assert native_channel.COMPILE_SUPPORTED_KEYS.isdisjoint(native_channel.COMPILE_REFUSAL_KEYS)
