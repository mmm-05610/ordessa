"""Exact Local Library instruction-backed case; original owners and one dispatch.

This case glue consumes the reviewed M1/M2 entry. Default mode composes only a
complete private snapshot, creates no Unit/Grant, reads no provider key and
contacts no provider. Real mode is an explicit one-shot invocation. Historical
roots, UNKNOWNs and consumed grants are never reopened for writes or retried.
"""
from __future__ import annotations
import argparse
import ast
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
ORIGINAL = ROOT / '.nightly-cache/local-library-sections-r2-capacity-real-20261017-0316'
TARGET = Path('/home/maoqh/projects/ordessa-demo-local-library')
ACTION, STEP = 'incremental.implement-package', 'implement'
WORK = INTENT_DIGEST = None
FIXED_WORK = 'local-library-instruction-implementation-20261017-180413'
# Trusted operator selection, pinned with the candidate; never derived from wire
# input. Historical cases retain their original four-hour window.
GRANT_VALIDITY_SECONDS = 14400
REGISTERED_RUNTIME = ROOT / '.nightly-cache' / FIXED_WORK / 'registered-runtime.json'
BRIDGE = Path('/tmp/ordessa-library-b3-catalog-acp-20261017-1005')
BRIDGE_SHA = 'ff022463da951f170218d106f551b5f467fa2293da3c738d6beeedee396ae227'
FROZEN_PACKAGE_DIGEST = '201104e51dc0d2db77f9975f160d338761f99643b88f9d8a79a77fef3e11b724'
CHECK_CONFIGURATION = ROOT / '.nightly-cache/local-library-check-prepared-20261017-1008/configuration.json'
CHECK_CONFIGURATION_SHA256 = '30cb4a3d5ee19c965b5e336bae6c77e7cfb8e8caa1f51a2097097ff80c5bd9aa'
MATERIAL_MANIFEST = ROOT / '.nightly-cache/local-library-generation-20261016/inputs/citation-r5/INPUT-MANIFEST.json'
MATERIAL_MANIFEST_SHA256 = 'a0c0accd5bd9774b42027b3ed5083fc541475b6fc8fd63285da81079dcee577b'
PREVIOUS_SOURCE_PINS = ROOT / '.nightly-cache/local-library-implementation-third-20261017-1310/sources-r2.json'
BEFORE = {
    'catalog/views.py': '66f25c44b460f5b92e223d4f29bfa129734a9b71fc8fc4bd057ae992e90cf580',
    'catalog/templates/catalog/book_list.html': '320c07af7c3c3f598d1568b0c408a05c169ca2795f5bd37f4007a5c6c449dcf9',
    'catalog/tests/test_views.py': '6cf3846f7a7627cb2d72fe0435a40e930a46fec83cb072cf97131c17627799de',
    'catalog/tests/test_search.py': None}
CAPS = ('engineering.work.get', 'engineering.work.invoke', 'engineering.operations.get',
    'engineering.approvals.get', 'engineering.approvals.get_control', 'engineering.approvals.get_budget',
    'engineering.executions.dispatch', 'engineering.submissions.record_report',
    'engineering.reviews.request', 'engineering.reviews.assign_reviewer', 'engineering.reviews.record',
    'engineering.reviewer.unit', 'engineering.conversation.attest', 'engineering.notices.publish',
    'engineering.approvals.prepare_intent', 'engineering.approvals.request',
    'engineering.approvals.get_challenge', 'engineering.approvals.record_conversation')
M1 = ROOT / 'apps/server/src/ordessa_server/composition/engineering_declared_work_case_assembly.py'
M2 = ROOT / 'tooling/checks/server_product/run_declared_work_case.py'
PINNED = {str(M1):'29a7784e1c85d5cd343f67d8c0d8e96a67c4bef8b90a79fc341621241a9ac89e',
    str(M2):'13ec258ba6fa4aed409288470f97816362c1386ce594b8830acc895debe4d353',
    str(ROOT/'tooling/checks/server_product/probe-work-package-generation.py'):
    'a5f0bd45ef859061edc3598466e6972a35a868a1d66a8c3e4b2064144fe922bd',
    str(BRIDGE):BRIDGE_SHA}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()
    with Path(path).open('xb') as handle:
        handle.write(raw)
    os.chmod(path, 0o600)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def plain(value):
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    return json.loads(safe_json(value))


def target_hashes():
    result = {}
    for name in BEFORE:
        path = TARGET / name
        if any(part.is_symlink() for part in (path, *path.parents)):
            raise RuntimeError('Target symlink refused')
        result[name] = sha(path) if path.exists() else None
    return result


def graph_files(root):
    result = {}
    for path in root.rglob('*'):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RuntimeError('State graph symlink refused')
        if path.is_file():
            result[name] = sha(path)
    return result


def protected_original():
    # No credential bytes are opened or copied from the historical root.
    return {p.relative_to(ORIGINAL).as_posix(): sha(p) for p in ORIGINAL.rglob('*')
        if p.is_file() and 'secrets' not in p.relative_to(ORIGINAL).parts}


def prepare_snapshot(output, entry):
    frozen = output / 'frozen-owner-graph'
    frozen.mkdir(mode=0o700)
    original_before = protected_original()
    exclusions = []
    for path in ORIGINAL.rglob('*'):
        relative = path.relative_to(ORIGINAL)
        if 'secrets' in relative.parts or relative.as_posix() == 'product/server.lock':
            if path.is_file():
                exclusions.append(relative.as_posix())
            continue
        if path.is_symlink():
            raise RuntimeError('Historical symlink refused')
        if path.is_file():
            destination = frozen / relative
            destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with destination.open('xb') as handle:
                handle.write(path.read_bytes())
            os.chmod(destination, 0o600)
    if original_before != protected_original():
        raise RuntimeError('Historical graph changed during freeze')
    manifest = graph_files(frozen)
    for name in entry.FROZEN_ROOT_REQUIRED:
        if manifest.get(name) != original_before.get(name):
            raise RuntimeError('Incomplete original owner graph')
    save(output / 'snapshot-source.json', {'files':manifest,
        'original_files_sha256':original_before, 'excluded_original_paths':exclusions,
        'credentials_copied':False, 'historical_root_opened_for_write':False,
        'scope':'complete original state databases/caller/evidence graph; credential files and process lock excluded'})
    cloned = entry.clone_frozen_root(frozen, output/'runtime', manifest=manifest)
    # mkdir(parents=True) gives intermediate directories the process umask,
    # while the original evidence owner requires private 0700 directories.
    # Apply this only to the newly created private graph, before any owner opens it.
    for directory in (output/'runtime', *(p for p in (output/'runtime').rglob('*') if p.is_dir())):
        os.chmod(directory, 0o700)
    save(output/'clone-before-composition.json',cloned)
    return output/'runtime', original_before


