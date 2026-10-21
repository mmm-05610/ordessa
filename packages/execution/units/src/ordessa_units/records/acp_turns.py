"""ACP facts in the original UnitRecords journal; no independent authority."""
import hashlib
import json

from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping
from ordessa_infrastructure.encoding.canonical_json import CanonicalJSONError

# A receipt retains the exact input, SDK request and original native frame,
# followed by bounded observations and the derived summary. The complete prompt
# is bounded to 576KiB. Three 12KB documents streamed in native four-byte chunks
# measure 4.39MB including the real full-material input/frame. Retain those
# original events within a finite 8MiB receipt; prompt/request limits stay fixed.
MAX_EVIDENCE_BYTES = 8388608
# The complete-material fixture, including the full admitted review, measures
# 535839 prompt bytes and 1661107 request-receipt bytes. These separate finite
# gates preserve that input and leave at least 768KiB for output evidence.
MAX_REQUEST_EVIDENCE_BYTES = 1835008
MAX_PROMPT_BYTES = 589824
MAX_REQUEST_ID_BYTES = 256



ACP_SCHEMA_SQL = """CREATE TABLE harness_acp_turn_attempts (
            operation_ref TEXT PRIMARY KEY, unit_ref TEXT NOT NULL,
            state TEXT NOT NULL, revision INTEGER NOT NULL,
            body_json TEXT NOT NULL, body_digest TEXT NOT NULL,
            FOREIGN KEY(unit_ref) REFERENCES harness_unit_reservations(unit_ref))"""

def _json(value, *, max_bytes=MAX_EVIDENCE_BYTES):
    try:
        return safe_json(value, max_bytes=max_bytes)
    except CanonicalJSONError as error:
        if error.reason == 'size':
            from .unit_records import AcpEvidenceCapacityRefused
            raise AcpEvidenceCapacityRefused('Complete ACP evidence capacity exceeded') from error
        raise


def refuse(message):
    from .unit_records import UnitRecordsRefused
    raise UnitRecordsRefused(message)


def digest(value):
    # The wrapper adds exactly ten bytes; it is not part of the stored receipt.
    return 'sha256:' + hashlib.sha256(_json({'value':value}, max_bytes=MAX_EVIDENCE_BYTES + 10).encode()).hexdigest()


def initialize(owner):
    with owner.journal._connect() as db:
        db.execute(ACP_SCHEMA_SQL)


def _provenance(owner, db, row, body, *, query_unit=None):
    # Only query() supplies this immutable identity, after the original query
    # verifier succeeds. Every mutation still resolves through the live fence.
    unit = owner._unit(db, row['unit_ref']) if query_unit is None else query_unit
    session = db.execute('SELECT * FROM harness_unit_sessions WHERE unit_ref=?', (row['unit_ref'],)).fetchone()
    from .unit_records import _digest
    if (unit.unit_ref != row['unit_ref']
            or safe_json(unit.public_ref) != safe_json(body['unitRef']) or _digest(unit.intent_json) != body['unitIntentDigest']
            or session is None or session['state'] != 'confirmed'
            or _digest(session['native_json']) != session['native_digest']
            or safe_json(body['nativeBinding']) != session['native_json']):
        refuse('ACP operation original Unit/session provenance differs')
    return unit


def _check(owner, db, row, *, query_unit=None):
    if row is None:
        return None
    body = json.loads(row['body_json'])
    if digest(body) != row['body_digest'] or _json(body) != row['body_json']:
        refuse('ACP operation content integrity differs')
    if (body['contractVersion'] not in {'unit-acp-turn/1', 'unit-acp-turn/2'}
            or body['operationRef'] != row['operation_ref'] or body['unitRef']['unitId'] != row['unit_ref']
            or body['state'] != row['state'] or body['revision'] != row['revision']
            or type(body['revision']) is not int or body['revision'] < 1
            or body['state'] not in {'reserved', 'possibly-written', 'completed', 'failed', 'unknown'}):
        refuse('ACP operation identity/state integrity differs')
    unit = _provenance(owner, db, row, body, query_unit=query_unit)
    if (digest(body['input']) != body['inputDigest'] or body['input']['unitRef'] != body['unitRef']
            or body['input']['params'].get('sessionId') != body['nativeBinding']['sessionId']):
        refuse('ACP operation input integrity differs')
    if body['contractVersion'] == 'unit-acp-turn/2':
        _validate_managed(unit, body['operationRef'], body['input']['params'], body['managedInput'])
    elif 'managedInput' in body:
        refuse('Historical ACP receipt cannot carry managed input evidence')
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
    encoded = _json(body)
    db.execute('UPDATE harness_acp_turn_attempts SET state=?,revision=?,body_json=?,body_digest=? WHERE operation_ref=?',
               (body['state'], body['revision'], encoded, digest(body), body['operationRef']))


