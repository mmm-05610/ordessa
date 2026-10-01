"""Probe boundary checks with controlled HTTP data; no network/model calls."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[1] / 'scripts/probe-opencode-go.py'
    spec = importlib.util.spec_from_file_location('go_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_selected_key_line_does_not_concatenate_providers(probe, tmp_path):
    path = tmp_path / 'keys'
    path.write_text('synthetic-first\nsynthetic-second\n')
    assert probe.read_key(path, 1) == 'synthetic-first'
    assert probe.read_key(path, 2) == 'synthetic-second'
    for line in (0, 3, True):
        with pytest.raises(ValueError):
            probe.read_key(path, line)


def test_protocol_models_and_endpoints_are_not_interchangeable(probe):
    cases = probe.payloads()
    assert [(p, endpoint) for p, endpoint, _ in cases] == [
        ('openai-chat', 'chat/completions'), ('anthropic-messages', 'messages'),
        ('openai-responses', 'responses')]
    assert all(payload.get('max_tokens', payload.get('max_output_tokens')) == 256
               for _, _, payload in cases)


def test_auth_opt_in_and_error_output_never_print_secrets(probe, tmp_path, monkeypatch, capsys):
    path = tmp_path / 'keys'
    path.write_text('synthetic-first\nsynthetic-second\n')
    args = SimpleNamespace(allow_model_calls=False, key_file=path, key_line=2)
    requests = []
    class Response:
        status = 401
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps({'error': 'synthetic-second'}).encode()
    def http(request, **kwargs):
        requests.append(request)
        return Response()
    monkeypatch.setattr(probe, 'urlopen', http)
    with pytest.raises(ValueError): probe.run(args)
    assert not requests
    args.allow_model_calls = True
    assert probe.run(args) == 1
    output = capsys.readouterr().out
    assert 'synthetic-first' not in output and 'synthetic-second' not in output
    assert len(requests) == 3
    assert all(request.get_header('Authorization') == 'Bearer synthetic-second' for request in requests)
    assert len({request.get_header('X-opencode-session') for request in requests}) == 1
