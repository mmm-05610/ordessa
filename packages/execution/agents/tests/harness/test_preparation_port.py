"""The shared preparation port: injected owners, no application state.

The port is owned by the agents distribution, so it reaches no environment
owner, no CLI state directory and no host installation layout of another
owner. Every owner-specific piece is injected: the endpoint service that
owns directory existence, the authority that decides whether a preparation
may run, the roots the caller approves and the trusted harness
configuration.

The tests use recording fakes only: no Harness distribution, no environment
store and no process is started.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_agents.harness.preparation import PreparationResolver
from ordessa_agents.preparation import PreparationRefused
from ordessa_agents.profiles import ProfileContent, ProfileRevision, ProfileRevisionRef
from ordessa_agents.sdk.harness import HarnessDescriptor

ROOTS = ('work', 'home', 'config', 'data', 'state', 'cache', 'tmp')
PIN = {'environmentNamespace': 'local-test', 'definitionId': 'fake-brand', 'revision': '1'}


class _Endpoints:
    """The caller's endpoint service: it owns directory existence."""

    def __init__(self, root: Path):
        self.root = root
        self.requested: list[str] = []

    def directory_ready(self, locator, scope, bound, *, invocation, create=False):
        self.requested.append(bound['rootKey'])
        path = self.root / bound['rootKey']
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        return path

    def verify(self, locator, scope, prepared_ref, *, invocation):
        return {'verified': True}


class _Authority:
    """The caller's authority port: it keeps its own decision and refusal."""

    def __init__(self):
        self.asked: list[str] = []

    def allow(self, action, invocation):
        self.asked.append(action)
        return invocation


def _request():
    return SimpleNamespace(profile_revision_ref=object(), session_mode='fresh',
                           resume_ref=None, material_refs=(),
                           prepared_configuration_refs=())


def _bound():
    return SimpleNamespace(
        ref=SimpleNamespace(projection=lambda: {'schemaVersion': 'agent-endpoint/1'}),
        descriptor={'capabilities': ['launcher', 'communicate'],
                    'rootKeys': list(ROOTS), 'preparedConfigurations': [],
                    'endpointKind': 'local-directory'})


def _revision():
    return ProfileRevision(
        ProfileRevisionRef('local-test', 'demo-profile', 1, 'sha256:' + 'a' * 64),
        ProfileContent('1', PIN, ()))


def _port(tmp_path, *, roots=None, authority=None, harness_config=None):
    endpoints = _Endpoints(tmp_path / 'file-area')
    provider = SimpleNamespace(descriptor=HarnessDescriptor(
        'fake-brand', PIN, 'sha256:' + 'b' * 64, None, ROOTS, ()))
    resolver = PreparationResolver(
        profile_service=SimpleNamespace(get_revision=lambda ref: _revision()),
        catalog=SimpleNamespace(resolve=lambda pin: provider),
        endpoints=endpoints, authority=authority if authority is not None else _Authority(),
        roots=roots if roots is not None else {key: tmp_path / key for key in ROOTS},
        harness_config=harness_config if harness_config is not None
        else {'fake-brand': {'command': ['/bin/true']}})
    return resolver, endpoints


def test_the_port_binds_only_the_approved_roots_of_the_injected_endpoint(tmp_path):
    resolver, endpoints = _port(tmp_path)
    prepared = resolver.resolve(_request(), _bound(), SimpleNamespace(owner_scope='scope'))
    assert set(prepared.context.private_dirs) == set(ROOTS)
    assert sorted(endpoints.requested) == sorted(ROOTS)
    assert prepared.context.command_prefix == ('/bin/true',)
    assert prepared.context.launch_environment['HOME'] == str(tmp_path / 'file-area' / 'home')
    assert prepared.native_working_directory == str(tmp_path / 'file-area' / 'work')
    assert prepared.context.session_bootstrap.mode == 'fresh'


def test_a_root_the_caller_did_not_approve_is_refused(tmp_path):
    approved = {key: tmp_path / key for key in ROOTS if key != 'tmp'}
    resolver, endpoints = _port(tmp_path, roots=approved)
    with pytest.raises(PreparationRefused, match='harness root is not approved: tmp'):
        resolver.resolve(_request(), _bound(), SimpleNamespace(owner_scope='scope'))
    assert 'tmp' not in endpoints.requested


def test_the_authority_port_decides_before_any_directory_is_requested(tmp_path):
    authority = _Authority()
    resolver, endpoints = _port(tmp_path, authority=authority)
    resolver.resolve(_request(), _bound(), SimpleNamespace(owner_scope='scope'))
    assert authority.asked == ['agents.start']

    class _Refusing(_Authority):
        def allow(self, action, invocation):
            raise PreparationRefused('action is not locally enabled: ' + action)

    refusing, refusing_endpoints = _port(tmp_path, authority=_Refusing())
    with pytest.raises(PreparationRefused, match='not locally enabled'):
        refusing.resolve(_request(), _bound(), SimpleNamespace(owner_scope='scope'))
    assert refusing_endpoints.requested == []


def test_a_missing_authority_port_is_refused_instead_of_guessed(tmp_path):
    resolver, _ = _port(tmp_path, authority=object())
    with pytest.raises(PreparationRefused, match='preparation authority is unavailable'):
        resolver.resolve(_request(), _bound(), SimpleNamespace(owner_scope='scope'))


def test_the_harness_configuration_stays_the_callers_decision(tmp_path):
    resolver, _ = _port(tmp_path)
    resolver.set_harness_config({'fake-brand': {'command': ['/bin/echo', 'hello']}})
    prepared = resolver.resolve(_request(), _bound(), SimpleNamespace(owner_scope='scope'))
    assert prepared.context.command_prefix == ('/bin/echo', 'hello')


def test_the_port_names_no_environment_owner(tmp_path):
    import ordessa_agents.harness.preparation as module
    source = Path(module.__file__).read_text(encoding='utf-8')
    assert 'ordessa_environments' not in source