class FrozenScope:
    """This case's product policy; every approval rereads the original Grant."""
    def __init__(self):
        self.holder = None
        self.review_id = None
        import ordessa_units.public
        config_path = CHECK_CONFIGURATION
        if hashlib.sha256(config_path.read_bytes()).hexdigest() != CHECK_CONFIGURATION_SHA256:
            raise RuntimeError('Prepared check configuration changed')
        config = json.loads(config_path.read_bytes())
        producer = load_module('successor_catalog_check_runtime', ROOT / 'tooling/checks/server_product/local_library_check_runtime.py')
        self.check_command, self.check_approval_factory, self.check_verify = producer.fixed_catalog_check(
            python_executable=config['python_executable'], runner=config['runner'], project_root=TARGET,
            pinned_files=config['pinned_files'], runtime_tree_digest=config['runtime_tree_digest'],
            allowed_paths=tuple(str(TARGET / name) for name in BEFORE), scope_guard=self.callback)
        if self.check_command != config['approved_check_command']:
            raise RuntimeError('Prepared check command differs')

    def bind(self, holder):
        if self.holder is not None:
            raise RuntimeError('Case scope already bound')
        self.holder = holder

    def grant(self, uow):
        from ordessa_engineering.application.usecases.packages.authorization import resolve_work_package_authorization
        from ordessa_engineering.application.usecases.support.clock import utc_now
        h = self.holder
        if h.get('preapproval_build_only') is True or h.get('grant_ref') is None:
            raise RuntimeError('Instruction has no formally registered Grant')
        grant = uow.authorization.get_grant(h['grant_ref'])
        control = uow.authorization.get_control(grant.ref)
        if (grant.ref != h['grant_ref'] or grant.intent.digest.hex !=
                INTENT_DIGEST
                or control != {'state': 'granted', 'version': 0, 'revoked_at': None}
                or not grant.intent.not_before <= utc_now() < grant.intent.expires_at
                or (datetime.fromisoformat(grant.intent.expires_at.replace('Z','+00:00'))
                    - datetime.fromisoformat(grant.intent.not_before.replace('Z','+00:00'))).total_seconds() != GRANT_VALIDITY_SECONDS):
            raise RuntimeError('Original Grant is no longer current')
        facts = resolve_work_package_authorization(uow, grant.intent.authorization)
        auth = grant.intent.authorization
        frozen = json.loads(auth.request_summary)
        if (auth.work_id != WORK or auth.action_id != ACTION or auth.step_id != STEP
                or auth.work_revision != 1 or auth.package_ref.digest.hex !=
                    FROZEN_PACKAGE_DIGEST
                or frozen['root'] != str(TARGET) or frozen['before_sha256'] != BEFORE
                or set(frozen['allowed_operations']) != set(BEFORE)
                or auth.actions != ('edit_repository', 'run_checks')):
            raise RuntimeError('Original frozen authorization differs')
        return grant, facts, control

    @contextmanager
    def work_scope(self, context, package_ref, unit_ref, scopes):
        h = self.holder
        h['access'].require(context, 'engineering.executions.dispatch')
        with h['factory'].begin(h['scope'], 'read') as uow:
            grant, facts, _ = self.grant(uow)
            if package_ref != facts.package.ref or scopes != grant.intent.authorization.scope_by_action:
                raise RuntimeError('Case effect scope changed')
        owner = h['runtime'].unit_execution_owner
        unit = owner.manager.get(unit_ref)
        owner.native_unit(unit, owner.authorization())
        # The original dispatcher revalidates Grant/debits in its own write
        # transaction. Do not leave a read UoW open across that transaction.
        yield

    def tip_binding(self, uow, scope):
        """The persisted tip binding of this step, with its continuation chain.

        A continuation attempt is the tip only after the owner's own chain walk
        proves it: ``resolve_continuation_root`` re-reads every predecessor
        row and refuses a break, a skipped attempt or a forged marker. Taking the
        latest row alone would be blind; taking attempt 1 alone would reject the
        legitimate successor Unit.
        """
        from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
        from ordessa_engineering.application.usecases.changes.dispatch_continuation import (
            resolve_continuation_root,
        )
        from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
        key = work_dispatch_key(WORK, ACTION, STEP)
        attempt = uow.work_dispatch.latest_attempt(key, STEP, scope)
        row = uow.work_dispatch.get(key, STEP, attempt, scope)
        binding = decode_dispatch(row['binding_bytes'])
        resolve_continuation_root(uow, binding)
        return row, binding

    @contextmanager
    def callback(self, *, unit_ref, session_id, method, params):
        from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
        from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
        from ordessa_engineering.application.usecases.changes.declared_report import resolve_declared_report_binding
        from ordessa_units.api import UnitApiRefused
        h = self.holder
        if h is None:
            raise UnitApiRefused('Original case Grant has not been bound')
        with h['factory'].begin(h['scope'], 'read') as uow:
            grant, _, control = self.grant(uow)
            try:
                row, binding = self.tip_binding(uow, h['scope'])
            except UnitApiRefused:
                raise
            except Exception as error:
                # A missing, broken or forged continuation relation is refused
                # by name, never replaced by attempt 1 or by "latest wins".
                raise UnitApiRefused('Persisted step binding is not this callback') from error
            if (binding.approval_ref != grant.ref or binding.intent_digest != grant.intent.digest
                    or binding.control_version != control['version']
                    or {a for a, _ in binding.action_instances} != set(grant.intent.actions)):
                raise UnitApiRefused('Original dispatch authority changed')
            author = json.loads(binding.unit_ref_bytes)
            if plain(unit_ref) == author:
                if row['dispatch_phase'] != 'possibly_written':
                    raise UnitApiRefused('Implementation is outside its original write cut')
            else:
                if self.review_id is None or row['dispatch_phase'] != 'completed':
                    raise UnitApiRefused('No original independent review assignment')
                assignment, ctl = uow.reviewer_assignments.active_for_review(self.review_id)
                request = uow.reviews.get_request(self.review_id)
                plan = uow.reviews.get_plan(self.review_id)
                submission = uow.submissions.resolve(plan.requirement.expected_targets.targets[0].ref)
                if (ctl.state != 'active' or request.state != 'requested'
                        or assignment.request_version != request.version or assignment.fence != request.fence
                        or assignment.plan_digest != plan.plan_digest
                        or assignment.reviewer_unit_ref != plain(unit_ref)
                        or assignment.author_unit_ref_bytes != binding.unit_ref_bytes
                        or resolve_declared_report_binding(uow, submission) != binding
                        or method != 'fs/read_text_file' and (method != 'session/request_permission'
                            or params.get('toolCall', {}).get('kind') != 'read')):
                    raise UnitApiRefused('Independent review is read-only under its current assignment')
            # Original UnitFileCallbackApproval additionally verifies retained
            # Unit/session, live permission, cwd and each exact path/allow-once.
            yield

    def callback_factory(self, **kwargs):
        return self.check_approval_factory(**kwargs)


