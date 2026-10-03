"""T007-04/05 verification gates for the native-history owner.

Pins existing `server_acp` behaviour only; no production code changes:

- the durable history event appears only through the correlated live path
  (observed native session + accepted prompt), never for a bare `session/new`;
- `entries`/`list`/`lookup` are read-only projections, and `lookup` refuses a
  retained locator outside `<data_root>/harness-instances` or one that is not
  a private directory;
- listing history opens no channel, launches no Agent and opens no run record,
  and reads no Profile store;
- the wire projections carry data only -- no executable handle and no locator
  in the public listing;
- a composition without a history recorder answers the typed
  `CAPABILITY_UNSUPPORTED`.

SQLite event-log fixtures and correlated ACP frames only. No model inference.
"""
import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from server_plugin_api import ServerPluginContext, WireError

from ordessa_harness.server_acp.history import KIND, NativeSessionHistory
from ordessa_harness.server_acp.instance_directory import allocate_instance_directory
from ordessa_harness.server_acp.plugin import PLUGIN_ID, AcpChannelServerPlugin
from ordessa_harness.server_acp.registry import _Channel, _ObservedTransport


def _event_count(records):
    with records.database.read() as conn:
        return conn.execute('SELECT COUNT(*) FROM server_session_events').fetchone()[0]


@pytest.fixture
def records(tmp_path):
    path = tmp_path / 'history.sqlite'

    @contextmanager
    def read():
        with sqlite3.connect(path) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    with read() as conn:
        conn.executescript(
            'CREATE TABLE server_sessions(id TEXT,archived_at TEXT);'
            'CREATE TABLE server_session_events(session_id TEXT,data_json TEXT,created_at TEXT,kind TEXT);'
            "INSERT INTO server_sessions VALUES('ledger',NULL);")

    def append(turn, kind, data):
        assert turn == 'execution'
        with read() as conn:
            conn.execute('INSERT INTO server_session_events VALUES(?,?,?,?)',
                         ('ledger', json.dumps(data), '2026-10-03T00:00:00Z', kind))

    return SimpleNamespace(database=SimpleNamespace(data_root=tmp_path, read=read),
                           append_turn_event=append)


def _channel(records):
    value = _Channel(connection_id='connection', harness_id='pi', workspace_id='project',
                     profile_id='native', cwd='/project', session_scope_id='attempt')
    value.session_id, value.execution_id = 'ledger', 'execution'
    value.transport = _ObservedTransport(value, SimpleNamespace(
        instance_directory=str(allocate_instance_directory(records.database.data_root)),
        send_line=lambda _line: None))
    value.history_writer = NativeSessionHistory(records).remember
    return value


def _request(value, request_id, method, **params):
    value.transport.send_line(json.dumps(dict(jsonrpc='2.0', id=request_id,
                                              method=method, params=params)))


def _reply(value, request_id, **body):
    value.deliver(json.dumps(dict(jsonrpc='2.0', id=request_id, **body)))


def _accept_prompt(value, request_id, native_id, text):
    _request(value, request_id, 'session/prompt', sessionId=native_id,
             prompt=[{'type': 'text', 'text': text}])
    _reply(value, request_id, result={'stopReason': 'end_turn'})


def test_remember_publishes_only_after_observed_native_session_and_accepted_prompt(records):
    history = NativeSessionHistory(records)
    value = _channel(records)
    assert _event_count(records) == 0

    # A correlated session/new reply alone creates the native owner, not history.
    _request(value, 'new', 'session/new')
    _reply(value, 'new', result={'sessionId': 'native'})
    assert history.list('pi') == []
    assert _event_count(records) == 0

    # An errored prompt is not durable history either.
    _request(value, 'rejected', 'session/prompt', sessionId='native',
             prompt=[{'type': 'text', 'text': 'hello'}])
    _reply(value, 'rejected', error={'code': -1})
    assert history.list('pi') == []
    assert _event_count(records) == 0

    # A prompt naming a native session this channel never observed is ignored.
    _request(value, 'foreign', 'session/prompt', sessionId='other',
             prompt=[{'type': 'text', 'text': 'hello'}])
    _reply(value, 'foreign', result={'stopReason': 'end_turn'})
    assert history.list('pi') == []
    assert _event_count(records) == 0

    # Only the accepted prompt on the observed native session persists.
    _accept_prompt(value, 'accepted', 'native', 'hello')
    assert [item['id'] for item in history.list('pi')] == ['ledger']
    assert _event_count(records) == 1


