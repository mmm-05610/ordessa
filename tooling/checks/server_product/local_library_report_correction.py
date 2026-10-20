"""Run one declared-report format correction against the original owner graph.

This module owns no authority. It never decides that a source is trusted, never
marks a journal row complete and never runs the business case or its checks. It
takes the three frozen RC1 collaborators as explicit arguments:

* ``service``  — the Engineering service exposing the frozen
  ``prepare_report_correction`` / ``complete_report_correction`` entry points;
* ``assembly`` — the read-only report-Unit assembly (create, capture, close);
* ``materials`` — the trusted read-only material port for the original rejected
  report and the preserved business artefacts.

Every refusal below is a *contract* refusal, not a judgement about a particular
Work: no Work id, parent id, operation id or byte count is hard-coded, so an
unrelated Work cannot be passed by naming it, and a matching Work cannot be
refused by naming it differently.

Nothing here starts a Unit unless the plan says ``created=True`` and
``state="ready"``, and nothing is sent twice: an existing pending claim is
reconciled read-only.
"""
from __future__ import annotations

import hashlib
import argparse
import asyncio
import importlib.util
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.common.models.values import Digest

PLAN_OPERATION_PREFIX = 'report-format-rework/'
PLAN_CONTRACT = 'ordessa.declared-report-format-rework-plan/1'
CHECKPOINT_CONTRACT = 'ordessa.declared-report-format-rework/1'
RULE = 'remove-json-object-type-only'
PREPARE_KEYS = frozenset({'plan_ref', 'operation_ref', 'created', 'state', 'params', 'submission_ref'})
STATES = frozenset({'ready', 'pending_query_only', 'report_registered'})
CORRECTION_KEYS = frozenset({'unit_ref', 'operation_ref', 'prompt_input_digest',
    'observation_ref', 'observation_revision', 'output_ref', 'stop_record_digest',
    'release_record_digest'})
SELECTOR_KEYS = frozenset({'parent_operation_id', 'execution_operation_ref',
    'expected_parent_version', 'expected_dispatch_version', 'expected_observation_revision'})
EVIDENCE_CHECK_KEYS = frozenset({'origin_operation_ref', 'journal_ref', 'excerpt_ref',
    'tool_call_id', 'command_digest', 'limitation'})
SUBMISSION_REF_KEYS = frozenset({'realm_id', 'project_id', 'submission_id', 'digest', 'kind'})
LIMITATION = ('selected original Pi journal observation; '
              'not independently authenticated execution proof')
ROOT = Path(__file__).resolve().parents[3]
NIGHTLY = ROOT / '.nightly-cache'
SOURCE_PIN_PATHS = (
    'apps/server/src/ordessa_server/composition/report_rework_budget.py',
    'apps/server/src/ordessa_server/composition/report_rework_approval.py',
    'apps/server/src/ordessa_server/composition/conversation_attestor.py',
    'plugins/harness/pi/src/ordessa_harness_pi/acp/request-budget.mjs',
    'plugins/harness/pi/pyproject.toml',
    'packages/engineering/src/ordessa_engineering/application/orchestration/report_only_disposition.py',
    'packages/engineering/src/ordessa_engineering/application/orchestration/declared_implementation_results.py',
    'packages/engineering/src/ordessa_engineering/application/orchestration/steps/declared_implementation_dispatch.py',
    'packages/engineering/src/ordessa_engineering/adapters/native_records/declared_review_runtime.py',
    'tooling/checks/server_product/local_library_report_correction.py',
    'tooling/checks/server_product/run_declared_work_case.py',
    'tooling/checks/server_product/local_library_instruction_case.py',
    'tooling/checks/server_product/probe-work-package-generation.py',
    'apps/server/src/ordessa_server/composition/engineering_declared_work_case_assembly.py',
    'apps/server/src/ordessa_server/composition/unit_file_callback_approval.py',
    'apps/server/src/ordessa_server/composition/agent_owner.py',
    'apps/server/src/ordessa_server/composition/pi_selection.py',
    'plugins/harness/pi/src/ordessa_harness_pi/acp_preparation.py',
    'apps/server/src/ordessa_server/composition/product_native_configuration.py',
    'packages/engineering/src/ordessa_engineering/application/api/service.py',
    'packages/engineering/src/ordessa_engineering/application/usecases/changes/declared_report.py',
    'packages/engineering/src/ordessa_engineering/application/usecases/changes/report_content_rework.py',
    'packages/engineering/src/ordessa_engineering/application/orchestration/report_content_rework.py',
    'packages/engineering/src/ordessa_engineering/application/assembly/submission_sources.py',
    'packages/engineering/src/ordessa_engineering/application/usecases/reviews/assignments.py',
    'packages/engineering/src/ordessa_engineering/application/assembly/reviewer_assignments.py',
    'packages/engineering/src/ordessa_engineering/domain/changes/submission.py',
    'packages/engineering/src/ordessa_engineering/adapters/native_records/declared_reviewer.py',
    'packages/execution/units/src/ordessa_units/assembly/local_owner.py',
    'packages/execution/units/src/ordessa_units/records/acp_turns.py',
    'packages/execution/units/src/ordessa_units/records/unit_records.py',
)


class CorrectionRefused(RuntimeError):
    """A bounded, non-secret refusal; the caller never gets a fabricated plan."""


def _digest_hex(value: Any) -> str:
    if (type(value) is not dict or set(value) != {'algorithm', 'hex'}
            or value['algorithm'] != 'sha256' or type(value['hex']) is not str
            or len(value['hex']) != 64
            or any(character not in '0123456789abcdef' for character in value['hex'])):
        raise CorrectionRefused('plan_ref digest shape is invalid')
    return value['hex']


def _blob_ref(value: Any) -> bool:
    """Recognize only the closed public BlobRef projection."""
    if type(value) is not dict or set(value) != {
            'digest', 'byte_length', 'media_type', 'storage_object_id'}:
        return False
    digest = value['digest']
    return (type(digest) is dict and set(digest) == {'algorithm', 'hex'}
            and digest['algorithm'] == 'sha256' and type(digest['hex']) is str
            and len(digest['hex']) == 64
            and all(character in '0123456789abcdef' for character in digest['hex'])
            and type(value['byte_length']) is int
            and value['byte_length'] >= 0 and type(value['media_type']) is str
            and bool(value['media_type']) and type(value['storage_object_id']) is str
            and bool(value['storage_object_id']))


def validate_review_successor_selector(value: Any) -> dict:
    """Validate the only CLI projection that may select a review successor."""
    if type(value) is not dict or set(value) != {'checkpoint_ref', 'predecessor_review'}:
        raise CorrectionRefused('successor selector must contain exactly checkpoint_ref and predecessor_review')
    checkpoint_ref = value['checkpoint_ref']
    predecessor = value['predecessor_review']
    keys = {'review_id', 'operation_ref', 'expected_observation_revision', 'observation_ref'}
    if not _blob_ref(checkpoint_ref):
        raise CorrectionRefused('checkpoint_ref is not an exact BlobRef projection')
    if (type(predecessor) is not dict or set(predecessor) != keys
            or type(predecessor['review_id']) is not str or not predecessor['review_id']
            or type(predecessor['operation_ref']) is not str or not predecessor['operation_ref']
            or type(predecessor['expected_observation_revision']) is not int
            or predecessor['expected_observation_revision'] < 0
            or not _blob_ref(predecessor['observation_ref'])):
        raise CorrectionRefused('predecessor_review is not the exact closed projection')
    return value


def _digest(value: Any) -> bool:
    return (type(value) is dict and set(value) == {'algorithm', 'hex'}
            and value['algorithm'] == 'sha256' and type(value['hex']) is str
            and len(value['hex']) == 64
            and all(character in '0123456789abcdef' for character in value['hex']))


def _contains_session_id(value: Any) -> bool:
    if isinstance(value, Mapping):
        return 'sessionId' in value or any(_contains_session_id(item) for item in value.values())
    if type(value) in (list, tuple):
        return any(_contains_session_id(item) for item in value)
    return False


def expected_operation_ref(plan_ref: Mapping[str, Any]) -> str:
    """The only admissible operation id: derived from the frozen plan digest."""
    return PLAN_OPERATION_PREFIX + _digest_hex(plan_ref.get('digest'))


