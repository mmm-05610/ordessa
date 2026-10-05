"""Bounded, summary-only evidence encoding. Never stringify arbitrary objects."""
import re
from collections.abc import Mapping
from ..contracts.codec import ContractError, canonical, digest, plain

class EvidenceError(ContractError):
    """The message is a fixed safe code, never an OS error or source payload."""

_TOKEN = re.compile(r'^[A-Za-z0-9_.:/+-]{1,256}$')
_HASH = re.compile(r'^sha256:[0-9a-f]{64}$')
_SUMMARY = frozenset(('type', 'event', 'run_id', 'call_id', 'attempt', 'attempt_no',
    'request_digest', 'flow_digest', 'manifest_digest', 'run_manifest_digest',
    'question_digest', 'answer_digest', 'provider_settings_digest', 'stage',
    'error_code', 'code', 'usage', 'consumed', 'effective_policy_refs',
    'policy_refs', 'flow_ref', 'task_revision', 'request_id', 'evidence_refs',
    'result_digest', 'terminal_record_digest'))
_FORBIDDEN = frozenset(('prompt', 'body', 'headers', 'header', 'secret', 'token',
    'api_key', 'raw', 'raw_response', 'response', 'exception', 'state', 'text',
    'description', 'instructions', 'title', 'content'))
_CREDENTIALS = frozenset(('token','accesstoken','apikey','password','secret',
    'clientsecret','privatekey','authorization','credential','credentials',
    'refreshtoken','bearertoken'))

def _normal_key(key): return key.lower().replace('_','').replace('-','')

def _secret_reference(value):
    if not isinstance(value, Mapping) or set(value) != {'secretRef'}: return False
    ref = value['secretRef']
    if not (isinstance(ref,Mapping)
            and set(ref)=={'ref','revision','owner_namespace','access_purpose'}
            and all(type(v) is str for v in ref.values())): return False
    return (re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,191}',ref['ref']) is not None
        and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:+-]{0,63}',ref['revision']) is not None
        and all(re.fullmatch(r'[a-z][a-z0-9._-]{0,95}',ref[k]) is not None
                for k in ('owner_namespace','access_purpose')))

def redact(value, *, depth=0):
    if depth > 24: raise EvidenceError('evidence_depth')
    if isinstance(value, Mapping):
        return {k: redact(v, depth=depth+1) for k,v in value.items()
                if type(k) is str and k.lower() not in _FORBIDDEN
                and _normal_key(k) not in _CREDENTIALS}
    if type(value) in (list, tuple):
        return [redact(v, depth=depth+1) for v in value]
    if value is None or type(value) in (bool, int, float): return value
    if type(value) is str:
        if not _TOKEN.fullmatch(value): raise EvidenceError('evidence_unsafe_string')
        return value
    raise EvidenceError('evidence_type')

def summary(value):
    if not isinstance(value, Mapping): raise EvidenceError('evidence_mapping')
    return redact({k:v for k,v in value.items() if k in _SUMMARY})

def terminal(value):
    if not isinstance(value, Mapping): raise EvidenceError('evidence_terminal')
    supplied = value.get('result_digest', value.get('terminal_digest'))
    if type(supplied) is not str or not _HASH.fullmatch(supplied):
        raise EvidenceError('evidence_terminal_digest')
    if value.get('terminal_digest', supplied) != supplied:
        raise EvidenceError('evidence_terminal_digest')
    result = value.get('result')
    # Unlike event summaries, terminal results must not be silently rewritten:
    # the runtime digest binds the exact validated public DTO.
    allowed = {'run_id', 'status', 'result', 'result_digest', 'terminal_digest', 'expected_last_seq'}
    if set(value)-allowed: raise EvidenceError('evidence_terminal_field')
    def public_result(item, depth=0):
        if depth>24: raise EvidenceError('evidence_depth')
        if isinstance(item, Mapping):
            forbidden = {'prompt','body','headers','header','secret','api_key',
                         'access_token','authorization','raw','raw_response','exception','state'}
            if any(type(k) is not str or
                   (k.lower() in forbidden and not (_normal_key(k) in _CREDENTIALS and _secret_reference(v))) or
                   (_normal_key(k) in _CREDENTIALS and v is not None and not _secret_reference(v))
                   for k,v in item.items()):
                raise EvidenceError('evidence_terminal_sensitive')
            return {k:public_result(v,depth+1) for k,v in item.items()}
        if type(item) in (tuple,list): return [public_result(v,depth+1) for v in item]
        if item is None or type(item) in (bool,int,float): return item
        if type(item) is str and len(item.encode('utf-8'))<=4096: return item
        raise EvidenceError('evidence_terminal_type')
    safe = public_result(value)
    if not _TOKEN.fullmatch(safe.get('run_id','')): raise EvidenceError('evidence_run_id')
    if safe.get('status') not in ('completed', 'failed', 'cancelled', 'budget_exhausted'):
        raise EvidenceError('evidence_terminal_status')
    if result is not None and digest('result', result) != supplied:
        raise EvidenceError('evidence_terminal_digest')
    canonical(safe)
    return safe, supplied

def record(event, seq, previous, max_bytes):
    payload = summary(event)
    value = {'contract_version':'decision-evidence/1', 'seq':seq,
             'prev_digest':previous, 'payload_digest':digest('event', payload),
             'payload':payload}
    value['digest'] = digest('event', value)
    canonical(value, max_bytes=max_bytes)
    return value

def authorised(expected, supplied):
    from ..contracts.ports import ReadContext
    return (isinstance(supplied, ReadContext) and isinstance(expected, ReadContext)
            and supplied.authority is expected.authority
            and supplied.scope_ref == expected.scope_ref)

def projection(events, committed=None, *, alive=False):
    intents = {e['payload'].get('call_id') for e in events
               if e['payload'].get('type', e['payload'].get('event')) == 'call.intent'}
    responses = {e['payload'].get('call_id') for e in events
                 if e['payload'].get('type', e['payload'].get('event')) == 'call.response'}
    return {'status':'completed' if committed else ('running' if alive else 'interrupted'),
            'terminal':committed, 'events':events,
            'call_evidence':'unknown' if intents-responses else 'recorded'}
