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
