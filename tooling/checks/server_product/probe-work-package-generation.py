"""One fixed Local Library source review and conditional package generation.

Use the original Product/Work/Unit/Decision authorities with a fresh private
instance. No listener, historical replay, fallback provider or automatic retry.
Inputs are complete fixed DID captures; excerpts only bind the method's eight
review questions and never replace full source documents in the Unit prompt.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
CASE_ID = 'local-library-generation-20261016'
REAL_ROOT_NAME = 'local-library-generation-real-20261017-tls-recovered'
REQUEST_PREFIX = 'tls-20261017-0051-'
EXECUTION_INTENT = 'local-library-confirmed-tls-recovery-20261017'
WORK_ID = 'local-library-search-package-tls-20261017'
METHOD_DIR = ROOT / 'methods/incremental-engineering/candidates/2.7.2'
BRIDGE = Path('/tmp/ordessa-unit-live-acp-20261012-reproduced')
PI = Path('/home/maoqh/.local/bin/pi')
ENV_SOURCE = '/home/maoqh/projects/ordessa/.env'
BRIDGE_SHA = '5a2f8f008fdf6fdf274d99f358c37477d8bcf8c4bfacf8cefef2630ef12d1c84'
PROVIDER, MODEL, ENDPOINT = 'deepseek', 'deepseek-flash', 'https://api.deepseek.com'
RETRY_OFF = {'enabled':False,'maxRetries':0,'provider':{'maxRetries':0,'maxRetryDelayMs':0}}
ACTIONS = frozenset({'prepare','start','interaction','stop','release'})
CAPABILITIES = ('engineering.work.start','engineering.work.invoke','engineering.work.get',
    'engineering.operations.get','engineering.references.resolve','engineering.reviews.request',
    'engineering.reviews.record','engineering.proposals.create','engineering.proposals.associate_review',
    'engineering.methods.control','engineering.executions.dispatch','engineering.reviewer.jev')

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.chmod(path, 0o600)


def safe_error(error):
    result = {'type': type(error).__module__ + '.' + type(error).__qualname__}
    for key in ('code', 'diagnostic', 'decision_run_id', 'decision_status'):
        value = getattr(error, key, None)
        if type(value) is str and len(value) <= 128 and all(c.isalnum() or c in '_.:-' for c in value):
            result[key] = value
    for attribute in ('details', 'data'):
        data = getattr(error, attribute, None)
        value = data.get('internalCode') if type(data) is dict else None
        if (type(value) is str and len(value) <= 128
                and all(c.isalnum() or c in '_.:-' for c in value)):
            result['internal_code'] = value
            break
    # Retain only the closed, payload-free dispatch diagnostic contract. A
    # generic wrapper code must not discard the original write-stage facts.
    from ordessa_engineering.application.api import FailureDiagnostic
    from ordessa_engineering.domain.common.mechanisms.codec import decode_blob_ref
    from ordessa_engineering.domain.common.models.refs import BlobRef
    diagnostic = getattr(error, 'failure_diagnostic', None)
    evidence = getattr(error, 'failure_evidence_ref', None)
    linked = getattr(error, 'failure_evidence_linked', False)
    if type(data) is dict and 'failureDiagnostic' in data:
        try:
            diagnostic = FailureDiagnostic.from_record(data['failureDiagnostic'])
            evidence = (decode_blob_ref(data['failureEvidenceRef'])
                        if 'failureEvidenceRef' in data else None)
            linked = data.get('failureEvidenceLinked', False)
        except (TypeError, ValueError):
            diagnostic, evidence, linked = None, None, False
    if type(diagnostic) is FailureDiagnostic:
        result['failure_diagnostic'] = diagnostic.to_dict()
        if type(evidence) is BlobRef and type(linked) is bool:
            result['failure_evidence_ref'] = asdict(evidence)
            result['failure_evidence_linked'] = linked
    return result


def jev_failure_for_error(provider, error):
    """Read only the sanitized diagnostic bound to this failed Decision run.

    This is host diagnostics, not a review result or evidence reconciliation.
    A different run's last failure must never be attached to this request.
    """
    run_id = getattr(error, 'decision_run_id', None)
    if type(run_id) is not str:
        return None
    read_failure = getattr(provider, 'last_failure_for', None)
    return read_failure(run_id) if callable(read_failure) else None


def jev_http_client(holder, timeout):
    """Observe native network phases without changing proxy, TLS or retries."""
    import httpx2
    phases = {'connect_tcp', 'start_tls', 'send_request_headers',
              'send_request_body', 'receive_response_headers', 'receive_response_body'}
    prefixes = {'connection', 'http_proxy', 'proxy', 'http11', 'http2'}

    async def before_request(request):
        records = holder.setdefault('jev_network_trace', [])
        if len(records) >= 8:
            return
        record = {'request_no': len(records) + 1, 'origin_write_started': False,
                  'response_headers_received': False, 'proxy_tunnel_seen': False, 'events': []}
        records.append(record)
        started = time.monotonic()
        proxy_phase = False

        async def trace(event, info):
            nonlocal proxy_phase
            parts = event.split('.')
            if (len(parts) != 3 or parts[0] not in prefixes or parts[1] not in phases
                    or parts[2] not in {'started', 'complete', 'failed'} or len(record['events']) >= 32):
                return
            native = info.get('request')
            method = getattr(native, 'method', None)
            if method == b'CONNECT':
                record['proxy_tunnel_seen'] = True
                proxy_phase = True
            elif method in (b'GET', b'POST') and parts[1] == 'send_request_headers' and parts[2] == 'started':
                proxy_phase = False
                record['origin_write_started'] = True
            if not proxy_phase and parts[1] == 'receive_response_headers' and parts[2] == 'complete':
                record['response_headers_received'] = True
            item = {'event': event, 'elapsed_ms': round((time.monotonic() - started) * 1000)}
            error = info.get('exception')
            allowed = {'ConnectError', 'ConnectTimeout', 'ReadError', 'ReadTimeout',
                       'WriteError', 'WriteTimeout', 'gaierror', 'OSError',
                       'SSLError', 'SSLCertVerificationError', 'BrokenResourceError', 'EndOfStream'}
            if error is not None:
                causes = []; seen = set()
                for _ in range(8):
                    if error is None or id(error) in seen:
                        break
                    seen.add(id(error))
                    if type(error).__name__ in allowed:
                        causes.append(type(error).__name__)
                    if isinstance(error, OSError) and type(error.errno) is int:
                        item['errno'] = error.errno
                    error = error.__cause__ or error.__context__
                item['cause_types'] = causes
            record['events'].append(item)

        request.extensions['trace'] = trace

    return httpx2.AsyncClient(timeout=timeout, event_hooks={'request': [before_request]})


def load_materials(manifest_path, expected_digest):
    """Read only explicit immutable members; no discovery or identity repair."""
    manifest_path = manifest_path.absolute()
    directory = manifest_path.parent
    expected_root = ROOT / '.nightly-cache' / CASE_ID / 'inputs' / 'citation-r5'
    if (directory != expected_root or directory.resolve() != expected_root
            or manifest_path.name != 'INPUT-MANIFEST.json' or manifest_path.is_symlink()
            or re.fullmatch(r'[0-9a-f]{64}',expected_digest) is None):
        raise RuntimeError('Explicit private material manifest required')
    manifest_raw = manifest_path.read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest() != expected_digest:
        raise RuntimeError('Selected material manifest changed')
    manifest = json.loads(manifest_raw)
    if (manifest.get('contract') != 'ordessa.validation.review-materials/1'
            or manifest.get('revision_id') != 'local-library-search-citation-r5'
            or manifest.get('source_commit') != '342d4e9a590caa50bb0749b48cee80b5a3146439'
            or set(manifest.get('sources',{})) != {'baseline','candidate','project_facts','capture_adapter','independent_review'}
            or set(manifest.get('source_versions',{})) != set(manifest['sources'])):
        raise RuntimeError('Selected case identity differs')
    def member(item):
        if (type(item) is not dict or set(item) != {'path','sha256','bytes'}
                or type(item['path']) is not str or Path(item['path']).name != item['path']
                or item['path'] in ('.','..') or type(item['bytes']) is not int):
            raise RuntimeError('Selected member location differs')
        path=directory/item['path']
        if path.is_symlink() or path.resolve() != path.absolute():
            raise RuntimeError('Selected member location differs')
        raw=path.read_bytes()
        if len(raw)!=item['bytes'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:
            raise RuntimeError('Selected material content differs')
        return raw
    raw_inputs={name:member(item) for name,item in manifest['sources'].items()}
    claims=json.loads(member(manifest['claims']))['checks']
    bindings=[{'check_id':item['check_id'],'sources':[e['source'] for e in item['evidence']],
        'excerpt_sha256':[hashlib.sha256(e['excerpt'].encode()).hexdigest() for e in item['evidence']]}
        for item in claims]
    if bindings!=manifest['excerpt_bindings']:
        raise RuntimeError('Selected review evidence identity differs')
    for item in claims:
        for evidence in item['evidence']:
            if evidence['excerpt'] not in raw_inputs[evidence['source']].decode('utf-8'):
                raise RuntimeError('Selected excerpt differs')
    return {'raw_inputs':raw_inputs,'claims':claims,'versions':manifest['source_versions'],
        'revision_id':manifest['revision_id'],'manifest_digest':expected_digest}


def selected_model():
    if (not BRIDGE.is_file() or hashlib.sha256(BRIDGE.read_bytes()).hexdigest()!=BRIDGE_SHA
            or not PI.is_file()):
        raise RuntimeError('Pinned original Pi/ACP executable unavailable')
    return {'id':MODEL,'name':'DeepSeek V4.1 Flash (explicit package generation)',
        'provider':PROVIDER,'api':'openai-completions','baseUrl':ENDPOINT,
        'reasoning':False,'input':['text'],'contextWindow':1000000,'maxTokens':16384,
        'samplingParams':{'thinking':{'type':'disabled'},
            'response_format':{'type':'json_object'}},
        'compat':{'supportsStore':False,'supportsDeveloperRole':False,'maxTokensField':'max_tokens',
            'supportsStrictMode':True,'requiresReasoningContentOnAssistantMessages':True,'thinkingFormat':'deepseek'},
        'cost':{'input':0.3,'output':1.2,'cacheRead':0.006,'cacheWrite':0}}


def generation_file_approval(*, runtime, permission, environment_instance):
    """Approve only this case's three documents in the original Unit cwd.

    The existing owner still rejects execute, directory probing, other files,
    substituted identities and any request without one native allow-once option.
    """
    from ordessa_server.composition.unit_file_callback_approval import UnitFileCallbackApproval
    return UnitFileCallbackApproval(runtime=runtime, permission=permission,
        environment_instance=environment_instance,
        allowed_relative_paths=('spec.md', 'plan.md', 'tasks.md'))


def compose(root, model, app_factory, holder):
    from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
    from ordessa_environments_local import LocalEnvironmentResourceProvider
    from ordessa_execution_agents.profiles import ProfileService
    from ordessa_units.bindings.profile_admission import UnitProfileAdmission
    from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
    from ordessa_units.assembly import UnitRunPermission
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
    from ordessa_interfaces.system_access.contracts.refs import Scope
    from ordessa_server.composition.configuration.product_selection import create_host_product_composition
    from ordessa_server.composition.product_native_configuration import construct_pi_harness_declaration
    from ordessa_server.composition.pi_selection import PiExecutionSelection, PiExecutionPorts
    from ordessa_server.composition.product_runtime import build_product_runtime

    runtime_root = holder.get('runtime_root', root)
    reuse = holder.get('reuse_existing_runtime') is True
    fingerprint = ProtectedFingerprintHmac({'process-only': os.urandom(32)}, active_key_id='process-only')
    setup = create_host_product_composition(fingerprint_port=fingerprint).default_runtime(runtime_root / 'product')
    try:
        context = setup.unit_runtime.context
        namespace = context.environment_namespace
        bridge = holder.get('bridge_executable', BRIDGE)
        bridge_sha = holder.get('reviewed_bridge_sha256', BRIDGE_SHA)
        declaration = construct_pi_harness_declaration(
            setup, bridge_executable=bridge, pi_executable=PI,
            reviewed_bridge_sha256=(bridge_sha if 'reviewed_bridge_sha256' in holder else None))
        profiles = ProfileService(UnitProfileAdmission(context))
        if reuse:
            from ordessa_execution_agents.profiles import decode_revision_ref
            profile_ref = decode_revision_ref(holder['profile_revision'])
            revision = profiles.get_revision(profile_ref)
            if revision.ref != profile_ref or profile_ref.environment_namespace != namespace:
                raise RuntimeError('Existing immutable Profile differs')
        else:
            profile_request = 'create-local-library-generation-profile'
            profile = profiles.create(profile_id='local-library-generation-' + uuid4().hex,
            name='Independent first package generation',
            content={'schemaVersion': '1', 'harnessDefinitionRef': dict(declaration.descriptor.definition_ref),
                'declarations': [{'declarationId': 'selected-model',
                    'configurationKind': 'assets.model-provider', 'schemaVersion': '1',
                    'action': 'value', 'requirement': 'required',
                    'payload': {'provider': PROVIDER, 'model': MODEL, 'protocol': 'openai-chat',
                                'endpoint': ENDPOINT, 'requestParams': {'retry': RETRY_OFF}}}]},
                request=profiles.request_key(profile_request))
            profile_ref = profile.current_revision
    finally:
        setup.stop()
    environment_root = runtime_root / 'local-environment'
    if not reuse:
        environment_root.mkdir(mode=0o700)
    environment_store = SQLiteEnvironmentStore(runtime_root / 'environments.sqlite')
    environments = EnvironmentManager(store=environment_store,
        providers={'local': LocalEnvironmentResourceProvider(default_root=str(environment_root))})
    environment = (environments.get(holder['environment_identity']) if reuse else
                   environments.register('local', str(environment_root)))
    if reuse and (environment.snapshot.backend_id != str(environment_root)
                  or environment.snapshot.provider_id != 'local'):
        raise RuntimeError('Existing Environment selection differs')
    holder['environment'] = environment
    holder['environment_store'] = environment_store
    scope = Scope(namespace, CASE_ID)

    def permission_factory(*, runtime, admission_context, selection, environment_instance):
        permission_seconds = holder.get('execution_permission_seconds', 600)
        if type(permission_seconds) not in (int, float) or not 60 <= permission_seconds <= 3600:
            raise RuntimeError('Finite task execution permission lifetime required')
        authority = runtime.wire.identity_authority
        authority.replace_grants((AccessGrant(scope, tuple('execution.units.' + action for action in sorted(ACTIONS)) + CAPABILITIES),))
        holder['runtime'] = runtime
        principal = authority.authenticate('Bearer ' + runtime.token)
        return UnitRunPermission(access_authority=authority, principal=principal, scope=scope,
            agent_id=selection.agent_id, profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity, root_directory=str(environment_root),
            actions=ACTIONS, expires_at=time.time() + permission_seconds)

    selection = PiExecutionSelection('local-library-generation-agent', profile_ref, environment.identity,
        'local', 'none', True, 'selected-model', PROVIDER, MODEL,
        str(bridge), bridge_sha, str(PI), str(ENV_SOURCE))
    ports = PiExecutionPorts(environments, declaration, fingerprint, permission_factory,
        (MODEL,), model, acp_turn_opt_in=True, defer_effect_write_guard_factory=True,
        credential_environment_variable='DEEPSEEK_API_KEY',
        callback_approval_factory=holder.get('callback_approval_factory', generation_file_approval),
        restricted_file_tools=holder.get('restricted_file_tools', False),
        approved_check_command=holder.get('approved_check_command'),
        agent_journal_reopen=holder.get('agent_journal_reopen'))
    runtime = build_product_runtime(runtime_root / 'product', pi_selection=selection, pi_ports=ports,
        method_unit_options=None, library_path=str(runtime_root / 'engineering.sqlite'),
        library_id=CASE_ID,
        scope=scope, create_library=not reuse, schema_version=17,
        machine_capabilities=CAPABILITIES, application_ports_factory=app_factory)
    return runtime, environment, environment_store


def review_section_manifest(scope, method, refs, raw_inputs, claims):
    """Explicit context allocation for this approved Local Library case only."""
    from ordessa_engineering.adapters.decision.source_sections import CONTRACT, complete_sections
    indexes = {role: complete_sections(raw_inputs[name].decode('utf-8', 'strict'))
               for role, name in (('base', 'baseline'), ('proposed', 'candidate'))}
    common = {
        'source-version-preservation': ('SRS.md|### 1.1 ', 'SDD.md|### 1.1 ', 'SRS.md|### LL-REQ-041 '),
        'scoped-read-boundary': ('SRS.md|#### 3.2.1 ', 'SRS.md|#### 3.3.2 ', 'SRS.md|### 3.8 ',
            'SDD.md|### 3.1 ', 'SDD.md|### 4.3 ', 'SDD.md|### B.1 '),
        'evidence-support': ('SRS.md|#### 3.2.1 ', 'SRS.md|### LL-REQ-041 ', 'SDD.md|### 4.2 '),
        'unique-record-authority': ('SRS.md|### 3.4 ', 'SRS.md|### 3.5 ', 'SDD.md|### 4.1 ',
            'SDD.md|### A.1 ', 'SDD.md|### A.3 ', 'SDD.md|## Appendix C.'),
        'public-call-chain': ('SRS.md|#### 3.2.1 ', 'SRS.md|#### 3.3.2 ', 'SDD.md|### 4.2 ',
            'SDD.md|### 4.3 ', 'SDD.md|### B.1 ', 'SDD.md|### B.2 '),
        'changed-source-refusal': (),
        'acceptance-coverage': ('SRS.md|## 4. ', 'SRS.md|## 5. '),
        'declared-limitations': ('SRS.md|### LL-REQ-028 ',),
    }
    amendment = {
        'source-version-preservation': (), 'scoped-read-boundary': (1, 2, 4),
        'evidence-support': (1, 2, 3, 8), 'unique-record-authority': (2, 3),
        'public-call-chain': (2, 3), 'changed-source-refusal': (4, 6),
        'acceptance-coverage': (2, 3, 5, 7, 8), 'declared-limitations': 'whole',
    }
    checks = []
    for claim in claims:
        check_id = claim['check_id']
        chosen = []
        for role, rows in indexes.items():
            # Every check keeps exact source/member identities. Full identity
            # tables belong to preservation/limitations; scoped behavior checks
            # keep the complete candidate status warning and relevant chapters.
            source_raw = raw_inputs['baseline' if role == 'base' else 'candidate']
            chosen.extend({'role': role, 'section': row} for row in rows if
                (row['kind'] == 'front_matter' and check_id in
                 ('source-version-preservation', 'declared-limitations'))
                or (row['member'] is None and row['kind'] == 'chapter')
                or (row['member'] is not None and row['kind'] == 'preamble'
                    and source_raw[row['byte_start']:row['byte_end']].strip()))
            for pattern in common[check_id]:
                member, prefix = pattern.split('|', 1)
                matches = [row for row in rows if row['member'] == member
                           and row['kind'] == 'chapter' and (row['heading'] or '').startswith(prefix)]
                if len(matches) != 1:
                    raise RuntimeError('Case-specific complete context section unavailable')
                chosen.append({'role': role, 'section': matches[0]})
        for member, letter in (('SRS.md', 'D'), ('SDD.md', 'E')):
            prefixes = ([f'## Appendix {letter}.'] if amendment[check_id] == 'whole' else
                        [f'### {letter}.{number} ' for number in amendment[check_id]])
            for prefix in prefixes:
                matches = [row for row in indexes['proposed'] if row['member'] == member
                           and row['kind'] == 'chapter' and (row['heading'] or '').startswith(prefix)]
                if len(matches) != 1:
                    raise RuntimeError('Case-specific complete amendment section unavailable')
                chosen.append({'role': 'proposed', 'section': matches[0]})
        # Supplement the declared context with the smallest COMPLETE source
        # section containing every original DID quotation occurrence. This never
        # changes the claim, quoted evidence, or method judgment semantics.
        for evidence in claim['evidence']:
            if evidence['source'] not in ('baseline', 'candidate'):
                continue
            role = 'base' if evidence['source'] == 'baseline' else 'proposed'
            raw, needle = raw_inputs[evidence['source']], evidence['excerpt'].encode('utf-8')
            start = 0
            while (start := raw.find(needle, start)) >= 0:
                matches = [row for row in indexes[role] if row['byte_start'] <= start
                           and row['byte_end'] >= start + len(needle)]
                if not matches:
                    raise RuntimeError('Original evidence lacks complete chapter coverage')
                chosen.append({'role': role, 'section': min(matches,
                    key=lambda row: row['byte_end'] - row['byte_start'])})
                start += 1
        unique = {(row['role'], row['section']['section_id']): row for row in chosen}
        chosen = [row for key, row in unique.items() if not any(
            other_key != key and other['role'] == row['role']
            and other['section']['byte_start'] <= row['section']['byte_start']
            and other['section']['byte_end'] >= row['section']['byte_end']
            for other_key, other in unique.items())]
        chosen.sort(key=lambda row:(row['role'], row['section']['byte_start']))
        checks.append({'check_id': check_id, 'related_sections': chosen})
    return {'contract': CONTRACT, 'scope': asdict(scope), 'method_ref': asdict(method),
            'sources': [{'role': role, 'source_ref': asdict(refs[name])}
                        for role, name in (('base', 'baseline'), ('proposed', 'candidate'))],
            'checks': checks}


def application_factory(root, holder, *, live, long_context=False, review_input_mode='complete'):
    if review_input_mode not in ('complete', 'sections-v1'):
        raise ValueError('Explicit source review input mode required')
    def build(factory, access, selected_scope):
        from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
        from ordessa_engineering.adapters.filesystem.project_sources import ProjectSourceMaterials
        from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
        from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
        from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
        from ordessa_engineering.adapters.decision.source_bindings import DeclaredSourceReviewBindings
        from ordessa_engineering.adapters.decision.source_reviewer import DecisionReviewerSource
        from ordessa_engineering.application.api.method_publication import publish_method_declaration
        from ordessa_engineering.application.api import ApplicationError
        from ordessa_engineering.application.assembly import build_method_management
        from ordessa_engineering.application.usecases.reviews.admission import EngineeringReviewAdmission
        from ordessa_engineering.domain.artifacts.provenance import SourceRef, SourceLocator, VersionCapture
        from ordessa_engineering.domain.common.models.identity import Scope, ActorRef
        from ordessa_engineering.domain.common.models.values import Digest
        from ordessa_engineering.methods import load_method
        from ordessa_engineering.methods.definitions.models import MethodSource
        from decision_runtime import DecisionServices, ReadContext, FileEvidenceSink, PolicyRef
        from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
        from ordessa_server.composition.temporary_process_capability import ExistingOpenCodeInput
        from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts
        from ordessa_engineering.adapters.native_records import build_local_dispatch_bindings
        from ordessa_units.public import unit_services
        from ordessa_server.composition.engineering_native_dispatch_assembly import bind_engineering_native_generation

        def request_name(value):
            return REQUEST_PREFIX + value
        runtime = holder['runtime']
        reuse = holder.get('reuse_existing_runtime') is True
        caller = runtime.wire.identity_authority.authenticate('Bearer ' + runtime.token)
        scope = Scope(selected_scope.realm_id, selected_scope.project_id)
        with access.admit(caller, selected_scope, 'engineering.references.resolve',
                          request_id=request_name('capture-inputs'), trace_id=CASE_ID) as context:
            actor, captured_at = context.authenticated_actor, context.received_at
        project = (Path(holder['frozen_source_files']) if reuse else
                   holder.get('attempt_root', root) / 'caller-files')
        if reuse:
            from ordessa_engineering.domain.artifacts.provenance_codec import decode_source
            frozen_input = json.loads((project/'caller_review_input.txt').read_bytes())
            frozen_source = decode_source(frozen_input['baseline'])
            actor, captured_at = frozen_source.captured_by, frozen_source.captured_at
        else:
            project.mkdir(mode=0o700)
        selection=holder['material_selection']
        raw_inputs=dict(selection['raw_inputs'])
        def source(name, raw):
            did = name in ('baseline', 'candidate')
            return SourceRef('local-library-DID' if did else name, 'document',
                SourceLocator('document', provider='project-files', document_id='local-library-DID' if did else name),
                VersionCapture('local-library-claims-r5' if name=='caller_review_input' else
                    'local-library-review-sections-r2' if name=='question_sections' else selection['versions'][name],
                    Digest('sha256', hashlib.sha256(raw).hexdigest())),
                captured_at, actor, 'text/markdown' if did else 'text/plain', len(raw))
        refs = {name:source(name, raw) for name,raw in raw_inputs.items()}
        claims = selection['claims']
        caller_input = {'scope':asdict(scope), 'baseline':asdict(refs['baseline']), 'candidate':asdict(refs['candidate']),
            'checks':[{'check_id':item['check_id'],'claim':item['claim'],
                'evidence':[{'source_ref':asdict(refs[e['source']]),'excerpt':e['excerpt']} for e in item['evidence']]} for item in claims]}
        for item in claims:
            for evidence in item['evidence']:
                if evidence['excerpt'] not in raw_inputs[evidence['source']].decode():
                    raise RuntimeError('Explicit review excerpt differs')
        caller_raw = json.dumps(caller_input, indent=2).encode()
        if reuse and caller_raw != (project/'caller_review_input.txt').read_bytes():
            raise RuntimeError('Original caller material bytes differ')
        raw_inputs['caller_review_input'] = caller_raw
        refs['caller_review_input'] = source('caller_review_input', caller_raw)
        mappings = []
        for name,raw in raw_inputs.items():
            filename = name + '.txt'
            if reuse:
                if (project/filename).read_bytes() != raw:
                    raise RuntimeError('Original source material bytes differ')
            else:
                (project/filename).write_bytes(raw)
            mappings.append((refs[name],filename))
        snapshots = SQLiteSnapshotStore(factory.library)
        loaded = load_method(MethodSource(METHOD_DIR,'method.json'), FileResourceReader())
        if not loaded.ok: raise RuntimeError('Fixed method failed to load')
        published = publish_method_declaration(loaded.value,snapshots)
        if not published.ok: raise RuntimeError('Fixed method failed to publish locally')
        method = published.value
        section_ref = None
        if review_input_mode == 'sections-v1':
            section_raw = json.dumps(review_section_manifest(scope, method, refs, raw_inputs, claims),
                                     ensure_ascii=False, indent=2).encode('utf-8')
            section_ref = source('question_sections', section_raw)
            if reuse:
                if (project/'question_sections.txt').read_bytes() != section_raw:
                    raise RuntimeError('Original question sections differ')
            else:
                (project/'question_sections.txt').write_bytes(section_raw)
            mappings.append((section_ref, 'question_sections.txt'))
            holder['question_materials_ref'] = section_ref
        controls = SQLiteMethodControl(factory,snapshots)
        class ExplicitManagement:
            @contextmanager
            def guard_management(self, context, operation, selected_method, parameters):
                access.require(context,operation)
                if operation!='engineering.methods.control' or selected_method!=method:
                    raise RuntimeError('Only this fixed validation method is authorized')
                yield Digest('sha256',hashlib.sha256(json.dumps(parameters,sort_keys=True).encode()).hexdigest())
        management = build_method_management(factory,access=access,snapshots=snapshots,management=ExplicitManagement())
        with access.admit(caller,selected_scope,'engineering.methods.control',request_id=request_name('enable-fixed-method'),trace_id=CASE_ID) as context:
            if reuse:
                with controls.guard(context, method):
                    pass
            else:
                management.control(method,context,expected_version=0,enabled=True,reason='Explicit independent validation of fixed 2.7.2; no human Engineering Grant')
        materials = ProjectSourceMaterials(factory,scope=scope,root=project,source_mappings=tuple(mappings))
        holder['materials'] = materials
        bindings = DeclaredSourceReviewBindings(factory,controls,scope=scope,method_ref=method,
            baseline=refs['baseline'],candidate=refs['candidate'],action_id='incremental.review-change',
            binding_resource_id='source-review-binding',criteria_resource_id='change-review-criteria',
            prompt_resource_id='change-review-prompt',result_schema_resource_id='review-result-schema',
            reviewer_roles=('reviewer',),caller_materials_ref=refs['caller_review_input'],
            caller_input_schema_resource_id='caller-review-input-schema',
            question_materials_ref=section_ref)
        holder['bindings'] = bindings
        blobs = SQLiteBlobStore(factory.library)
        holder['blobs'] = blobs
        read_context = ReadContext(object(), CASE_ID)
        evidence_root = holder.get('runtime_root',root)/'decision-runs'
        if not reuse:
            evidence_root.mkdir(mode=0o700)
        sink = FileEvidenceSink(evidence_root,read_context=read_context)
        holder['sink'] = sink
        settings = JevProviderSettings(binding_ref='opencode-zen-jev/1',secret_ref='selected-jev-credential',
            base_url='https://opencode.ai/inference/systemone',model='jev-1.13-free',
            accepted_response_models=('jev-1.13.0',),timeout_seconds=20,
            long_context=long_context)
        def secret_resolver(ref):
            if ref!='selected-jev-credential': raise RuntimeError('Unknown credential selection')
            if not live: return 'non-secret-preflight-placeholder'
            raw = ExistingOpenCodeInput(holder['jev_source'],variable_name=holder['jev_variable']).read()
            try: return raw.decode('ascii')
            finally: raw[:]=b'\0'*len(raw);raw.clear()
        provider = JevDecisionProvider(settings,secret_resolver=secret_resolver,
            http_client=jev_http_client(holder, settings.timeout_seconds))
        holder['provider'] = provider
        # Pin the exact immutable method resource consumed by the native source
        # reviewer. This remains local and does not call the provider.
        with access.admit(caller, selected_scope, 'engineering.references.resolve',
                          request_id=request_name('pin-source-review-policy'), trace_id=CASE_ID) as context:
            preflight_plan = bindings.plan(context, 'local-source-review-preflight')
            selected = bindings.review_inputs(context, preflight_plan)
            binding_ref = next(ref for ref in selected['refs']
                               if ref.resource_id == bindings.binding_resource_id)
            contract = selected['policy'].get('contract')
            if contract not in ('engineering-source-review/1', 'engineering-source-review/2'):
                raise RuntimeError('Unsupported fixed source-review binding')
            policy_ref = PolicyRef(binding_ref.resource_id,
                '2' if contract == 'engineering-source-review/2' else '1',
                'sha256:' + binding_ref.resource_digest.hex)
        services = DecisionServices(None,None,None,None,provider,sink,{},read_context,
            (policy_ref,),mode='real')
        reviewer = DecisionReviewerSource(factory,blobs,controls,materials,bindings,scope=scope,
            principal_id=caller.principal_id,reviewer=ActorRef('jev-real-source-reviewer','service','explicit-host-selection'),
            roles=('reviewer',),services=services)
        holder['reviewer'] = reviewer
        holder.update(factory=factory,access=access,scope=scope,wire_scope=selected_scope,
            caller=caller,refs=refs,method=method)
        # Validate all caller claims, excerpts, schemas and source pins locally;
        # no decision-provider call is made during this preflight.
        with access.admit(caller, selected_scope, 'engineering.references.resolve',
                          request_id=request_name('validate-source-review-inputs'), trace_id=CASE_ID) as context:
            reviewer._inputs(context, bindings.plan(context, 'local-eight-check-preflight'), 1,
                             'local-preflight-fence')
        admission = EngineeringReviewAdmission(factory,controls,None,reviewer,
            source_materials=materials,method_guard=controls,source_review_bindings=bindings)
        with access.admit(caller, selected_scope, 'engineering.references.resolve',
                          request_id=request_name('validate-source-review-admission'), trace_id=CASE_ID) as context:
            with admission.guard_plan(context, bindings.plan(context, 'local-admission-preflight')):
                pass
        owner = runtime.unit_execution_owner
        _,_,query_factory = build_local_dispatch_bindings(owner,access,
            prompt_parameters=lambda *_args,**_kwargs: (_ for _ in ()).throw(RuntimeError('Generation-only case')))
        def bind(service):
            holder['service']=service
            return bind_engineering_native_generation(service,runtime,
                services=unit_services(runtime.unit_runtime.context),records=owner.records,blobs=blobs,
                query_factory=query_factory, generation_timeout=holder.get('generation_timeout', 60),
                format_rework=holder.get('format_rework'))
        holder.update(factory=factory,access=access,scope=scope,wire_scope=selected_scope,caller=caller,
            actor=actor,captured_at=captured_at,refs=refs,method=method,controls=controls,
            materials=materials,bindings=bindings,reviewer=reviewer,provider=provider,sink=sink,blobs=blobs,
            caller_review_input=caller_input)

        async def review_run(context, plan, request):
            if reuse:
                raise RuntimeError('This new generation reuses the recorded review; JEV dispatch is disabled')
            with access.guard_current_capability(
                    context, selected_scope, 'engineering.reviewer.jev'):
                try:
                    return await reviewer.run_review(context, plan, request)
                except Exception as error:
                    try:
                        diagnostic = jev_failure_for_error(provider, error)
                        if diagnostic is not None:
                            holder['jev_provider_failure'] = diagnostic
                    except Exception as capture_error:
                        holder['jev_diagnostic_capture_error'] = safe_error(capture_error)
                    raise
                finally:
                    # Close the HTTP client on the same loop that issued its
                    # single review run before the synchronous wire call exits.
                    await provider.close()

        def review_plan_factory(context, binding, *, review_id, baseline, candidate):
            if (binding.method_ref != method or baseline != refs['baseline']
                    or candidate != refs['candidate']):
                raise ApplicationError('WORK_ACTION_PLAN_SUBJECT_MISMATCH')
            return bindings.plan(context, review_id)

        return EngineeringApplicationPorts(review_admission=admission,blobs=blobs,
            declared_generation_binder=bind,review_run=review_run,
            review_plan_factory=review_plan_factory)
    return build


def payload(answer):
    if answer.get('record_type')=='command_result': return answer['result']
    if isinstance(answer.get('data'), dict): return answer['data']
    record=answer.get('record')
    return record if isinstance(record,dict) else answer


def progress_projection(result):
    """Small stdout receipt; raw source/model/operation payloads stay private."""
    operation = result.get('operation')
    if not isinstance(operation, dict):
        operation = result.get('operation_cold_read')
    if isinstance(operation, dict):
        operation = payload(operation)
    operation_state = (operation.get('state') if isinstance(operation, dict) else None)
    documents = [{key:item.get(key) for key in ('role','bytes','sha256','formal_read')}
                 for item in result.get('documents', ()) if isinstance(item, dict)]
    review_work = result.get('review_work')
    return {key:result[key] for key in ('case','execution_intent','material_revision','work_id',
            'stage','status','generation_invocations',
            'generation_state','real_jev','review_verdict','jev_run_id','package_ref') if key in result} | {
        'jev_attempt_limit':result.get('jev_attempt_limit'),
        'generation_attempt_limit':result.get('generation_attempt_limit'),
        'operation_state':operation_state,
        'failure':result.get('failure'),
        'jev_provider_failure':result.get('jev_provider_failure'),
        'review_work_state':review_work.get('state') if isinstance(review_work,dict) else None,
        'documents':documents,
        'unit_close':result.get('unit_close', []),
        'cleanup_errors':{key:value for key,value in result.items()
            if key.endswith('_error') or key in ('stop_error','operation_cold_read_error')},
    }


def emit_progress(result):
    print(json.dumps(progress_projection(result), sort_keys=True), flush=True)


def close_generated_units(runtime, unit_before, *, timeout=10.0, observations=None):
    """Retain the original owner while a zero-effect pending close settles.

    Only an explicit pending result permits another idle check. Unknown,
    partial, refused and confirmed outcomes are never retried here. This
    neither sends another prompt nor reconstructs a lost process owner.
    """
    if observations is not None and type(observations) is not list:
        raise ValueError('Explicit close observation list required')
    units = getattr(runtime, 'units', None)
    selected = tuple(unit for unit in (() if units is None else units.list())
                     if unit not in unit_before)
    if not selected:
        return [], []
    authorization = runtime.unit_execution_owner.authorization()
    states, attempts = [None] * len(selected), [0] * len(selected)
    pending = tuple(range(len(selected)))
    started = time.monotonic()
    deadline = started + timeout
    while pending:
        next_pending = []
        for index in pending:
            outcome = selected[index].close(authorization)
            states[index] = outcome.get('state')
            attempts[index] += 1
            if observations is not None:
                from ordessa_infrastructure.encoding.immutable_json import safe_json
                try:
                    observation = json.loads(safe_json(outcome.get('quiescence', {})))
                except Exception:
                    observation = {'reason': 'observation_unavailable'}
                observations.append({'unit_index': index, 'attempt': attempts[index],
                    'observed_at_unix': time.time(), 'elapsed_seconds': time.monotonic() - started,
                    'state': states[index], 'unresolved': outcome.get('unresolved') is True,
                    'quiescence': observation})
            if states[index] == 'pending' and outcome.get('unresolved') is True:
                next_pending.append(index)
        pending = tuple(next_pending)
        remaining = deadline - time.monotonic()
        if not pending or remaining <= 0:
            break
        time.sleep(min(.05, remaining))
    return states, attempts


def retain_generation_owner(runtime, unit_before, *, on_observation, wait_for_resume,
                            before_runtime_stop=None):
    """Never return an unclosed one-shot owner; never recreate or replay it.

    Waiting controls inspection only. Uncertain native outcomes are retained
    without another close attempt; only explicit zero-effect pending can retry.
    """
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    initial_error = None
    selected, authorization = (), None
    try:
        units = getattr(runtime, 'units', None)
        selected = tuple(unit for unit in (() if units is None else units.list())
                         if unit not in unit_before)
        authorization = runtime.unit_execution_owner.authorization() if selected else None
    except BaseException as error:
        initial_error = safe_error(error)
    states, attempts = [None] * len(selected), [0] * len(selected)
    retryable = [initial_error is None] * len(selected)
    details = [{} for _ in selected]
    disposed = False
    while True:
        for index, unit in enumerate(selected):
            if states[index] == 'confirmed' or not retryable[index]:
                continue
            attempts[index] += 1
            try:
                outcome = unit.close(authorization)
                states[index] = outcome.get('state')
                retryable[index] = states[index] == 'pending' and outcome.get('unresolved') is True
                try:
                    details[index] = {'quiescence': json.loads(safe_json(outcome.get('quiescence', {})))}
                except Exception:
                    details[index] = {'quiescence': {'reason': 'observation_unavailable'}}
            except BaseException as error:
                states[index] = 'unknown'
                retryable[index] = False
                details[index] = {'error': safe_error(error)}
        stop_error = None
        if initial_error is None and all(state == 'confirmed' for state in states):
            try:
                if not disposed:
                    if before_runtime_stop is not None:
                        before_runtime_stop()
                    disposed = True
                runtime.stop()
                if runtime.stop_state != 'completed':
                    raise RuntimeError('Original runtime stop has no confirmed outcome')
                return states, attempts
            except BaseException as error:
                stop_error = safe_error(error)
        observation = {'state': 'OWNER_RETAINED', 'runtime_stopped': False,
            'observed_at_unix': time.time(),
            'units': [dict(index=index, state=states[index], attempts=attempts[index], **details[index])
                      for index in range(len(selected))]}
        if stop_error is not None:
            observation['stop_error'] = stop_error
        if initial_error is not None:
            observation['initialization_error'] = initial_error
        if any(state != 'confirmed' and not retryable[index]
               for index, state in enumerate(states)):
            observation['inspection_required'] = True
            # Refresh the original public owner view on every inspection. A
            # read never converts UNKNOWN/partial/refused into close authority
            # and never reconstructs a lost Unit or retries native effects.
            inspection = []
            for index, unit in enumerate(selected):
                try:
                    snapshot = getattr(unit, 'snapshot', None)
                    if states[index] == 'confirmed' or not callable(snapshot):
                        continue
                    current = snapshot().get('state')
                    current = current if current in {'prepared', 'notCreated', 'opening', 'unknown',
                        'confirmed', 'stopped', 'released', 'releasePending'} else 'unavailable'
                    inspection.append({'index': index, 'owner_state': current})
                except BaseException as error:
                    inspection.append({'index': index, 'error': safe_error(error)})
            if inspection:
                observation['inspection'] = inspection
        try:
            on_observation(observation)
        except BaseException:
            pass  # A failed receipt writer cannot authorize discarding its owner.
        try:
            wait_for_resume(observation)
        except BaseException:
            time.sleep(1)


def wait_generation_owner_resume(observation):
    """Keep the same process; only pending zero-effect checks advance unaided."""
    if ('stop_error' not in observation and 'initialization_error' not in observation
            and observation.get('inspection_required') is not True
            and observation['units'] and all(unit['state'] in {'pending', 'confirmed'}
                                    for unit in observation['units'])):
        time.sleep(1)
        return
    try:
        # EOF/disconnection retains the owner too. There is no prompt/relaunch
        # command on this inspection surface.
        input('Owner retained; press Enter to inspect the same owner again: ')
    except (EOFError, KeyboardInterrupt):
        time.sleep(1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-real',action='store_true')
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--material-manifest',type=Path,required=True)
    parser.add_argument('--material-manifest-sha256',required=True)
    parser.add_argument('--jev-source',default=ENV_SOURCE)
    parser.add_argument('--jev-variable',choices=('OPENCODE_API_KEY','OPEN_CODE_GO_API_KEY'),default=None)
    parser.add_argument('--jev-long-context',action='store_true')
    parser.add_argument('--review-input-mode',choices=('complete','sections-v1'),default='complete')
    args=parser.parse_args()
    root=args.root.absolute()
    if (root.parent.resolve()!=(ROOT/'.nightly-cache').resolve() or root.is_symlink()
            or root.exists() or root.name==CASE_ID):
        raise SystemExit('A fresh private direct cache child is required; no historical replay')
    selection=load_materials(args.material_manifest,args.material_manifest_sha256)
    model=selected_model()
    if args.run_real:
        if root.name != REAL_ROOT_NAME:
            raise SystemExit('This authorized case has one fixed live root; query an existing attempt instead of selecting another root')
        if args.jev_variable is None:
            raise SystemExit('Explicit authorized JEV credential variable is required')
        from ordessa_server.composition.temporary_process_capability import ExistingOpenCodeInput
        for source,variable in ((ENV_SOURCE,'DEEPSEEK_API_KEY'),(args.jev_source,args.jev_variable)):
            raw=ExistingOpenCodeInput(source,variable_name=variable).read()
            raw[:]=b'\0'*len(raw);raw.clear()
    root.mkdir(mode=0o700,exist_ok=False)
    attempt_root=root
    holder={'material_selection':selection,'attempt_root':root,
        'jev_source':args.jev_source,'jev_variable':args.jev_variable}
    runtime=None;unit_before=()
    result={'case':CASE_ID,'execution_intent':EXECUTION_INTENT,'request_prefix':REQUEST_PREFIX,
        'material_revision':selection['revision_id'],
        'review_input_mode':args.review_input_mode,
        'material_manifest_digest':selection['manifest_digest'],'stage':'preflight',
        'jev_attempt_limit':8,'generation_attempt_limit':1,'generation_invocations':0,
        'real_jev':False,'package_registered':False,'documents':[],
        'historical_replay':False,'method_edited':False,'server_listener_started':False,
        'started_at':datetime.now(timezone.utc).isoformat()}
    def request_name(value):return REQUEST_PREFIX + value
    try:
        runtime,environment,_=compose(root,model,application_factory(root,holder,
            live=args.run_real,long_context=args.jev_long_context,
            review_input_mode=args.review_input_mode),holder)
        holder['runtime'] = runtime
        result['configuration']={'provider':PROVIDER,'model':MODEL,'base_url':ENDPOINT,'retry':RETRY_OFF,
            'jev_model':'jev-1.13-free','jev_endpoint':'https://opencode.ai/inference/systemone/v1/systemone',
            'jev_long_context_requested':args.jev_long_context,
            'machine_authority':'original InstanceAccessAuthority; not a human grant'}
        result['method_ref']=asdict(holder['method'])
        if not args.run_real:
            result['status']='PREFLIGHT_READY';emit_progress(result);return 0
        runtime.start()
        unit_before=tuple(runtime.units.list())
        def invoke(operation,parameters,request_id):
            receipt_name = request_id
            request_id = request_name(request_id)
            if operation in ('engineering.proposals.create', 'engineering.work.start',
                    'engineering.work.invoke', 'engineering.reviews.request',
                    'engineering.reviews.record', 'engineering.proposals.associate_review'):
                holder['last_operation_request'] = request_id
            descriptor=runtime.plugin_host.methods.lookup(operation)
            if descriptor is None: raise RuntimeError('Formal Engineering operation unavailable')
            answer=asyncio.run(descriptor.handler({'scope':asdict(holder['wire_scope']),
                'requestId':request_id,'parameters':parameters},holder['caller']))
            save(attempt_root/(receipt_name+'.json'),answer)
            return answer
        from ordessa_engineering.domain.changes.models import Proposal,SourceChange
        from ordessa_engineering.domain.changes.codec import encode_proposal
        from ordessa_engineering.domain.changes.ref_codec import decode_proposal_ref
        from ordessa_engineering.domain.common.models.identity import Scope
        from ordessa_infrastructure.encoding import decode_json
        scope,method,refs=holder['scope'],holder['method'],holder['refs']
        with holder['access'].admit(holder['caller'],holder['wire_scope'],'engineering.references.resolve',
                request_id=request_name('exact-source-resources'),trace_id=CASE_ID) as context:
            with holder['controls'].guard(context,method) as definition:
                resources=tuple(holder['controls'].resource_ref(context,method,item.resource_id) for item in definition.resources)
        proposal=Proposal(scope,'caller-draft',holder['captured_at'],holder['actor'],'unspecified-change',
            'Prepare the implementation package for fixed Local Library search candidate',
            'Design review and generation only; search is not implemented or accepted; full DID conformance gaps remain',
            (),(),(),(),method,(),None,(),2,SourceChange(refs['baseline'],refs['candidate'],resources))
        encoded=decode_json(encode_proposal(proposal))
        draft={key:encoded[key] for key in ('intent','rationale','mutations','basis_sources','claim_refs','evidence_links',
            'method_ref','review_requirement_templates','implementation_intent','supersedes_refs','source_change')}
        created=invoke('engineering.proposals.create',{'change_id':None,'expected_version':0,'draft':draft},'create-proposal')
        proposal_ref=decode_proposal_ref(payload(created)['proposal_ref'])
        work_id=WORK_ID
        result['work_id'] = work_id
        invoke('engineering.work.start',{'work_id':work_id,'revision':1,'method_ref':asdict(method),
            'associations':[{'kind':'proposal','ref':asdict(proposal_ref)}]},'start-review-work')
        result['stage']='formal_work_review'
        emit_progress(result)
        reviewed=invoke('engineering.work.invoke',{'work_id':work_id,'action_id':'incremental.review-change',
            'inputs':{'baseline':asdict(refs['baseline']),'candidate':asdict(refs['candidate']),
                'scope':asdict(scope),'method':asdict(method),
                'caller_review_input':holder['caller_review_input']}},'invoke-review-work')
        review_business=payload(reviewed)
        review_steps=review_business.get('steps', [])
        recorded_step=next((step.get('business') for step in review_steps
                            if step.get('step_id')=='record'),None)
        registered_step=next((step.get('business') for step in review_steps
                              if step.get('step_id')=='register'),None)
        result['review_work']=review_business
        if recorded_step:
            result['review_verdict']=recorded_step.get('verdict')
            result['review_ref']=recorded_step.get('review_ref')
        compare_step=next((step.get('business') for step in review_steps
                           if step.get('step_id')=='compare'),None)
        review_receipt=(compare_step or {}).get('receipt') if isinstance(compare_step,dict) else None
        if isinstance(review_receipt,dict):
            result['jev_run_id']=review_receipt.get('run_id')
            result['real_jev']=type(result['jev_run_id']) is str
            recorded_result=review_receipt.get('result')
            checks=recorded_result.get('checks', []) if isinstance(recorded_result,dict) else []
            if isinstance(checks, (list, tuple)):
                result['jev_choices']=[{'check_id':item.get('check_id'),
                    'choice':item.get('choice')} for item in checks if isinstance(item,dict)]
        if review_business.get('state')!='completed' or not recorded_step or not registered_step:
            result['review_operation']=payload(invoke('engineering.operations.get',
                {'request_id':request_name('invoke-review-work')},'read-review-operation'))
            result['status']='REVIEW_BLOCKED' if result.get('review_verdict')=='fail' else 'REVIEW_WORK_FAILED'
            return 1
        if result['review_verdict']!='pass':
            result['status']='REVIEW_BLOCKED'
            return 1
        change_ref=registered_step.get('proposal_ref')
        if type(change_ref) is not dict:
            result['status']='REVIEW_SUCCESSOR_MISSING'
            return 1
        result['review_work']=review_business
        emit_progress(result)
        result['stage']='work_generation'
        invoke('engineering.work.start',{'work_id':work_id,'revision':2,'method_ref':asdict(method),
            'associations':[{'kind':'proposal','ref':change_ref}]},'start-generation-work')
        from ordessa_execution_agents.profiles import encode_revision_ref
        result['generation_invocations']=1
        # Persist the one-shot boundary before dispatch. If the host disconnects
        # after this point, reconcile the original operation; never invoke again.
        result['generation_invocation_started_at']=datetime.now(timezone.utc).isoformat()
        save(attempt_root/'receipt.json',result)
        emit_progress(result)
        generated=invoke('engineering.work.invoke',{'work_id':work_id,'action_id':'incremental.prepare-packages',
            'inputs':{'baseline':asdict(refs['baseline']),'candidate':asdict(refs['candidate']),'scope':asdict(scope),
                'review':result['review_ref'],'method':asdict(method),
                'profile':encode_revision_ref(runtime.unit_execution_owner.permission.profile_revision)}},'invoke-generation-work')
        business=payload(generated)
        generation=next((s['business'] for s in business.get('steps',[]) if s.get('business',{}).get('package_ref')),None)
        result['generation_state']=business.get('state')
        if generation:
            from ordessa_engineering.domain.packages.codec import decode_package_ref
            from ordessa_engineering.adapters.persistence.sqlite.package_document_materials import PackageDocumentMaterials
            from ordessa_engineering.application.usecases.material_closure import verify_external_source
            package_ref=decode_package_ref(generation['package_ref'])
            with holder['factory'].begin(scope,'read') as uow: package=uow.implementation.resolve_package(package_ref)
            result['package_registered']=True;result['package_ref']=asdict(package_ref)
            result['stage']='formal_document_reads'
            archive=PackageDocumentMaterials(holder['factory'],holder['blobs'],scope=scope,package_ref=package_ref)
            with holder['access'].admit(holder['caller'],holder['wire_scope'],'engineering.references.resolve',
                    request_id=request_name('read-generated-documents'),trace_id=CASE_ID) as context:
                for doc in package.payload.documents:
                    raw=verify_external_source(context,doc.source_ref,archive)
                    (attempt_root/(doc.role+'.md')).write_bytes(raw)
                    result['documents'].append({'role':doc.role,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'formal_read':True})
            # Reopen the same committed Library through its public owner. Fresh
            # admission still uses the active original instance authority.
            from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
            from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
            from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
            reopened = EngineeringLibrary.open(holder['factory'].library.path,
                library_id=holder['factory'].library.library_id)
            try:
                cold_factory = SQLiteUoWFactory(reopened)
                with cold_factory.begin(scope,'read') as uow:
                    cold_package = uow.implementation.resolve_package(package_ref)
                cold_archive = PackageDocumentMaterials(cold_factory,SQLiteBlobStore(reopened),
                    scope=scope,package_ref=package_ref)
                with holder['access'].admit(holder['caller'],holder['wire_scope'],'engineering.references.resolve',
                        request_id=request_name('cold-read-generated-documents'),trace_id=CASE_ID) as context:
                    cold_documents = []
                    for doc in cold_package.payload.documents:
                        raw = verify_external_source(context,doc.source_ref,cold_archive)
                        cold_documents.append({'role':doc.role,'bytes':len(raw),
                            'sha256':hashlib.sha256(raw).hexdigest(),'formal_read':True})
                if cold_documents != result['documents']:
                    raise RuntimeError('Committed package cold document read differs')
                result['cold_documents'] = cold_documents
                result['package_cold_read'] = True
            finally:
                reopened.close()
        operation=payload(invoke('engineering.operations.get',{'request_id':request_name('invoke-generation-work')},'read-operation'))
        work=payload(invoke('engineering.work.get',{'work_id':work_id},'read-work'))
        result['operation']=operation
        result['work_dispatch']=work.get('generation_dispatch')
        roles=[item['role'] for item in result['documents']]
        complete=(result['package_registered'] and len(roles)==3
            and set(roles)=={'spec','plan','tasks'}
            and all(item.get('formal_read') is True for item in result['documents'])
            and result.get('package_cold_read') is True)
        result['status']='COMPLETED' if complete else 'GENERATION_FAILED'
        emit_progress(result)
        return 0 if result['status']=='COMPLETED' else 1
    except Exception as error:
        result['failure']=safe_error(error);result['status']='BLOCKED'
        if 'jev_provider_failure' in holder:
            result['jev_provider_failure'] = holder['jev_provider_failure']
        if 'jev_diagnostic_capture_error' in holder:
            result['jev_diagnostic_capture_error'] = holder['jev_diagnostic_capture_error']
        # A failed invoke may have crossed the durable boundary. Read its
        # original operation once; never repeat the Work or model request.
        selected_runtime = runtime or holder.get('runtime')
        cold_request = holder.get('last_operation_request')
        if (selected_runtime is not None and getattr(selected_runtime, 'started', False)
                and cold_request is not None):
            try:
                descriptor = selected_runtime.plugin_host.methods.lookup('engineering.operations.get')
                if descriptor is None:
                    raise RuntimeError('Operation query unavailable for cold reconciliation')
                answer = asyncio.run(descriptor.handler({'scope':asdict(holder['wire_scope']),
                    'requestId':request_name('cold-read-operation'),'parameters':{'request_id':cold_request}},
                    holder['caller']))
                save(attempt_root/'failure-operation.json', answer)
                result['operation_cold_read'] = answer
            except Exception as cold_error:
                result['operation_cold_read_error'] = safe_error(cold_error)
        return 1
    finally:
        if 'jev_network_trace' in holder:
            result['jev_network_trace'] = holder['jev_network_trace']
        runtime = runtime or holder.get('runtime')
        if runtime is not None:
            def retained(observation):
                result['owner_retention'] = observation
                result['runtime_stopped'] = False
                save(attempt_root/'receipt.json', result)
                print(json.dumps(observation, sort_keys=True), flush=True)
            def dispose():
                for name in ('reviewer','materials'):
                    if name in holder:
                        holder[name].close()
                async def close_decision():
                    if 'provider' in holder: await holder['provider'].close()
                    if 'sink' in holder: await holder['sink'].close()
                asyncio.run(close_decision())
            states, attempts = retain_generation_owner(runtime, unit_before,
                on_observation=retained, wait_for_resume=wait_generation_owner_resume,
                before_runtime_stop=dispose)
            result['unit_close'] = states
            result['unit_close_attempts'] = attempts
            result['runtime_stopped'] = True
            selected_environment = holder.get('environment', locals().get('environment'))
            if selected_environment is not None:
                result['environment_active_uses']=selected_environment.snapshot.active_uses
        result['finished_at']=datetime.now(timezone.utc).isoformat()
        cleanup_failed=(result.get('status')=='COMPLETED' and (
            result.get('runtime_stopped') is not True
            or result.get('environment_active_uses') != 0
            or any(key.endswith('_error') for key in result)
            or any(state!='confirmed' for state in result.get('unit_close',()))))
        if cleanup_failed:
            result['status']='CLEANUP_INCOMPLETE'
        save(attempt_root/'receipt.json',result)
        emit_progress(result)
        if cleanup_failed:
            return 1


if __name__=='__main__': raise SystemExit(main())
