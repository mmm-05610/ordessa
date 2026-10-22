"""The Server names OpenShell in its catalog and binds its provider binding.

Three facts must be visible to a client of the Server:

* an unconfigured OpenShell is **explicitly unavailable**, never silently
  absent from the catalog;
* "the provider plugin is not installed" and "the declared OpenShell SDK extra
  is not installed" are two different statements about this machine;
* the provider is bound to its immutable gateway/workspace binding in the
  environment registry, so a changed binding is refused instead of silently
  rebound.
"""
from __future__ import annotations

import json
import sqlite3
import sys

import pytest

from ordessa_interfaces.system_access.access_control.authentication import (
    InstanceAccessAuthority,
)
from ordessa_server.composition.environment_owner import (
    ENVIRONMENT_OPERATIONS, build_environment_owner,
)


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


class _FakeProvider:
    """A provider stand-in: only the registry binding facts are exercised."""

    identity = 'openshell'
    operations = frozenset({'start', 'stop', 'delete'})

    def __init__(self, binding_id):
        self.binding_id = binding_id


class _FakeBinding:
    def __init__(self, binding_id):
        self.provider = _FakeProvider(binding_id)
        self.catalog = {'id': 'openshell', 'available': True,
                        'capabilities': ['process', 'file-area']}


def _owner(tmp_path):
    authority = InstanceAccessAuthority(lambda: 'controlled-instance-token', grants=())
    return build_environment_owner(tmp_path, authority=authority,
                                   invocation_resolver=lambda context: None)


def _catalog(owner):
    return {entry['id']: entry for entry in owner.services.provider_catalog}


def _bindings(root):
    with sqlite3.connect(root / 'state' / 'environments.sqlite') as db:
        return dict(db.execute(
            "SELECT identity,binding_id FROM environment_provider_bindings").fetchall())


def test_unconfigured_openshell_is_explicitly_unavailable(tmp_path):
    owner = _owner(tmp_path)
    try:
        entry = _catalog(owner)['openshell']
        assert entry['available'] is False
        assert entry['status'] == 'UNAVAILABLE'
        assert entry['reason'] == 'no OpenShell configuration in this state directory'
        assert entry['capabilities'] == []
        assert 'openshell' not in owner.manager.providers
    finally:
        owner.close()


def test_missing_plugin_distribution_is_reported_as_such(absent, tmp_path):
    absent('ordessa_environments_openshell')
    owner = _owner(tmp_path)
    try:
        entry = _catalog(owner)['openshell']
        assert entry['available'] is False
        assert entry['status'] == 'UNAVAILABLE'
        assert entry['reason'] == 'OpenShell plugin is not installed'
        assert 'SDK' not in entry['reason']
    finally:
        owner.close()


def test_missing_sdk_extra_is_not_reported_as_a_missing_plugin(absent, tmp_path):
    absent('openshell')
    owner = _owner(tmp_path)
    try:
        entry = _catalog(owner)['openshell']
        assert entry['available'] is False
        assert entry['status'] == 'UNAVAILABLE'
        assert entry['reason'] != 'OpenShell plugin is not installed'
        assert 'OpenShell SDK is not installed' in entry['reason']
    finally:
        owner.close()


def test_configured_openshell_is_bound_in_the_environment_registry(monkeypatch, tmp_path):
    import ordessa_environments_openshell

    binding_id = json.dumps(['openshell', 'controlled-gateway', 'workspace-test'],
                            separators=(',', ':'))
    monkeypatch.setattr(ordessa_environments_openshell, 'build_binding',
                        lambda config: _FakeBinding(binding_id))
    state = tmp_path / 'state'
    state.mkdir(parents=True, exist_ok=True)
    (state / 'openshell.json').write_text(
        json.dumps({'endpoint': '127.0.0.1:17670', 'workspace': 'workspace-test'}),
        encoding='utf-8')
    owner = _owner(tmp_path)
    try:
        entry = _catalog(owner)['openshell']
        assert entry['available'] is True
        assert 'openshell' in owner.manager.providers
        assert _bindings(tmp_path)['openshell'] == binding_id
    finally:
        owner.close()


def test_a_changed_provider_binding_is_refused_not_rebound(monkeypatch, tmp_path):
    import ordessa_environments_openshell

    first = json.dumps(['openshell', 'controlled-gateway', 'workspace-test'],
                       separators=(',', ':'))
    second = json.dumps(['openshell', 'other-gateway', 'workspace-test'],
                        separators=(',', ':'))
    state = tmp_path / 'state'
    state.mkdir(parents=True, exist_ok=True)
    (state / 'openshell.json').write_text(
        json.dumps({'endpoint': '127.0.0.1:17670', 'workspace': 'workspace-test'}),
        encoding='utf-8')
    monkeypatch.setattr(ordessa_environments_openshell, 'build_binding',
                        lambda config: _FakeBinding(first))
    owner = _owner(tmp_path)
    owner.close()
    assert _bindings(tmp_path)['openshell'] == first
    monkeypatch.setattr(ordessa_environments_openshell, 'build_binding',
                        lambda config: _FakeBinding(second))
    changed = _owner(tmp_path)
    try:
        entry = _catalog(changed)['openshell']
        assert entry['available'] is False
        assert entry['status'] == 'UNAVAILABLE'
        assert 'binding changed' in entry['reason']
        assert 'openshell' not in changed.manager.providers
        assert _bindings(tmp_path)['openshell'] == first
    finally:
        changed.close()


def test_the_product_exposes_the_reconcile_operation():
    assert 'environments.reconcile' in ENVIRONMENT_OPERATIONS
