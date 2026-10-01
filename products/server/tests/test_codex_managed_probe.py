"""Inference probe opt-in must fail before process, secret-store or network effects."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[1] / 'scripts/probe-installed-codex-managed-profile.py'
    spec = importlib.util.spec_from_file_location('managed_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('allow,key,line', [(False, '/missing', 2), (True, None, 2),
                                          (True, '/missing', 0), (True, '/missing', True)])
def test_provider_transition_refuses_absent_authorization_or_key_scope(probe, allow, key, line):
    with pytest.raises(ValueError, match='Provider history acceptance'):
        probe.run(allow_model_calls=allow, switch_go=True, key_file=key, key_line=line)


def test_absent_key_fails_before_starting_product(probe, tmp_path):
    path = tmp_path / 'keys'
    path.write_text('synthetic-first\n')
    with pytest.raises(ValueError, match='Destination key is absent'):
        probe.run(allow_model_calls=True, switch_go=True, key_file=path, key_line=2)
