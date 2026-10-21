"""One actual Pi/OpenCode Go prompt on original Units records and a disposable Local Use.

Invocation authority is the explicitly controlled qualification fixture, not a
production human Grant. No tools permitted, retries, auth files or paid fallback.
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

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('qualification_authority', ROOT/'packages/execution/units/tests/test_unit_instance.py')
helpers = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helpers
spec.loader.exec_module(helpers)
BRIDGE = '/tmp/ordessa-pi-failure-protocol-acp'
BRIDGE_SHA = '5a2f8f008fdf6fdf274d99f358c37477d8bcf8c4bfacf8cefef2630ef12d1c84'
PI = '/home/maoqh/.local/bin/pi'

def native_audit_summary(output):
    """Count native notifications, preserving unknown HTTP/billing facts."""
    path = output.with_suffix('.acp.jsonl')
    retries, usage = [], []
    def mapping(value):
        return value if isinstance(value, dict) else {}
    if path.exists():
        for line in path.read_text().splitlines():
            message = mapping(json.loads(line)['message'])
            params = mapping(message.get('params'))
            update = mapping(params.get('update'))
            status = params.get('status') or update.get('title')
            if status in ('backend_error_retrying', 'backend_restarted_retrying'):
                retries.append(status)
            for location, value in (('params', params), ('update', update),
                    ('result', mapping(message.get('result'))),
                    ('error.data.usage', mapping(mapping(mapping(message.get('error')).get('data')).get('usage')))):
                fields = {k:value[k] for k in ('used','size','cost') if k in value}
                if fields:
                    usage.append({'source':location, 'values':fields})
    return {'native_retry_notifications':retries,
        'native_retry_notification_count':len(retries),
        'native_http_attempt_count':'not exposed by ACP; not inferred from notifications',
        'usage_cost_evidence':usage,
        'billing_source':'native ACP usage/cost when present; no provider billing statement',
        'actual_billed_amount':'unknown'}

def qualify(output):
    output.parent.mkdir(parents=True, exist_ok=True)
    phase_path = output.with_suffix('.phase.json')
    if output.exists() or phase_path.exists():
        raise RuntimeError('existing_attempt_refused_inspect_original_receipt')
    def checkpoint(phase, prompt_intents=0):
        phase_path.write_text(json.dumps({
            'phase':phase,'prompt_intents':prompt_intents,'consumer_replays':0,'paid_fallback':False})+'\n')
    checkpoint('preparing')
    if hashlib.sha256(Path(BRIDGE).read_bytes()).hexdigest() != BRIDGE_SHA:
        raise RuntimeError('bridge_pin_changed')
    with retained_attempt_root(output) as temporary:
        root = Path(temporary)/'environment'
        roots = {k: str(root/k) for k in ('home', 'cwd', 'piHome')}
        definition = {'environmentNamespace': 'env', 'definitionId': 'pi', 'revision': 'live-go-fixed-1'}
        descriptor = RuntimeProviderDescriptor('pi', RUNTIME_PROVIDER_VERSION, definition, 'sha256:'+'a'*64,
            ('plan_preparation','prepare','start','connect','describe_access','stop','release'))
        provider = {'environmentNamespace':'env','providerId':'pi','generation':1,
            'contractVersion':RUNTIME_PROVIDER_VERSION,'implementationDigest':descriptor.implementation_digest}
        authority = helpers.Authority(provider, {'environmentNamespace':'env','nodeId':'unit','generation':1})
        evidence = AcpUnitEvidence(preparation_authority=lambda plan,facts:plan['context']['privateRootFacts'],
            start_authority=authority.continuation, configuration_authority=authority.continuation)
        records = UnitRecords(OperationJournal(Path(temporary)/'original.sqlite'),scope_authority=helpers.Scope(),
            native_evidence=evidence,verifier=authority,epoch_port=SimpleNamespace(current_epoch=lambda n:0),
            termination_evidence=evidence,configuration_evidence=evidence)
        evidence.attach_owner(records)
        environments = helpers.Provider(root, [])
        binding = UnitProcessInputBinding(instance=environments.instance, agent_id='live-pi',sharing=True,
            input_source=ExistingOpenCodeInput('/home/maoqh/projects/ordessa/.env'))
        manifest = {'schemaVersion':'1','harnessDefinitionRef':definition,'declarations':[
            {'declarationId':'fixed-model','configurationKind':'assets.model-provider','schemaVersion':'1',
             'action':'value','requirement':'required','payload':{'provider':'opencode-go','model':'glm-5.3-flash',
             'protocol':'openai-chat','endpoint':'https://opencode.ai/zen/go/v1'}}]}
        revision = ProfileRevisionRef('env','profile',1,content_digest(canonical_content(manifest,'env')))
        snapshot = {'ref':encode_revision_ref(revision),'manifest':manifest}
        materializer = PiUnitProfileMaterializer(fixed_revision=revision,harness_definition_ref=definition,
            model_declaration_id='fixed-model',model_catalogue=['glm-5.3-flash'],credential_environment_variable='OPENCODE_API_KEY')
        leases = ConnectionLeasePort()
        unit = UnitInstance(descriptor=descriptor,agent_id='live-pi',profile_revision=revision,
            environment_instance=binding.capability,environment_sharing=True,
            environment_reference={'environmentId':environments.identity},
            preparation=PiAcpHarnessPreparation(bridge_executable=BRIDGE,bridge_sha256=BRIDGE_SHA,pi_executable=PI,
                **materializer.selected_launch_configuration(snapshot)),materializer=materializer,records=records,
            projection=evidence,verifier=authority,lease_port=leases,termination_evidence=evidence,timeout=20)
        binding.attach(unit)
        try:
            plan = unit.plan_preparation(snapshot,{'nodeRef':authority.node,'privateRootFacts':roots},{'scope':'one synthetic live prompt'})
            prepared = unit.prepare(plan,authority.issue('prepare'))
            start = authority.issue('start')
            binding.fix_start(prepared,start)
            unit.start(prepared,start)
            checkpoint('native_started')
            ref = prepared['unitRef']
            lease = leases.grant(ref)
            configuration = unit.configuration_snapshot(ref,lease)
            model = next(o['currentValue'] for o in configuration['configOptions'] if o['id']=='model')
            if model != 'opencode-go/glm-5.3-flash':
                raise RuntimeError('fixed_model_changed')
            client = unit.channel_factory.owned_record.entry
            audit_secret = ExistingOpenCodeInput('/home/maoqh/projects/ordessa/.env').read()
            audit_active = True
            def observe(event):
                # Original SDK observer: evidence only; never sends or retries.
                if not audit_active:
                    return
                raw = json.dumps({'direction':event.direction.value,'message':event.message},
                    ensure_ascii=False)
                raw = raw.replace(audit_secret.decode('ascii'), '[REDACTED]')
                with output.with_suffix('.acp.jsonl').open('a') as stream:
                    stream.write(raw+'\n')
            client.sdk_connection.add_observer(observe)
            checkpoint('prompt_intent_recorded', 1)
            try:
                response = unit.prompt(ref,lease,prompt=[{'type':'text','text':'Do not use tools or read files. Reply with exactly ORDESSA_PI_OK.'}],timeout=45)
            finally:
                audit_active = False
                audit_secret[:] = b'\0'*len(audit_secret)
            checkpoint('prompt_receipt_received', 1)
            chunks = []
            for event in client.events():
                raw = event.raw
                update = raw.get('params',{}).get('update',{})
                if raw.get('method')=='session/update' and update.get('sessionUpdate')=='agent_message_chunk':
                    chunks.append(update.get('content',{}).get('text',''))
            text = ''.join(chunks)
            stopped = unit.stop(ref,authority.issue('stop'))
            exited = unit.channel_factory.owned_record.process.observe().state
            released = unit.release(ref,authority.issue('release'))
            secret = ExistingOpenCodeInput('/home/maoqh/projects/ordessa/.env').read()
            try:
                if secret.decode('ascii') in text or any(bytes(secret) in p.read_bytes() for p in Path(temporary).rglob('*') if p.is_file()):
                    raise RuntimeError('credential_persistence_detected')
            finally:
                secret[:] = b'\0'*len(secret)
            return {'kind':'actual-Pi-ACP-OpenCode-Go-qualification','model':model,'profile_revision':encode_revision_ref(revision),
                'bridge_sha256':BRIDGE_SHA,'pi_sha256':hashlib.sha256(Path(PI).read_bytes()).hexdigest(),
                'prompt_result':response,'assistant_text':text,'quality_pass':text.strip()=='ORDESSA_PI_OK',
                'acp_prompts':1,'consumer_replays':0, **native_audit_summary(output),
                'paid_fallback':False,'stop':stopped['state'],'process':exited,
                'release':released['state'],'active_uses':environments.instance.snapshot.active_uses,
                'credential_persisted':False,'invocation_owner':'controlled original fixture; not production human Grant',
                'product_end_to_end_complete':False}
        except Exception as error:
            details = {'status':'qualification_failed','error_type':type(error).__name__,
                'consumer_replays':0,'attempt_replay_permitted':False,
                'frames':[{'file':frame.filename,'line':frame.lineno,'function':frame.name}
                    for frame in traceback.extract_tb(error.__traceback__)]}
            # Native/owner text can contain process inputs. Preserve structural
            # cause boundaries without printing messages, arguments or locals.
            causes = []
            cause = error.__cause__ or error.__context__
            visited = {id(error)}
            while cause is not None and id(cause) not in visited:
                visited.add(id(cause))
                causes.append({'error_type':type(cause).__name__, 'frames':[
                    {'file':frame.filename,'line':frame.lineno,'function':frame.name}
                    for frame in traceback.extract_tb(cause.__traceback__)]})
                cause = cause.__cause__ or cause.__context__
            details['cause_boundaries'] = causes
            if callable(getattr(error, 'errors', None)):
                details['validation_errors'] = [{'location':list(item['loc']),'type':item['type']}
                    for item in error.errors(include_input=False, include_url=False)]
            output.with_suffix('.failure.json').write_text(json.dumps(details,indent=2)+'\n')
            raise
        finally:
            cleanup = cleanup_attempt(unit, authority,
                prepared=locals().get('prepared'), released=locals().get('released'), binding=binding)
            cleanup['active_uses'] = environments.instance.snapshot.active_uses
            cleanup['cleanup_completed'] = cleanup['cleanup_completed'] and cleanup['active_uses'] == 0
            output.with_suffix('.cleanup.json').write_text(json.dumps(cleanup, indent=2)+'\n')
            output.with_suffix('.native-summary.json').write_text(json.dumps(
                native_audit_summary(output), indent=2)+'\n')

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--authorize-live',action='store_true')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not args.authorize_live:
        raise SystemExit('explicit_live_authorization_required')
    if args.output.exists() or args.output.with_suffix('.phase.json').exists() or args.output.with_suffix('.root.json').exists():
        raise SystemExit('existing_attempt_refused_inspect_original_receipt')
    try:
        receipt=qualify(args.output)
        args.output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(receipt,ensure_ascii=False,indent=2))
    except Exception as error:
        failure = args.output.with_suffix('.failure.json')
        if not failure.exists():
            args.output.parent.mkdir(parents=True, exist_ok=True)
            failure.write_text(json.dumps({**failure_boundary(error),
                'status':'qualification_failed', 'consumer_replays':0,
                'attempt_replay_permitted':False}, indent=2)+'\n')
        print(json.dumps({'status':'qualification_failed','error_type':type(error).__name__}))
        raise SystemExit(1)
