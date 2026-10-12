from dataclasses import FrozenInstanceError
from importlib import metadata
from types import SimpleNamespace
import os
import subprocess
import sys

import pytest

from ordessa_infrastructure.discovery import (
    EntryPointSource,
    enumerate_entry_points,
    entry_point_source,
    load_entry_point,
)


def test_enumeration_preserves_order_duplicates_and_exact_group_without_loading(monkeypatch):
    first = metadata.EntryPoint('z', 'fake_z:factory', 'test.group')
    duplicate = metadata.EntryPoint('z', 'fake_z:factory', 'test.group')
    last = metadata.EntryPoint('a', 'fake_a:factory', 'test.group')
    other = metadata.EntryPoint('other', 'fake_other:factory', 'Test.Group')
    selected = metadata.EntryPoints((first, other, duplicate, last))
    calls = []

    def discover():
        calls.append(True)
        return selected

    def forbidden_load(*args):
        raise AssertionError('enumeration loaded executable code')

    monkeypatch.setattr(metadata, 'entry_points', discover)
    monkeypatch.setattr(metadata.EntryPoint, 'load', forbidden_load)
    result = enumerate_entry_points('test.group')
    assert len(result) == 3 and calls == [True]
    assert result[0] is first and result[1] is duplicate and result[2] is last
    assert enumerate_entry_points('missing') == ()
    assert enumerate_entry_points('Test.Group') == (other,)


@pytest.mark.parametrize('group,error', [(None, TypeError), (17, TypeError), (b'test', TypeError), ('', ValueError)])
def test_invalid_group_is_refused_before_discovery(monkeypatch, group, error):
    def forbidden():
        raise AssertionError('invalid request reached metadata discovery')

    monkeypatch.setattr(metadata, 'entry_points', forbidden)
    with pytest.raises(error):
        enumerate_entry_points(group)


def test_enumeration_failure_propagates_without_retry(monkeypatch):
    failure = OSError('controlled metadata failure')
    calls = []

    def fail():
        calls.append(True)
        raise failure

    monkeypatch.setattr(metadata, 'entry_points', fail)
    with pytest.raises(OSError) as caught:
        enumerate_entry_points('test.group')
    assert caught.value is failure and calls == [True]


def test_source_reports_distribution_without_loading_or_discovering(monkeypatch):
    def forbidden(*args):
        raise AssertionError('source observation performed discovery/loading')

    entry = SimpleNamespace(group='test.group', name='sample', value='sample_module:create',
                            dist=SimpleNamespace(name='sample-distribution', version='9.1'), load=forbidden)
    monkeypatch.setattr(metadata, 'entry_points', forbidden)
    source = entry_point_source(entry)
    assert source == EntryPointSource('test.group', 'sample', 'sample_module:create', 'sample-distribution', '9.1')
    with pytest.raises(FrozenInstanceError):
        source.name = 'modified'


def test_missing_distribution_remains_optional_for_real_and_injected_entry_points():
    actual = metadata.EntryPoint('sample', 'sample_module:create', 'test.group')
    source = entry_point_source(actual)
    assert source == EntryPointSource('test.group', 'sample', 'sample_module:create')
    # Existing caller-injected entry points need not attach group/dist.
    injected = SimpleNamespace(name='sample', value='sample_module:create')
    assert entry_point_source(injected) == EntryPointSource(None, 'sample', 'sample_module:create')


@pytest.mark.parametrize('broken', ['name', 'version'])
def test_broken_distribution_attribute_reports_error_and_retains_other_fields(broken):
    class Distribution:
        @property
        def name(self):
            if broken == 'name':
                raise OSError('broken name')
            return 'sample-distribution'

        @property
        def version(self):
            if broken == 'version':
                raise ValueError('broken version')
            return '9.1'

    source = entry_point_source(SimpleNamespace(group='g', name='n', value='m:create', dist=Distribution()))
    assert (source.group, source.name, source.value) == ('g', 'n', 'm:create')
    assert source.distribution_name == (None if broken == 'name' else 'sample-distribution')
    assert source.distribution_version == (None if broken == 'version' else '9.1')
    assert source.metadata_errors == (f'distribution_{broken}: ' + ('OSError' if broken == 'name' else 'ValueError'),)


def test_broken_distribution_reference_and_nontext_fields_are_reported():
    class Entry:
        group, name, value = 'g', 'n', 'm:create'

        @property
        def dist(self):
            raise RuntimeError('broken reference')

    assert entry_point_source(Entry()).metadata_errors == ('distribution: RuntimeError',)
    source = entry_point_source(SimpleNamespace(group='g', name=17, value='m:create',
                                              dist=SimpleNamespace(name='distribution', version=17)))
    assert source.name is None and source.distribution_version is None
    assert source.distribution_name == 'distribution'
    assert source.metadata_errors == ('name: TypeError', 'distribution_version: TypeError')


def test_metadata_observation_does_not_swallow_process_cancellation():
    class Distribution:
        @property
        def name(self):
            raise KeyboardInterrupt('controlled cancellation')

    with pytest.raises(KeyboardInterrupt):
        entry_point_source(SimpleNamespace(dist=Distribution()))


def test_load_returns_exact_target_once_without_calling_factory_or_build():
    calls = []

    class Target:
        def __call__(self):
            raise AssertionError('discovery invoked a factory')

        def build(self, *args):
            raise AssertionError('discovery invoked build')

        def descriptor(self):
            raise AssertionError('discovery validated a descriptor')

    target = Target()

    def load():
        calls.append(True)
        return target

    assert load_entry_point(SimpleNamespace(load=load)) is target
    assert calls == [True]


def test_load_native_errors_propagate_without_fallback_or_retry():
    failure = ModuleNotFoundError('controlled target absence')
    calls = []

    def fail():
        calls.append(True)
        raise failure

    with pytest.raises(ModuleNotFoundError) as caught:
        load_entry_point(SimpleNamespace(load=fail))
    assert caught.value is failure and calls == [True]


def test_real_entry_point_load_uses_native_attribute_resolution_without_invocation(monkeypatch):
    import types

    module = types.ModuleType('infra_discovery_test_owned')
    calls = []

    def factory():
        calls.append(True)
        raise AssertionError('factory was invoked')

    module.factory = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    entry = metadata.EntryPoint('sample', module.__name__ + ':factory', 'test.group')
    assert load_entry_point(entry) is factory and calls == []


def test_isolated_import_does_not_discover_load_or_perform_runtime_io():
    code = '''
import importlib.metadata, importlib.abc, sys, os, sqlite3, subprocess, socket
class OnlyStdlibAndInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] not in sys.stdlib_module_names | {'ordessa_infrastructure'}:
            raise AssertionError('foreign import: ' + fullname)
sys.meta_path.insert(0, OnlyStdlibAndInfrastructure())
def forbidden(*args, **kwargs):
    raise AssertionError('import performed discovery/loading/runtime IO')
importlib.metadata.entry_points = forbidden
importlib.metadata.EntryPoint.load = forbidden
os.open = os.makedirs = os.mkdir = os.pipe = os.fsync = forbidden
sqlite3.connect = subprocess.Popen = socket.socket = forbidden
import ordessa_infrastructure.discovery
'''
    result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    for planted in ['importlib.metadata.entry_points()', 'importlib.metadata.EntryPoint("n","m:f","g").load()',
                    'import ordessa_execution_agents']:
        negative = subprocess.run([sys.executable, '-B', '-c', code + '\n' + planted], capture_output=True, text=True, timeout=10)
        assert negative.returncode != 0
        assert 'AssertionError' in negative.stderr