def test_remember_guards_instance_locator_and_changed_identity(records):
    history = NativeSessionHistory(records)
    value = _channel(records)

    original = value.transport
    value.transport = _ObservedTransport(value, SimpleNamespace(instance_directory=None))
    with pytest.raises(ValueError, match='Native session instance locator unavailable'):
        history.remember(value, 'native', 'hello')
    value.transport = original
    assert _event_count(records) == 0

    history.remember(value, 'native', 'hello')
    with pytest.raises(ValueError, match='Native continuation identity changed'):
        history.remember(value, 'moved-native', 'hello')
    assert _event_count(records) == 1


def test_history_reads_are_read_only(records):
    value = _channel(records)
    history = NativeSessionHistory(records)
    history.remember(value, 'native', 'hello')
    before = _event_count(records)

    assert list(history.entries('pi')) == ['ledger']
    assert [item['id'] for item in history.list('pi')] == ['ledger']
    retained = history.lookup('pi', 'ledger', 'project')
    assert retained['nativeId'] == 'native' and retained['title'] == 'hello'

    assert _event_count(records) == before


def test_lookup_rejects_locator_outside_or_not_private_under_data_root(records, tmp_path):
    history = NativeSessionHistory(records)
    _channel(records)  # allocates the retained root and one private directory
    root = records.database.data_root / 'harness-instances'

    def seed(history_id, directory):
        records.append_turn_event('execution', KIND, {
            'historyId': history_id, 'nativeId': 'native', 'harnessId': 'pi',
            'projectId': 'project', 'instanceDirectory': str(directory), 'title': 'hello'})

    outside = tmp_path / 'elsewhere'
    outside.mkdir(mode=0o700)
    seed('outside-ledger', outside)
    with pytest.raises(ValueError, match='outside data root'):
        history.lookup('pi', 'outside-ledger', 'project')

    link = root / 'link'
    link.symlink_to(allocate_instance_directory(records.database.data_root),
                    target_is_directory=True)
    seed('link-ledger', link)
    with pytest.raises(ValueError, match='outside data root'):
        history.lookup('pi', 'link-ledger', 'project')

    exposed = allocate_instance_directory(records.database.data_root)
    exposed.chmod(0o755)
    seed('mode-ledger', exposed)
    with pytest.raises(ValueError, match='must be private'):
        history.lookup('pi', 'mode-ledger', 'project')

    # An unavailable locator stays visible in the listing; no fallback instance.
    assert {item['id'] for item in history.list('pi')} >= {
        'outside-ledger', 'link-ledger', 'mode-ledger'}


class _PoisonProfiles:
    """Any attribute read means the history surface reached a Profile store."""

    def __getattr__(self, name):
        raise AssertionError(f'Profile store must not be read while listing history: {name}')


def test_listing_history_opens_no_channel_no_run_and_reads_no_profile_store(records, monkeypatch):
    import ordessa_harness.server_acp.registry as registry_module

    seeded = _channel(records)
    NativeSessionHistory(records).remember(seeded, 'native', 'hello')
    launches = []

    def launch(**kwargs):
        launches.append(kwargs)
        raise AssertionError('listing history must not launch an Agent')

    def identity_for(harness_id):
        if harness_id != 'pi':
            return None
        return {'mode': 'native', 'harness': 'pi', 'profileId': 'profile-1'}

    plugin = AcpChannelServerPlugin(launch=launch, native_identity_for=identity_for)
    registration = plugin.build(ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=None,
        ports={'workspace.service': object(), 'sessions.records': records,
               'profiles.records': _PoisonProfiles()}))
    registry = registration.provided_ports['acp.channels']

    def open_run(**_kwargs):
        raise AssertionError('listing history must not open a run record')

    monkeypatch.setattr(registry_module, 'open_run', open_run)
    handler = next(method for method in registration.methods
                   if method.method_id == 'acp.sessions.list').handler

    before = _event_count(records)
    listed = registry.list_history('pi')
    assert handler({'harnessId': 'pi'}) == {'items': listed}
    assert [item['id'] for item in listed] == ['ledger']

    assert launches == []
    assert registry._by_id == {} and registry._by_pair == {}
    assert registry._spent_scopes == set()
    assert _event_count(records) == before

    # Unknown harness: typed absence from the identity stub, same read-only path.
    with pytest.raises(WireError) as excinfo:
        handler({'harnessId': 'codex'})
    assert excinfo.value.family == 'CAPABILITY_UNSUPPORTED'
    assert excinfo.value.message == 'native Harness unavailable'


