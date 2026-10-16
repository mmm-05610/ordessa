"""ACP facts in the original UnitRecords journal; no independent authority."""
import hashlib
import json

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping


def refuse(message):
    from .unit_records import UnitRecordsRefused
    raise UnitRecordsRefused(message)


def digest(value):
    return 'sha256:' + hashlib.sha256(safe_json({'value':value}).encode()).hexdigest()


def initialize(owner):
    with owner.journal._connect() as db:
        db.execute('''CREATE TABLE harness_acp_turn_attempts (
            operation_ref TEXT PRIMARY KEY, unit_ref TEXT NOT NULL,
            state TEXT NOT NULL, revision INTEGER NOT NULL,
            body_json TEXT NOT NULL, body_digest TEXT NOT NULL,
            FOREIGN KEY(unit_ref) REFERENCES harness_unit_reservations(unit_ref))''')


def _check(owner, db, row):
    if row is None:
        return None
    body = json.loads(row['body_json'])
    if digest(body) != row['body_digest'] or safe_json(body) != row['body_json']:
        refuse('ACP operation content integrity differs')
    if (body['contractVersion'] != 'unit-acp-turn/1'
            or body['operationRef'] != row['operation_ref'] or body['unitRef']['unitId'] != row['unit_ref']
            or body['state'] != row['state'] or body['revision'] != row['revision']
            or type(body['revision']) is not int or body['revision'] < 1
            or body['state'] not in {'reserved', 'possibly-written', 'completed', 'failed', 'unknown'}):
        refuse('ACP operation identity/state integrity differs')
    unit = owner._unit(db, row['unit_ref'])
    session = db.execute('SELECT * FROM harness_unit_sessions WHERE unit_ref=?', (row['unit_ref'],)).fetchone()
    from .unit_records import _digest
    if (safe_json(unit.public_ref) != safe_json(body['unitRef']) or _digest(unit.intent_json) != body['unitIntentDigest']
            or session is None or session['state'] != 'confirmed'
            or _digest(session['native_json']) != session['native_digest']
            or safe_json(body['nativeBinding']) != session['native_json']):
        refuse('ACP operation original Unit/session provenance differs')
    if (digest(body['input']) != body['inputDigest'] or body['input']['unitRef'] != body['unitRef']
            or body['input']['params'].get('sessionId') != body['nativeBinding']['sessionId']):
        refuse('ACP operation input integrity differs')
    request = body['request']
    if ((body['state'] == 'reserved' and request is not None)
            or (body['state'] == 'possibly-written' and request is None)
            or (body['state'] in {'reserved','possibly-written','unknown'} and body['response'] is not None)):
        refuse('ACP state/request/receipt boundary differs')
    if request is not None:
        raw = request['raw']
        frame = request['frameUtf8'].encode()
        if (raw.get('jsonrpc') != '2.0' or raw.get('method') != 'session/prompt' or raw.get('params') != body['input']['params']
                or not frame.endswith(b'\n') or frame.count(b'\n') != 1 or json.loads(frame) != raw
                or request['frameDigest'] != 'sha256:'+hashlib.sha256(frame).hexdigest()
                or type(raw.get('id')) not in (str, int)):
            refuse('ACP request frame integrity differs')
    if body['state'] in {'completed', 'failed'}:
        response = body['response']
        if (request is None or response is None or response.get('jsonrpc') != '2.0'
                or safe_json({'id':response.get('id')}) != safe_json({'id':request['raw']['id']})
                or int('result' in response) + int('error' in response) != 1
                or response not in [event['raw'] for event in body['events']]
                or (body['state'] == 'completed') != ('result' in response)):
            refuse('ACP terminal receipt integrity differs')
        if body['state'] == 'completed':
            from acp.schema import PromptResponse
            PromptResponse.model_validate(response['result'])
        elif (not isinstance(response['error'], dict) or type(response['error'].get('code')) is not int
                or not isinstance(response['error'].get('message'), str)):
            refuse('ACP remote error receipt differs')
    if digest(body['events']) != body['eventsDigest'] or digest(body['response']) != body['responseDigest']:
        refuse('ACP observations integrity differs')
    for index, event in enumerate(body['events'], 1):
        params = event['raw'].get('params', {})
        matched = isinstance(params, dict) and params.get('sessionId') == body['nativeBinding']['sessionId']
        if type(event['sequence']) is not int or event['sequence'] != index or event['sessionMatched'] is not matched:
            refuse('ACP event sequence/session association differs')
    if body['summary'] is not None and body['summary'] != _summary(body):
        refuse('ACP derived output summary differs')
    return body


def _write(db, body):
    encoded = safe_json(body)
    if len(encoded.encode()) > 262144:
        refuse('ACP evidence bound exceeded; complete outcome unavailable')
    db.execute('UPDATE harness_acp_turn_attempts SET state=?,revision=?,body_json=?,body_digest=? WHERE operation_ref=?',
               (body['state'], body['revision'], encoded, digest(body), body['operationRef']))


def _read(owner, db, operation):
    from .unit_records import UnitRecordsRefused
    try:
        return _check(owner, db, db.execute('SELECT * FROM harness_acp_turn_attempts WHERE operation_ref=?', (operation,)).fetchone())
    except UnitRecordsRefused:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise UnitRecordsRefused('ACP evidence structure integrity invalid') from error


