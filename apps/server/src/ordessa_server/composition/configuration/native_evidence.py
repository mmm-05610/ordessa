"""Authorized original Agent facts and explicit read-only historical native rows.

No journal construction, stand-in receipt issuer, apply or runtime reconciliation.
Historical evidence is never accepted as current Agent identity or authorization.
"""
from pathlib import Path
import sqlite3

from ordessa_execution_agents.public import InteractionService


class NativeEvidenceUnavailable(RuntimeError):
    pass


class AgentNativeEvidenceReader:
    def __init__(self, source):
        if type(source) is not InteractionService:
            raise NativeEvidenceUnavailable('original Agent interaction source required')
        self.source=source

    def read_binding(self, agent_ref, *, invocation):
        return self.source.read_binding(agent_ref,invocation=invocation)

    def read_turn(self, query, *, invocation):
        return self.source.query_turn(query,invocation=invocation)


class HistoricalNativeEvidenceReader:
    """Explicit historical file reader; external existing authority checks every read.

    `authorize` is a trusted composition callback over an opaque invocation and
    exact principal/target/operation. Missing/refused checks never open the DB.
    No path, principal label or serialized target authenticates a caller.
    """
    def __init__(self,path,*,authorize):
        if not callable(authorize):raise NativeEvidenceUnavailable('historical read authority required')
        self.path=Path(path).absolute();self.authorize=authorize

    def read(self,principal,target,operation_id,*,invocation):
        if (type(principal) is not str or not principal or type(operation_id) is not str or not operation_id
                or type(target) is not dict or set(target)!=
                    {'server_id','session_id','channel_id','runtime_generation'}
                or any(type(target[k]) is not str or not target[k] for k in ('server_id','session_id','channel_id'))
                or type(target['runtime_generation']) is not int or target['runtime_generation']<0):
            raise NativeEvidenceUnavailable('exact historical identity required')
        target=dict(target)  # snapshot before trusted read check; no mutable target rebind
        if self.authorize(invocation,principal,dict(target),operation_id) is not True:
            raise NativeEvidenceUnavailable('historical read refused')
        if self.path.is_symlink() or any(p.is_symlink() for p in self.path.parents):
            raise NativeEvidenceUnavailable('historical database symlink refused')
        db=None
        try:
            db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)
            db.execute('PRAGMA query_only=ON')
            db.row_factory=sqlite3.Row
            row=db.execute('SELECT operation_id,principal,server_id,session_id,channel_id,runtime_generation,'
                'operation_key,plan_id,fingerprint,state,result_json FROM operations '
                'WHERE operation_id=? AND principal=? AND server_id=? AND session_id=? AND channel_id=? AND runtime_generation=?',
                (operation_id,principal,target['server_id'],target['session_id'],target['channel_id'],target['runtime_generation'])).fetchone()
            if row is None:return None
            native=db.execute('SELECT manifest_digest,receipt_json FROM native_evidence WHERE operation_id=?',(operation_id,)).fetchone()
            verification=db.execute('SELECT readback_evidence_ref FROM native_verifications WHERE operation_id=?',(operation_id,)).fetchone()
            # Keep old JSON strings/state verbatim, including unknown and absent
            # readback. No upgrade into current TurnReceipt/role/confirmation.
            return {'historical':True,'operation':dict(row),'native':None if native is None else dict(native),
                'verification':None if verification is None else dict(verification)}
        except sqlite3.Error as exc:
            raise NativeEvidenceUnavailable('historical database unavailable or schema invalid') from exc
        finally:
            if db is not None:db.close()


__all__=['AgentNativeEvidenceReader','HistoricalNativeEvidenceReader','NativeEvidenceUnavailable']
