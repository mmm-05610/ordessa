"""Offline evidence. These ACKs never claim disk durability."""
from decision_runtime.definitions.ports import DurabilityAck
from ..codec import EvidenceError, authorised, projection, record, summary, terminal, require_terminal_binding

class MemoryEvidenceSink:
    durable = False
    def __init__(self, *, read_context=None, max_events=4096, max_record_bytes=65536):
        self.read_context = read_context
        self.max_events, self.max_record_bytes = max_events, max_record_bytes
        self._runs = {}
        self._closed = False

    async def start(self, run_meta):
        meta = summary(run_meta)
        run_id = meta.get('run_id')
        if self._closed or not run_id or run_id in self._runs:
            raise EvidenceError('evidence_start')
        entry = record(dict(meta, type='run.started'), 1, None, self.max_record_bytes)
        self._runs[run_id] = {'events':[entry], 'terminal':None, 'ack':None}
        return DurabilityAck(1, entry['digest'], 'memory')

    async def append_durable(self, event):
        run = self._runs.get(event.get('run_id'))
        if self._closed or run is None or run['terminal'] is not None:
            raise EvidenceError('evidence_writer')
        events = run['events']
        if len(events) >= self.max_events: raise EvidenceError('evidence_limit')
        item = record(event, len(events)+1, events[-1]['digest'], self.max_record_bytes)
        events.append(item)
        return DurabilityAck(item['seq'], item['digest'], 'memory')

    async def finish(self, value):
        safe, result_digest = terminal(value)
        run = self._runs.get(safe.get('run_id'))
        if self._closed or run is None: raise EvidenceError('evidence_writer')
        require_terminal_binding(safe,run['events'][0]['payload'])
        if run['terminal'] is not None:
            if run['terminal'] != safe: raise EvidenceError('terminal_conflict')
            return run['ack']
        run['terminal'] = safe
        run['ack'] = DurabilityAck(len(run['events']), result_digest, 'memory')
        return run['ack']

    async def read(self, run_id, read_context):
        if not authorised(self.read_context, read_context): return {'status':'refused'}
        run = self._runs.get(run_id)
        if run is None: return {'status':'not_found'}
        from decision_runtime.definitions.values import canonical, decode, plain
        return plain(decode(canonical(projection(run['events'], run['terminal'], alive=not self._closed))))

    async def close(self): self._closed = True
