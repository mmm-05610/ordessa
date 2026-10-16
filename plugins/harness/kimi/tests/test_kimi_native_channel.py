"""N006 kimi driver tests — pure planning/compile behaviour (no real process).

Gate mapping: G1 (pinned release/version negotiation fields), G3 (unsupported
config refused before launch), G9/G12 (isolated share dir, no credential
keys), EVIDENCE (no runtimeReady claim, observed never `yes`, replay fence
stated explicitly). No kimi binary is executed here; L2 is NOT RUN and is
registered as such.
"""

from __future__ import annotations

import pytest

from ordessa_harness_kimi import native_channel


def test_plan_launch_shapes_isolated_wire_argv(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    argv = plan["argv"]
    assert argv[:2] == ["kimi", "--wire"]  # bare `kimi` is never planned
    assert "--work-dir" in argv
    assert argv[argv.index("--work-dir") + 1] == str(tmp_path / "work")
    assert "--session" not in argv and "--continue" not in argv
    assert plan["executable"] == "kimi"
    assert plan["cwd"] == str(tmp_path / "work")


def test_plan_launch_env_pins_share_dir_and_drops_tokens(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    env = plan["env"]
    assert env["HOME"] == str(tmp_path / "home")
    assert env["KIMI_SHARE_DIR"] == str(tmp_path / "home" / "kimi")  # G12 anchor
    assert env["KIMI_CLI_NO_AUTO_UPDATE"] == "1"
    assert env["LANG"] == "C.UTF-8"
    for key in env:
        assert "TOKEN" not in key.upper() and "KEY" not in key.upper() and "SECRET" not in key.upper()


def test_plan_launch_pure_no_subprocess(tmp_path, monkeypatch) -> None:
    def explode(*args, **kwargs):
        raise AssertionError("plan_launch must not spawn or resolve processes")

    monkeypatch.setattr(native_channel.os, "system", explode)
    monkeypatch.setattr("subprocess.Popen", explode)
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert isinstance(plan["argv"], list)


def test_plan_launch_session_flags_are_exclusive(tmp_path) -> None:
    resumed = native_channel.plan_launch(
        home=tmp_path / "home", workspace=tmp_path / "work", session="sess-1"
    )
    argv = resumed["argv"]
    assert argv[argv.index("--session") + 1] == "sess-1"
    continued = native_channel.plan_launch(
        home=tmp_path / "home", workspace=tmp_path / "work", continue_session=True
    )
    assert "--continue" in continued["argv"]
    with pytest.raises(ValueError):
        native_channel.plan_launch(
            home=tmp_path / "home",
            workspace=tmp_path / "work",
            session="sess-1",
            continue_session=True,
        )


def test_plan_launch_model_and_thinking_only_with_documented_flags(tmp_path) -> None:
    plan = native_channel.plan_launch(
        home=tmp_path / "home",
        workspace=tmp_path / "work",
        model="kimi-k2",
        thinking=True,
    )
    argv = plan["argv"]
    assert argv[argv.index("--model") + 1] == "kimi-k2"
    assert "--thinking" in argv
    off = native_channel.plan_launch(
        home=tmp_path / "home", workspace=tmp_path / "work", thinking=False
    )
    assert "--no-thinking" in off["argv"]


def test_compile_config_maps_supported_keys() -> None:
    compiled = native_channel.compile_config(
        {"model": "kimi-k2", "thinking": True, "session": "sess-2", "replay": True}
    )
    args = compiled["args"]
    assert args[args.index("--model") + 1] == "kimi-k2"
    assert "--thinking" in args
    assert args[args.index("--session") + 1] == "sess-2"
    assert compiled["plan"]["replay"] is True
    assert compiled["plan"]["session"] == "sess-2"


def test_compile_config_session_true_means_continue() -> None:
    compiled = native_channel.compile_config({"session": True})
    assert compiled["args"] == ["--continue"]
    assert compiled["plan"]["continue_session"] is True


def test_compile_config_provider_is_deferred_not_guessed() -> None:
    compiled = native_channel.compile_config({"provider": "moonshot"})
    assert compiled["args"] == []  # no invented --provider flag
    deferred = compiled["deferred"]["provider"]
    assert deferred["value"] == "moonshot"
    assert "config file" in deferred["reason"]


def test_compile_config_thinking_on_off_strings() -> None:
    assert native_channel.compile_config({"thinking": "on"})["args"] == ["--thinking"]
    assert native_channel.compile_config({"thinking": "off"})["args"] == ["--no-thinking"]


def test_compile_config_invalid_thinking_refused_with_key_and_reason() -> None:
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({"thinking": "high"})
    assert excinfo.value.key == "thinking"
    assert excinfo.value.reason


@pytest.mark.parametrize("bad_key", ["mcpServers", "sandbox", "hotModelSwitch", "someUnknownKey"])
def test_compile_config_refuses_unsupported_keys(bad_key) -> None:
    # G3 counter-example: refused before any launch, never silently swallowed
    with pytest.raises(native_channel.ConfigRefusal) as excinfo:
        native_channel.compile_config({bad_key: {"anything": 1}})
    assert excinfo.value.key == bad_key
    assert excinfo.value.reason


def test_cli_without_wire_is_never_planned(tmp_path) -> None:
    plan = native_channel.plan_launch(home=tmp_path / "home", workspace=tmp_path / "work")
    assert "--wire" in plan["argv"]  # a bare `kimi` downloads a CDN installer


def test_channel_report_pins_release_and_has_no_runtime_ready_claim() -> None:
    report = native_channel.channel_report()
    text = repr(report)
    assert "runtimeReady" not in text
    assert report["release"]["version"] == native_channel.PINNED_RELEASE == "1.52.0"
    assert report["protocol"]["version_negotiation"]["mismatch_policy"].startswith("unknown")
    assert "no-handshake" in report["protocol"]["version_negotiation"]["no_handshake_fallback"]
    assert report["upstream"]["archived"] is True
    assert report["l2_status"].startswith("NOT RUN")
    assert native_channel.REPLAY_APPROVAL_FENCE in report["session"]["replay"]


def test_channel_report_rust_variant_not_masquerading() -> None:
    variants = native_channel.channel_report()["variants"]
    assert "kimi-agent" in variants["rust"]
    assert "NOT the same capability set" in variants["rust"]


def test_capability_matrix_is_honest() -> None:
    matrix = native_channel.capability_matrix()
    for name, row in matrix.items():
        assert set(row) == {"declared", "implemented", "observed"}, name
        assert not row["observed"].startswith("yes"), name  # L2 NOT RUN
        assert row["observed"] in {"no", "unknown"}, name
    assert native_channel.REPLAY_APPROVAL_FENCE in matrix["replay"]["implemented"]
    assert matrix["transportFence"]["observed"] == "no"
    assert matrix["sessionCreate"]["observed"] == "unknown"


def test_identity_matches_registered_family() -> None:
    # G2: family identity is the pinned catalog id; no second identity
    assert native_channel.FAMILY_ID == "kimi"
    assert native_channel.WIRE_PROTOCOL_VERSION == "1.10"
    assert native_channel.COMPILE_SUPPORTED_KEYS.isdisjoint(native_channel.COMPILE_REFUSAL_KEYS)
