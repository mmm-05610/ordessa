"""One real DeepSeek operation through Product, public Units and original records.

Only a fresh private cache root is allowed. Credentials are selected by name
from the existing approved source and read only by the original spawn binding.
No Server listener, Engineering Work, backend policy change or automatic retry.

Reporting stays finite: the raw receipt DTO is reduced to the declared
`RECEIPT_FIELDS`, a failure is reduced to a bounded category plus a fixed
summary (never the raw error text, module path, process environment or
configuration), and the original operation ref is written next to the fresh
root before the prompt is sent so a lost final output is still reconcilable.
Nothing here retries a prompt, switches provider or substitutes an authority.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any
from uuid import uuid4
from ordessa_infrastructure.encoding.immutable_json import safe_json

ROOT = Path(__file__).resolve().parents[3]
BRIDGE = Path('/tmp/ordessa-unit-live-acp-20261012-reproduced')
PI = Path('/home/maoqh/.local/bin/pi')
BRIDGE_SHA = '5a2f8f008fdf6fdf274d99f358c37477d8bcf8c4bfacf8cefef2630ef12d1c84'
SOURCE = '/home/maoqh/projects/ordessa/.env'
PROVIDER, MODEL, ENDPOINT = 'deepseek', 'deepseek-flash', 'https://api.deepseek.com'
VARIABLE = 'DEEPSEEK_API_KEY'
RETRY = {'enabled': False, 'maxRetries': 0,
         'provider': {'maxRetries': 0, 'maxRetryDelayMs': 0}}
ACTIONS = frozenset({'prepare', 'start', 'interaction', 'stop', 'release'})
TEXT_PROMPT = 'Reply only UNIT_OK. Do not use tools.'
FILE_PROMPT = ("In the current working directory, create a file named unit-smoke.txt "
    "containing exactly ordessa-unit-ok followed by a newline. Use a file writing tool "
    "to perform this single change. Do not read or modify any other file. "
    "After the write succeeds reply only UNIT_OK.")

# Owner budgets for the two encodings this diagnostic performs: the raw receipt
# read back from the original records, and the finite result it reports.
RECEIPT_MAX_BYTES = 2 * 1024 * 1024
RESULT_MAX_BYTES = 128 * 1024

# The declared finite projection of an original receipt DTO. Anything not named
# here is dropped, so a receipt growing a new field cannot widen this report.
RECEIPT_FIELDS = ('state', 'operation_ref', 'input_digest', 'receipt_sha256',
    'request_frame_digest', 'response_digest', 'event_count',
    'successful_rpc_response', 'model_text_matches_ok', 'model_text_bytes',
    'native_error_code', 'known_remote_failure')

# A failure is reported as one of these bounded categories plus a fixed summary
# text. The raw error text is never reported: it can carry paths, provider
# endpoints, request material or configured values.
ERROR_CATEGORIES = (('timeout', (TimeoutError,)), ('connection', (ConnectionError,)),
    ('permission', (PermissionError,)), ('missing_field', (KeyError,)),
    ('invalid_input', (ValueError,)), ('runtime', (RuntimeError,)))
ERROR_SUMMARIES = {'timeout': 'Timeout error', 'connection': 'Connection error',
    'permission': 'Permission error', 'missing_field': 'Missing receipt field',
    'invalid_input': 'Invalid value', 'runtime': 'Runtime error',
    'unexpected': 'Unclassified error'}
_CLASS_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]{0,63}')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def bounded(fields: Mapping[str, Any], order: Sequence[str]) -> dict:
    """Project a mapping onto the declared field list, in that order.

    This is the finite-projection primitive: undeclared keys cannot leak, and a
    declared key that is missing raises (KeyError) instead of silently reading
    as absent.
    """
    return {field: fields[field] for field in order}


def error_class_name(error: BaseException) -> str:
    """A bounded class identifier, never a module path, message or attribute."""
    name = type(error).__qualname__.rsplit('.', 1)[-1]
    return name if _CLASS_NAME.fullmatch(name) else 'UnclassifiedError'


def error_summary(error: BaseException) -> dict:
    """Reduce a caught error to a category, a fixed summary and a class name."""
    category = 'unexpected'
    for name, types in ERROR_CATEGORIES:
        if isinstance(error, types):
            category = name
            break
    return {'error_category': category, 'error_summary': ERROR_SUMMARIES[category],
        'error_class': error_class_name(error)}


def operation_reference(root: Path) -> str:
    """The original ref, reconstructible from the fresh root alone.

    It is never an instruction to resend: a pending or unknown operation is
    reconciled by reading this same ref, not by issuing a new one.
    """
    return 'unit-probe/' + digest(str(root).encode())[:40]


def build_operation_intent(unit_ref: Mapping[str, Any], operation_ref: str,
                           input_digest: str, params: Mapping[str, Any]) -> dict:
    return {'unit_ref': unit_ref, 'operation_ref': operation_ref,
        'input_digest': input_digest, 'params': params,
        'provider': PROVIDER, 'model': MODEL}


def save_operation_reference(path: Path, intent: Mapping[str, Any]) -> None:
    """Write the original ref beside the fresh root before any prompt is sent."""
    path.write_text(json.dumps(intent, indent=2) + '\n')
    os.chmod(path, 0o600)


def encode_receipt(body: Mapping[str, Any]) -> bytes:
    """Canonical bytes of the original receipt DTO under the receipt budget."""
    return safe_json(body, max_bytes=RECEIPT_MAX_BYTES).encode()


def project_receipt(body: Mapping[str, Any], *, operation_ref: str, input_digest: str,
                    encoded: bytes | None = None) -> dict:
    """Reduce the original receipt DTO to the declared finite fields."""
    if encoded is None:
        encoded = encode_receipt(body)
    if body['operationRef'] != operation_ref or body['inputDigest'] != input_digest:
        raise RuntimeError('Original receipt correlation differs')
    summary, response = body.get('summary') or {}, body.get('response') or {}
    text = summary.get('text', '')
    fields = {'state': body['state'], 'operation_ref': operation_ref,
        'input_digest': input_digest, 'receipt_sha256': digest(encoded),
        'request_frame_digest': body['request']['frameDigest'],
        'response_digest': body.get('responseDigest'),
        'event_count': len(body['events']),
        'successful_rpc_response': summary.get('successfulRpcResponse'),
        'model_text_matches_ok': text.strip() == 'UNIT_OK',
        'model_text_bytes': len(text.encode()),
        'native_error_code': (response.get('error') or {}).get('code'),
        'known_remote_failure': summary.get('knownRemoteFailure')}
    return bounded(fields, RECEIPT_FIELDS)


def initial_result() -> dict:
    """The fixed outer shape of the reported result."""
    return {'started_at': datetime.now(timezone.utc).isoformat(), 'provider': PROVIDER,
        'model': MODEL, 'endpoint': ENDPOINT, 'credential_variable': VARIABLE,
        'status': 'UNKNOWN', 'prompt_attempts': 0, 'retry': RETRY,
        'environment_provider': 'local', 'isolation': 'none',
        'outside_directory_denial_verified': False, 'engineering_grant_created': False}


def serialize_result(result: Mapping[str, Any]) -> str:
    """Canonical result text; a value the encoder rejects keeps a bounded record."""
    try:
        return safe_json(result, max_bytes=RESULT_MAX_BYTES)
    except Exception as error:
        return safe_json({'status': 'UNKNOWN', 'result_serialization': error_summary(error),
            'operation_ref': result.get('operation_ref'), 'unit_ref': result.get('unit_ref'),
            'started_at': result.get('started_at')}, max_bytes=RESULT_MAX_BYTES)


def save_result(path: Path, text: str) -> None:
    path.write_text(text + '\n')
    os.chmod(path, 0o600)


def compose(root, *, file_operation=False):
    from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
    from ordessa_environments_local import LocalEnvironmentResourceProvider
    from ordessa_agents.profiles import ProfileService
    from ordessa_units.bindings.profile_admission import UnitProfileAdmission
    from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
    from ordessa_units.assembly import UnitRunPermission
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
    from ordessa_interfaces.system_access.contracts.refs import Scope
    from ordessa_server.composition.configuration.product_selection import create_host_product_composition
    from ordessa_server.composition.product_native_configuration import construct_pi_harness_declaration
    from ordessa_server.composition.pi_selection import PiExecutionSelection, PiExecutionPorts
    from ordessa_server.composition.product_runtime import build_product_runtime

    fingerprint = ProtectedFingerprintHmac({'process-only': os.urandom(32)}, active_key_id='process-only')
    setup = create_host_product_composition(fingerprint_port=fingerprint).default_runtime(root / 'product')
    try:
        namespace = setup.unit_runtime.context.environment_namespace
        declaration = construct_pi_harness_declaration(setup,
            bridge_executable=BRIDGE, pi_executable=PI)
        profiles = ProfileService(UnitProfileAdmission(setup.unit_runtime.context))
        profile = profiles.create(profile_id='deepseek-unit-' + uuid4().hex,
            name='DeepSeek public Unit diagnostic', content={'schemaVersion': '1',
                'harnessDefinitionRef': dict(declaration.descriptor.definition_ref),
                'declarations': [{'declarationId': 'selected-model',
                    'configurationKind': 'assets.model-provider', 'schemaVersion': '1',
                    'action': 'value', 'requirement': 'required',
                    'payload': {'provider': PROVIDER, 'model': MODEL, 'protocol': 'openai-chat',
                        'endpoint': ENDPOINT, 'requestParams': {'retry': RETRY}}}]},
            request=profiles.request_key('create-deepseek-unit'))
        profile_ref = profile.current_revision
    finally:
        setup.stop()
    workdir = root / 'workspace'
    workdir.mkdir(mode=0o700)
    store = SQLiteEnvironmentStore(root / 'environments.sqlite')
    environments = EnvironmentManager(store=store,
        providers={'local': LocalEnvironmentResourceProvider(default_root=str(workdir))})
    environment = environments.register('local', str(workdir))
    scope = Scope(namespace, 'deepseek-unit-probe')

    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        authority = runtime.wire.identity_authority
        authority.replace_grants((AccessGrant(scope,
            tuple('execution.units.' + action for action in sorted(ACTIONS))),))
        principal = authority.authenticate('Bearer ' + runtime.token)
        return UnitRunPermission(access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity, root_directory=str(workdir),
            actions=ACTIONS, expires_at=time.time() + 600)

    model = {'id': MODEL, 'name': 'DeepSeek V4.1 Flash (explicit bounded diagnostic)',
        'provider': PROVIDER, 'api': 'openai-completions', 'baseUrl': ENDPOINT,
        'reasoning': False, 'input': ['text'], 'contextWindow': 1000000, 'maxTokens': 512,
        'samplingParams': {'thinking': {'type': 'disabled'}},
        'compat': {'supportsStore': False, 'supportsDeveloperRole': False,
            'maxTokensField': 'max_tokens', 'supportsStrictMode': True,
            'requiresReasoningContentOnAssistantMessages': True, 'thinkingFormat': 'deepseek'},
        'cost': {'input': 0.3, 'output': 1.2, 'cacheRead': 0.006, 'cacheWrite': 0}}
    selection = PiExecutionSelection('deepseek-unit-agent', profile_ref, environment.identity,
        'local', 'none', True, 'selected-model', PROVIDER, MODEL,
        str(BRIDGE), BRIDGE_SHA, str(PI), SOURCE)
    ports = PiExecutionPorts(environments, declaration, fingerprint, permission_factory,
        (MODEL,), model, acp_turn_opt_in=True, credential_environment_variable=VARIABLE)
    if file_operation:
        from dataclasses import replace
        from ordessa_server.composition.unit_file_callback_approval import UnitFileCallbackApproval
        def approval_factory(*, runtime, permission, environment_instance):
            return UnitFileCallbackApproval(runtime=runtime, permission=permission,
                environment_instance=environment_instance, allowed_relative_paths=('unit-smoke.txt',))
        ports = replace(ports, callback_approval_factory=approval_factory)
    runtime = build_product_runtime(root / 'product', pi_selection=selection, pi_ports=ports)
    return runtime, environment, workdir


def query(owner, unit_ref, operation_ref, params, label):
    from ordessa_infrastructure.identifiers import RequestKey
    records = owner.records
    prompt_digest = records.acp_prompt_input_digest(unit_ref, params)
    request = RequestKey(owner.admission.environment_namespace, owner.permission.principal_scope,
        'probe-read-' + label + '-' + uuid4().hex[:16])
    invocation = owner.authorize_acp_turn_query(owner.authorization(), request,
        unit_ref, operation_ref, expected_prompt_input_digest=prompt_digest)
    raw = records.query_acp_turn(unit_ref, operation_ref, invocation,
        input_digest=records.acp_turn_query_digest(unit_ref, operation_ref, prompt_digest),
        expected_prompt_input_digest=prompt_digest)
    encoded = encode_receipt(raw)
    return project_receipt(json.loads(encoded), operation_ref=operation_ref,
        input_digest=prompt_digest, encoded=encoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--run-once', action='store_true')
    parser.add_argument('--file-operation', action='store_true')
    args = parser.parse_args()
    root = args.root.absolute()
    if root.parent.resolve() != (ROOT / '.nightly-cache').resolve() or root.is_symlink():
        raise SystemExit('Only a fresh direct private cache child is allowed')
    root.mkdir(mode=0o700, exist_ok=False)
    output = initial_result()
    runtime = unit = interaction = None
    try:
        runtime, environment, workdir = compose(root, file_operation=args.file_operation)
        owner = runtime.unit_execution_owner
        with owner.permission.guard('prepare'):
            output['permission_preflight'] = True
        if not args.run_once:
            output['status'] = 'PREFLIGHT_READY'
            return 0
        runtime.start()
        unit = runtime.units.create(owner.spec, owner.authorization())
        snapshot = unit.snapshot()
        unit_ref = json.loads(safe_json(unit.identity))
        output.update(unit_ref=unit_ref, unit_state=snapshot['state'])
        paths = list(workdir.rglob('models.json'))
        if len(paths) != 1:
            raise RuntimeError('Exactly one original Unit model configuration required')
        configured = json.loads(paths[0].read_text())['providers'][PROVIDER]
        if (configured['baseUrl'] != ENDPOINT or configured['apiKey'] != '$' + VARIABLE
                or configured['models'][0]['id'] != MODEL
                or json.loads(paths[0].with_name('settings.json').read_text()).get('retry') != RETRY):
            raise RuntimeError('Unit-private route or retry configuration differs')
        output['unit_private_route_verified'] = True
        prompt = FILE_PROMPT if args.file_operation else TEXT_PROMPT
        params = {'prompt': [{'type': 'text', 'text': prompt}], 'sessionId': snapshot['sessionId']}
        # The caller can reconstruct this ref from its fresh root even if this
        # diagnostic loses its final output. It is never an instruction to resend.
        operation_ref = operation_reference(root)
        output['operation_ref'] = operation_ref
        intent = build_operation_intent(unit_ref, operation_ref,
            owner.records.acp_prompt_input_digest(unit.identity, params), params)
        save_operation_reference(root / 'operation-reference.json', intent)
        interaction = unit.interaction(owner.authorization())
        output['prompt_attempts'] = 1
        try:
            interaction.prompt(params, timeout=90, operation_ref=operation_ref)
        except Exception as error:
            output['prompt_error'] = error_summary(error)
        receipt = query(owner, unit.identity, operation_ref, params, 'initial')
        output['receipt'] = receipt
        interaction.disconnect()
        interaction = None
        cold = query(owner, unit.identity, operation_ref, params, 'disconnected')
        output['disconnected_read_same_receipt'] = cold == receipt
        original = owner.records.owner_read_unit(unit.identity['unitId'])
        target = Path(original.facts['privateRootFacts']['cwd']) / 'unit-smoke.txt'
        output['file_artifact'] = ({'relative_path': 'unit-smoke.txt',
            'sha256': digest(target.read_bytes()), 'byte_length': target.stat().st_size,
            'expected_bytes': target.read_bytes() == b'ordessa-unit-ok\n'} if target.is_file() else None)
        passed = (receipt['state'] == 'completed' and receipt['successful_rpc_response'] is True
            and receipt['model_text_matches_ok'] and cold == receipt
            and (not args.file_operation or bool(output['file_artifact']
                                                and output['file_artifact']['expected_bytes'])))
        output['status'] = 'COMPLETED' if passed else ('FAILED' if receipt['state'] in {'failed', 'completed'} else 'UNKNOWN')
        return 0 if passed else 1
    except Exception as error:
        output['failure'] = error_summary(error)
        output['status'] = 'FAILED_BEFORE_PROMPT' if output['prompt_attempts'] == 0 else 'UNKNOWN'
        return 2 if output['prompt_attempts'] == 0 else 1
    finally:
        if interaction is not None:
            interaction.disconnect()
        if unit is not None:
            try:
                output['unit_close'] = unit.close(runtime.unit_execution_owner.authorization()).get('state')
                output['environment_active_uses'] = environment.snapshot.active_uses
            except Exception as error:
                output['cleanup_error'] = error_summary(error)
        if runtime is not None:
            try:
                runtime.stop()
                output['runtime_stopped'] = True
            except Exception as error:
                output['runtime_stopped'] = False
                output['runtime_stop_error'] = error_summary(error)
        output['finished_at'] = datetime.now(timezone.utc).isoformat()
        text = serialize_result(output)
        save_result(root / 'receipt.json', text)
        print(text)


if __name__ == '__main__':
    raise SystemExit(main())
