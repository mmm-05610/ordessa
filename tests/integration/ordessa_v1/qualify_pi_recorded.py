"""One actual Pi/OpenCode Go prompt through the frozen durable ACP-turn contract.

This is an explicitly controlled qualification fixture, not a production human
Grant. Running requires --authorize-live and separate user authorization for a
real recorded model call (scope and cost). Never retries an unresolved attempt.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace
from probe_evidence import retained_attempt_root, cleanup_attempt, failure_boundary
from ordessa_units.management import UnitInstance
from ordessa_units.records import UnitRecords, OperationJournal
from ordessa_units.sessions.evidence import AcpUnitEvidence
from ordessa_units.admission.connection import ConnectionLeasePort
from ordessa_agents.profiles import ProfileRevisionRef, canonical_content, content_digest, encode_revision_ref
from ordessa_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION
from ordessa_harness_pi import PiAcpHarnessPreparation
from ordessa_harness_pi.configuration.unit_materialization import PiUnitProfileMaterializer
from ordessa_units.assembly.process_input import UnitProcessInputBinding
from ordessa_server.composition.temporary_process_capability import ExistingOpenCodeInput
from ordessa_infrastructure.encoding.immutable_json import safe_json

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('qualification_authority', ROOT/'packages/execution/units/tests/test_unit_instance.py')
helpers = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helpers
spec.loader.exec_module(helpers)
BRIDGE = '/tmp/ordessa-pi-failure-protocol-acp'
BRIDGE_SHA = '5a2f8f008fdf6fdf274d99f358c37477d8bcf8c4bfacf8cefef2630ef12d1c84'
PI = '/home/maoqh/.local/bin/pi'


class ControlledQueryAuthority(helpers.Authority):
    """Fixture query authority bound to the exact durable ACP read digest."""
    def issue_query(self, input_digest):
        context = helpers.Invocation({'query': True, 'action': 'query',
            'providerRef': self.provider, 'targetRef': self.node,
            'inputDigest': input_digest, 'managementEpoch': 0,
            'request': {'environmentNamespace': 'env', 'principalScope': 'controlled',
                'requestId': 'recorded-acp-query'},
            'operationRef': 'recorded-acp-query', 'stepId': 'recorded-acp-query'})
        self.issued.add(context)
        return context


def qualify(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    phase_path = output.with_suffix('.phase.json')
    if output.exists() or phase_path.exists():
        raise RuntimeError('existing_attempt_refused_inspect_original_receipt')
    def checkpoint(phase, prompt_intents=0):
        phase_path.write_text(json.dumps({'phase': phase, 'prompt_intents': prompt_intents,
            'consumer_replays': 0, 'paid_fallback': False})+'\n')
    checkpoint('preparing')
    if hashlib.sha256(Path(BRIDGE).read_bytes()).hexdigest() != BRIDGE_SHA:
        raise RuntimeError('bridge_pin_changed')
    with retained_attempt_root(output, prefix='ordessa-v1-recorded-pi-') as temporary:
        root = Path(temporary)/'environment'
        roots = {k: str(root/k) for k in ('home', 'cwd', 'piHome')}
        definition = {'environmentNamespace': 'env', 'definitionId': 'pi', 'revision': 'live-go-fixed-1'}
        descriptor = RuntimeProviderDescriptor('pi', RUNTIME_PROVIDER_VERSION, definition, 'sha256:'+'a'*64,
            ('plan_preparation', 'prepare', 'start', 'connect', 'describe_access', 'stop', 'release'))
        provider = {'environmentNamespace': 'env', 'providerId': 'pi', 'generation': 1,
            'contractVersion': RUNTIME_PROVIDER_VERSION, 'implementationDigest': descriptor.implementation_digest}
        authority = ControlledQueryAuthority(provider, {'environmentNamespace': 'env', 'nodeId': 'unit', 'generation': 1})
        evidence = AcpUnitEvidence(preparation_authority=lambda plan, facts: plan['context']['privateRootFacts'],
            start_authority=authority.continuation, configuration_authority=authority.continuation)
        journal_path = Path(temporary)/'original.sqlite'
        journal_path.touch(exist_ok=False)
        journal = OperationJournal(journal_path, acp_turn_opt_in=True)
        records = UnitRecords(journal, scope_authority=helpers.Scope(), native_evidence=evidence,
            verifier=authority, epoch_port=SimpleNamespace(current_epoch=lambda n: 0),
            termination_evidence=evidence, configuration_evidence=evidence, acp_turn_opt_in=True)
        evidence.attach_owner(records)
        environments = helpers.Provider(root, [])
        binding = UnitProcessInputBinding(instance=environments.instance, agent_id='recorded-pi', sharing=True,
            input_source=ExistingOpenCodeInput('/home/maoqh/projects/ordessa/.env'))
        manifest = {'schemaVersion': '1', 'harnessDefinitionRef': definition, 'declarations': [
            {'declarationId': 'fixed-model', 'configurationKind': 'assets.model-provider', 'schemaVersion': '1',
             'action': 'value', 'requirement': 'required', 'payload': {'provider': 'opencode-go',
             'model': 'glm-5.3-flash', 'protocol': 'openai-chat',
             'endpoint': 'https://opencode.ai/zen/go/v1'}}]}
        revision = ProfileRevisionRef('env', 'profile', 1, content_digest(canonical_content(manifest, 'env')))
        snapshot = {'ref': encode_revision_ref(revision), 'manifest': manifest}
        materializer = PiUnitProfileMaterializer(fixed_revision=revision, harness_definition_ref=definition,
            model_declaration_id='fixed-model', model_catalogue=['glm-5.3-flash'],
            credential_environment_variable='OPENCODE_API_KEY')
        leases = ConnectionLeasePort()
        unit = UnitInstance(descriptor=descriptor, agent_id='recorded-pi', profile_revision=revision,
            environment_instance=binding.capability, environment_sharing=True,
            environment_reference={'environmentId': environments.identity},
            preparation=PiAcpHarnessPreparation(bridge_executable=BRIDGE, bridge_sha256=BRIDGE_SHA,
                pi_executable=PI, **materializer.selected_launch_configuration(snapshot)),
            materializer=materializer, records=records, projection=evidence, verifier=authority,
            lease_port=leases, termination_evidence=evidence, timeout=20)
        binding.attach(unit)
        try:
            plan = unit.plan_preparation(snapshot, {'nodeRef': authority.node, 'privateRootFacts': roots},
                {'scope': 'one synthetic recorded prompt'})
            prepared = unit.prepare(plan, authority.issue('prepare'))
            start = authority.issue('start')
            binding.fix_start(prepared, start)
            unit.start(prepared, start)
            checkpoint('native_started')
            unit_ref = prepared['unitRef']
            lease = leases.grant(unit_ref)
            configuration = unit.configuration_snapshot(unit_ref, lease)
            model = next(o['currentValue'] for o in configuration['configOptions'] if o['id'] == 'model')
            if model != 'opencode-go/glm-5.3-flash':
                raise RuntimeError('fixed_model_changed')
            params = {'sessionId': evidence.read_session(unit_ref).native_facts['sessionId'],
                'prompt': [{'type': 'text', 'text': 'Do not use tools or read files. Reply with exactly ORDESSA_PI_OK.'}]}
            operation_ref = 'recorded-pi-' + Path(temporary).name
            expected_prompt_input_digest = records.acp_prompt_input_digest(unit_ref, params)
            checkpoint('recorded_prompt_intent', 1)
            audit_secret = ExistingOpenCodeInput('/home/maoqh/projects/ordessa/.env').read()
            try:
                response = unit.prompt(unit_ref, lease, operation_ref=operation_ref,
                    timeout=45, **params)
                if audit_secret and any(bytes(audit_secret) in path.read_bytes()
                        for path in Path(temporary).rglob('*') if path.is_file()):
                    raise RuntimeError('credential_persistence_detected')
            finally:
                audit_secret[:] = b'\0'*len(audit_secret)
            checkpoint('recorded_prompt_returned', 1)
            query_digest = records.acp_turn_query_digest(unit_ref, operation_ref, expected_prompt_input_digest)
            query_context = authority.issue_query(query_digest)
            live_receipt = records.query_acp_turn(unit_ref, operation_ref, query_context,
                input_digest=query_digest, expected_prompt_input_digest=expected_prompt_input_digest)
            live_digest = {'input': live_receipt['inputDigest'],
                'events': live_receipt['eventsDigest'], 'response': live_receipt['responseDigest']}
            state = live_receipt['state']
            if state not in {'completed', 'failed'}:
                raise RuntimeError('recorded_attempt_not_terminal_no_replay')
            # Reopen the original SQLite owner without schema opt-in or live
            # process evidence. The cold owner can authorize reads only.
            def refuse_live_evidence(*args, **kwargs):
                raise RuntimeError('cold_read_must_not_consult_live_process_or_acp_evidence')
            cold_records = UnitRecords(OperationJournal(journal_path), scope_authority=helpers.Scope(),
                native_evidence=SimpleNamespace(verify_binding=refuse_live_evidence), verifier=authority,
                epoch_port=SimpleNamespace(current_epoch=lambda n: 0))
            cold_context = authority.issue_query(query_digest)
            cold_receipt = cold_records.query_acp_turn(unit_ref, operation_ref, cold_context,
                input_digest=query_digest, expected_prompt_input_digest=expected_prompt_input_digest)
            cold_digest = {'input': cold_receipt['inputDigest'],
                'events': cold_receipt['eventsDigest'], 'response': cold_receipt['responseDigest']}
            if cold_receipt != live_receipt:
                raise RuntimeError('cold_durable_read_differs_from_original_receipt')
            text = live_receipt.get('summary', {}).get('text', '') if live_receipt.get('summary') else ''
            stopped = unit.stop(unit_ref, authority.issue('stop'))
            exited = unit.channel_factory.owned_record.process.observe().state
            released = unit.release(unit_ref, authority.issue('release'))
            return {'kind': 'actual-Pi-ACP-recorded-OpenCode-Go-qualification',
                'model': model, 'profile_revision': encode_revision_ref(revision),
                'bridge_sha256': BRIDGE_SHA, 'pi_sha256': hashlib.sha256(Path(PI).read_bytes()).hexdigest(),
                'operation_ref': operation_ref, 'expected_prompt_input_digest': expected_prompt_input_digest,
                'query_digest': query_digest, 'state': state, 'rpc_success': state == 'completed',
                'legal_rpc_failure': state == 'failed',
                'model_quality_pass': state == 'completed' and text.strip() == 'ORDESSA_PI_OK',
                'assistant_text': text, 'live_receipt_digest': live_digest,
                'cold_receipt_digest': cold_digest, 'live_and_cold_receipts_match': live_receipt == cold_receipt,
                'cold_read_no_live_handles': True,
                'response': response, 'consumer_replays': 0, 'paid_fallback': False,
                'credential_persisted': False,
                'stop': stopped['state'], 'process': exited, 'release': released['state'],
                'active_uses': environments.instance.snapshot.active_uses,
                'invocation_owner': 'controlled query fixture; not production human Grant',
                'product_end_to_end_complete': False}
        except Exception as error:
            details = {'status': 'qualification_failed', 'error_type': type(error).__name__,
                'consumer_replays': 0, 'attempt_replay_permitted': False,
                'frames': [{'file': frame.filename, 'line': frame.lineno, 'function': frame.name}
                    for frame in traceback.extract_tb(error.__traceback__)]}
            output.with_suffix('.failure.json').write_text(json.dumps(details, indent=2)+'\n')
            raise
        finally:
            cleanup = cleanup_attempt(unit, authority, prepared=locals().get('prepared'),
                released=locals().get('released'), binding=binding)
            cleanup['active_uses'] = environments.instance.snapshot.active_uses
            cleanup['cleanup_completed'] = cleanup['cleanup_completed'] and cleanup['active_uses'] == 0
            output.with_suffix('.cleanup.json').write_text(json.dumps(cleanup, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize-live', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.authorize_live:
        raise SystemExit('explicit_live_authorization_required')
    if args.output.exists() or args.output.with_suffix('.phase.json').exists() or args.output.with_suffix('.root.json').exists():
        raise SystemExit('existing_attempt_refused_inspect_original_receipt')
    try:
        receipt = qualify(args.output)
        encoded = safe_json(receipt)
        args.output.write_text(encoded+'\n')
        print(encoded)
    except Exception as error:
        failure = args.output.with_suffix('.failure.json')
        if not failure.exists():
            args.output.parent.mkdir(parents=True, exist_ok=True)
            failure.write_text(json.dumps({**failure_boundary(error), 'status': 'qualification_failed',
                'consumer_replays': 0, 'attempt_replay_permitted': False}, indent=2)+'\n')
        print(json.dumps({'status': 'qualification_failed', 'error_type': type(error).__name__}))
        raise SystemExit(1)