def reserve(owner, unit_ref, operation, params):
    if not owner.acp_turn_available or not owner.journal.acp_turn_opt_in:
        refuse('ACP durable schema is unavailable; explicit pristine opt-in required')
    if not isinstance(operation, str) or not operation or len(operation) > 256 or any(ord(c) < 32 for c in operation):
        refuse('Explicit bounded ACP operation reference required')
    with owner.journal._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        unit = owner._unit(db, unit_ref['unitId'])
        if safe_json(unit.public_ref) != safe_json(unit_ref):
            refuse('Complete original Unit reference differs')
        binding = owner._binding(db, unit.unit_ref)
        if binding.state != 'confirmed' or params.get('sessionId') != binding.native_facts['sessionId']:
            refuse('Original confirmed ACP session required')
        if db.execute('SELECT 1 FROM harness_acp_turn_attempts WHERE operation_ref=?', (operation,)).fetchone():
            refuse('Original ACP operation already exists; no replay')
        if db.execute("SELECT 1 FROM harness_acp_turn_attempts WHERE unit_ref=? AND state IN ('reserved','possibly-written','unknown')", (unit.unit_ref,)).fetchone():
            refuse('Original ACP operation unresolved; no new dispatch')
        inputs = {'unitRef':dict(unit_ref), 'params':params}
        body = {'contractVersion':'unit-acp-turn/1', 'operationRef':operation, 'unitRef':dict(unit_ref),
                'unitIntentDigest':hashlib.sha256(unit.intent_json.encode()).hexdigest(), 'nativeBinding':dict(binding.native_facts),
                'input':inputs, 'inputDigest':digest(inputs), 'state':'reserved', 'revision':1,
                'request':None, 'events':[], 'eventsDigest':digest([]), 'response':None,
                'responseDigest':digest(None), 'observationAssociation':'session-request-window',
                'summary':None}
        db.execute('INSERT INTO harness_acp_turn_attempts VALUES (?,?,?,1,?,?)',
                   (operation, unit.unit_ref, 'reserved', safe_json(body), digest(body)))
        db.commit()
    return body


def dispatch(owner, operation, raw):
    with owner.journal._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        body = _read(owner, db, operation)
        if body is None or body['state'] != 'reserved' or body['request'] is not None:
            refuse('ACP original dispatch barrier already crossed; no replay')
        if (raw.get('jsonrpc') != '2.0' or raw.get('method') != 'session/prompt'
                or raw.get('params') != body['input']['params'] or type(raw.get('id')) not in (int, str)):
            refuse('ACP dispatch differs from original frozen prompt')
        frame = (json.dumps(raw, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode()
        body['request'] = {'raw':raw, 'frameUtf8':frame.decode(), 'frameDigest':'sha256:'+hashlib.sha256(frame).hexdigest()}
        body['state'] = 'possibly-written'; body['revision'] += 1
        _write(db, body); db.commit()


def observe(owner, operation, raw):
    with owner.journal._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        body = _read(owner, db, operation)
        if body is None or body['state'] != 'possibly-written':
            refuse('ACP observation has no original dispatched operation')
        params = raw.get('params', {})
        matched = isinstance(params, dict) and params.get('sessionId') == body['nativeBinding']['sessionId']
        body['events'].append({'sequence':len(body['events'])+1, 'sessionMatched':matched, 'raw':raw})
        body['eventsDigest'] = digest(body['events']); body['revision'] += 1
        _write(db, body); db.commit()


def _summary(body):
    texts = []
    for event in body['events']:
        raw = event['raw']; update = raw.get('params', {}).get('update', {}) if isinstance(raw.get('params'), dict) else {}
        content = update.get('content', {}) if isinstance(update, dict) else {}
        if (event['sessionMatched'] and raw.get('method') == 'session/update'
                and update.get('sessionUpdate') == 'agent_message_chunk'
                and isinstance(content, dict) and content.get('type') == 'text'):
            texts.append(content.get('text', ''))
    output = ''.join(texts); response = body['response']
    return {'text':output, 'textDigest':digest(output), 'stopReason':response.get('result', {}).get('stopReason') if response else None,
            'eventCount':len(body['events']), 'knownRemoteFailure':body['state'] == 'failed',
            'successfulRpcResponse':body['state'] == 'completed', 'modelQualityVerified':False}


def finish(owner, operation, state, response=None):
    with owner.journal._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        body = _read(owner, db, operation)
        if body is None or body['state'] not in {'reserved', 'possibly-written'}:
            refuse('ACP original outcome already sealed')
        body['state'] = state; body['revision'] += 1; body['response'] = response
        body['responseDigest'] = digest(response)
        body['summary'] = _summary(body)
        _write(db, body)
        # Validate the prospective sealed row before committing it.
        _read(owner, db, operation); db.commit()
        return sealed_mapping(body)


def query(owner, unit_ref, operation, context, *, input_digest, expected_prompt_input_digest, allow_absent=False):
    if type(allow_absent) is not bool:
        refuse("Explicit boolean absent-receipt policy required")
    if input_digest != owner.acp_turn_query_digest(unit_ref, operation, expected_prompt_input_digest):
        refuse('ACP query input differs from authorized exact read request')
    unit = owner.resolve_unit_reference(unit_ref, context, input_digest=input_digest)
    with owner.journal._connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='harness_acp_turn_attempts'").fetchone():
            refuse('ACP durable schema unavailable')
        body = _read(owner, db, operation)
        if body is None and allow_absent:
            return None  # Authorized absence; never a receipt or dispatch permission.
        if body is None or body['unitRef']['unitId'] != unit.unit_ref:
            refuse('Original ACP operation not found on this Unit')
        if body['inputDigest'] != expected_prompt_input_digest:
            refuse('ACP prompt input digest differs from original operation')
        return sealed_mapping(body)