def assemble_with_mode(entry, *, continuation, **kwargs):
    """The one place the CLI continuation switch reaches the binder.

    ``compose`` calls this with the real entry module, so a spy entry in a test
    observes exactly the call the real graph would receive - the switch is not a
    separate helper that production never uses.
    """
    return entry.assemble_declared_work_case(**kwargs, continuation=continuation is not None)


def compose(output, graph, candidate, policy, entry, driver, *, real,
            environment_identity=None, continuation=None):
    import ordessa_units.public
    from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
    from ordessa_environments_local import LocalEnvironmentResourceProvider
    from ordessa_agents.profiles import ProfileService, decode_revision_ref
    from ordessa_units.bindings.profile_admission import UnitProfileAdmission
    from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
    from ordessa_units.assembly import UnitRunPermission
    from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
    from ordessa_interfaces.system_access.contracts.refs import Scope
    from ordessa_server.composition.configuration.product_selection import create_host_product_composition
    from ordessa_server.composition.product_native_configuration import construct_pi_harness_declaration
    from ordessa_server.composition.pi_selection import PiExecutionSelection, PiExecutionPorts
    from ordessa_server.composition.agent_owner import AgentJournalReopen
    from ordessa_server.composition.conversation_attestor import RegisteredMainAgentAttestor
    from ordessa_server.composition.engineering_chat_confirmation import FrozenChatInstruction, MainAgentChatConfirmation
    from ordessa_engineering.adapters.confirmation.conversation import ConversationAdmission
    from ordessa_engineering.application.usecases.packages.authorization import ImplementationIntentAdmission
    from ordessa_engineering.domain.approvals.consent import WorkPackageNotice
    from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorizationIntent
    from ordessa_engineering.domain.approvals.consent_codec import decode_record
    from ordessa_engineering.domain.common.models.identity import ActorRef
    from ordessa_infrastructure.encoding import canonical_bytes
    fingerprint = ProtectedFingerprintHmac({'process-only': os.urandom(32)}, active_key_id='process-only')
    setup = create_host_product_composition(fingerprint_port=fingerprint).default_runtime(graph/'product')
    try:
        context = setup.unit_runtime.context
        namespace = context.environment_namespace
        declaration = construct_pi_harness_declaration(setup, bridge_executable=BRIDGE,
            pi_executable=driver.PI, reviewed_bridge_sha256=BRIDGE_SHA)
        ref = decode_revision_ref(candidate['fixed_profile_ref'])
        if ProfileService(UnitProfileAdmission(context)).get_revision(ref).ref != ref or ref.environment_namespace != namespace:
            raise RuntimeError('Original immutable Profile differs')
    finally:
        setup.stop()
    environment_root = graph/'local-environment'
    environment_root.mkdir(mode=0o700, exist_ok=True)
    environment_store = SQLiteEnvironmentStore(graph/'environments.sqlite')
    environments = EnvironmentManager(store=environment_store,
        providers={'local':LocalEnvironmentResourceProvider(default_root=str(environment_root))})
    # Register a fresh local resource inside this private graph. Historical
    # Environment identities/backend IDs are retained untouched, never relocated.
    environment = (environments.get(environment_identity) if environment_identity is not None
                   else environments.register('local',str(environment_root)))
    if environment.snapshot.backend_id != str(environment_root):
        raise RuntimeError('Private environment backend changed')
    scope = Scope(namespace, driver.CASE_ID)
    product = graph/'product'
    identity = lambda path:(path.stat().st_dev,path.stat().st_ino)
    reopen = AgentJournalReopen(expected_namespace=namespace, root_path=str(product),
        root_identity=identity(product),core_identity=identity(product/'state/core.sqlite'),
        journal_identity=identity(product/'state/agent-owner/operations.sqlite'))
    h = dict(material_selection=driver.load_materials(
        MATERIAL_MANIFEST, MATERIAL_MANIFEST_SHA256),
        attempt_root=output,runtime_root=graph,reuse_existing_runtime=True,
        environment_identity=environment.identity,profile_revision=candidate['fixed_profile_ref'],
        frozen_source_files=graph/'caller-files',candidate_intent_digest=INTENT_DIGEST,
        environment=environment, environment_store=environment_store,
        jev_source=driver.ENV_SOURCE,jev_variable='OPEN_CODE_GO_API_KEY',
        case_scope=policy,output=output,driver=driver,preapproval_build_only=not real)
    policy.bind(h)
    def permission_factory(*,runtime,admission_context,selection,environment_instance):
        authority = runtime.wire.identity_authority
        authority.replace_grants((AccessGrant(scope,tuple('execution.units.'+x for x in sorted(driver.ACTIONS))+driver.CAPABILITIES),))
        h['runtime'] = runtime
        principal = authority.authenticate('Bearer '+runtime.token)
        return UnitRunPermission(access_authority=authority,principal=principal,scope=scope,
            agent_id=selection.agent_id,profile_revision=selection.profile_revision,
            environment_identity=environment_instance.identity,root_directory=str(environment_root),
            actions=driver.ACTIONS,expires_at=time.time()+3600)
    selection = PiExecutionSelection('local-library-generation-agent',ref,environment.identity,
        'local','none',True,'selected-model',driver.PROVIDER,driver.MODEL,
        str(BRIDGE),BRIDGE_SHA,str(driver.PI),str(driver.ENV_SOURCE))
    ports = PiExecutionPorts(environments,declaration,fingerprint,permission_factory,
        (driver.MODEL,),driver.selected_model(),acp_turn_opt_in=True,
        defer_effect_write_guard_factory=True,credential_environment_variable='DEEPSEEK_API_KEY',
        callback_approval_factory=policy.callback_factory,restricted_file_tools=True,
        approved_check_command=policy.check_command,agent_journal_reopen=reopen)
    base = driver.application_factory(output,h,live=real,long_context=True,review_input_mode='sections-v1')
    intent = decode_record(canonical_bytes(candidate['intent']),WorkPackageAuthorizationIntent)
    notice = decode_record(canonical_bytes(candidate['notice']),WorkPackageNotice)
    frozen = FrozenChatInstruction(intent,notice,candidate['actual_instruction'],
        candidate['original_business_context'],notice.source)
    def application(factory,access,wire_scope):
        result = base(factory,access,wire_scope)
        raw = (ROOT/'methods/incremental-engineering/policies/product-chat-confirmation.v2.yaml').read_bytes()
        if hashlib.sha256(raw).hexdigest() != intent.policy_ref.digest.hex:
            raise RuntimeError('Explicit instruction policy changed')
        attestor = RegisteredMainAgentAttestor(access,scope=wire_scope,
            principal_id=h['caller'].principal_id,selected_policy_ref=intent.policy_ref)
        admission = ImplementationIntentAdmission(factory,h['controls'],h['bindings'])
        conversation = ConversationAdmission(raw,intent.policy_ref,attestor_guard=attestor.guard,
            intent_guard=admission.guard_intent)
        chat = MainAgentChatConfirmation(factory,conversation,
            conversation_locator=notice.source.locator,instruction_binding=frozen)
        h.update(chat=chat,policy=intent.policy_ref)
        def deliver(plan,report):
            save(output/'implementation-report.json',report.method_content.value)
            save(output/'implementation-submission.json',asdict(report.ref))
            print(json.dumps({'stage':'IMPLEMENTATION_REPORT_REGISTERED','submission_ref':asdict(report.ref),'review_id':plan.review_id}),flush=True)
            return {'submission_ref':asdict(report.ref)}
        def prompt_parameters(context,package,unit,recipe=None):
            if recipe is None:
                raise RuntimeError('Declared frozen recipe required')
            return recipe['params']
        assembly = assemble_with_mode(entry, continuation=continuation,
            runtime=h['runtime'],holder=h,
            scope=wire_scope,caller=h['caller'],frozen_scope=policy,
            expected_selection=(ActorRef('jev-real-source-reviewer','service','explicit-host-selection'),('reviewer',),1),
            prompt_parameters=prompt_parameters,review_paths=tuple(str(TARGET/name) for name in BEFORE),
            deliver=deliver,implementation_timeout=1800)
        h['assembly'] = assembly
        selected = assembly.applier(replace(result,conversation_admission=chat))
        binder = selected.execution_dispatch_binder
        def bind(service):
            h['service'] = service
            return binder(service)
        h['review_admission'] = selected.review_admission
        return replace(selected,execution_dispatch_binder=bind)
    # The first verified copy was opened only by its native owners above. This
    # second snapshot records exactly their legitimate setup mutations before
    # the accepted M2 builder opens the very same graph for the actual gates.
    before_build = graph_files(graph)
    save(output/'native-setup-before-product.json',{'files':before_build,
        'environment_identity':environment.identity,'historical_environment_rows_rewritten':False,
        'new_private_instance_token_generated_by_original_owner':True})
    runtime, cloned = entry.build_clone_runtime(clone_root=graph,manifest=before_build,
        pi_selection=selection,pi_ports=ports,application_ports_factory=application,
        engineering_options=dict(library_path=str(graph/'engineering.sqlite'),library_id=driver.CASE_ID,
            scope=scope,create_library=False,schema_version=17,machine_capabilities=driver.CAPABILITIES))
    return runtime,h,cloned


