"""N009 copilot driver tests — pure planning/compile behaviour (no real process).

Gate mapping: G1 (pinned release, no runtimeReady), G2 (no parallel registry),
G3 (unsupported/token config refused before launch), G9/G12 (isolation env, no
credential keys), EVIDENCE (no all-true capability matrix).

Every fixture here is L1-static (pure functions only); no copilot binary is
installed or executed, so no test may claim a real process observation.
"""

from __future__ import annotations

import inspect

import pytest

from ordessa_harness.copilot import native_channel


# -- plan_launch (pure) -------------------------------------------------------


def test_plan_launch_shapes_isolated_stdio_server_argv(tmp_path) -> None:
    plan = native_channel.plan_launch(
        executable=str(tmp_path / "bin" / "copilot"),
        home=tmp_path / "home",
        workspace=tmp_path / "work",
    )
    argv = plan["argv"]
    assert argv[0] == str(tmp_path / "bin" / "copilot")  # explicit bound binary
    assert "--headless" in argv and "--stdio" in argv  # documented server mode
    for flag in ("--no-auto-update", "--no-auto-login"):
        assert flag in argv
    assert argv[argv.index("--log-level") + 1] == "debug"
    for flag in native_channel.FORBIDDEN_AUTO_APPROVE_FLAGS:
        assert flag not in argv


def test_plan_launch_env_pins_home_and_never_carries_tokens(tmp_path) -> None:
    plan = native_channel.plan_launch(
        executable="/opt/pinned/copilot",
        home=tmp_path / "home",
        workspace=tmp_path / "work",
    )
    env = plan["env"]
    assert env["HOME"] == str(tmp_path / "home")
    assert env["COPILOT_HOME"] == str(tmp_path / "home" / "copilot")
    assert env["COPILOT_HOME"].startswith(str(tmp_path / "home"))
    assert env["XDG_CONFIG_HOME"].startswith(str(tmp_path / "home"))
    assert env[native_channel.DOWNLOAD_DISABLE_ENV] == "1"
    assert env["COPILOT_DISABLE_KEYTAR"] == "1"
    assert env["LANG"] == "C.UTF-8"
    for key in env:
        assert not native_channel.is_token_key(key), key
        assert key not in {"GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN", "COPILOT_SDK_AUTH_TOKEN"}


