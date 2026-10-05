"""N005 claude driver tests — pure planning/compile (no real process).

Gates: G2 (both identities recorded, neither renamed), G3 (refuse before
launch), G12 (no token keys, no subscription token), EVIDENCE honesty.
"""

from __future__ import annotations

import pytest

from ordessa_harness_claude_code import native_channel


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
        }
    )
    args = compiled["args"]
    assert args[args.index("--model") + 1] == "claude-x"
    assert args[args.index("--permission-mode") + 1] == "acceptEdits"
    assert args[args.index("--resume") + 1] == "sess-1"
    assert "--continue" in native_channel.compile_config({"continue_": True})["args"]


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


@pytest.mark.parametrize("bad_mode", ["bypassPermissions", "auto", "acceptAll", "yolo"])
def test_auto_approve_permission_modes_are_refused(bad_mode) -> None:
    # SAFETY counter-example: auto-approve/bypass modes are never compiled.
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.compile_config({"permission_mode": bad_mode})


def test_bidirectional_is_explicit_with_native_control_flags(tmp_path):
    plain = native_channel.plan_launch(home=tmp_path/'home', workspace=tmp_path/'work')
    assert '--input-format' not in plain['argv']
    assert '--permission-prompt-tool' not in plain['argv']
    duplex = native_channel.plan_launch(home=tmp_path/'home', workspace=tmp_path/'work', bidirectional=True)
    argv = duplex['argv']
    assert argv[argv.index('--input-format') + 1] == 'stream-json'
    assert argv[argv.index('--output-format') + 1] == 'stream-json'
    assert argv[argv.index('--permission-prompt-tool') + 1] == 'stdio'
    assert argv.count('--verbose') == 1
    assert not (tmp_path/'home').exists() and not (tmp_path/'work').exists()


def test_bidirectional_prompt_must_follow_control_initialize(tmp_path):
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.plan_launch(home=tmp_path/'home', workspace=tmp_path/'work', prompt='never dispatched', bidirectional=True)


@pytest.mark.parametrize('args', [
    ('--input-format', 'stream-json'), ('--output-format=json',),
    ('--permission-prompt-tool', 'other'), ('--print',), ('--verbose',),
    ('--dangerously-skip-permissions',), ('--allow-dangerously-skip-permissions',),
    ('--permission-mode=bypassPermissions',), ('--resume=sess', '--continue'),
])
def test_extra_args_cannot_change_transport_or_bypass_permissions(tmp_path, args):
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.plan_launch(home=tmp_path/'home', workspace=tmp_path/'work', extra_args=args)


@pytest.mark.parametrize('materials', [
    {'permission_mode':'acceptEdits'}, {'permission_mode':'dontAsk'},
    {'allowed_tools':'Bash'}, {'resume':'session-1','continue_':True},
])
def test_bidirectional_config_refuses_shadowed_approval_or_ambiguous_session(materials):
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.compile_config(materials, bidirectional=True)


def test_resume_and_continue_are_distinct_explicit_plans(tmp_path):
    for materials, expected in [({'resume':'session-1'},'--resume'),({'continue_':True},'--continue')]:
        compiled = native_channel.compile_config(materials, bidirectional=True)
        plan = native_channel.plan_launch(home=tmp_path/'home', workspace=tmp_path/'work',
            bidirectional=True, extra_args=tuple(compiled['args']))
        assert expected in plan['argv']
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.compile_config({'resume':'session-1', 'continue_':True})


@pytest.mark.parametrize('args', [('--allowedTools=Read',), ('--permission-mode','acceptEdits'), ('--settings','/caller/file')])
def test_bidirectional_launch_cannot_shadow_callback(args,tmp_path):
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.plan_launch(home=tmp_path/'home',workspace=tmp_path/'work',bidirectional=True,extra_args=args)


def test_fixed_sdk_source_is_not_installed_runtime_evidence():
    report = native_channel.channel_report()
    assert report['sdk_source']['commit'] == '9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b'
    assert report['sdk_source']['version'] == '0.2.163'
    assert report['sdk_source']['license'] == 'MIT'
    assert report['sdk_source']['installed'] is False
    assert report['artifact']['sha256'] == 'unknown'
    assert 'official Claude Agent SDK' in report['consumer']['productionPreference']
    assert 'not observed' in report['network']['default']


@pytest.mark.parametrize('args',[('positional prompt',),('--', 'prompt'),('-r','session','-c'),('--resume',),('--resume=',)])
def test_duplex_positional_input_and_ambiguous_aliases_refuse(tmp_path,args):
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.plan_launch(home=tmp_path/'home',workspace=tmp_path/'work',bidirectional=True,extra_args=args)


@pytest.mark.parametrize('materials',[{'resume':''},{'resume':True},{'continue_':'true'}])
def test_native_session_selection_has_explicit_types(materials):
    with pytest.raises(native_channel.ConfigRefusal):
        native_channel.compile_config(materials)