def dispose(h):
    for name in ('reviewer','materials'):
        if name in h:
            h[name].close()
    async def close():
        for name in ('provider','sink'):
            if name in h:
                await h[name].close()
    asyncio.run(close())


def continuation_parameters(selector, *, work_id, action_id, expected_revision, inputs):
    """The formal v2 continuation selector, built from the case's own values.

    This registers nothing: no Work, Notice, Intent, Challenge, Grant or
    authorization snapshot is created here. The origin identities come from the
    original rows the operator last read; the entry refuses if any is missing.
    """
    required = ('execution_operation_ref', 'attempt', 'expected_dispatch_version',
                'expected_acp_revision')
    if (type(selector) is not dict or set(selector) != set(required)
            or type(selector['execution_operation_ref']) is not str
            or not selector['execution_operation_ref']
            or type(selector['attempt']) is not int or selector['attempt'] < 1
            or type(selector['expected_dispatch_version']) is not int
            or selector['expected_dispatch_version'] < 1
            or type(selector['expected_acp_revision']) is not int
            or selector['expected_acp_revision'] < 1
            or type(work_id) is not str or not work_id
            or type(action_id) is not str or not action_id
            or type(expected_revision) is not int or expected_revision < 1
            or type(inputs) is not dict):
        raise RuntimeError('Explicit v2 continuation selector required; no new authority is created')
    return {'invocation_version': 2, 'work_id': work_id, 'action_id': action_id,
            'expected_revision': expected_revision, 'inputs': dict(inputs),
            'continuation_of': {key: selector[key] for key in (
                'execution_operation_ref', 'expected_dispatch_version', 'expected_acp_revision')}}


