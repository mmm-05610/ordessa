"""N002 codex driver tests — pure planning/compile behaviour (no real process).

Gate mapping: G2 (no parallel registry), G3 (unsupported config refused before
launch), G9/G12 (isolation env, no credential keys), G1/EVIDENCE (broken local
artifact recorded verbatim, no runtimeReady claim, no observed-yes capability
matrix; L2 stays BLOCKED until a working artifact is authorized/re-installed).
"""

from __future__ import annotations

import re

import pytest

from ordessa_harness_codex import native_channel


def test_plan_launch_shapes_app_server_argv(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    argv = plan["argv"]
    assert argv[:2] == ["codex", "app-server"]
    assert plan["executable"] == "codex"
    assert plan["cwd"] == str(tmp_path / "work")
    # --listen defaults to stdio; the ws/unix alternatives are never selected
    assert not any(flag in argv for flag in ("--listen", "ws", "unix"))


def test_plan_launch_env_pins_codex_home_scratch(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    env = plan["env"]
    assert env["HOME"] == str(tmp_path / "home")
    # G12 anchor: CODEX_HOME is pinned inside the scratch tree, never ~/.codex
    assert env["CODEX_HOME"] == str(tmp_path / "home" / "codex")
    for key in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"):
        assert env[key].startswith(str(tmp_path / "home")), key
    assert env["LANG"] == "C.UTF-8"
    assert env["NO_COLOR"] == "1"


def test_plan_launch_env_drops_credential_keys(tmp_path) -> None:
    env = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")["env"]
    for key in env:
        assert "TOKEN" not in key.upper() and "KEY" not in key.upper() and "SECRET" not in key.upper()


def test_plan_launch_pure_no_subprocess(tmp_path, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("plan_launch must not spawn or resolve processes")

    monkeypatch.setattr(native_channel.os, "system", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    monkeypatch.setattr("subprocess.run", explode)
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert isinstance(plan["argv"], list) and plan["executable"] == "codex"


def test_plan_launch_extra_args_passthrough(tmp_path) -> None:
    plan = native_channel.plan_launch(
        home=tmp_path / "home", workspace=tmp_path / "work", extra_args=("--trace", "verbose")
    )
    assert plan["argv"][-2:] == ["--trace", "verbose"]
    assert plan["argv"][:2] == ["codex", "app-server"]


def test_compile_config_maps_thread_start_params() -> None:
    compiled = native_channel.compile_config(
        {
            "model": "gpt-5-codex",
            "cwd": "/tmp/workspace",
            "approval_policy": "untrusted",
            "sandbox": "workspace-write",
        }
    )
    params = compiled["thread_params"]
    assert params["model"] == "gpt-5-codex"
    assert params["cwd"] == "/tmp/workspace"
    assert params["approvalPolicy"] == "untrusted"
    assert params["sandbox"] == "workspace-write"
    assert compiled["args"] == []


def test_compile_config_accepts_effort_history_mode_offline() -> None:
    compiled = native_channel.compile_config(
        {"effort": "high", "history_mode": "save-all", "offline": True}
    )
    # effort follows the in-repo app-server precedent
    assert compiled["thread_params"]["effort"] == "high"
    # accepted family vocabulary with no pinned thread/start wire name yet
    # (L2 blocked): carried as deferred, never silently dropped (G3)
    assert compiled["deferred"]["history_mode"] == "save-all"
    assert compiled["deferred"]["offline"] is True


def test_compile_config_empty_materials_is_empty_plan() -> None:
    compiled = native_channel.compile_config({})
    assert compiled["thread_params"] == {}
    assert compiled["args"] == []
    assert compiled["deferred"] == {}


@pytest.mark.parametrize("bad_key", ["mcpServers", "sandboxInstancePool", "hotModelSwitch", "someUnknownKey"])
def test_compile_config_refuses_unsupported_keys(bad_key) -> None:
    # G3 counter-example: refused before any launch, never silently swallowed
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({bad_key: {"anything": 1}})
    assert excinfo.value.key == bad_key
    assert excinfo.value.reason


def test_compile_config_sandbox_value_vs_pool_key() -> None:
    # the per-thread sandbox value is supported; the standalone instance pool
    # is another ownership surface and must be refused
    compiled = native_channel.compile_config({"sandbox": "workspace-write"})
    assert compiled["thread_params"]["sandbox"] == "workspace-write"
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({"sandboxInstancePool": ["a", "b"]})
    assert excinfo.value.key == "sandboxInstancePool"


def test_channel_report_records_broken_artifact_no_runtime_ready() -> None:
    report = native_channel.channel_report()
    text = repr(report)
    # broken local artifact evidence, verbatim (L2 BLOCKED)
    evidence = native_channel.BROKEN_LOCAL_ARTIFACT
    assert str(evidence["file_size"]) in text
    assert str(evidence["elf_section_offset"]) in text
    assert evidence["failure"] in text
    assert report["l2_status"].startswith("BLOCKED")
    assert report["artifact"]["local_state"]["broken"] is True
    # EVIDENCE gate: no runtimeReady anywhere in the report
    assert "runtimeReady" not in text


def test_channel_report_keeps_registered_family_shape() -> None:
    report = native_channel.channel_report()
    assert report["family"] == native_channel.FAMILY_ID == "codex"
    assert report["upstream"]["repo"] == "github.com/openai/codex"
    assert report["upstream"]["license"] == "Apache-2.0"
    assert report["release"]["version"] == native_channel.PINNED_RELEASE
    assert report["artifact"]["sha256"] == native_channel.PINNED_ARTIFACT_DIGEST
    for key in (
        "channel", "upstream", "release", "artifact", "protocol", "launch",
        "isolation", "network", "auth", "session", "callbacks", "cancel",
        "unknown_boundary",
    ):
        assert key in report, key
    assert "thread/resume" in report["session"]["resume"]
    assert "not observed" in report["session"]["resume"]
    # SAFETY gate: no auto-approve wording anywhere
    assert "auto-approve forbidden" in report["callbacks"]["outbound"]


def test_capability_matrix_is_honest() -> None:
    matrix = native_channel.capability_matrix()
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
    # counter-example gate: L2 fully blocked, so nothing may claim observed yes
    observed_yes = {name for name, row in matrix.items() if row["observed"].startswith("yes")}
    assert observed_yes == set()
    assert matrix["prompt"]["observed"].startswith("no")
    assert matrix["turn"]["observed"].startswith("no")
    assert matrix["transportFence"]["observed"] == "no"
    assert matrix["resume"]["implemented"] == "plan-only"
    assert matrix["requestReconciliation"]["implemented"].startswith("unavailable")
    assert "historical requirement: yes" in matrix["requestReconciliation"]["implemented"]
    assert matrix["approvalCallback"]["observed"] == "no"
    assert matrix["cancel"]["observed"] == "no"


def test_identity_matches_registered_family() -> None:
    # G2: family identity is the already-registered one; no second identity
    assert native_channel.FAMILY_ID == "codex"
    assert native_channel.PINNED_RELEASE == "0.157.1"
    assert re.fullmatch(r"[0-9a-f]{64}", native_channel.PINNED_ARTIFACT_DIGEST)
    assert native_channel.COMPILE_SUPPORTED_KEYS.isdisjoint(native_channel.COMPILE_REFUSAL_KEYS)
    # broken artifact evidence carries the pinned fields
    assert {
        "file_size", "elf_section_offset", "failure",
    } <= set(native_channel.BROKEN_LOCAL_ARTIFACT)
    assert native_channel.BROKEN_LOCAL_ARTIFACT["failure"] == "execve EFAULT → SIGSEGV"