def _read(owner, db, operation, *, query_unit=None):
    from .unit_records import UnitRecordsRefused
    try:
        return _check(owner, db, db.execute('SELECT * FROM harness_acp_turn_attempts WHERE operation_ref=?', (operation,)).fetchone(),
                      query_unit=query_unit)
    except UnitRecordsRefused:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise UnitRecordsRefused('ACP evidence structure integrity invalid') from error


def _validate_managed(unit, operation, params, binding):
    from ordessa_infrastructure.identifiers import RequestKey
    from ordessa_units.channels.acp_input import ManagedAcpCapture, BINDING_VERSION, operation_reference
    from ordessa_units.channels.reservations import CapturedInputRef
    from ordessa_units.channels.contracts import EXECUTION_EVIDENCE_VERSION
    from ordessa_agents.profiles import decode_revision_ref
    try:
        fields = {'contractVersion', 'request', 'capturedInputRef', 'contentDigest', 'unitRef',
                  'nodeRef', 'providerRef', 'managementEpoch', 'profileRevision',
                  'nativeSessionId', 'issuerRef', 'workspaceExecutionEvidence'}
        request = binding['request']
        captured = binding['capturedInputRef']
        ref = CapturedInputRef(captured['environmentNamespace'], captured['captureId'],
                               captured['captureRevision'], captured['contentDigest'])
        namespace = unit.public_ref['environmentNamespace']
        execution = binding['workspaceExecutionEvidence']
        expected_execution = {'contractVersion': EXECUTION_EVIDENCE_VERSION,
            'environmentNamespace': namespace, 'principalScope': request['principalScope'],
            'nodeRef': unit.facts['nodeRef'], 'unitRef': unit.public_ref, 'operationRef': operation,
            'captureRef': captured, 'contentDigest': ref.content_digest,
            'managementEpoch': unit.facts['managementEpoch'], 'evidenceRef': execution['evidenceRef']}
        if (set(binding) != fields or binding['contractVersion'] != BINDING_VERSION
                or set(request) != {'environmentNamespace', 'principalScope', 'requestId'}
                or request['environmentNamespace'] != namespace or ref.environment_namespace != namespace
                or captured != ref.to_dict() or binding['contentDigest'] != ref.content_digest
                or operation_reference(RequestKey(namespace, request['principalScope'], request['requestId'])) != operation
                or safe_json(binding['unitRef']) != safe_json(unit.public_ref)
                or safe_json(binding['nodeRef']) != safe_json(unit.facts['nodeRef'])
                or safe_json(binding['providerRef']) != safe_json(unit.facts['providerRef'])
                or type(binding['managementEpoch']) is not int
                or binding['managementEpoch'] != unit.facts['managementEpoch']
                or binding['nativeSessionId'] != params['sessionId']
                or decode_revision_ref(dict(binding['profileRevision'])).environment_namespace != namespace
                or binding['issuerRef'].get('environmentNamespace') != namespace
                or not binding['issuerRef'].get('issuerId') or not binding['issuerRef'].get('permissionId')
                or not isinstance(execution['evidenceRef'], str) or not execution['evidenceRef']
                or safe_json(execution) != safe_json(expected_execution)):
            refuse('Managed ACP capture/Workspace/original Unit identity differs')
        ManagedAcpCapture(ref, binding['nodeRef'], binding['unitRef'],
                         {key: value for key, value in params.items() if key != 'sessionId'}).verify_digest()
    except Exception as error:
        from .unit_records import UnitRecordsRefused
        if isinstance(error, UnitRecordsRefused):
            raise
        raise UnitRecordsRefused('Managed ACP input binding integrity differs') from error


