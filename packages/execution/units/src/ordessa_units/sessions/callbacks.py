"""Same-session ACP reverse requests over a bound environment and approval port.

The injected port is the deployment owner, never inferred from a DTO, Profile,
connection grant or machine identity. No default approval, host file access,
terminal fallback or external MCP sandbox claim is provided.
"""
import hashlib
import os
from collections.abc import Mapping

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping
from ordessa_units.lifecycle.unit_lifecycle import plain, UnitLifecycleRefused


class UnitCallbacks:
    def __init__(self, unit, approval):
        self.unit, self.approval = unit, approval
        self._seen = {}  # original channel request outcomes, never replay effects

    def capabilities(self):
        return {'fs': {'readTextFile': self.approval is not None,
                       'writeTextFile': self.approval is not None}, 'terminal': False}

    def _relative(self, path):
        if not isinstance(path, str) or not path or not os.path.isabs(path):
            raise UnitLifecycleRefused('ACP path must name the bound file area')
        files = self.unit.channel_factory.environment.files
        relative = os.path.relpath(path, files.root())
        files.path(relative)  # actual provider containment, including symlinks
        return relative

    def handle(self, message):
        raw = message.raw
        request_id, method = raw.get('id'), raw.get('method')
        params = raw.get('params', {})
        record = self.unit.channel_factory.owned_record
        client = record.entry
        if type(request_id) not in (str, int):
            raise UnitLifecycleRefused('Reverse request requires its original JSON-RPC identity')
        key = (type(request_id), request_id)
        digest = hashlib.sha256(safe_json(raw).encode()).hexdigest()
        if key in self._seen:
            prior, result, error = self._seen[key]
            if prior != digest:
                client.reply_request_error(request_id, code=-32602, message='Callback identity reused for another request')
            elif error:
                client.reply_request_error(request_id, **error)
            else:
                client.reply_request(request_id, result)
            return
        # Unknown is fixed before any effect. A lost effect/response never lets
        # the same channel request invoke a second write.
        error = {'code': -32603, 'message': 'Original callback outcome unknown; no replay'}
        self._seen[key] = (digest, None, error)
        result = None
        try:
            if (not isinstance(params, Mapping) or params.get('sessionId') != client.session_id
                    or record.process.observe().state != "running"):
                raise UnitLifecycleRefused('Callback belongs to another or unavailable Unit session')
            if method not in {'fs/read_text_file', 'fs/write_text_file', 'session/request_permission'}:
                error = {'code': -32601, 'message': 'Callback capability unavailable on this Unit'}
            elif self.approval is None:
                error = {'code': -32000, 'message': 'Original callback approval owner unavailable'}
            else:
                unit_ref = self.unit.records.owner_read_unit(self.unit._callback_unit_id).public_ref
                decision = self.approval.authorize(unit_ref=unit_ref, session_id=client.session_id,
                    environment_identity=record.environment_identity, request_id=request_id,
                    method=method, params=sealed_mapping(plain(params)))
                if method == 'session/request_permission':
                    options = params.get('options', [])
                    ids = {o.get('optionId') for o in options if isinstance(o, Mapping)}
                    if isinstance(decision, str) and decision in ids:
                        result = {'outcome': {'outcome': 'selected', 'optionId': decision}}
                    else:
                        result = {'outcome': {'outcome': 'cancelled'}}
                    error = None
                elif decision is not True:
                    error = {'code': -32000, 'message': 'Original callback approval refused'}
                else:
                    relative = self._relative(params.get('path'))
                    files = self.unit.channel_factory.environment.files
                    if method == 'fs/write_text_file':
                        files.write_text(relative, params.get('content'))
                        result = {}
                    else:
                        content = files.read_text(relative)
                        if len(content.encode('utf-8')) > 1024 * 1024:
                            raise UnitLifecycleRefused('File callback exceeds bounded UTF-8 limit')
                        line, limit = params.get('line', 1), params.get('limit')
                        if type(line) is not int or line < 1 or limit is not None and (type(limit) is not int or limit < 1):
                            raise UnitLifecycleRefused('Invalid bounded file line/limit')
                        result = {'content': ''.join(content.splitlines(keepends=True)[line-1:None if limit is None else line-1+limit])}
                    error = None
        except Exception:
            # Never report successful effect on denied/unavailable/lost outcome.
            # The raw exception may contain host/user data, so do not echo it.
            error = {'code': -32000, 'message': 'Callback refused or outcome unavailable; no replay'}
        self._seen[key] = (digest, result, error)
        if error:
            client.reply_request_error(request_id, **error)
        else:
            client.reply_request(request_id, result)