_LIST_PROJECTION_KEYS = frozenset({'id', 'title', 'workspaceId', 'updatedAt'})
_RETAINED_PROJECTION_KEYS = frozenset({
    'historyId', 'nativeId', 'harnessId', 'projectId', 'instanceDirectory',
    'title', 'updatedAt'})
_NEVER_PROJECTED_KEYS = frozenset({
    'command', 'args', 'argv', 'env', 'environment', 'executable', 'handle',
    'pid', 'token', 'secret', 'credentials', 'profileId',
    'configurationProfileId'})


def test_history_projections_are_data_only_without_executable_handle(records):
    value = _channel(records)
    history = NativeSessionHistory(records)
    history.remember(value, 'native', 'hello')

    listed = history.list('pi')[0]
    retained = history.lookup('pi', 'ledger', 'project')

    assert type(listed) is dict and type(retained) is dict
    assert set(listed) == _LIST_PROJECTION_KEYS
    assert set(retained) == _RETAINED_PROJECTION_KEYS
    assert _NEVER_PROJECTED_KEYS.isdisjoint(listed)
    assert _NEVER_PROJECTED_KEYS.isdisjoint(retained)
    # The public listing carries no locator or native handle; only the backend
    # lookup resolves them, and even that view is data, not an executable.
    assert 'nativeId' not in listed and 'instanceDirectory' not in listed
    assert set(json.loads(json.dumps(retained))) == _RETAINED_PROJECTION_KEYS


def test_history_absent_is_typed_capability_unsupported():
    # A recorder whose store exposes no database leaves the registry without
    # a history projection: the wire surface must answer typed unsupported.
    bare_records = SimpleNamespace(append_turn_event=lambda *_args, **_kwargs: None)
    launches = []
    plugin = AcpChannelServerPlugin(
        launch=lambda **kwargs: launches.append(kwargs),
        native_identity_for=lambda harness_id: {
            'mode': 'native', 'harness': harness_id, 'profileId': 'profile-1'})
    registration = plugin.build(ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=None,
        ports={'workspace.service': object(), 'sessions.records': bare_records,
               'profiles.records': object()}))
    registry = registration.provided_ports['acp.channels']
    assert registry.history is None
    with pytest.raises(ValueError, match='native session history unavailable'):
        registry.list_history('pi')

    handler = next(method for method in registration.methods
                   if method.method_id == 'acp.sessions.list').handler
    with pytest.raises(WireError) as excinfo:
        handler({'harnessId': 'pi'})
    assert excinfo.value.family == 'CAPABILITY_UNSUPPORTED'
    assert excinfo.value.message == 'native session history unavailable'
    assert launches == []

    # No managed-channel composition at all answers the same typed absence.
    empty_registration = AcpChannelServerPlugin().build(ServerPluginContext(
        plugin_id=PLUGIN_ID, data_root=None,
        ports={'workspace.service': object(), 'sessions.records': object(),
               'profiles.records': object()}))
    empty_handler = next(method for method in empty_registration.methods
                         if method.method_id == 'acp.sessions.list').handler
    with pytest.raises(WireError) as excinfo:
        empty_handler({'harnessId': 'pi'})
    assert excinfo.value.family == 'CAPABILITY_UNSUPPORTED'
    assert excinfo.value.message == 'native session history unavailable'
