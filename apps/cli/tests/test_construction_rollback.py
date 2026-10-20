"""A24: a failed foreground-session construction closes what it already built."""
from pathlib import Path

import pytest

import ordessa_agent_tools.session as session_module
from ordessa_agent_tools.composition.state import LocalState


class Domain:
    def __init__(self, name):
        self.name, self.closed = name, False

    def close(self):
        self.closed = True


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    root = tmp_path / 'state'
    root.mkdir(mode=0o700)
    return LocalState.open(str(root))


def test_a_refused_agent_domain_closes_the_environment(state, monkeypatch):
    environment = Domain('environment')

    def refuse(*args, **kwargs):
        raise RuntimeError('agent domain refused')

    monkeypatch.setattr(session_module, 'build_environment_domain', lambda *a, **k: environment)
    monkeypatch.setattr(session_module, 'build_agent_domain', refuse)
    with pytest.raises(RuntimeError, match='agent domain refused'):
        session_module.Session(state)
    assert environment.closed is True


def test_a_refused_decision_domain_closes_agents_then_environment(state, monkeypatch):
    environment, agents = Domain('environment'), Domain('agents')

    def refuse(*args, **kwargs):
        raise RuntimeError('decision domain refused')

    monkeypatch.setattr(session_module, 'build_environment_domain', lambda *a, **k: environment)
    monkeypatch.setattr(session_module, 'build_agent_domain', lambda *a, **k: agents)
    monkeypatch.setattr(session_module, 'build_decision_domain', refuse)
    with pytest.raises(RuntimeError, match='decision domain refused'):
        session_module.Session(state)
    assert agents.closed is True and environment.closed is True


def test_rollback_keeps_going_when_one_close_fails(state, monkeypatch):
    environment = Domain('environment')

    class Broken(Domain):
        def close(self):
            raise RuntimeError('close failed')

    agents = Broken('agents')

    def refuse(*args, **kwargs):
        raise RuntimeError('decision refused')

    monkeypatch.setattr(session_module, 'build_environment_domain', lambda *a, **k: environment)
    monkeypatch.setattr(session_module, 'build_agent_domain', lambda *a, **k: agents)
    monkeypatch.setattr(session_module, 'build_decision_domain', refuse)
    with pytest.raises(RuntimeError, match='decision refused'):
        session_module.Session(state)
    assert environment.closed is True