def validate_prepare_result(result: Any) -> dict:
    """Accept exactly the frozen prepare projection; anything else is refused."""
    if type(result) is not dict or set(result) != PREPARE_KEYS:
        raise CorrectionRefused('prepare returned an unknown shape')
    if type(result['created']) is not bool or type(result['state']) is not str or result['state'] not in STATES:
        raise CorrectionRefused('prepare state is not a frozen value')
    plan_ref = result['plan_ref']
    if not _blob_ref(plan_ref):
        raise CorrectionRefused('plan_ref is not a BlobRef projection')
    if result['operation_ref'] != expected_operation_ref(plan_ref):
        raise CorrectionRefused('operation_ref does not derive from the plan digest')
    if (result['created'] != (result['state'] == 'ready')):
        raise CorrectionRefused('created flag does not match the frozen plan state')
    if result['created'] and result['state'] == 'ready':
        params = result['params']
        if (type(params) is not dict or set(params) != {'prompt'}
                or type(params['prompt']) is not list or len(params['prompt']) != 1
                or type(params['prompt'][0]) is not dict
                or set(params['prompt'][0]) != {'type', 'text'}
                or params['prompt'][0]['type'] != 'text'
                or type(params['prompt'][0]['text']) is not str
                or not params['prompt'][0]['text'] or _contains_session_id(params)):
            raise CorrectionRefused('ready plan has no native capture parameters')
        if result['submission_ref'] is not None:
            raise CorrectionRefused('ready plan already carries a submission')
    else:
        # A pending claim, an unreadable origin or an already registered report
        # must be reconciled read-only: no Unit, no send.
        if result['params'] is not None:
            raise CorrectionRefused('non-ready plan must not carry capture parameters')
        if result['state'] == 'pending_query_only' and result['submission_ref'] is not None:
            raise CorrectionRefused('pending query-only plan must not carry a submission')
        if result['state'] == 'report_registered':
            ref = result['submission_ref']
            if (type(ref) is not dict or set(ref) != SUBMISSION_REF_KEYS
                    or any(type(ref[name]) is not str or not ref[name]
                           for name in ('realm_id', 'project_id', 'submission_id'))
                    or not _digest(ref['digest']) or ref['kind'] != 'submission'):
                raise CorrectionRefused('registered report has no exact submission reference')
    return result


@dataclass(frozen=True)
class Capture:
    """What the new read-only report Unit actually produced."""

    unit_ref: dict
    operation_ref: str
    output_bytes: bytes
    prompt_input_digest: dict
    observation_ref: dict
    observation_revision: int


def validate_capture(capture: Any, *, operation_ref: str) -> Capture:
    """Map the Server adapter's exact public projection into a local value."""
    if type(capture) is Capture:
        values = {name: getattr(capture, name) for name in Capture.__dataclass_fields__}
    elif isinstance(capture, Mapping):
        values = dict(capture)
    else:
        values = None
    if (values is None or set(values) != set(Capture.__dataclass_fields__)
            or type(values['unit_ref']) is not dict or not values['unit_ref']
            or values['operation_ref'] != operation_ref
            or type(values['output_bytes']) is not bytes or not values['output_bytes']
            or not _digest(values['prompt_input_digest'])
            or not _blob_ref(values['observation_ref'])
            or type(values['observation_revision']) is not int
            or values['observation_revision'] < 1):
        raise CorrectionRefused('native capture projection is invalid')
    return Capture(**values)


def _completion_payload(result: Any) -> Mapping[str, Any]:
    """Decode the Engineering owner's public CommandResult projection."""
    if getattr(result, 'status', None) != 'completed':
        raise CorrectionRefused('report-correction completion is not terminal')
    payload = getattr(result, 'result', None)
    if isinstance(payload, Mapping):
        return payload
    raw = getattr(result, 'result_bytes', None)
    if type(raw) is bytes:
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError) as error:
            raise CorrectionRefused('report-correction result payload is invalid') from error
        if isinstance(value, Mapping):
            return value
    raise CorrectionRefused('report-correction result payload is unavailable')


def build_checkpoint(*, plan_ref: Mapping[str, Any], capture: Capture,
                     closed: Mapping[str, Any]) -> dict:
    """Assemble the final ``Submission.checkpoint_ref`` payload.

    The rejected original bytes are preserved and referenced, never rewritten:
    this object only links the frozen plan to the new capture.
    """
    if (not _blob_ref(plan_ref) or type(closed) is not dict
            or set(closed) != {'stop_confirmed', 'release_confirmed',
            'output_ref', 'stop_record_digest', 'release_record_digest'}
            or closed.get('stop_confirmed') is not True
            or closed.get('release_confirmed') is not True
            or not _blob_ref(closed.get('output_ref'))
            or not _digest(closed.get('stop_record_digest'))
            or not _digest(closed.get('release_record_digest'))):
        raise CorrectionRefused('unit termination is not confirmed')
    output_ref = closed['output_ref']
    if (output_ref['digest']['hex'] != hashlib.sha256(capture.output_bytes).hexdigest()
            or output_ref['byte_length'] != len(capture.output_bytes)):
        raise CorrectionRefused('closed output reference does not match the captured bytes')
    correction = {
        'unit_ref': capture.unit_ref,
        'operation_ref': capture.operation_ref,
        'prompt_input_digest': capture.prompt_input_digest,
        'observation_ref': capture.observation_ref,
        'observation_revision': capture.observation_revision,
        'output_ref': closed.get('output_ref'),
        'stop_record_digest': closed.get('stop_record_digest'),
        'release_record_digest': closed.get('release_record_digest'),
    }
    if (set(correction) != CORRECTION_KEYS
            or not _blob_ref(correction['output_ref'])):
        raise CorrectionRefused('closed correction projection is invalid')
    return {
        'contract': CHECKPOINT_CONTRACT,
        'plan_ref': plan_ref,
        'correction': correction,
    }


def validate_inputs(*, invoke_parameters, origin, evidence, preserved_report):
    """Reject malformed RC1 inputs before reserving a claim or creating a Unit."""
    if (type(invoke_parameters) is not dict or set(invoke_parameters) != {
            'work_id', 'action_id', 'expected_revision', 'inputs'}
            or any(type(invoke_parameters[name]) is not str or not invoke_parameters[name]
                   for name in ('work_id', 'action_id'))
            or type(invoke_parameters['expected_revision']) is not int
            or invoke_parameters['expected_revision'] < 1
            or type(invoke_parameters['inputs']) is not dict
            or type(origin) is not dict or set(origin) != SELECTOR_KEYS
            or type(evidence) is not dict or set(evidence) != {'files', 'check'}):
        raise CorrectionRefused('original invoke parameters, selector, or evidence are invalid')
    if (type(origin['parent_operation_id']) is not str or not origin['parent_operation_id']
            or type(origin['execution_operation_ref']) is not str
            or not origin['execution_operation_ref']):
        raise CorrectionRefused('origin operation selectors are invalid')
    for name, minimum in (('expected_parent_version', 0),
                          ('expected_dispatch_version', 1),
                          ('expected_observation_revision', 1)):
        value = origin[name]
        if type(value) is not int or value < minimum:
            raise CorrectionRefused('origin version selectors are invalid')

    files, check = evidence['files'], evidence['check']
    if type(files) is not list or len(files) != 4:
        raise CorrectionRefused('original evidence file projection is invalid')
    if (type(check) is not dict
            or set(check) != EVIDENCE_CHECK_KEYS
            or check.get('origin_operation_ref') != origin['execution_operation_ref']
            or type(check.get('tool_call_id')) is not str or not check['tool_call_id']
            or check.get('limitation') != LIMITATION):
        raise CorrectionRefused('original evidence projection is invalid')
    seen = set()
    for item in files:
        if (type(item) is not dict or set(item) != {'path', 'blob_ref'}
                or type(item['path']) is not str or not item['path'].startswith('/')
                or str(Path(item['path'])) != item['path'] or '..' in Path(item['path']).parts
                or item['path'] in seen or not _blob_ref(item['blob_ref'])):
            raise CorrectionRefused('original evidence file projection is invalid')
        seen.add(item['path'])
    for name in ('journal_ref', 'excerpt_ref'):
        if not _blob_ref(check[name]):
            raise CorrectionRefused('original evidence reference is invalid')
    if not _digest(check['command_digest']):
        raise CorrectionRefused('original check command digest is invalid')

    if preserved_report is None:
        return None
    if not isinstance(preserved_report, Mapping) or set(preserved_report) != {
            'bytes', 'digest', 'length'}:
        raise CorrectionRefused('preserved rejected report projection is invalid')
    original = preserved_report.get('bytes')
    if (type(original) is not bytes
            or hashlib.sha256(original).hexdigest() != preserved_report.get('digest')
            or type(preserved_report.get('digest')) is not str
            or len(preserved_report['digest']) != 64
            or type(preserved_report.get('length')) is not int
            or len(original) != preserved_report['length']):
        raise CorrectionRefused('preserved rejected report does not match its own digest')
    return original


def validate_sources_config(value: Any, *, origin_operation_ref: str,
                            allowed_paths) -> dict:
    """Validate the only permitted journal/excerpt selector shape.

    Paths are finite operator selections, not import paths or factories. Their
    relationship to the original Unit and operation is re-established by the
    Server owner before returning bytes.
    """
    if (type(value) is not dict or set(value) != {
            'origin_operation_ref', 'original_journal', 'original_check_excerpt'}
            or value['origin_operation_ref'] != origin_operation_ref
            or type(origin_operation_ref) is not str or not origin_operation_ref):
        raise CorrectionRefused('source selector projection is invalid')
    selected_paths = set()
    normalized = {'origin_operation_ref': origin_operation_ref}
    for name in ('original_journal', 'original_check_excerpt'):
        item = value[name]
        if (type(item) is not dict or set(item) != {'path', 'digest'}
                or type(item['path']) is not str or not item['path'].startswith('/')
                or not _digest(item['digest'])
                or any(character not in '0123456789abcdef' for character in item['digest']['hex'])):
            raise CorrectionRefused('source selector projection is invalid')
        path = Path(item['path'])
        if (not path.is_absolute() or '..' in path.parts or path.resolve() != path
                or not path.is_file()
                or path.name == '.env' or path.name.startswith('.env.')
                or any(part.lower() in {'secrets', 'credentials'} for part in path.parts)
                or path.suffix.lower() in {'.key', '.pem', '.p12', '.pfx'}
                or any(part.is_symlink() for part in (path, *path.parents))):
            raise CorrectionRefused('source path is not a stable absolute file')
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise CorrectionRefused('selected source file is unavailable') from error
        if len(raw) > 8 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != item['digest']['hex']:
            raise CorrectionRefused('selected source file digest changed')
        selected_paths.add(str(path))
        normalized[name] = {'path': str(path), 'digest': dict(item['digest'])}
    if len(selected_paths) != 2:
        raise CorrectionRefused('source journal and excerpt must be distinct')
    try:
        scoped = tuple(Path(path) for path in allowed_paths)
    except (TypeError, ValueError) as error:
        raise CorrectionRefused('finite report read scope is invalid') from error
    if (len(scoped) != 4 or len({str(path) for path in scoped}) != 4
            or any(not path.is_absolute() or '..' in path.parts
                   or path.resolve() != path
                   or any(part.is_symlink() for part in (path, *path.parents))
                   for path in scoped)):
        raise CorrectionRefused('finite report read scope is invalid')
    # Source paths are not Unit repository reads; their operation binding is
    # re-established by the original owner before it returns bytes.
    return normalized


