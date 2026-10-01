import importlib.util
from pathlib import Path
import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[1] / 'scripts/probe-authorized-chat.py'
    spec = importlib.util.spec_from_file_location('authorized_chat_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_keys_are_selected_independently_and_bounded(probe):
    lines = ['synthetic-first', 'synthetic-second']
    assert probe.bounded_key(lines, 1) == 'synthetic-first'
    assert probe.bounded_key(lines, 2) == 'synthetic-second'
    for index in (0, 3, True):
        with pytest.raises(ValueError):
            probe.bounded_key(lines, index)
    for value in ('', 'x\x7f', 'x\nkey', 'x' * 8001):
        with pytest.raises(ValueError):
            probe.bounded_key([value], 1)


def test_go_destination_is_a_distinct_fixed_upstream_not_a_model_alias(probe):
    mapping = probe.relay_upstreams(True)
    assert mapping['/claude/'] == 'https://api.deepseek.com/anthropic/'
    assert mapping['/claude-next/'] == 'https://opencode.ai/zen/go/'
    assert probe.relay_upstreams(False)['/claude-next/'] == mapping['/claude/']
    assert mapping['/pi-next/'] == 'https://opencode.ai/zen/go/v1/'
    assert probe.relay_upstreams(False)['/pi-next/'] == mapping['/pi/']


def test_direct_provider_mode_rejects_wrong_scope_before_process_or_network(probe, tmp_path):
    from types import SimpleNamespace
    key = tmp_path / 'synthetic-keys.txt'
    key.write_text('synthetic-first\nsynthetic-second\n')
    for patch in [dict(brand=['claude-code']), dict(switch_go=False), dict(switch_provider=False),
                  dict(local_relay=True), dict(fixed_assets=False)]:
        args = dict(allow_model_calls=True, key_file=key, key_line=1, destination_key_line=2,
                    brand=['pi'], switch_go=True, switch_provider=True, local_relay=False,
                    direct_provider=True, fixed_assets=True)
        args.update(patch)
        with pytest.raises(ValueError, match='Direct provider acceptance'):
            probe.run(SimpleNamespace(**args))
