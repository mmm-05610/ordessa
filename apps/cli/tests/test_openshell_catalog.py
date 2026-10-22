"""The CLI names OpenShell in its provider catalog, with an honest reason.

``environments providers`` must never be silent about a provider it cannot
address. Three states are distinguished: not configured here, the provider
plugin is not installed, and the declared OpenShell SDK extra is not installed.
The last two are different installations; reporting one as the other would
state something false about this machine.
"""
from __future__ import annotations

import sys

import pytest

from ordessa_cli.composition.environments import _openshell_entry


class _State:
    """The one state file the OpenShell entry reads."""

    def __init__(self, path):
        self.openshell_config = path


class _Absent:
    """One module name behaves as if it were never installed."""

    def __init__(self, name):
        self.name = name

    def find_spec(self, fullname, path=None, target=None):
        if fullname == self.name or fullname.startswith(self.name + '.'):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name=self.name)
        return None


@pytest.fixture
def absent(monkeypatch):
    """Install one absent module name for the duration of one test."""
    def install(*names):
        # The provider plugin is imported again inside the test, so the absent
        # installation is observed by the import that actually happens.
        for key in [key for key in list(sys.modules)
                    if key == 'ordessa_environments_openshell'
                    or key.startswith('ordessa_environments_openshell.')]:
            monkeypatch.delitem(sys.modules, key, raising=False)
        for name in names:
            for key in [key for key in list(sys.modules)
                        if key == name or key.startswith(name + '.')]:
                monkeypatch.delitem(sys.modules, key, raising=False)
            monkeypatch.setattr(sys, 'meta_path', [_Absent(name)] + list(sys.meta_path))
    yield install
    for key in [key for key in list(sys.modules)
                if key == 'ordessa_environments_openshell'
                or key.startswith('ordessa_environments_openshell.')]:
        sys.modules.pop(key, None)


def test_unconfigured_openshell_is_explicitly_unavailable(tmp_path):
    binding, entry = _openshell_entry(_State(tmp_path / 'openshell.json'))
    assert binding is None
    assert entry['id'] == 'openshell'
    assert entry['available'] is False
    assert entry['status'] == 'UNAVAILABLE'
    assert entry['reason'] == 'no OpenShell configuration in this state directory'
    assert entry['capabilities'] == []


def test_missing_plugin_distribution_is_reported_as_such(absent, tmp_path):
    absent('ordessa_environments_openshell')
    binding, entry = _openshell_entry(_State(tmp_path / 'openshell.json'))
    assert binding is None
    assert entry['available'] is False
    assert entry['status'] == 'UNAVAILABLE'
    assert entry['reason'] == 'OpenShell plugin is not installed'
    assert 'SDK' not in entry['reason']


def test_missing_sdk_extra_is_not_reported_as_a_missing_plugin(absent, tmp_path):
    absent('openshell')
    binding, entry = _openshell_entry(_State(tmp_path / 'openshell.json'))
    assert binding is None
    assert entry['available'] is False
    assert entry['status'] == 'UNAVAILABLE'
    assert entry['reason'] != 'OpenShell plugin is not installed'
    assert 'OpenShell SDK is not installed' in entry['reason']
    assert 'openshell' in entry['reason']