def run_continuation(*, entry, continuation, work_id, action_id, expected_revision, inputs,
                     case, invoke_parameters, execute_case, save, output,
                     request_id, receipt_path):
    """Dispatch one explicit continuation; never creates or registers authority.

    Only the v2 selector is built here. No Work, Notice, Intent, Challenge,
    Grant, authorization snapshot or Unit is created on this path - the caller
    passes the already registered graph's case record and a function that
    executes the formal invoke once.
    """
    parameters = continuation_parameters(
        continuation, work_id=work_id, action_id=action_id,
        expected_revision=expected_revision, inputs=inputs)
    if parameters['continuation_of'] != {key: continuation[key] for key in (
            'execution_operation_ref', 'expected_dispatch_version', 'expected_acp_revision')}:
        raise RuntimeError('Continuation selector changed before dispatch')
    answer = execute_case(parameters=parameters, case=case, mode='continuation',
                          origin=continuation, request_id=request_id,
                          receipt_path=receipt_path)
    save(output / 'continuation-invoke.json', {'parameters': {key: value for key, value in parameters.items()
                                                              if key != 'inputs'},
                                               'origin': continuation,
                                               'answer': answer})
    return answer, parameters


def invoke(runtime,h,operation,parameters,label):
    descriptor = runtime.plugin_host.methods.lookup(operation)
    if descriptor is None:
        raise RuntimeError('Formal operation unavailable: '+operation)
    answer = asyncio.run(descriptor.handler({'scope':asdict(h['wire_scope']),
        'requestId':h['driver'].REQUEST_PREFIX+label,'parameters':parameters},h['caller']))
    save(h['output']/(label+'.json'),answer)
    return h['driver'].payload(answer)