def test_plan_launch_pure_no_subprocess(tmp_path, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("plan_launch must not spawn or resolve processes")

    monkeypatch.setattr(native_channel.os, "system", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    plan = native_channel.plan_launch(
        executable="/pinned/copilot", home=tmp_path / "home", workspace=tmp_path / "work"
    )
    assert isinstance(plan["argv"], list)
    assert plan["executable"] == "/pinned/copilot"
    assert plan["cwd"] == str(tmp_path / "work")


def test_plan_launch_requires_explicit_executable_parameter() -> None:
    # G1: the planner binds a caller-supplied path; there is no default and no
    # PATH resolution, so no user path can ever be hardcoded here.
    parameter = inspect.signature(native_channel.plan_launch).parameters["executable"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_plan_launch_optional_session_idle_timeout(tmp_path) -> None:
    plan = native_channel.plan_launch(
        executable="/pinned/copilot",
        home=tmp_path / "home",
        workspace=tmp_path / "work",
        session_idle_timeout=300,
    )
    argv = plan["argv"]
    assert argv[argv.index("--session-idle-timeout") + 1] == "300"


# -- compile_config (G3/G12) --------------------------------------------------


def test_compile_config_maps_supported_keys() -> None:
    compiled = native_channel.compile_config(
        {
            "model": "gpt-5",
            "reasoning_effort": "high",
            "session_id": "user-alice-task-1",
            "log_level": "info",
            "session_idle_timeout": 120,
        }
    )
    args = compiled["args"]
    assert args[args.index("--log-level") + 1] == "info"
    assert args[args.index("--session-idle-timeout") + 1] == "120"
    # session-level keys are materials for session.create, never guessed flags
    assert compiled["session"] == {
        "model": "gpt-5",
        "reasoning_effort": "high",
        "session_id": "user-alice-task-1",
    }


@pytest.mark.parametrize("bad_key", ["hotModelSwitch", "sandbox", "mcpServers", "someUnknownKey"])
def test_compile_config_refuses_second_ownership_and_unknown_keys(bad_key) -> None:
    # G3 counter-example: refused before any launch, never silently swallowed
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({bad_key: {"anything": 1}})
    assert excinfo.value.key == bad_key


@pytest.mark.parametrize(
    "token_key",
    ["GH_TOKEN", "github_token", "COPILOT_GITHUB_TOKEN", "providerToken", "apiKey"],
)
def test_compile_config_refuses_token_class_keys(token_key) -> None:
    # G12 counter-example: credential-shaped keys are refused outright
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({token_key: "secret-value"})
    assert excinfo.value.key == token_key
    assert "credential" in excinfo.value.reason


def test_compile_config_accepts_empty_materials() -> None:
    assert native_channel.compile_config({}) == {"args": [], "session": {}}


# -- channel_report / capability honesty --------------------------------------


def test_channel_report_has_no_runtime_ready_claim_and_pins_release() -> None:
    report = native_channel.channel_report()
    text = repr(report)
    assert "runtimeReady" not in text
    assert report["release"]["sdk"] == native_channel.PINNED_SDK_RELEASE
    assert report["release"]["cli"] == native_channel.PINNED_CLI_RELEASE
    assert report["release"]["protocol_version"] == native_channel.PINNED_PROTOCOL_VERSION
    assert report["artifact"]["sha256"] == native_channel.ARTIFACT_DIGEST
    assert report["release"]["local_artifact"].startswith("unknown")


def test_channel_report_documents_sdk_auto_download_and_mitigation() -> None:
    # N009 attack point: the SDK may auto-start/download the CLI and read
    # account state. The report must pin that documented behaviour and the
    # explicit mitigation instead of silently trusting the SDK.
    block = native_channel.channel_report()["sdk_process_management"]
    assert "auto-download" in block["auto_download"] or "auto-downloads" in block["auto_download"]
    assert "COPILOT_CLI_PATH" in block["resolution_order"]
    assert "explicit" in block["resolution_order"]
    assert "COPILOT_HOME" in block["process_ownership"]
    assert native_channel.DOWNLOAD_DISABLE_ENV in block["mitigation"]
    assert "never invokes the SDK" in block["mitigation"]
    assert "NOT executed" in block["verified"]  # no fake L2


def test_channel_report_pins_token_isolation_and_isolated_home() -> None:
    report = native_channel.channel_report()
    isolation = report["isolation"]
    assert isolation["token_isolation"].startswith("GH_TOKEN")
    for key in ("COPILOT_HOME", "scratch"):
        assert key in isolation["home"]
    assert "session-state" in isolation["state_dir"]
    auth = report["auth"]
    assert "COPILOT_GITHUB_TOKEN" in auth["method"]
    assert auth["device_flow"].startswith("unknown")
    assert report["auth"]["isolated_behavior"].startswith("no credential")


def test_channel_report_upgrade_boundary_is_not_a_guarantee() -> None:
    report = native_channel.channel_report()
    assert report["release"]["volatile"] is True
    assert "re-pin" in report["unknown_boundary"]["upgrade"]
    assert "(observed: no)" in report["session"]["delete_vs_disconnect"]  # documented, not measured
    assert "unknown" in report["protocol"]["framing"] or "unverified" in report["protocol"]["framing"]


def test_capability_matrix_is_honest() -> None:
    matrix = native_channel.capability_matrix()
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
        # no local CLI exists: every observed claim stays no (L2 NOT RUN)
        assert row["observed"] in {"no", "unknown"}, name
    # counter-example gate: nothing auto-switches models or auto-approves
    assert matrix["modelHotSwitch"]["implemented"] == "no-refused"
    assert matrix["approvalCallback"]["implemented"] == "reply-no-auto"
    assert matrix["transportFence"]["observed"] == "no"


# -- identity -----------------------------------------------------------------


def test_identity_matches_assigned_family_and_key_sets_disjoint() -> None:
    # G2: seams.md §1 assigns id "copilot"; no parallel registry is built here
    assert native_channel.FAMILY_ID == "copilot"
    assert native_channel.COMMAND_CATALOG_ID == "copilot"
    assert native_channel.COMPILE_SUPPORTED_KEYS.isdisjoint(native_channel.COMPILE_REFUSAL_KEYS)
    for key in native_channel.COMPILE_SUPPORTED_KEYS:
        assert not native_channel.is_token_key(key)


@pytest.mark.parametrize("flag", ["--allow-all", "--yolo", "--auto-approve", "--yes"])
def test_plan_launch_refuses_auto_approve_flags(tmp_path, flag) -> None:
    # SAFETY counter-example: the forbidden-flag list is a real fence in
    # plan_launch, not a dead constant.
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.plan_launch(
            executable="copilot",
            home=tmp_path / "home",
            workspace=tmp_path / "work",
            extra_args=(flag,),
        )
