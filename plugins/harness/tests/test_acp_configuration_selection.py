"""Configuration selection is an acquisition identity, not client auth data."""
from types import SimpleNamespace
import pytest
import ordessa_harness.server_acp.registry as implementation


def registry(monkeypatch):
    launches = []
    monkeypatch.setattr(implementation, 'open_run', lambda **kw: ('ledger', 'execution', {}))
    def launch(**kw):
        launches.append(kw)
        return SimpleNamespace(terminate=lambda: None)
    return implementation.AcpChannelRegistry(session_records=None, profile_records=None, launch=launch), launches


def test_configuration_reference_reaches_launch_before_ledger_and_is_scope_fenced(monkeypatch):
    channels, launches = registry(monkeypatch)
    kwargs = dict(harness_id='codex', workspace_id='project', profile_id='native-ledger-profile',
                  cwd='/project', session_scope_id='draft', configuration_profile_id='saved-profile')
    first = channels.acquire(**kwargs)
    assert launches[0]['configuration_profile_id'] == 'saved-profile'
    assert channels.get(first['connectionId']).profile_id == 'native-ledger-profile'
    assert channels.acquire(**kwargs) == first
    for changed in ['another-profile', None]:
        with pytest.raises(implementation.SessionAcquisitionRefused, match='configuration Profile changed'):
            channels.acquire(**{**kwargs, 'configuration_profile_id': changed})
    assert len(launches) == 1


@pytest.mark.parametrize('selection,scope', [('p', None), ('', 'scope'), (' p ', 'scope'), ('p\x00', 'scope'), ('p'*129, 'scope')])
def test_invalid_configuration_acquisition_never_launches(monkeypatch, selection, scope):
    channels, launches = registry(monkeypatch)
    with pytest.raises(implementation.SessionAcquisitionRefused):
        channels.acquire(harness_id='codex', workspace_id='project', profile_id='ledger', cwd='/project',
                         session_scope_id=scope, configuration_profile_id=selection)
    assert launches == []