def main(argv=None):
    global WORK,INTENT_DIGEST
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--candidate-sha256',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--run-real',action='store_true')
    parser.add_argument('--resume-state',type=Path)
    parser.add_argument('--resume-state-sha256')
    parser.add_argument('--continuation-operation-ref')
    parser.add_argument('--continuation-attempt',type=int)
    parser.add_argument('--continuation-dispatch-version',type=int)
    parser.add_argument('--continuation-acp-revision',type=int)
    args = parser.parse_args(argv)
    if not args.run_real:
        def deny_external_effects(event, values):
            if event in ('subprocess.Popen', 'os.posix_spawn', 'socket.connect'):
                raise RuntimeError('Preparation refuses process/network effects')
            if event == 'open' and values and isinstance(values[0], (str, bytes)):
                selected = Path(os.fsdecode(values[0]))
                if selected.name == '.env' or 'secrets' in selected.parts and ORIGINAL in selected.parents:
                    raise RuntimeError('Preparation refuses historical/provider credential reads')
        sys.addaudithook(deny_external_effects)
    continuation = None
    given = (args.continuation_operation_ref, args.continuation_attempt,
             args.continuation_dispatch_version, args.continuation_acp_revision)
    if any(value is not None for value in given):
        continuation = {'execution_operation_ref': args.continuation_operation_ref,
                        'attempt': args.continuation_attempt,
                        'expected_dispatch_version': args.continuation_dispatch_version,
                        'expected_acp_revision': args.continuation_acp_revision}
    if sha(args.candidate) != args.candidate_sha256:
        raise RuntimeError('Frozen instruction candidate changed')
    candidate = json.loads(args.candidate.read_bytes())
    WORK = candidate['authorization']['work_id'];INTENT_DIGEST=candidate['intent']['digest']['hex']
    if WORK != FIXED_WORK or candidate['new_question_or_answer_presented'] is not False:
        raise RuntimeError('Explicit new instruction candidate required')
    if continuation is not None:
        # A continuation is bound to the existing registered graph. A changed
        # database manifest after legitimate execution is not a new snapshot.
        continuation_parameters(continuation, work_id=WORK, action_id=ACTION,
            expected_revision=1, inputs=candidate['invoke_parameters']['inputs'])
        if args.resume_state is not None or not REGISTERED_RUNTIME.is_file():
            raise RuntimeError('Continuation requires the original registered runtime; no pre-Grant resume')
        registered = json.loads(REGISTERED_RUNTIME.read_bytes())
        if registered.get('work_id') != WORK or type(registered.get('graph')) is not str:
            raise RuntimeError('Registered continuation graph differs from the frozen Work')
    elif args.run_real and REGISTERED_RUNTIME.exists():
        registered = json.loads(REGISTERED_RUNTIME.read_bytes())
        if (args.resume_state is None or registered.get('state') != 'claimed_pre_registration'
                or sha(args.resume_state) != args.resume_state_sha256
                or json.loads(args.resume_state.read_bytes()).get('graph') != registered.get('graph')):
            raise RuntimeError('This exact real case already has a registered graph; read its original operation, never re-clone or dispatch')
    if args.output.exists() or not args.output.is_absolute():
        raise RuntimeError('A fresh absolute output directory is required')
    args.output.resolve().relative_to((ROOT/'.nightly-cache').resolve())
    for path,digest in PINNED.items():
        if sha(path) != digest:
            raise RuntimeError('Reviewed source/bridge changed: '+Path(path).name)
    if target_hashes() != BEFORE:
        raise RuntimeError('Business baseline differs')
    if continuation is None and args.run_real and not REGISTERED_RUNTIME.exists():
        # Operator fence only, before a snapshot/runtime/Grant can be created.
        # An exclusive file prevents concurrent fresh-directory re-cloning of
        # this one fixed case. It creates no authority and grants no permission.
        graph = (Path(json.loads(args.resume_state.read_bytes())['graph'])
                 if args.resume_state is not None else args.output/'runtime')
        save(REGISTERED_RUNTIME, {'work_id':WORK, 'graph':str(graph),
            'state':'claimed_pre_registration', 'retry_allowed':False,
            'meaning':'operator duplicate-run fence; formal owner records remain authoritative'})
    args.output.mkdir(mode=0o700)
    entry=load_module('instruction_declared_case_entry',M2)
    driver=load_module('instruction_case_driver',ROOT/'tooling/checks/server_product/probe-work-package-generation.py')
    driver.CAPABILITIES=tuple(dict.fromkeys((*driver.CAPABILITIES,*CAPS)))
    driver.REQUEST_PREFIX=WORK+'-'
    # The exact scope guard is the previously reviewed case policy, parameterized
    # only by this new Work/Intent. Original Unit callbacks remain mandatory.
    policy=FrozenScope();policy.check_verify()
    runtime=None;h={};initial=();protected=protected_original()
    result={'work_id':WORK,'real':args.run_real,'unit_started':False,'grant_registered':False,
        'models':0,'accept_adopt':False,'historical_root_opened_for_write':False}
    try:
        environment_identity = None
        if continuation is not None:
            graph = Path(registered['graph'])
            graph.resolve().relative_to((ROOT/'.nightly-cache').resolve())
            if graph.is_symlink() or not (graph/'engineering.sqlite').is_file() or not (graph/'product').is_dir():
                raise RuntimeError('Registered continuation graph is unavailable')
            environment_identity=json.loads((graph.parent/'native-setup-before-product.json').read_bytes())['environment_identity']
        elif args.resume_state is None:
            graph,protected=prepare_snapshot(args.output,entry)
        else:
            if (not args.run_real or sha(args.resume_state) != args.resume_state_sha256):
                raise RuntimeError('Exact pre-Grant private graph state required')
            resume=json.loads(args.resume_state.read_bytes())
            graph=Path(resume['graph'])
            graph.resolve().relative_to((ROOT/'.nightly-cache').resolve())
            actual={p:hsh for p,hsh in graph_files(graph).items() if 'secrets' not in Path(p).parts}
            if actual != resume['files'] or resume['work_id'] != WORK:
                raise RuntimeError('Private graph changed before registration resume')
            with sqlite3.connect((graph/'engineering.sqlite').as_uri()+'?mode=ro',uri=True) as check:
                check.execute('PRAGMA query_only=ON')
                if (check.execute('SELECT COUNT(*) FROM eng_approval_grants').fetchone()[0] != 2
                        or check.execute('SELECT COUNT(*) FROM eng_action_consumptions').fetchone()[0] != 4
                        or check.execute('SELECT COUNT(*) FROM eng_commands WHERE request_id=?',
                            (driver.REQUEST_PREFIX+'invoke-implementation',)).fetchone()[0] != 0):
                    raise RuntimeError('Resume is limited to the preserved pre-Grant failure')
            environment_identity=json.loads((graph.parent/'native-setup-before-product.json').read_bytes())['environment_identity']
            save(args.output/'registration-resume.json',{'original_graph':str(graph),
                'new_graph_created':False,'new_dispatch_or_model_before_resume':False,
                'prior_receipts_preserved':True,'resume_state_sha256':args.resume_state_sha256})
        runtime,h,cloned=compose(args.output,graph,candidate,policy,entry,driver,real=args.run_real,
            continuation=continuation,
            environment_identity=environment_identity)
        owner=runtime.unit_execution_owner
        owner.ensure_unit_creation_ready()
        pins=dict(PINNED)
        previous_pins = json.loads(PREVIOUS_SOURCE_PINS.read_bytes())
        reviewed_changes = {
            "apps/server/src/ordessa_server/composition/engineering_chat_confirmation.py": "cb39c4944a27b0c72e5b7fdc9cc4d04e10127ccbebcbec658f22f943d0d87c61",
            "apps/server/src/ordessa_server/composition/engineering_native_dispatch_assembly.py": "69476f81b0c5f89c9e1c8ea0b601692aae4b927d6ad905c04a7df8a20f8ea115",
            "packages/engineering/src/ordessa_engineering/adapters/registry/resources/operation_registry.v1.json": "c8808cd2eaeded69737ac40ffabc41b171dd581b112e1fd150306829b5d5d1f7",
            "packages/engineering/src/ordessa_engineering/adapters/registry/source_integrity.py": "aa2b5708e847492e3efb534d423b355ce8fb3c3665fbfb03789f2a762850546c",
            "packages/engineering/src/ordessa_engineering/application/contracts/failure_diagnostic.py": "da7e7175a86da4fe9a4fcec04e7046595597c0c87cd04c4dde01d905b849f59e",
            "packages/engineering/src/ordessa_engineering/application/orchestration/steps/declared_implementation_dispatch.py": "8c376187e277507810f58ac7aa4ae2d10c9ab7d41109a928e58c1853687a0589",
            "packages/engineering/src/ordessa_engineering/application/contracts/execution_observations.py": "dd0aa46851439055668f202a44a45633b93681ea3fd3ca9db116dcaa33c5ec95",
            "packages/engineering/src/ordessa_engineering/application/usecases/changes/dispatch_continuation.py": "b209816c3dd71834965f03d11e949c5f5e3e412858d94f9cbbf2112a599f8a2c",
            "packages/engineering/src/ordessa_engineering/application/usecases/reviews/assignments.py": "ed5cec85655980bef181f0e009b79625f64150d998927e6fd80e05cb9557a172",
            "packages/engineering/src/ordessa_engineering/application/usecases/works.py": "7819279a70da4f14f327339802e194c06c542ee964e2b01707e499992ddae249",
            "packages/engineering/src/ordessa_engineering/application/api/service.py": "ace89f482f2b2e969d52086e67b7743e24a612972c463b217f2adf6a75125563",
            "packages/engineering/src/ordessa_engineering/application/usecases/owner_operations.py": "daf9236ec465d369f7bef9d2b00956c3a1754bb2b8069105092f166f2fc1e476",
            "packages/engineering/src/ordessa_engineering/adapters/persistence/sqlite/dispatch_repository.py": "2c82f8957a3ab3143a17e5be87ac2d3e11d6a1fc4efb48aeea8a2dbc4c2e37e8",
            "packages/engineering/src/ordessa_engineering/application/orchestration/declared_implementation_results.py": "0c3a862d7cb198be84e228e09930adf281d8f6b3aa39db6bd566bd9a75954fe7",
            "packages/engineering/src/ordessa_engineering/application/usecases/changes/declared_report.py": "b5586827217ad6ea2f75446c10c4cbe40ab08981f9d1f150bd0f674fcde4bd6b",
            "packages/engineering/src/ordessa_engineering/adapters/native_records/__init__.py": "342b47008d10b28af1bf3cba16be3af3f3581232ee375b2d28a16444f6707de1",
            "packages/engineering/src/ordessa_engineering/adapters/native_records/declared_review_runtime.py": "c6c5849d162115feb4b069386917fb1d91616e38ad8155d1acca7987a043589f",
            "packages/engineering/src/ordessa_engineering/adapters/native_records/declared_reviewer.py": "786b6c23104ccf21b1fbbed5187a103d9c4e2d66d1171e12cc351bea4b6b9c0e",
            "packages/engineering/src/ordessa_engineering/adapters/native_records/local_bindings.py": "828f6ebad67a03844630960c217fa813c968364c20a5aca52842bc9b0639cc78",
            "packages/engineering/src/ordessa_engineering/application/assembly/execution_dispatch.py": "64601b58c58e7f2d02890d5b9d8521c1ae50dd2da9c62f35c1f3e1df458eafdd",
            "packages/execution/units/src/ordessa_units/records/unit_records.py": "dc1bd4aead4df70e35de31a7a1029e56926b12eaa41706384c38b2bfe5018931",
            "packages/execution/units/src/ordessa_units/records/acp_turns.py": "3528545c7a69612ba1d4beb847b449d340a9c75ab8890629122c04676ba73bf2",
            "packages/execution/units/src/ordessa_units/assembly/local_owner.py": "1a23f01abe5e0a293a8325a9818c5447033191e36915e39659dea5cb4f8f59d8",
            "packages/execution/units/src/ordessa_units/admission/local_state.py": "c1e55d8eb5ead33c04e7df6e7d05e6bf4a5d3aa91579d45430fd4ac526c86d78",
            "tooling/checks/server_product/run_declared_work_case.py": "13ec258ba6fa4aed409288470f97816362c1386ce594b8830acc895debe4d353"
        }
        for path, digest in previous_pins.items():
            selected = Path(path)
            actual = sha(selected)
            approved = reviewed_changes.get(selected.relative_to(ROOT).as_posix()) if selected.is_relative_to(ROOT) else None
            if actual != digest and actual != approved:
                raise RuntimeError('Unreviewed prior source drift: '+selected.name)
            pins[path] = actual
        for path in sorted((ROOT/'packages/engineering/src/ordessa_engineering').rglob('*.py')):
            pins[str(path)]=sha(path)
        for path in (Path(__file__),args.candidate,
                ROOT/'packages/engineering/src/ordessa_engineering/adapters/registry/resources/operation_registry.v1.json',
                ROOT/'apps/server/src/ordessa_server/composition/engineering_chat_confirmation.py'):
            pins[str(path)]=sha(path)
        save(args.output/'sources.json',pins)
        result.update(stage='FULL_CLONE_NATIVE_OWNER_COMPOSED',source_files=len(pins),
            same_factory_and_access=True,unit_count=len(runtime.units.list()),
            permission_scope=asdict(owner.permission.scope),effect_factory_bound=owner.effect_write_guard_factory is h['assembly'].case_ports.review_runtime,
            profile=asdict(owner.permission.profile_revision),private_environment=owner.permission.environment_identity)
        save(args.output/'preflight.json',result)
        print(json.dumps(result),flush=True)
        if not args.run_real:
            return 0
        from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
        from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
        from ordessa_infrastructure.encoding import canonical_bytes
        if target_hashes()!=BEFORE or protected_original()!=protected:
            raise RuntimeError('Protected source changed before registration')
        if continuation is None:
            # First attempt: the case's own registration chain.
            invoke(runtime,h,'engineering.work.start',candidate['start_parameters'],'start-work')
            invoke(runtime,h,'engineering.notices.publish',{'notice':candidate['notice']},'publish-notice')
            invoke(runtime,h,'engineering.approvals.prepare_intent',{'intent':candidate['intent']},'prepare-intent')
            challenge=invoke(runtime,h,'engineering.approvals.request',{'intent_id':candidate['authorization']['intent_id'],
                'intent_digest':candidate['intent']['digest']},'request-challenge')
            with h['access'].admit(h['caller'],h['wire_scope'],'engineering.approvals.record_conversation',
                    request_id=driver.REQUEST_PREFIX+'record-instruction',trace_id=driver.CASE_ID) as ctx:
                record=h['chat'].record_instruction(h['access'],h['review_admission'],ctx,
                    challenge_id=challenge['challenge']['challenge_id'],nonce=challenge['nonce'],
                    expected_version=challenge['version'],evidence_id=WORK+'-instruction',disposition='confirm')
            recorded=record.result
            save(args.output/'record-instruction.json',{'operation_id':record.operation_id,'result':recorded})
            h['grant_ref']=decode_approval_ref(recorded['approval_ref'])
            result.update(stage='INSTRUCTION_GRANT_REGISTERED',grant_registered=True,
                          grant_ref=recorded['approval_ref'])
        else:
            # Continuation: the original Grant comes from the origin binding's
            # own row; nothing is registered and no Unit is created here.
            with h['factory'].begin(h['scope'],'read') as uow:
                row=uow.work_dispatch.by_operation(continuation['execution_operation_ref'], h['scope'])
                origin_binding=decode_dispatch(row['binding_bytes'])
            if origin_binding.approval_ref is None:
                raise RuntimeError('Origin binding carries no original Grant')
            h['grant_ref']=origin_binding.approval_ref
            result.update(stage='CONTINUATION_ORIGIN_SELECTED',work_started=False,
                          grant_registered=False,grant_ref=asdict(origin_binding.approval_ref))
        with h['factory'].begin(h['scope'],'read') as uow:
            grant,facts,control=policy.grant(uow)
            budget=uow.authorization.action_budget(grant.ref)
        expected={'work_id':WORK,'action_id':ACTION,'step_id':STEP,'work_revision':1,
            'package_digest':candidate['authorization']['package_ref']['digest']['hex'],
            'intent_digest':INTENT_DIGEST,'actions':['edit_repository','run_checks'],'required_capabilities':list(CAPS)}
        evidence={'grant':dict(expected,ref=asdict(grant.ref),digest=INTENT_DIGEST),
            'budget':{'actions':{v['action']:{'limit':v['limit'],'consumed':v['consumed']} for v in budget['actions']}},
            'permission_capabilities':list(driver.CAPABILITIES)}
        save(args.output/'evidence-reference.json',evidence)
        reference=entry.validate_evidence_reference(args.output/'evidence-reference.json',expected,
            mode='continuation' if continuation is not None else 'first',origin=continuation)
        entry.read_case_records(factory=h['factory'],scope=h['scope'],grant_ref=asdict(grant.ref),
            expectations=expected,mode='continuation' if continuation is not None else 'first',
            origin=continuation)
        view=entry.read_formal_work_action(runtime,caller=h['caller'],scope=h['wire_scope'],work_id=WORK,
            action_id=ACTION,request_id=driver.REQUEST_PREFIX+'exact-action-preflight')
        result.update(stage='EXACT_REAL_PREFLIGHT_READY',budget=budget,work_action=view)
        save(args.output/'exact-real-preflight.json',result)
        print(json.dumps(result),flush=True)
        policy.check_verify();entry.verify_sources(args.output/'sources.json',sha(args.output/'sources.json'))
        if target_hashes()!=BEFORE or protected_original()!=protected:
            raise RuntimeError('Protected inputs changed before first Unit')
        runtime.start();initial=tuple(runtime.units.list())
        if continuation is None:
            unit=owner.manager.create(owner.spec,owner.authorization())
            result.update(stage='REAL_UNIT_CREATED',unit_started=True,unit_ref=plain(unit.identity))
            print(json.dumps(result),flush=True)
        case={'grant':reference,'grant_ref':asdict(grant.ref),'expectations':expected,
            'library_id':driver.CASE_ID,'pins':{'sources_path':str(args.output/'sources.json'),
            'sources_sha256':sha(args.output/'sources.json')},'clone':cloned}
        result['models'] = None  # native records, rather than an invented call counter, are authoritative
        if continuation is None:
            answer=entry.execute_case(runtime=runtime,caller=h['caller'],scope=h['wire_scope'],
                parameters=candidate['invoke_parameters'],request_id=driver.REQUEST_PREFIX+'invoke-implementation',
                case=case,receipt_path=args.output/'dispatch-receipt.json')
        else:
            # The formal owner may bootstrap a successor inside work.invoke.
            # A local pre-creation flag cannot prove whether that happened,
            # especially when the invocation later becomes unconfirmed.
            result['unit_started'] = None
            answer,parameters=run_continuation(entry=entry,continuation=continuation,work_id=WORK,
                action_id=ACTION,expected_revision=expected['work_revision'],
                inputs=candidate['invoke_parameters'].get('inputs') or {},
                case=case,invoke_parameters=candidate['invoke_parameters'],
                execute_case=lambda **values: entry.execute_case(runtime=runtime,caller=h['caller'],
                    scope=h['wire_scope'],**values),
                save=save,output=args.output,
                request_id=driver.REQUEST_PREFIX+'continuation-implementation',
                receipt_path=args.output/'continuation-receipt.json')
        result.update(stage='FORMAL_INVOKE_RETURNED',operation=answer.get('read_back'),
            report_delivered=h.get('report_delivered'),target_hashes=target_hashes())
        return 0 if h.get('report_delivered') else 1
    except BaseException as error:
        result.update(stage='BLOCKED',error=driver.safe_error(error),
            frames=[{'file':Path(item.filename).name,'line':item.lineno,'function':item.name}
                for item in traceback.extract_tb(error.__traceback__)])
        save(args.output/'failure-before-cleanup.json',result)
        print(json.dumps(result),flush=True)
        return 1
    finally:
        if runtime is not None and runtime.started:
            def retained(observation):
                print(json.dumps(observation),flush=True)
            states,attempts=driver.retain_generation_owner(runtime,initial,on_observation=retained,
                wait_for_resume=driver.wait_generation_owner_resume,before_runtime_stop=lambda:dispose(h))
            result.update(unit_close=states,close_attempts=attempts)
        else:
            dispose(h)
            if runtime is not None:
                runtime.stop()
        result.update(runtime_stopped=runtime is None or not runtime.started,
            historical_files_unchanged=protected==protected_original(),target_hashes=target_hashes())
        save(args.output/'completion.json',result)
        print(json.dumps({'stage':'CASE_CLOSED','runtime_stopped':result['runtime_stopped'],
            'historical_files_unchanged':result['historical_files_unchanged'],
            'business_changed':result['target_hashes']!=BEFORE,'unit_started':result['unit_started']}),flush=True)


if __name__=='__main__':
    raise SystemExit(main())
