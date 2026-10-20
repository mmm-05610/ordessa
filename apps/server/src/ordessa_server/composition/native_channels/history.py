"""Native continuation metadata in the existing durable session event log.

Not an execution ledger or Profile configuration: only the Harness can write
this event after observing a real native session and an accepted prompt.
Private instance locators never leave this module's backend projection.
"""
import json
from pathlib import Path

KIND = 'acp.session.history.v1'


class NativeSessionHistory:
    def __init__(self, records):
        self.records = records

    def remember(self, channel, native_id, title):
        directory = getattr(channel.transport, 'instance_directory', None)
        if not directory:
            raise ValueError('Native session instance locator unavailable')
        history_id = getattr(channel, 'history_id', None) or channel.session_id
        previous = self.entries(channel.harness_id).get(history_id)
        if previous and (previous['nativeId'] != native_id or previous['instanceDirectory'] != directory
                         or previous['projectId'] != channel.workspace_id):
            raise ValueError('Native continuation identity changed')
        self.records.append_turn_event(channel.execution_id, KIND, {
            'historyId': history_id, 'nativeId': native_id,
            'harnessId': channel.harness_id, 'projectId': channel.workspace_id,
            'instanceDirectory': directory, 'title': previous['title'] if previous else title[:160] or 'Session',
        })

    def entries(self, harness_id):
        with self.records.database.read() as conn:
            rows = conn.execute('SELECT e.data_json,e.created_at FROM server_session_events e '
                'JOIN server_sessions s ON s.id=e.session_id WHERE e.kind=? '
                'AND s.archived_at IS NULL ORDER BY e.created_at,e.rowid', (KIND,)).fetchall()
        latest = {}
        for row in rows:
            item = json.loads(row['data_json'])
            if not isinstance(item, dict) or any(type(item.get(key)) is not str or not item[key]
                    for key in ('historyId', 'nativeId', 'harnessId', 'projectId', 'instanceDirectory', 'title')):
                raise ValueError('Invalid native continuation metadata')
            if item.get('harnessId') != harness_id:
                continue
            latest[item['historyId']] = {**item, 'updatedAt': row['created_at']}
        return latest

    def list(self, harness_id):
        return [{'id': item['historyId'], 'title': item['title'],
                 'workspaceId': item['projectId'], 'updatedAt': item['updatedAt']}
                for item in self.entries(harness_id).values()]

    def lookup(self, harness_id, history_id, workspace_id):
        item = self.entries(harness_id).get(history_id)
        if item is None or item['projectId'] != workspace_id:
            raise ValueError('Native session history target unavailable')
        directory = Path(item['instanceDirectory'])
        # Same trust boundary as instance allocation, additionally constrained
        # to the Server's own retained harness-instances collection.
        from .instance_directory import _private
        root = Path(self.records.database.data_root) / 'harness-instances'
        if directory.parent != root or directory.resolve() != directory:
            raise ValueError('Native session instance locator outside data root')
        _private(root)
        _private(directory)
        return item