def validate_sources_bundle(value: Any, *, origin_operation_ref: str,
                            allowed_paths) -> dict:
    """Validate the finite CLI bundle before opening a graph or creating output."""
    if type(value) is not dict or set(value) != {'source_selection', 'origin', 'evidence'}:
        raise CorrectionRefused('source bundle projection is invalid')
    selection = validate_sources_config(value['source_selection'],
        origin_operation_ref=origin_operation_ref, allowed_paths=allowed_paths)
    validate_inputs(invoke_parameters={'work_id': 'preflight', 'action_id': 'preflight',
        'expected_revision': 1, 'inputs': {}}, origin=value['origin'],
        evidence=value['evidence'], preserved_report=None)
    if value['origin']['execution_operation_ref'] != origin_operation_ref:
        raise CorrectionRefused('source bundle operation differs from its origin selector')
    if {item['path'] for item in value['evidence']['files']} != set(allowed_paths):
        raise CorrectionRefused('evidence files differ from the frozen read-only path set')
    return {'source_selection': selection, 'origin': value['origin'],
            'evidence': value['evidence']}


def _load_fixed_module(name: str, path: Path):
    """Load only a repository-fixed case module, never a caller-selected import."""
    if not path.is_file() or path.is_symlink():
        raise CorrectionRefused('fixed report-correction module is unavailable')
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CorrectionRefused('fixed report-correction module is unavailable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _json_file(path: Path, expected_sha256: str | None = None) -> Any:
    if (not path.is_absolute() or path.is_symlink() or not path.is_file()
            or path.resolve() != path):
        raise CorrectionRefused('selected JSON input is not a stable absolute file')
    raw = path.read_bytes()
    if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise CorrectionRefused('selected JSON input digest changed')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise CorrectionRefused('selected JSON input is invalid') from error


def _cache_path(path: Path, *, must_exist: bool) -> Path:
    if (not path.is_absolute()
            or any(part.is_symlink() for part in (path, *path.parents))):
        raise CorrectionRefused('registered graph or output path must be absolute and stable')
    resolved = path.resolve(strict=must_exist)
    try:
        resolved.relative_to(NIGHTLY.resolve())
    except ValueError as error:
        raise CorrectionRefused('registered graph and output must remain under .nightly-cache') from error
    return resolved


def _source_manifest(path: Path, expected_sha256: str) -> dict:
    path = Path(path)
    if (not path.is_absolute() or path.is_symlink()
            or any(part.is_symlink() for part in (path, *path.parents))):
        raise CorrectionRefused('source manifest path is not stable')
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError as error:
        raise CorrectionRefused('source manifest must be inside the repository') from error
    manifest = _json_file(path, expected_sha256)
    if type(manifest) is not dict or set(manifest) != set(SOURCE_PIN_PATHS):
        raise CorrectionRefused('fixed source manifest projection is invalid')
    for relative, digest in manifest.items():
        if (type(digest) is not str or len(digest) != 64
                or any(character not in '0123456789abcdef' for character in digest)):
            raise CorrectionRefused('fixed source manifest digest is invalid')
        source = ROOT / relative
        if (source.is_symlink() or not source.is_file()
                or hashlib.sha256(source.read_bytes()).hexdigest() != digest):
            raise CorrectionRefused('fixed report-correction source changed')
    if manifest['tooling/checks/server_product/local_library_report_correction.py'] != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise CorrectionRefused('report-correction driver changed during startup')
    return manifest


def _safe_graph_manifest(graph: Path, case) -> dict:
    # Reopen the original owners in place. Their instance credential remains
    # owned by the product; it is never read, hashed or copied into this receipt.
    manifest = {}
    for candidate in graph.rglob('*'):
        relative = candidate.relative_to(graph)
        if candidate.is_symlink() or candidate.name == '.env':
            raise CorrectionRefused('registered graph contains a forbidden credential or symlink path')
        if relative.parts[:2] == ('product', 'secrets'):
            continue
        if (len(relative.parts) == 4 and relative.parts[0] == 'local-environment'
                and relative.parts[1].startswith('unit-')
                and relative.parts[2:] == ('profile', 'auth.json')):
            continue
        if 'secrets' in relative.parts:
            raise CorrectionRefused('registered graph contains an unexpected credential path')
        if candidate.is_file():
            manifest[relative.as_posix()] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if not manifest or any(type(name) is not str for name in manifest):
        raise CorrectionRefused('registered graph manifest is unavailable')
    return manifest


def _canonical_body(prepared: Mapping[str, Any], allowed_paths):
    params = prepared['params']
    text = params['prompt'][0]['text']
    try:
        body = json.loads(text)
    except (ValueError, UnicodeError) as error:
        raise CorrectionRefused('report-only native prompt body is invalid') from error
    required = {'instruction', 'report_correction_plan', 'plan_ref',
                'rejected_report_utf8', 'implementation_report_schema', 'allowed_read_paths'}
    if (type(body) is not dict or set(body) != required
            or type(body['instruction']) is not str or not body['instruction']
            or type(body['report_correction_plan']) is not dict
            or body['plan_ref'] != prepared['plan_ref']
            or body['allowed_read_paths'] != sorted(allowed_paths)
            or type(body['implementation_report_schema']) is not dict
            or type(body['rejected_report_utf8']) is not str
            or text != canonical_bytes(body).decode('utf-8')):
        raise CorrectionRefused('native prompt is outside the frozen report-only contract')
    original = body['rejected_report_utf8'].encode('utf-8')
    try:
        rejected = json.loads(original)
    except (ValueError, UnicodeError) as error:
        raise CorrectionRefused('preserved rejected report is not JSON') from error
    if type(rejected) is not dict or 'type' not in rejected:
        raise CorrectionRefused('preserved rejected report has no removable top-level type')
    preserved = {'bytes': original, 'digest': hashlib.sha256(original).hexdigest(),
                 'length': len(original)}
    return body, preserved


def _admit_original_parent(holder, origin):
    """Resolve and admit with the original journaled request key."""
    from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
    with holder['factory'].begin(holder['scope'], 'read') as uow:
        entry = uow.commands.find_operation(holder['scope'], origin['parent_operation_id'],
                                            operation='engineering.work.invoke')
    if entry is None or entry.state not in {'pending', 'completed'}:
        raise CorrectionRefused('original invoke journal entry is unavailable')
    request_id = entry.key.request_id
    wire_scope = WireScope(holder['wire_scope'].realm_id, holder['wire_scope'].project_id)
    return request_id, wire_scope, entry.state


def _stop_runtime(runtime, holder, case):
    if holder and not holder.get('_report_correction_disposed'):
        try:
            case.dispose(holder)
            holder['_report_correction_disposed'] = True
        finally:
            if runtime is not None:
                runtime.stop()
    elif runtime is not None:
        runtime.stop()


def recover_registered_graph(*, registration_path: Path, registration_sha256: str,
                             candidate_path: Path,
                             candidate_sha256: str, sources_config: Mapping[str, Any],
                             output: Path, source_manifest_path: Path,
                             source_manifest_sha256: str, run_report: bool) -> dict:
    """Run the three RC1 phases over the original registered graph owners.

    The caller must explicitly opt into the report flow with ``run_report``.
    This function has no snapshot, registration, Grant or business-dispatch path.
    """
    if run_report is not True:
        raise CorrectionRefused('explicit --run-report is required')
    _source_manifest(source_manifest_path, source_manifest_sha256)
    registration_path = _cache_path(Path(registration_path), must_exist=True)
    registration = _json_file(registration_path, registration_sha256)
    candidate_path = _cache_path(Path(candidate_path), must_exist=True)
    candidate = _json_file(candidate_path, candidate_sha256)
    if type(candidate) is not dict:
        raise CorrectionRefused('original candidate projection is invalid')
    if (type(registration) is not dict or type(registration.get('work_id')) is not str
            or type(registration.get('graph')) is not str
            or registration.get('retry_allowed') is not False
            or registration.get('work_id') != candidate.get('authorization', {}).get('work_id')
            or registration.get('state') not in {'native_completed_report_schema_blocked',
                                                    'report_correction_pending'}):
        raise CorrectionRefused('registered Work and candidate identity differ')
    graph = _cache_path(Path(registration['graph']), must_exist=True)
    output = _cache_path(Path(output), must_exist=False)
    if output.exists() or output.is_symlink():
        raise CorrectionRefused('report-correction output directory already exists')
    authorization = candidate.get('authorization')
    invoke_parameters = candidate.get('invoke_parameters')
    if (type(authorization) is not dict or type(invoke_parameters) is not dict
            or set(invoke_parameters) != {'work_id', 'action_id', 'expected_revision', 'inputs'}
            or authorization.get('work_id') != invoke_parameters.get('work_id')):
        raise CorrectionRefused('original candidate invocation is invalid')
    try:
        frozen_scope = json.loads(authorization['request_summary'])
        if type(frozen_scope) is not dict:
            raise TypeError('scope')
        root = Path(frozen_scope['root'])
        before = frozen_scope['before_sha256']
        if (type(before) is not dict or len(before) != 4
                or any(type(name) is not str or not name
                       or Path(name).is_absolute() or '..' in Path(name).parts
                       or str(Path(name)) != name or name in ('.', '..')
                       for name in before)
                or any(digest is not None and (type(digest) is not str or len(digest) != 64
                       or any(character not in '0123456789abcdef' for character in digest))
                       for digest in before.values())):
            raise CorrectionRefused('original four-file scope is invalid')
        allowed_paths = tuple(sorted(str(root / name) for name in before))
    except (KeyError, TypeError, ValueError) as error:
        raise CorrectionRefused('original finite file scope is unavailable') from error
    if (not root.is_absolute() or root.resolve() != root
            or any(part.is_symlink() for part in (root, *root.parents))
            or len(allowed_paths) != 4
            or set(frozen_scope.get('allowed_operations', ())) != set(before)):
        raise CorrectionRefused('original four-file scope is invalid')
    if type(sources_config) is not dict or type(sources_config.get('source_selection')) is not dict:
        raise CorrectionRefused('source bundle projection is invalid')
    bundle = validate_sources_bundle(sources_config,
        origin_operation_ref=sources_config['source_selection'].get('origin_operation_ref'),
        allowed_paths=allowed_paths)
    validate_inputs(invoke_parameters=invoke_parameters, origin=bundle['origin'],
        evidence=bundle['evidence'], preserved_report=None)
    output.mkdir(mode=0o700, parents=False)
    os.chmod(output, 0o700)
    entry = _load_fixed_module('report_correction_declared_case_entry',
        ROOT / 'tooling/checks/server_product/run_declared_work_case.py')
    case = _load_fixed_module('report_correction_original_case',
        ROOT / 'tooling/checks/server_product/local_library_instruction_case.py')
    driver = _load_fixed_module('report_correction_product_driver',
        ROOT / 'tooling/checks/server_product/probe-work-package-generation.py')
    report = {'contract': 'ordessa.registered-report-correction-cli/1',
              'work_id': invoke_parameters['work_id'], 'graph': str(graph),
              'output': str(output), 'unit_created': False, 'submitted': False,
              'source_manifest_sha256': source_manifest_sha256,
              'candidate_sha256': candidate_sha256}
    _write_receipt(output / 'recovery.json', report)

    runtime = holder = None
    initial_units = ()
    prepared = None
    try:
        manifest = _safe_graph_manifest(graph, case)
        runtime, holder, _projection = entry.open_local_library_registered_graph(
            graph_root=graph, manifest=manifest, candidate=candidate, output=output,
            driver=driver, case=case, source_selection=bundle['source_selection'])
        parent_request_id, wire_scope, parent_state = _admit_original_parent(holder, bundle['origin'])
        if parent_state == 'completed':
            report.update(state='terminal_replay_query_only', submitted=False,
                          parent_operation_state='completed')
            _write_receipt(output / 'recovery.json', report)
            return report
        access = holder['access']
        with access.admit(holder['caller'], wire_scope, 'engineering.work.invoke',
                          request_id=parent_request_id,
                          trace_id='report-correction-prepare-' + parent_request_id[-24:]) as context:
            prepared = validate_prepare_result(holder['service'].prepare_report_correction({
                'invoke_parameters': invoke_parameters, 'origin': bundle['origin'],
                'evidence': bundle['evidence']}, context))
        report.update(state=prepared['state'], created=prepared['created'],
                      plan_ref=prepared['plan_ref'], operation_ref=prepared['operation_ref'])
        _write_receipt(output / 'recovery.json', report)
    finally:
        _stop_runtime(runtime, holder, case)

    if prepared is None or not (prepared['created'] and prepared['state'] == 'ready'):
        report.update(submitted=False, disposition='query_only')
        _write_receipt(output / 'recovery.json', report)
        return report

    body, preserved = _canonical_body(prepared, allowed_paths)
    validate_inputs(invoke_parameters=invoke_parameters, origin=bundle['origin'],
        evidence=bundle['evidence'], preserved_report=preserved)

    runtime = holder = None
    unit = None
    capture = None
    assembly = None
    checkpoint_ref = None
    initial_units = ()
    try:
        manifest = _safe_graph_manifest(graph, case)
        runtime, holder, _projection = entry.open_local_library_registered_graph(
            graph_root=graph, manifest=manifest, candidate=candidate, output=output,
            driver=driver, case=case, source_selection=bundle['source_selection'],
            report_correction_only=True)
        initial_units = tuple(runtime.units.list())
        parent_request_id, wire_scope, parent_state = _admit_original_parent(holder, bundle['origin'])
        if parent_state != 'pending':
            raise CorrectionRefused('report correction parent is no longer pending')
        with holder['access'].admit(holder['caller'], wire_scope, 'engineering.work.invoke',
                request_id=parent_request_id,
                trace_id='report-correction-unit-' + parent_request_id[-24:]) as context:
            approval, assembly = build_collaborators(runtime=runtime,
                permission=runtime.unit_execution_owner.permission,
                environment_instance=holder['environment'], allowed_paths=allowed_paths,
                owner=runtime.unit_execution_owner, factory=holder['factory'],
                access=holder['access'], blobs=holder['blobs'], context=context)
            if approval is None:
                raise CorrectionRefused('read-only report file approval is unavailable')
        # The independent read-only Unit has its original SDK permission. End
        # the Work qualification lease before native worker-thread operations;
        # this is not a dispatch/review child and cannot borrow their guards.
        report.update(state='report_unit_creating', unit_creation_attempted=True)
        _write_receipt(output / 'recovery.json', report)
        unit = assembly.create_read_only_unit(prepared['params'], prepared['operation_ref'])
        report.update(state='report_unit_created', unit_created=True)
        _write_receipt(output / 'recovery.json', report)
        capture = validate_capture(assembly.capture_unit_output(unit, prepared['operation_ref']),
            operation_ref=prepared['operation_ref'])
    finally:
        if runtime is not None:
            def after_report_closed():
                nonlocal checkpoint_ref
                if unit is not None:
                    closed = assembly.confirm_unit_closed(unit)
                    if capture is not None:
                        checkpoint = build_checkpoint(plan_ref=prepared['plan_ref'],
                            capture=capture, closed=closed)
                        raw = canonical_bytes(checkpoint)
                        checkpoint_ref = asdict(holder['blobs'].put_verified(raw,
                            Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/json'))
                        report.update(state='report_unit_closed', unit_created=True,
                            checkpoint_ref=checkpoint_ref,
                            output_digest=hashlib.sha256(capture.output_bytes).hexdigest())
                        _write_receipt(output / 'recovery.json', report)
                _dispose_holder(holder, case)

            def retained(observation):
                report.update(state='report_owner_retained', owner_retention=observation)
                _write_receipt(output / 'recovery.json', report)

            cleanup = driver.retain_generation_owner(runtime, initial_units,
                on_observation=retained, wait_for_resume=driver.wait_generation_owner_resume,
                before_runtime_stop=after_report_closed)
            report['report_unit_cleanup'] = {'states': cleanup[0], 'attempts': cleanup[1]}
            _write_receipt(output / 'recovery.json', report)
        else:
            _stop_runtime(runtime, holder, case)

    runtime = holder = None
    try:
        manifest = _safe_graph_manifest(graph, case)
        runtime, holder, _projection = entry.open_local_library_registered_graph(
            graph_root=graph, manifest=manifest, candidate=candidate, output=output,
            driver=driver, case=case, source_selection=bundle['source_selection'])
        parent_request_id, wire_scope, parent_state = _admit_original_parent(holder, bundle['origin'])
        if parent_state != 'pending':
            raise CorrectionRefused('report correction parent is no longer pending')
        initial_units = tuple(runtime.units.list())
        with holder['access'].admit(holder['caller'], wire_scope, 'engineering.work.invoke',
                request_id=parent_request_id,
                trace_id='report-correction-complete-' + parent_request_id[-24:]) as context:
            result = asyncio.run(holder['service'].complete_report_correction({
                'invoke_parameters': invoke_parameters,
                'checkpoint_ref': checkpoint_ref}, context))
        payload = _completion_payload(result)
        correction = payload.get('report_correction')
        if (type(correction) is not dict
                or set(correction) != {'checkpoint_ref', 'plan_ref', 'submission_ref'}
                or correction['checkpoint_ref'] != checkpoint_ref
                or correction['plan_ref'] != prepared['plan_ref']
                or type(correction['submission_ref']) is not dict):
            raise CorrectionRefused('complete result has no exact report-correction link')
        method_result = payload.get('method_result')
        if type(method_result) is not dict or not {'accepted', 'disposition'} <= set(method_result):
            raise CorrectionRefused('original method disposition is missing')
        report.update(submitted=True, report_correction=correction,
            accepted=method_result['accepted'], disposition=method_result['disposition'],
            completion_operation_id=getattr(result, 'operation_id', None))
        _write_receipt(output / 'recovery.json', report)
    finally:
        if runtime is not None:
            cleanup = driver.retain_generation_owner(runtime, initial_units,
                on_observation=lambda value: None,
                wait_for_resume=driver.wait_generation_owner_resume,
                before_runtime_stop=lambda: _dispose_holder(holder, case))
            report['unit_cleanup'] = {'states': cleanup[0], 'attempts': cleanup[1]}
            runtime.stop()
        else:
            _stop_runtime(runtime, holder, case)
    _write_receipt(output / 'recovery.json', report)
    return report


def recover_registered_review_successor(*, registration_path: Path, registration_sha256: str,
        candidate_path: Path, candidate_sha256: str, sources_config: Mapping[str, Any],
        output: Path, source_manifest_path: Path, source_manifest_sha256: str,
        checkpoint_ref: dict, predecessor_review: dict, run_review_successor: bool) -> dict:
    """Resume one previously completed correction review on its original graph.

    This successor-only path never prepares a correction, creates a report Unit,
    or dispatches the business implementation. Engineering owns the successor
    journal claim and its query/replay rules.
    """
    if run_review_successor is not True:
        raise CorrectionRefused('explicit --run-review-successor is required')
    _source_manifest(source_manifest_path, source_manifest_sha256)
    validate_review_successor_selector({'checkpoint_ref': checkpoint_ref,
                                        'predecessor_review': predecessor_review})

    registration_path = _cache_path(Path(registration_path), must_exist=True)
    registration = _json_file(registration_path, registration_sha256)
    candidate_path = _cache_path(Path(candidate_path), must_exist=True)
    candidate = _json_file(candidate_path, candidate_sha256)
    if type(candidate) is not dict:
        raise CorrectionRefused('original candidate projection is invalid')
    authorization = candidate.get('authorization')
    invoke_parameters = candidate.get('invoke_parameters')
    if (type(registration) is not dict or type(authorization) is not dict
            or type(invoke_parameters) is not dict
            or type(registration.get('work_id')) is not str
            or type(registration.get('graph')) is not str
            or registration.get('work_id') != authorization.get('work_id')
            or registration.get('work_id') != invoke_parameters.get('work_id')
            or registration.get('state') not in {'native_completed_report_schema_blocked',
                                                   'report_correction_pending'}
            or registration.get('retry_allowed') is not False):
        raise CorrectionRefused('registered Work and candidate identity differ')
    graph = _cache_path(Path(registration['graph']), must_exist=True)
    output = _cache_path(Path(output), must_exist=False)
    if output.exists() or output.is_symlink():
        raise CorrectionRefused('review-successor output directory already exists')
    if (set(invoke_parameters) != {'work_id', 'action_id', 'expected_revision', 'inputs'}
            or authorization.get('work_id') != invoke_parameters.get('work_id')):
        raise CorrectionRefused('original candidate invocation is invalid')
    try:
        frozen_scope = json.loads(authorization['request_summary'])
        if type(frozen_scope) is not dict:
            raise TypeError('scope')
        root = Path(frozen_scope['root'])
        before = frozen_scope['before_sha256']
        if (type(before) is not dict or len(before) != 4
                or any(type(name) is not str or not name
                       or Path(name).is_absolute() or '..' in Path(name).parts
                       or str(Path(name)) != name or name in ('.', '..')
                       for name in before)
                or any(digest is not None and (type(digest) is not str or len(digest) != 64
                       or any(character not in '0123456789abcdef' for character in digest))
                       for digest in before.values())):
            raise CorrectionRefused('original four-file scope is invalid')
        allowed_paths = tuple(sorted(str(root / name) for name in before))
    except (KeyError, TypeError, ValueError) as error:
        raise CorrectionRefused('original finite file scope is unavailable') from error
    if (not root.is_absolute() or root.resolve() != root
            or any(part.is_symlink() for part in (root, *root.parents))
            or len(allowed_paths) != 4
            or set(frozen_scope.get('allowed_operations', ())) != set(before)):
        raise CorrectionRefused('original four-file scope is invalid')
    if type(sources_config) is not dict or type(sources_config.get('source_selection')) is not dict:
        raise CorrectionRefused('source bundle projection is invalid')
    bundle = validate_sources_bundle(sources_config,
        origin_operation_ref=sources_config['source_selection'].get('origin_operation_ref'),
        allowed_paths=allowed_paths)
    validate_inputs(invoke_parameters=invoke_parameters, origin=bundle['origin'],
        evidence=bundle['evidence'], preserved_report=None)

    output.mkdir(mode=0o700, parents=False)
    os.chmod(output, 0o700)
    entry = _load_fixed_module('report_correction_declared_case_entry',
        ROOT / 'tooling/checks/server_product/run_declared_work_case.py')
    case = _load_fixed_module('report_correction_original_case',
        ROOT / 'tooling/checks/server_product/local_library_instruction_case.py')
    driver = _load_fixed_module('report_correction_product_driver',
        ROOT / 'tooling/checks/server_product/probe-work-package-generation.py')
    report = {'contract': 'ordessa.registered-review-successor-cli/1',
        'work_id': invoke_parameters['work_id'], 'graph': str(graph), 'output': str(output),
        'report_unit_created': False, 'business_dispatch': False, 'submitted': False,
        'source_manifest_sha256': source_manifest_sha256,
        'candidate_sha256': candidate_sha256, 'state': 'opening_original_graph'}
    _write_receipt(output / 'review-successor.json', report)

    runtime = holder = None
    initial_units = ()
    try:
        manifest = _safe_graph_manifest(graph, case)
        runtime, holder, _projection = entry.open_local_library_registered_graph(
            graph_root=graph, manifest=manifest, candidate=candidate, output=output,
            driver=driver, case=case, source_selection=bundle['source_selection'],
            review_successor_only=True)
        initial_units = tuple(runtime.units.list())
        parent_request_id, wire_scope, parent_state = _admit_original_parent(holder, bundle['origin'])
        report.update(state='querying_original_parent' if parent_state == 'completed'
                      else 'claiming_review_successor', parent_state=parent_state)
        _write_receipt(output / 'review-successor.json', report)
        with holder['access'].admit(holder['caller'], wire_scope, 'engineering.work.invoke',
                request_id=parent_request_id,
                trace_id='review-successor-' + parent_request_id[-24:]) as context:
            result = asyncio.run(holder['service'].resume_report_correction_review({
                'invoke_parameters': invoke_parameters,
                'checkpoint_ref': checkpoint_ref,
                'predecessor_review': predecessor_review}, context))
        payload = _completion_payload(result)
        method_result = payload.get('method_result')
        correction = payload.get('report_correction')
        recovery = payload.get('review_recovery')
        if (type(method_result) is not dict
                or type(method_result.get('accepted')) is not bool
                or type(method_result.get('disposition')) is not str
                or type(correction) is not dict
                or set(correction) != {'checkpoint_ref', 'plan_ref', 'submission_ref'}
                or correction['checkpoint_ref'] != checkpoint_ref
                or type(recovery) is not dict
                or recovery.get('predecessor') != predecessor_review
                or recovery.get('new_review_ref') != method_result.get('review_ref')):
            raise CorrectionRefused('successor result has no exact original disposition/source links')
        report.update(state='completed_query' if parent_state == 'completed' else 'successor_result',
            result_status=getattr(result, 'status', None),
            operation_id=getattr(result, 'operation_id', None), submitted=True,
            accepted=method_result['accepted'], disposition=method_result['disposition'],
            report_correction=correction, review_recovery=recovery, method_result=method_result)
        _write_receipt(output / 'review-successor.json', report)
    finally:
        if runtime is not None:
            def retained(observation):
                report.update(state='runtime_retained', owner_retention=observation)
                _write_receipt(output / 'review-successor.json', report)

            cleanup = driver.retain_generation_owner(runtime, initial_units,
                on_observation=retained, wait_for_resume=driver.wait_generation_owner_resume,
                before_runtime_stop=lambda: _dispose_holder(holder, case))
            report['unit_cleanup'] = {'states': cleanup[0], 'attempts': cleanup[1]}
            _write_receipt(output / 'review-successor.json', report)
        else:
            _stop_runtime(runtime, holder, case)
    _write_receipt(output / 'review-successor.json', report)
    return report


def _write_receipt(path: Path, value: Mapping[str, Any]):
    raw = canonical_bytes(dict(value)) + b'\n'
    temporary = path.with_name(path.name + '.next')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, 'wb', closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _dispose_holder(holder, case):
    if holder and not holder.get('_report_correction_disposed'):
        case.dispose(holder)
        holder['_report_correction_disposed'] = True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registration', type=Path, required=True)
    parser.add_argument('--registration-sha256', required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--candidate-sha256', required=True)
    parser.add_argument('--sources-json', type=Path, required=True)
    parser.add_argument('--sources-sha256', required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--source-manifest-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--run-report', action='store_true')
    parser.add_argument('--successor-json', type=Path)
    parser.add_argument('--successor-sha256')
    parser.add_argument('--run-review-successor', action='store_true')
    args = parser.parse_args(argv)
    if args.run_report == args.run_review_successor:
        print(json.dumps({'refused': 'select exactly one explicit recovery mode'}))
        return 2
    try:
        registration_path = _cache_path(args.registration, must_exist=True)
        candidate_path = _cache_path(args.candidate, must_exist=True)
        sources_path = _cache_path(args.sources_json, must_exist=True)
        registration = _json_file(registration_path, args.registration_sha256)
        candidate = _json_file(candidate_path, args.candidate_sha256)
        sources = _json_file(sources_path, args.sources_sha256)
        if args.run_report:
            if args.successor_json is not None or args.successor_sha256 is not None:
                raise CorrectionRefused('review-successor input is exclusive to its own mode')
            result = recover_registered_graph(registration_path=registration_path,
                registration_sha256=args.registration_sha256,
                candidate_path=candidate_path, candidate_sha256=args.candidate_sha256,
                sources_config=sources, output=args.output,
                source_manifest_path=args.source_manifest,
                source_manifest_sha256=args.source_manifest_sha256, run_report=True)
        else:
            if args.successor_json is None or args.successor_sha256 is None:
                raise CorrectionRefused('--run-review-successor requires --successor-json and digest')
            successor_path = _cache_path(args.successor_json, must_exist=True)
            successor = _json_file(successor_path, args.successor_sha256)
            successor = validate_review_successor_selector(successor)
            result = recover_registered_review_successor(
                registration_path=registration_path,
                registration_sha256=args.registration_sha256,
                candidate_path=candidate_path, candidate_sha256=args.candidate_sha256,
                sources_config=sources, output=args.output,
                source_manifest_path=args.source_manifest,
                source_manifest_sha256=args.source_manifest_sha256,
                checkpoint_ref=successor['checkpoint_ref'],
                predecessor_review=successor['predecessor_review'],
                run_review_successor=True)
    except CorrectionRefused as error:
        print(json.dumps({'refused': str(error)}))
        return 2
    except BaseException as error:
        # The raw exception can contain user data. Emit only its type.
        print(json.dumps({'refused': 'report correction stopped',
                          'error_type': type(error).__name__}))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())


def build_collaborators(*, runtime, permission, environment_instance, allowed_paths,
                        owner, factory, access, blobs, context, timeout=1800):
    """Bind Sol's two real Server entry points (no local re-implementation).

    ``report_correction_file_approval`` is the strict read-only scope guard for the
    report Unit; ``build_report_correction_unit_assembly`` is the real adapter over
    the already selected independent read-only owner. Missing entry points are a
    named refusal, never a fallback double.
    """
    try:
        from ordessa_server.composition.engineering_declared_work_case_assembly import (
            build_report_correction_unit_assembly, report_correction_file_approval)
    except Exception as error:  # pragma: no cover - depends on Sol's landing
        raise CorrectionRefused('report-correction Server entry points are unavailable') from error
    approval = report_correction_file_approval(runtime=runtime, permission=permission,
        environment_instance=environment_instance, allowed_paths=allowed_paths)
    assembly = build_report_correction_unit_assembly(owner=owner, factory=factory,
        access=access, blobs=blobs, context=context, timeout=timeout)
    return approval, assembly


async def run(service, assembly, blobs, *, context, invoke_parameters, origin, evidence,
              preserved_report: Mapping[str, Any], allowed_paths=None) -> dict:
    """Drive one correction: prepare -> (maybe) one Unit -> complete.

    ``preserved_report`` is the caller's read-only record of the rejected original
    (bytes, sha256, length). It is self-verified and never submitted, and the Pi
    journal is never compared to it: the rejected report comes from the original
    capture, the journal is a different source.
    """
    validate_inputs(invoke_parameters=invoke_parameters, origin=origin,
                    evidence=evidence, preserved_report=preserved_report)
    if allowed_paths is None:
        raise CorrectionRefused('finite report read scope is required')
    path_values = tuple(str(path) for path in allowed_paths)
    expected_paths = set(path_values)
    if (len(path_values) != 4 or len(expected_paths) != 4
            or any(not Path(path).is_absolute() or '..' in Path(path).parts
                   or str(Path(path)) != path for path in path_values)
            or {item['path'] for item in evidence['files']} != expected_paths):
        raise CorrectionRefused('evidence files differ from the frozen read-only path set')

    prepared = validate_prepare_result(service.prepare_report_correction(
        {'invoke_parameters': invoke_parameters, 'origin': origin, 'evidence': evidence},
        context))
    outcome = {'plan_ref': prepared['plan_ref'], 'operation_ref': prepared['operation_ref'],
               'state': prepared['state'], 'created': prepared['created'],
               'submitted': False, 'accepted': None, 'disposition': None,
               'checkpoint_ref': None, 'submission_ref': None,
               'preserved_rejected_report_digest': {'algorithm': 'sha256',
                                                    'hex': preserved_report['digest']},
               'refused': None}
    if not (prepared['created'] and prepared['state'] == 'ready'):
        # Existing claim / unreadable origin / already registered report: report
        # the authoritative state and stop. No Unit, no send, no completion.
        return outcome

    body, prompt_preserved = _canonical_body(prepared, sorted(path_values))
    if (prompt_preserved['bytes'] != preserved_report['bytes']
            or prompt_preserved['digest'] != preserved_report['digest']
            or prompt_preserved['length'] != preserved_report['length']):
        raise CorrectionRefused('ready plan does not preserve the supplied rejected report')

    unit = assembly.create_read_only_unit(prepared['params'], prepared['operation_ref'])
    capture = None
    try:
        capture = validate_capture(assembly.capture_unit_output(unit, prepared['operation_ref']),
                                   operation_ref=prepared['operation_ref'])
    finally:
        # Once created, the original Unit gets exactly one close attempt even if
        # prompt/capture validation fails. An unconfirmed close remains a refusal.
        closed = assembly.confirm_unit_closed(unit)
    checkpoint = build_checkpoint(plan_ref=prepared['plan_ref'], capture=capture, closed=closed)
    raw = canonical_bytes(checkpoint)
    checkpoint_ref = blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()),
                                        'application/json')
    outcome['checkpoint_ref'] = asdict(checkpoint_ref)
    result = await service.complete_report_correction(
        {'invoke_parameters': invoke_parameters, 'checkpoint_ref': outcome['checkpoint_ref']},
        context)
    payload = _completion_payload(result)
    correction = payload.get('report_correction')
    if (type(correction) is not dict
            or set(correction) != {'checkpoint_ref', 'plan_ref', 'submission_ref'}
            or correction['checkpoint_ref'] != outcome['checkpoint_ref']
            or correction['plan_ref'] != prepared['plan_ref']
            or type(correction['submission_ref']) is not dict
            or not correction['submission_ref']):
        outcome['refused'] = 'completion result carries no closed report_correction projection'
        return outcome
    method_result = payload.get('method_result') or {}
    if type(method_result) is not dict or not {'accepted', 'disposition'} <= set(method_result):
        outcome['refused'] = 'completion result has no method decision projection'
        return outcome
    outcome.update({
        'submitted': True,
        'checkpoint_ref': correction['checkpoint_ref'],
        'plan_ref': correction['plan_ref'],
        'submission_ref': correction['submission_ref'],
        'parent_operation_id': getattr(result, 'operation_id', None),
        'accepted': method_result.get('accepted'),
        'disposition': method_result.get('disposition'),
    })
    return outcome


def validate_content_resume_receipt(receipt):
    """Accept only the closed report checkpoint from the stopped one-shot run."""
    expected = {'contract', 'work_id', 'unit_created', 'submitted',
        'source_manifest_sha256', 'candidate_sha256', 'state', 'plan_ref',
        'checkpoint_ref', 'approval_ref'}
    if (type(receipt) is not dict or set(receipt) != expected
            or receipt['contract'] != 'ordessa.registered-report-content-rework/1'
            or receipt['state'] != 'report_unit_created'
            or receipt['unit_created'] is not True or receipt['submitted'] is not False
            or any(not _blob_ref(receipt[k]) for k in
                   ('plan_ref', 'approval_ref', 'checkpoint_ref'))):
        raise CorrectionRefused('Only a closed report checkpoint may resume')
    return receipt


def verify_content_resume_journal(graph, expected_claim, receipt):
    """Read-only fence: no partial report registration or review may be retried."""
    fields = ('realm_id', 'principal_id', 'request_id', 'project_id', 'operation',
        'operation_id', 'request_digest', 'state', 'version')
    if (type(expected_claim) is not dict or set(expected_claim) != set(fields)
            or expected_claim['operation'] != 'engineering.report_content_rework.claim'
            or expected_claim['state'] != 'pending'
            or type(expected_claim['version']) is not int or expected_claim['version'] != 0):
        raise CorrectionRefused('An exact untouched pending claim is required')
    plan_digest = receipt['plan_ref']['digest']['hex']
    suffix = hashlib.sha256(canonical_bytes({k: receipt[k] for k in
        ('plan_ref', 'approval_ref')})).hexdigest()
    requests = ('rework-record-' + plan_digest[:48],
        'report-content-rework-tail-' + suffix[:48],
        'rework-review-' + suffix[:48], 'rework-review-record-' + suffix[:40],
        'rework-disposition-' + suffix[:40])
    connection = sqlite3.connect((Path(graph) / 'engineering.sqlite').resolve().as_uri()
        + '?mode=ro', uri=True)
    try:
        row = connection.execute('SELECT ' + ','.join(fields) + ',result_bytes'
            ' FROM eng_commands WHERE realm_id=? AND principal_id=? AND request_id=?',
            tuple(expected_claim[k] for k in fields[:3])).fetchone()
        if row is None or dict(zip(fields, row[:-1])) != expected_claim or row[-1] is not None:
            raise CorrectionRefused('Original pending claim has changed')
        placeholders = ','.join('?' for _ in requests)
        if connection.execute('SELECT 1 FROM eng_commands WHERE realm_id=? AND principal_id=?'
                ' AND request_id IN (' + placeholders + ') LIMIT 1',
                (expected_claim['realm_id'], expected_claim['principal_id'], *requests)).fetchone():
            raise CorrectionRefused('Partial report/review requires query-only reconciliation')
        if connection.execute('SELECT 1 FROM eng_submissions WHERE realm_id=? AND project_id=?'
                ' AND submission_id=?', (expected_claim['realm_id'], expected_claim['project_id'],
                'content-rework-' + plan_digest[:40])).fetchone():
            raise CorrectionRefused('Report is already registered; do not resume')
        if connection.execute('SELECT 1 FROM eng_review_requests WHERE realm_id=? AND project_id=?'
                ' AND review_id=?', (expected_claim['realm_id'], expected_claim['project_id'],
                'report-content-rework-review-' + suffix)).fetchone():
            raise CorrectionRefused('Review already started; do not resume')
    finally:
        connection.close()


def resume_registered_report_content_rework(*, registration_path, registration_sha256,
        candidate_path, candidate_sha256, sources_config, output,
        source_manifest_path, source_manifest_sha256, previous_receipt_path,
        previous_receipt_sha256, expected_claim, approval_factory, budget):
    """Explicit checkpoint-only closeout; never prepare or create a report Unit.

    The selected budget must already be a single-owner cumulative review-only
    recovery. This function does not reopen it, grant permission or mint proof.
    Any partial write or unknown review blocks another automatic invocation.
    """
    if not callable(approval_factory) or budget is None:
        raise CorrectionRefused('Original trusted approval and cumulative budget required')
    _source_manifest(Path(source_manifest_path), source_manifest_sha256)
    registration = _json_file(_cache_path(Path(registration_path), must_exist=True), registration_sha256)
    candidate = _json_file(_cache_path(Path(candidate_path), must_exist=True), candidate_sha256)
    prior = validate_content_resume_receipt(_json_file(
        _cache_path(Path(previous_receipt_path), must_exist=True), previous_receipt_sha256))
    if (registration.get('retry_allowed') is not False
            or prior['work_id'] != registration.get('work_id')
            or prior['work_id'] != candidate.get('authorization', {}).get('work_id')
            or prior['candidate_sha256'] != candidate_sha256
            or type(sources_config) is not dict
            or set(sources_config) != {'source_selection', 'origin', 'supplement_refs'}
            or getattr(budget, 'plan_digest', None) != prior['plan_ref']['digest']['hex']
            or getattr(budget, 'resumed_review_only', False) is not True):
        raise CorrectionRefused('Resume input identity differs')
    budget.require_current()
    graph = _cache_path(Path(registration['graph']), must_exist=True)
    verify_content_resume_journal(graph, expected_claim, prior)
    output = _cache_path(Path(output), must_exist=False)
    if output.exists() or output.is_symlink():
        raise CorrectionRefused('A fresh recovery receipt directory is required')
    scope = json.loads(candidate['authorization']['request_summary'])
    root, before = Path(scope['root']), scope['before_sha256']
    if (not root.is_absolute() or root.resolve() != root or type(before) is not dict
            or len(before) != 4 or set(scope.get('allowed_operations', ())) != set(before)
            or any(type(name) is not str or Path(name).is_absolute()
                   or '..' in Path(name).parts or str(Path(name)) != name for name in before)):
        raise CorrectionRefused('Original finite read scope is invalid')
    selection = sources_config['source_selection']
    validate_sources_config(selection, origin_operation_ref=selection.get('origin_operation_ref'),
        allowed_paths=tuple(sorted(str(root / name) for name in before)))
    entry = _load_fixed_module('content_resume_entry', ROOT / 'tooling/checks/server_product/run_declared_work_case.py')
    case = _load_fixed_module('content_resume_case', ROOT / 'tooling/checks/server_product/local_library_instruction_case.py')
    driver = _load_fixed_module('content_resume_driver', ROOT / 'tooling/checks/server_product/probe-work-package-generation.py')
    output.mkdir(mode=0o700, parents=False)
    report = dict(prior, state='resume_entered', unit_created=False,
        source_manifest_sha256=source_manifest_sha256,
        previous_receipt_sha256=previous_receipt_sha256, report_prompt_sent=False)
    _write_receipt(output / 'content-resume.json', report)
    runtime = holder = None
    initial_units = ()
    try:
        runtime, holder, _ = entry.open_local_library_registered_graph(graph_root=graph,
            manifest=_safe_graph_manifest(graph, case), candidate=candidate, output=output,
            driver=driver, case=case, source_selection=selection, review_successor_only=True,
            report_content_rework_approval_factory=approval_factory,
            report_content_rework_budget=budget)
        initial_units = tuple(runtime.units.list())
        request_id, wire_scope, parent_state = _admit_original_parent(holder, sources_config['origin'])
        if parent_state != 'completed':
            raise CorrectionRefused('Original parent must remain completed')
        verify_content_resume_journal(graph, expected_claim, prior)
        with holder['access'].admit(holder['caller'], wire_scope, 'engineering.work.invoke',
                request_id=request_id, trace_id='report-content-checkpoint-resume') as context:
            result = asyncio.run(holder['service'].complete_report_content_rework({
                'invoke_parameters': candidate['invoke_parameters'],
                **{k: prior[k] for k in ('plan_ref', 'approval_ref', 'checkpoint_ref')}}, context))
        payload = _completion_payload(result)
        link = payload.get('report_content_rework')
        if (type(link) is not dict or any(link.get(k) != prior[k]
                for k in ('plan_ref', 'approval_ref', 'checkpoint_ref'))):
            raise CorrectionRefused('Resume result does not preserve original checkpoint')
        report.update(state='completed', submitted=True, report_content_rework=link,
            accepted=payload['method_result']['accepted'], disposition=payload['method_result']['disposition'])
    except BaseException as error:
        # The original Service may have committed a report/assignment before
        # a later cut refused. Do not claim that nothing was submitted.
        report.update(state='interrupted_query_only', submitted=None,
            error_type=type(error).__name__, error_code=getattr(error, 'code', None))
        raise
    finally:
        if runtime is not None:
            cleanup = driver.retain_generation_owner(runtime, initial_units,
                on_observation=lambda value: None, wait_for_resume=driver.wait_generation_owner_resume,
                before_runtime_stop=lambda: _dispose_holder(holder, case))
            report['unit_cleanup'] = {'states': cleanup[0], 'attempts': cleanup[1]}
        else:
            _stop_runtime(runtime, holder, case)
        _write_receipt(output / 'content-resume.json', report)
    return report


def recover_registered_report_content_rework(*, registration_path, registration_sha256,
        candidate_path, candidate_sha256, sources_config, output,
        source_manifest_path, source_manifest_sha256, run_report,
        approval_factory=None, budget=None):
    """Consume one report-only rework on a completed, formally rejected Work.

    The host may select an approval guard through ``approval_factory``. The
    default deliberately selects none: preparation can expose the immutable
    plan, but cannot reserve a claim or start a Unit. This entry has no business
    dispatch, catalog-check, approval-minting or Grant-reset path.
    """
    if run_report is not True:
        raise CorrectionRefused('explicit report-content opt-in is required')
    if approval_factory is not None and not callable(approval_factory):
        raise CorrectionRefused('host-selected approval factory is invalid')
    if approval_factory is not None and (budget is None or any(
            not callable(getattr(budget, name, None))
            for name in ('configuration', 'require_unit_ready'))):
        raise CorrectionRefused('report-content execution requires a hard request budget')
    _source_manifest(Path(source_manifest_path), source_manifest_sha256)
    registration = _json_file(_cache_path(Path(registration_path), must_exist=True), registration_sha256)
    candidate = _json_file(_cache_path(Path(candidate_path), must_exist=True), candidate_sha256)
    if (type(registration) is not dict or type(candidate) is not dict
            or registration.get('retry_allowed') is not False
            or registration.get('work_id') != candidate.get('authorization', {}).get('work_id')
            or type(registration.get('graph')) is not str
            or type(candidate.get('invoke_parameters')) is not dict
            or type(sources_config) is not dict
            or set(sources_config) != {'source_selection', 'origin', 'supplement_refs'}
            or type(sources_config['origin']) is not dict
            or set(sources_config['origin']) != {'parent_operation_id', 'expected_parent_version',
                                                'review_ref', 'submission_ref'}
            or type(sources_config['supplement_refs']) is not list):
        raise CorrectionRefused('report-content original selectors are invalid')
    graph = _cache_path(Path(registration['graph']), must_exist=True)
    output = _cache_path(Path(output), must_exist=False)
    if output.exists() or output.is_symlink():
        raise CorrectionRefused('report-content output directory already exists')
    scope = json.loads(candidate['authorization']['request_summary'])
    root, before = Path(scope['root']), scope['before_sha256']
    if (not root.is_absolute() or root.resolve() != root or type(before) is not dict
            or len(before) != 4 or set(scope.get('allowed_operations', ())) != set(before)
            or any(type(name) is not str or Path(name).is_absolute()
                   or '..' in Path(name).parts or str(Path(name)) != name for name in before)):
        raise CorrectionRefused('original finite read scope is invalid')
    paths = tuple(sorted(str(root / name) for name in before))
    selection = sources_config['source_selection']
    validate_sources_config(selection, origin_operation_ref=selection.get('origin_operation_ref'),
                            allowed_paths=paths)
    output.mkdir(mode=0o700, parents=False)
    entry = _load_fixed_module('report_content_case_entry', ROOT / 'tooling/checks/server_product/run_declared_work_case.py')
    case = _load_fixed_module('report_content_original_case', ROOT / 'tooling/checks/server_product/local_library_instruction_case.py')
    driver = _load_fixed_module('report_content_product_driver', ROOT / 'tooling/checks/server_product/probe-work-package-generation.py')
    report = {'contract': 'ordessa.registered-report-content-rework/1',
        'work_id': registration['work_id'], 'unit_created': False, 'submitted': False,
        'source_manifest_sha256': source_manifest_sha256,
        'candidate_sha256': candidate_sha256}
    _write_receipt(output / 'content-rework.json', report)
    runtime = holder = assembly = capture = prepared = None
    unit = None
    initial_units = ()
    try:
        runtime, holder, _ = entry.open_local_library_registered_graph(graph_root=graph,
            manifest=_safe_graph_manifest(graph, case), candidate=candidate, output=output,
            driver=driver, case=case, source_selection=selection,
            review_successor_only=True,
            report_content_rework_approval_factory=approval_factory,
            report_content_rework_budget=budget)
        request_id, wire_scope, parent_state = _admit_original_parent(holder, sources_config['origin'])
        if parent_state != 'completed':
            raise CorrectionRefused('report-content origin parent must be completed')
        initial_units = tuple(runtime.units.list())
        with holder['access'].admit(holder['caller'], wire_scope, 'engineering.work.invoke',
                request_id=request_id, trace_id='report-content-prepare') as context:
            prepared = holder['service'].prepare_report_content_rework({
                'invoke_parameters': candidate['invoke_parameters'],
                'origin': sources_config['origin'],
                'supplement_refs': sources_config['supplement_refs']}, context)
            if hasattr(prepared, 'result_bytes'):
                payload = _completion_payload(prepared)
                report.update(state='completed_query', accepted=payload['method_result']['accepted'],
                    disposition=payload['method_result']['disposition'],
                    report_content_rework=payload['report_content_rework'])
                _write_receipt(output / 'content-rework.json', report)
                return report
            if type(prepared) is not dict or prepared.get('state') not in {
                    'ready', 'approval_required', 'pending_query_only'}:
                raise CorrectionRefused('report-content preparation result is invalid')
            report.update(state=prepared['state'], plan_ref=prepared['plan_ref'])
            _write_receipt(output / 'content-rework.json', report)
            if prepared['state'] != 'ready':
                if prepared.get('params') is not None:
                    raise CorrectionRefused('non-ready rework carries Unit parameters')
                return report
        _stop_runtime(runtime, holder, case)
        runtime = holder = None
        runtime, holder, _ = entry.open_local_library_registered_graph(graph_root=graph,
            manifest=_safe_graph_manifest(graph, case), candidate=candidate, output=output,
            driver=driver, case=case, source_selection=selection,
            report_content_rework_only=True,
            report_content_rework_approval_factory=approval_factory,
            report_content_rework_budget=budget)
        initial_units = tuple(runtime.units.list())
        request_id, wire_scope, _ = _admit_original_parent(holder, sources_config['origin'])
        with holder['access'].admit(holder['caller'], wire_scope, 'engineering.work.invoke',
                request_id=request_id, trace_id='report-content-unit') as context:
            from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
            from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
            from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
            # Qualify the standalone graph's selected historical query before
            # creating a new Unit. Reopening must read the exact original
            # receipt under the current reader's native permission.
            with holder['factory'].begin(context.scope, 'read') as uow:
                row = uow.work_dispatch.by_operation(selection['origin_operation_ref'], context.scope)
                binding = decode_dispatch(row['binding_bytes'])
                original_ref = decode_blob_ref(json.loads(row['result_blob_json']))
            observation = capture_execution_observation(runtime.unit_execution_owner.records,
                holder['blobs'], authority_id=holder['factory'].authority_id,
                unit_ref=json.loads(binding.unit_ref_bytes),
                operation_ref=binding.execution_operation_ref,
                expected_prompt_digest='sha256:' + binding.prompt_input_digest.hex,
                query_invocation=holder['assembly'].dispatch_query(binding),
                max_receipt_bytes=runtime.unit_execution_owner.records.acp_turn_evidence_max_bytes)
            if observation.state != 'completed' or observation.blob_ref != original_ref:
                raise CorrectionRefused('standalone report-content provenance differs from original receipt')
            from ordessa_server.composition.engineering_declared_work_case_assembly import build_report_content_rework_unit_assembly
            assembly = build_report_content_rework_unit_assembly(owner=runtime.unit_execution_owner,
                factory=holder['factory'], access=holder['access'], blobs=holder['blobs'], context=context,
                before_native_prompt=(None if budget is None else
                    lambda owner, unit: budget.require_unit_ready(owner, unit, 'report')))
        # The native Unit uses its own permission after the Work lease ends.
        unit = assembly.create_read_only_unit(prepared['params'], prepared['operation_ref'])
        report.update(state='report_unit_created', unit_created=True)
        _write_receipt(output / 'content-rework.json', report)
        capture = validate_capture(assembly.capture_unit_output(unit, prepared['operation_ref']),
                                   operation_ref=prepared['operation_ref'])
    finally:
        if runtime is not None and unit is not None:
            def after_closed():
                closed = assembly.confirm_unit_closed(unit)
                if capture is not None:
                    original = build_checkpoint(plan_ref=prepared['plan_ref'], capture=capture, closed=closed)
                    checkpoint = {'contract': 'ordessa.declared-report-content-rework/1',
                        'plan_ref': prepared['plan_ref'], 'approval_ref': prepared['approval_ref'],
                        'report': original['correction']}
                    raw = canonical_bytes(checkpoint)
                    report['checkpoint_ref'] = asdict(holder['blobs'].put_verified(raw,
                        Digest('sha256', hashlib.sha256(raw).hexdigest()), 'application/json'))
                    report['approval_ref'] = prepared['approval_ref']
                    _write_receipt(output / 'content-rework.json', report)
                _dispose_holder(holder, case)
            cleanup = driver.retain_generation_owner(runtime, initial_units,
                on_observation=lambda value: None, wait_for_resume=driver.wait_generation_owner_resume,
                before_runtime_stop=after_closed)
            report['report_unit_cleanup'] = {'states': cleanup[0], 'attempts': cleanup[1]}
        else:
            _stop_runtime(runtime, holder, case)
    runtime = holder = None
    try:
        runtime, holder, _ = entry.open_local_library_registered_graph(graph_root=graph,
            manifest=_safe_graph_manifest(graph, case), candidate=candidate, output=output,
            driver=driver, case=case, source_selection=selection, review_successor_only=True,
            report_content_rework_approval_factory=approval_factory,
            report_content_rework_budget=budget)
        initial_units = tuple(runtime.units.list())
        request_id, wire_scope, _ = _admit_original_parent(holder, sources_config['origin'])
        with holder['access'].admit(holder['caller'], wire_scope, 'engineering.work.invoke',
                request_id=request_id, trace_id='report-content-complete') as context:
            result = asyncio.run(holder['service'].complete_report_content_rework({
                'invoke_parameters': candidate['invoke_parameters'], 'plan_ref': prepared['plan_ref'],
                'approval_ref': prepared['approval_ref'], 'checkpoint_ref': report['checkpoint_ref']}, context))
        payload = _completion_payload(result)
        link = payload.get('report_content_rework')
        if (type(link) is not dict or link.get('checkpoint_ref') != report['checkpoint_ref']
                or link.get('plan_ref') != prepared['plan_ref']
                or link.get('approval_ref') != prepared['approval_ref']):
            raise CorrectionRefused('report-content result has no exact source link')
        report.update(state='completed', submitted=True, report_content_rework=link,
            accepted=payload['method_result']['accepted'], disposition=payload['method_result']['disposition'])
    finally:
        if runtime is not None:
            cleanup = driver.retain_generation_owner(runtime, initial_units,
                on_observation=lambda value: None, wait_for_resume=driver.wait_generation_owner_resume,
                before_runtime_stop=lambda: _dispose_holder(holder, case))
            report['unit_cleanup'] = {'states': cleanup[0], 'attempts': cleanup[1]}
        else:
            _stop_runtime(runtime, holder, case)
    _write_receipt(output / 'content-rework.json', report)
    return report
