"""N010 goose driver tests — pure planning/compile (no real process)."""

from __future__ import annotations

import pytest

from ordessa_harness.goose import native_channel


def test_plan_launch_shapes_stdio_acp(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert plan["argv"][:2] == ["goose", "acp"]


def test_plan_launch_never_includes_unauthenticated_flag(tmp_path) -> None:
    # SAFETY counter-example: --dangerously-unauthenticated must be refused
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.plan_launch(
            home=tmp_path / "home", workspace=tmp_path / "work", extra_args=("--dangerously-unauthenticated",)
        )
    assert "--dangerously-unauthenticated" not in native_channel.plan_launch(
        home=tmp_path / "home", workspace=tmp_path / "work"
    )["argv"]
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.compile_config({"dangerouslyUnauthenticated": True})


def test_plan_launch_env_without_credentials(tmp_path) -> None:
    env = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")["env"]
    for key in env:
        upper = key.upper()
        for banned in ("TOKEN", "KEY", "SECRET", "PASSWORD"):
            assert banned not in upper


def test_compile_config_maps_session_params() -> None:
    compiled = native_channel.compile_config({"model": "g", "provider": "openai"})
    assert compiled["session_params"] == {"model": "g", "provider": "openai"}


@pytest.mark.parametrize("bad_key", ["secretKey", "hotModelSwitch", "mystery"])
def test_compile_config_refuses(bad_key) -> None:
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.compile_config({bad_key: 1})


def test_report_and_matrix_are_honest() -> None:
    report = native_channel.channel_report()
    assert "runtimeReady" not in repr(report)
    assert "NEVER" in report["launch"]["forbidden"]
    matrix = native_channel.capability_matrix()
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
        assert row["observed"] != "yes", name
    assert matrix["unauthenticatedMode"]["implemented"] == "refused"
