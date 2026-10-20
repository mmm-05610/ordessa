"""Infrastructure discovers; Environment composition selects the explicit factory."""
from types import SimpleNamespace
import pytest
import ordessa_infrastructure.discovery as discovery
from ordessa_environments.composition.sandbox_discovery import _load_factory
from ordessa_environments.definitions.sandbox_port import ENTRY_POINT_GROUP, SANDBOX_PORT_FACTORY, SandboxPortUnavailable

class Entry:
    def __init__(self, name, value, module):
        self.name, self.value, self.module, self.loads = name, value, module, 0
    def load(self):
        self.loads += 1
        return self.module

def test_declaration_order_and_duplicate_selection_remain_consumer_policy(monkeypatch):
    calls = []
    def factory():
        calls.append('factory')
        return 'port'
    selected = Entry('example', 'example:plugin', SimpleNamespace(**{SANDBOX_PORT_FACTORY: factory}))
    duplicate = Entry('example', 'example:duplicate', None)
    unrelated = Entry('different', 'different:plugin', None)
    groups = []
    monkeypatch.setattr(discovery, 'enumerate_entry_points', lambda group: groups.append(group) or (unrelated, selected, duplicate))
    assert _load_factory('example') is factory
    assert groups == [ENTRY_POINT_GROUP]
    assert selected.loads == 1 and duplicate.loads == unrelated.loads == 0
    assert calls == []
    assert factory() == 'port' and calls == ['factory']

def test_no_match_loads_nothing(monkeypatch):
    unrelated = Entry('other', 'other:plugin', None)
    monkeypatch.setattr(discovery, 'enumerate_entry_points', lambda group: (unrelated,))
    with pytest.raises(SandboxPortUnavailable):
        _load_factory('missing')
    assert unrelated.loads == 0

def test_selected_invalid_factory_refuses_without_loading_second_candidate(monkeypatch):
    first, second = Entry('same', 'same:first', object()), Entry('same', 'same:second', None)
    monkeypatch.setattr(discovery, 'enumerate_entry_points', lambda group: (first, second))
    with pytest.raises(SandboxPortUnavailable):
        _load_factory('same')
    assert first.loads == 1 and second.loads == 0
