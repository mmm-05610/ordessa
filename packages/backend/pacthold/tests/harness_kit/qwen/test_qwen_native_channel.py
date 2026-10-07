"""N007 qwen driver tests — pure planning/compile (no real process).

Gate mapping: G1 (release/revision pinned, doc drift registered), G3
(unsupported config refused before launch), G9/G12 (loopback-only plan, no
credential keys, isolated QWEN_HOME), EVIDENCE (no runtimeReady, observed
never yes, source-vs-docs difference recorded). No qwen binary exists on this
machine; L2 is NOT RUN and is registered as such.
"""

from __future__ import annotations

import pytest

from ordessa_harness_qwen import native_channel


def test_plan_launch_shapes_loopback_serve(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    argv = plan["argv"]
    assert argv[:3] == ["qwen", "serve", "--hostname"]
    assert argv[argv.index("--hostname") + 1] == "127.0.0.1"  # loopback pinned
    assert argv[argv.index("--workspace") + 1] == str(tmp_path / "work")
    assert "--no-web" in argv  # API-only by default
    assert "--port" not in argv  # default 4170 recorded in the report, not guessed
    assert plan["executable"] == "qwen"
    assert plan["cwd"] == str(tmp_path / "work")


def test_plan_launch_web_opt_in_omits_no_web(tmp_path) -> None:
    plan = native_channel.plan_launch(
        home=tmp_path / "home", workspace=tmp_path / "work", web=True
    )
    assert "--no-web" not in plan["argv"]


@pytest.mark.parametrize("port", [0, 4180])
def test_plan_launch_port_is_explicit_when_requested(tmp_path, port) -> None:
    plan = native_channel.plan_launch(
        home=tmp_path / "home", workspace=tmp_path / "work", port=port
    )
    argv = plan["argv"]
    assert argv[argv.index("--port") + 1] == str(port)


def test_plan_launch_env_pins_qwen_home_without_credentials(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    env = plan["env"]
    assert env["HOME"] == str(tmp_path / "home")
    assert env["QWEN_HOME"] == str(tmp_path / "home" / ".qwen")  # G12 anchor
    assert env["TMPDIR"] == str(tmp_path / "home" / "tmp")
    assert env["LANG"] == "C.UTF-8"
    for key in env:
        upper = key.upper()
        assert "TOKEN" not in upper and "KEY" not in upper and "SECRET" not in upper
        assert "PASSWORD" not in upper
    assert "QWEN_SERVER_TOKEN" not in env


def test_plan_launch_is_pure(tmp_path, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("plan_launch must not spawn processes")

    monkeypatch.setattr(native_channel.os, "system", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert isinstance(plan["argv"], list)
    # no bearer is ever planned into argv
    assert "token" not in " ".join(plan["argv"]).lower()


def test_plan_launch_rejects_relative_workspace(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        native_channel.plan_launch(home=tmp_path / "home", workspace="relative-dir")


def test_compile_config_maps_supported_keys() -> None:
    compiled = native_channel.compile_config(
        {
            "no_web": True,
            "prompt_deadline_ms": 60000,
            "event_ring_size": 100,
            "max_sessions": 4,
            "session_scope": "thread",
            "model_service_id": "qwen-prod",
        }
    )
    args = compiled["args"]
    assert "--no-web" in args
    assert args[args.index("--prompt-deadline-ms") + 1] == "60000"
    assert args[args.index("--event-ring-size") + 1] == "100"
    assert args[args.index("--max-sessions") + 1] == "4"
    assert compiled["session_fields"] == {
        "sessionScope": "thread",
        "modelServiceId": "qwen-prod",
    }


def test_compile_config_invents_no_defaults() -> None:
    compiled = native_channel.compile_config({})
    assert compiled == {"args": [], "session_fields": {}}


def test_compile_config_rejects_invalid_session_scope() -> None:
    with pytest.raises(ValueError):
        native_channel.compile_config({"session_scope": "shared-maybe"})


@pytest.mark.parametrize("bad_key", ["mcpServers", "sandbox", "hotModelSwitch", "unknownThing"])
def test_compile_config_refuses_before_launch(bad_key) -> None:
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({bad_key: 1})
    assert excinfo.value.key == bad_key


def test_channel_report_pins_ownership_and_no_runtime_ready() -> None:
    report = native_channel.channel_report()
    assert "runtimeReady" not in repr(report)
    assert report["release"]["version"] == "0.24.7"
    assert report["release"]["source_revision"] == native_channel.UPSTREAM_REVISION
    assert "unknown" in report["artifact"]["sha256"]
    ownership = report["ownership"]
    # serve-vs-ACP conclusion: the daemon holds workspace/runtime/permissions
    assert "workspace" in ownership["workspace"]
    assert "daemon owns each workspace runtime" in ownership["runtime"]
    assert "POST /session/:id/permission/:requestId" in ownership["permissions"]
    assert "NOT chosen" in ownership["direct_acp_contrast"]


def test_channel_report_records_source_vs_docs_difference() -> None:
    report = native_channel.channel_report()
    source_check = report["unknown_boundary"]["source_check"]
    assert "eventEpoch" in source_check  # verified additive difference
    assert "recorded, not hidden" in source_check
    assert report["unknown_boundary"]["sse_disconnect"].startswith("NOT task completion")
    # doc/version drift is registered instead of silently resolved
    assert "drift" in report["release"]["stage"]


def test_capability_matrix_is_three_state_and_honest() -> None:
    matrix = native_channel.capability_matrix()
    assert matrix  # never empty
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
        assert row["observed"] == "no", name  # nothing was observed (L2 untested)
    assert matrix["resume"]["declared"] == "yes"
    assert matrix["transportFence"] == {
        "declared": "no",
        "implemented": "no",
        "observed": "no",
    }


def test_identity_is_catalogued_family_and_keys_disjoint() -> None:
    assert native_channel.FAMILY_ID == "qwen"
    assert native_channel.COMPILE_SUPPORTED_KEYS.isdisjoint(native_channel.COMPILE_REFUSAL_KEYS)
    assert native_channel.COMPILE_REFUSAL_KEYS == {"mcpServers", "sandbox", "hotModelSwitch"}