def _new_body(owner, db, unit_ref, operation, params, managed_input=None):
    _json(params, max_bytes=MAX_PROMPT_BYTES)
    unit = owner._unit(db, unit_ref['unitId'])
    if safe_json(unit.public_ref) != safe_json(unit_ref):
        refuse('Complete original Unit reference differs')
    binding = owner._binding(db, unit.unit_ref)
    if binding.state != 'confirmed' or params.get('sessionId') != binding.native_facts['sessionId']:
        refuse('Original confirmed ACP session required')
    inputs = {'unitRef':dict(unit_ref), 'params':params}
    body = {'contractVersion':'unit-acp-turn/1', 'operationRef':operation, 'unitRef':dict(unit_ref),
            'unitIntentDigest':hashlib.sha256(unit.intent_json.encode()).hexdigest(), 'nativeBinding':dict(binding.native_facts),
            'input':inputs, 'inputDigest':digest(inputs), 'state':'reserved', 'revision':1,
            'request':None, 'events':[], 'eventsDigest':digest([]), 'response':None,
            'responseDigest':digest(None), 'observationAssociation':'session-request-window',
            'summary':None}
    if managed_input is not None:
        # The metadata is part of this same reservation COMMIT, never a native
        # ACP field, second journal or independently completed attempt.
        managed_input = json.loads(_json(managed_input))
        _validate_managed(unit, operation, params, managed_input)
        body.update(contractVersion='unit-acp-turn/2', managedInput=managed_input)
    return unit, body


