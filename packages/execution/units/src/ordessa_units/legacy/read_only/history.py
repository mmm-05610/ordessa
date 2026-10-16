"""Read-only SQLite inspector of historical execution-linked core_* records.

No connection is shared with a live owner, no schema is created/migrated, and
no old Work/Dispatch/Ref becomes a new Unit or authorizes an invocation. Rows
are copied verbatim for inspection, including unknown fields and fence state.
Standalone Work records are a tooling display requirement outside Unit history.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from types import MappingProxyType
from typing import Mapping

# Wire values only: these are not runtime resource kinds or a provider catalog.
_WIRE_TAGS = frozenset({'SessionRef', 'WorkflowInstanceRef', 'RunRef', 'WorkspaceRef', 'ArtifactRef'})

class HistoryNotFound(LookupError):
    pass

@dataclass(frozen=True)
class HistoricalRef:
    tag: str
    provider: str
    native_id: str
    uri: str | None
    metadata: Mapping[str, str]

    def __post_init__(self) -> None:
        if self.tag not in _WIRE_TAGS:
            raise ValueError('unknown historical Ref wire tag')
        if not isinstance(self.provider, str) or not self.provider or not isinstance(self.native_id, str) or not self.native_id:
            raise ValueError('historical Ref identity is required')
        metadata = dict(self.metadata)
        if len(metadata) > 16 or any(not isinstance(k, str) or not isinstance(v, str)
                or len(k) > 64 or len(v) > 256 for k, v in metadata.items()):
            raise ValueError('historical Ref metadata exceeds original bounds')
        object.__setattr__(self, 'metadata', MappingProxyType(metadata))

def parse_correlation(value: str | None) -> tuple[HistoricalRef | None, str | None]:
    """Preserve malformed and pre-ref:v1 correlations as opaque original text."""
    if value is None:
        return None, None
    if not value.startswith('ref:v1:'):
        return None, value
    try:
        payload = json.loads(value[len('ref:v1:'):])
        ref = HistoricalRef(payload['type'], payload['provider'], payload['native_id'],
                            payload.get('uri'), payload.get('metadata') or {})
    except (KeyError, TypeError, ValueError):
        return None, value
    return ref, None

class ExecutionHistory:
    """Explicit lifetime of one read-only inspector; receives an existing path."""
    def __init__(self, path: Path | str):
        existing = Path(path).resolve(strict=True)
        if not existing.is_file():
            raise ValueError('history path must name an existing database file')
        self.__connection = sqlite3.connect(existing.as_uri() + '?mode=ro', uri=True)
        self.__connection.row_factory = sqlite3.Row
        self.__connection.execute('PRAGMA query_only=ON')

    def close(self) -> None:
        self.__connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _rows(self, query: str, key: str):
        return tuple(MappingProxyType(dict(row)) for row in self.__connection.execute(query, (key,)))

    def execution(self, execution_id: str):
        rows = self._rows('SELECT * FROM core_executions WHERE id = ?', execution_id)
        if not rows:
            raise HistoryNotFound(execution_id)
        return rows[0]

    def historical_work(self, work_id: str):
        """Raw historical tooling display only; never a Unit business value."""
        rows = self._rows('SELECT * FROM core_works WHERE id = ?', work_id)
        if not rows:
            raise HistoryNotFound(work_id)
        return rows[0]

    def executions_for_work(self, work_id: str):
        self.historical_work(work_id)
        return self._rows('SELECT * FROM core_executions WHERE work_id = ? ORDER BY created_at, id', work_id)

    def responsibility_intent(self, execution_id: str):
        """Read the original creation event; never infer from a Work objective."""
        self.execution(execution_id)
        rows = self._rows("SELECT * FROM core_events WHERE subject_id = ? AND type = 'ExecutionCreated' ORDER BY occurred_at DESC, id DESC", execution_id)
        if not rows:
            return None
        facts = json.loads(rows[0]['data_json'])
        value = facts.get('responsibility_intent')
        return value if isinstance(value, str) else None

    def linked_work(self, execution_id: str):
        execution = self.execution(execution_id)
        rows = self._rows('SELECT * FROM core_works WHERE id = ?', execution['work_id'])
        if not rows:
            raise HistoryNotFound(execution['work_id'])
        return rows[0]

    def refs(self, execution_id: str):
        self.execution(execution_id)
        rows = self._rows('SELECT * FROM core_execution_refs WHERE execution_id = ? ORDER BY created_at, relation, type, provider, native_id', execution_id)
        return tuple((row, HistoricalRef(row['type'], row['provider'], row['native_id'], row['uri'], json.loads(row['metadata_json']))) for row in rows)

    def dispatches(self, execution_id: str):
        self.execution(execution_id)
        return self._rows('SELECT * FROM core_dispatches WHERE execution_id = ? ORDER BY created_at, id', execution_id)

    def events(self, execution_id: str):
        self.execution(execution_id)
        return self._rows('SELECT * FROM core_events WHERE subject_id = ? ORDER BY occurred_at, id', execution_id)

    def observations(self, execution_id: str):
        self.execution(execution_id)
        return self._rows('SELECT * FROM core_resource_observations WHERE execution_id = ? ORDER BY id', execution_id)

    def finalizations(self, execution_id: str):
        self.execution(execution_id)
        return self._rows('SELECT * FROM core_execution_finalizations WHERE execution_id = ? ORDER BY created_at', execution_id)