def _request(raw):
    # The SDK owns the actual RPC ID. Preflight reserves this finite maximum;
    # the actual frame is checked again, without substituting another ID.
    _json({'id':raw.get('id')}, max_bytes=MAX_REQUEST_ID_BYTES + 7)
    frame = (json.dumps(raw, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n').encode()
    return {'raw':raw, 'frameUtf8':frame.decode(), 'frameDigest':'sha256:'+hashlib.sha256(frame).hexdigest()}


def _preflight(body):
    prospective = dict(body, state='possibly-written', revision=body['revision'] + 1)
    prospective['request'] = _request({'jsonrpc':'2.0', 'id':'r' * (MAX_REQUEST_ID_BYTES - 2),
                                      'method':'session/prompt', 'params':body['input']['params']})
    # At least 768KiB remains for events/response/summary. No request is
    # reserved or native byte written merely to discover an oversized envelope.
    _json(prospective, max_bytes=MAX_REQUEST_EVIDENCE_BYTES)


def validate_prompt_capacity(owner, unit_ref, params):
    with owner.journal._connect() as db:
        _, body = _new_body(owner, db, unit_ref, 'o' * 256, params)
        _preflight(body)


def reserve(owner, unit_ref, operation, params, *, managed_input=None):
    if not owner.acp_turn_available or not owner.journal.acp_turn_opt_in:
        refuse('ACP durable schema is unavailable; explicit pristine opt-in required')
    if not isinstance(operation, str) or not operation or len(operation) > 256 or any(ord(c) < 32 for c in operation):
        refuse('Explicit bounded ACP operation reference required')
    with owner.journal._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        unit, body = _new_body(owner, db, unit_ref, operation, params, managed_input)
        _preflight(body)
        if db.execute('SELECT 1 FROM harness_acp_turn_attempts WHERE operation_ref=?', (operation,)).fetchone():
            refuse('Original ACP operation already exists; no replay')
        if managed_input is not None:
            for row in db.execute('SELECT * FROM harness_acp_turn_attempts WHERE unit_ref=?', (unit.unit_ref,)):
                previous = _check(owner, db, row)
                if previous.get('managedInput', {}).get('capturedInputRef') == body['managedInput']['capturedInputRef']:
                    refuse('Original managed capture already submitted; read its original request')
        if db.execute("SELECT 1 FROM harness_acp_turn_attempts WHERE unit_ref=? AND state IN ('reserved','possibly-written','unknown')", (unit.unit_ref,)).fetchone():
            refuse('Original ACP operation unresolved; no new dispatch')
        db.execute('INSERT INTO harness_acp_turn_attempts VALUES (?,?,?,1,?,?)',
                   (operation, unit.unit_ref, 'reserved', _json(body), digest(body)))
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
        body['request'] = _request(raw)
        body['state'] = 'possibly-written'; body['revision'] += 1
        _write(db, body); db.commit()


def _private_encoding(value):
    # Only privately copied values already validated with the original JSON
    # profile reach this encoder. Its canonical representation is identical;
    # avoiding repeated Python validation of the unchanged prefix matters for
    # native ACP streams containing thousands of small deltas.
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False)
    raw = encoded.encode('utf-8')
    if len(raw) > MAX_EVIDENCE_BYTES:
        from .unit_records import AcpEvidenceCapacityRefused
        raise AcpEvidenceCapacityRefused('Complete ACP evidence capacity exceeded')
    return encoded, 'sha256:' + hashlib.sha256(b'{"value":' + raw + b'}').hexdigest()


def observe(owner, operation, raw):
    # SQLite serializes DB writers; this lock additionally serializes cache
    # publication/clearing. No uncommitted body or caller-owned alias is kept.
    with owner._acp_observation_lock, owner.journal._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM harness_acp_turn_attempts WHERE operation_ref=?', (operation,)).fetchone()
        cached = owner._acp_observation_cache
        if row is not None and cached is not None and tuple(row) == cached[0]:
            body = cached[1]
            unit = _provenance(owner, db, row, body)
            if body['contractVersion'] == 'unit-acp-turn/2':
                _validate_managed(unit, operation, body['input']['params'], body['managedInput'])
        else:
            body = _read(owner, db, operation)
        if body is None or body['state'] != 'possibly-written':
            refuse('ACP observation has no original dispatched operation')
        params = raw.get('params', {})
        matched = isinstance(params, dict) and params.get('sessionId') == body['nativeBinding']['sessionId']
        event = {'sequence':len(body['events'])+1, 'sessionMatched':matched, 'raw':raw}
        # Include the complete stored envelope AND digest wrapper: validating
        # raw alone would silently admit values one level deeper than _check.
        event = json.loads(_json({'value': {'events': [event]}},
                                 max_bytes=MAX_EVIDENCE_BYTES + 10))['value']['events'][0]
        params = event['raw'].get('params', {})
        event['sessionMatched'] = isinstance(params, dict) and params.get('sessionId') == body['nativeBinding']['sessionId']
        events = body['events'] + [event]
        _, events_digest = _private_encoding(events)
        prospective = dict(body, events=events, eventsDigest=events_digest, revision=body['revision']+1)
        encoded, body_digest = _private_encoding(prospective)
        db.execute('UPDATE harness_acp_turn_attempts SET state=?,revision=?,body_json=?,body_digest=? WHERE operation_ref=?',
                   (prospective['state'], prospective['revision'], encoded, body_digest, operation))
        db.commit()
        owner._acp_observation_cache = ((operation, row['unit_ref'], prospective['state'],
            prospective['revision'], encoded, body_digest), prospective)


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
    with owner._acp_observation_lock:
        try:
            return _finish(owner, operation, state, response)
        finally:
            # Terminal writes and cold reads always use the complete original
            # validation. Failed terminal validation cannot keep a stale cache.
            owner._acp_observation_cache = None


def _finish(owner, operation, state, response):
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
        return sealed_mapping(body, max_bytes=MAX_EVIDENCE_BYTES)


def query(owner, unit_ref, operation, context, *, input_digest, expected_prompt_input_digest):
    if input_digest != owner.acp_turn_query_digest(unit_ref, operation, expected_prompt_input_digest):
        refuse('ACP query input differs from authorized exact read request')
    resolver = getattr(owner, 'owner_read_unit_for_query', None)
    if not callable(resolver):
        refuse('Original query identity resolver unavailable')
    unit = resolver(unit_ref)
    from .unit_records import UnitReservation
    if type(unit) is not UnitReservation or safe_json(unit.public_ref) != safe_json(unit_ref):
        refuse('Unit reference differs from original owner source')
    # Historical identity alone grants nothing. Keep the exact original live
    # issuer/verifier, query-only action, current authority and epoch checks.
    owner._authorize(context, 'query', unit.facts['providerRef'], unit.facts['nodeRef'],
                     input_digest, query=True)
    with owner.journal._connect() as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='harness_acp_turn_attempts'").fetchone():
            refuse('ACP durable schema unavailable')
        # Re-read the immutable reservation under the same read snapshot as the
        # ACP row, so a stale projection cannot substitute another Unit source.
        row = db.execute('SELECT * FROM harness_unit_reservations WHERE unit_ref=?',
                         (unit.unit_ref,)).fetchone()
        if (row is None or (row['intent_json'], row['scope_json']) != (unit.intent_json, unit.scope_json)
                or row['intent_digest'] != hashlib.sha256(unit.intent_json.encode()).hexdigest()
                or row['correlation'] != unit.facts['correlation']
                or row['scope_key'] != safe_json({'environmentNamespace': unit.scope_ref.environment_namespace,
                                                 'scopeId': unit.scope_ref.scope_id})):
            refuse('ACP original Unit identity changed during query')
        body = _read(owner, db, operation, query_unit=unit)
        if body is None or body['unitRef']['unitId'] != unit.unit_ref:
            refuse('Original ACP operation not found on this Unit')
        if body['inputDigest'] != expected_prompt_input_digest:
            refuse('ACP prompt input digest differs from original operation')
        return sealed_mapping(body, max_bytes=MAX_EVIDENCE_BYTES)
