"""Original graph + actual Codex owner's pure declaration compiler; no Harness."""
import argparse
import asyncio
from dataclasses import replace
import importlib.util
import json
from pathlib import Path

from pacthold.public import Environment, InstallationRecord
from pacthold.agents.public import AgentContributionSet, OwnerProposalInput, agent_services
from ordessa_environment_api.operations import safe_json
from ordessa_harness_codex import CodexRuntimeProvider
from ordessa_harness_codex import provider as native
from ordessa_decision.contracts import ValidationObligation, plain, digest
from ordessa_decision.integrations.ordessa import OwnerProposalValidator
from ordessa_decision.runtime import reviewed_code_digest

_spec=importlib.util.spec_from_file_location('codex_edge_helpers',Path(__file__).with_name('edge_flow_probe.py'))
edge=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(edge)


def binding_digest():
    return reviewed_code_digest(__file__,Path(native.__file__))


class NativeBinding:
    """A temporary real core, with the original Codex owner; no runtime ports."""
    def __init__(self,plan):
        edge.validate(plan,binding_digest=binding_digest())
        fixture=plan['fixture']; offer=fixture['offer']; identity=offer['provider_ref']['identity']
        if set(identity)!={'definition_ref','provider_ref'}: raise edge.EvaluationError('native_binding_invalid')
        self.definition=identity['definition_ref']
        if set(self.definition)!={'environmentNamespace','definitionId','revision'}: raise edge.EvaluationError('native_binding_invalid')
        implementation=reviewed_code_digest(Path(native.__file__))
        if offer['descriptor_digest']!=implementation: raise edge.EvaluationError('native_binding_invalid')
        class Policy:
            def admit_object_access(self,*args): return True
        self.env=Environment(self.definition['environmentNamespace'],policy=Policy(),principal_scope='synthetic-codex-read')
        self.effects=[]
        try:
            activation=identity['provider_ref']['ownerActivationRef']; plugin=activation['pluginId']
            self.env.install(InstallationRecord(plugin,implementation[7:]));self.env.enable(plugin)
            self.owner=CodexRuntimeProvider(definition_ref=self.definition,implementation_digest=implementation)
            def forbidden(*args,_method=None,**kwargs):
                self.effects.append(_method);raise edge.EvaluationError('native_effect_forbidden')
            for method in ('prepare','start','connect','apply_configuration','query_change','inspect_configuration',
                '_read_configuration','_facts','inspect_installation','plan_preparation','stop','release','recover'):
                setattr(self.owner,method,lambda *a,_method=method,**kw:forbidden(*a,_method=_method,**kw))
            self.env.activate(plugin,AgentContributionSet(agent_runtime_providers=(self.owner,)))
            self.api=agent_services(self.env); self.offers=self.api.providers.describe_configuration_offers(self.definition)
            description=self.offers.offers[0]
            expected_offer_ref={'source_namespace':offer['provider_ref']['source_namespace'],
                'identity':{'definition_ref':self.definition,'kind':description.configuration_kind,
                    'schema_version':description.schema_version}}
            if (safe_json(identity['provider_ref'])!=safe_json(self.offers.owner_ref)
                    or offer['provider_ref']['source_namespace']!='ordessa'
                    or safe_json(offer['offer_ref'])!=safe_json(expected_offer_ref)
                    or plain(offer['evidence_refs'])!=plain(self.offers.evidence_refs)
                    or offer['descriptor_revision']!=self.offers.descriptor_revision
                    or offer['configuration_kind']!=description.configuration_kind
                    or offer['schema_version']!=description.schema_version
                    or offer['input_schema']!=plain(description.input_schema)
                    or offer['support_status']!='unknown' or self.offers.complete is not False
                    or fixture['kind']!='configuration_unverifiable'):
                raise edge.EvaluationError('native_offer_mapping_invalid')
        except BaseException:
            self.env.close();raise

    def services(self,values,fixture,provider,sink,context,row,save,mode):
        settings,policy,kind,candidate,draft,offer,flow,request=values
        compile_obligation=ValidationObligation('native_compile',candidate.observation.subject_ref,
            'must','codex.defaults.compile',native.DEFAULTS_SCHEMA)
        draft=replace(draft,required_validation_obligations=draft.required_validation_obligations+(compile_obligation,))
        def mapped(draft):
            return {'declarations':[{'declarationId':fixture['template_id'],
                'configurationKind':offer.configuration_kind,'schemaVersion':offer.schema_version,
                'action':'value','requirement':'required','payload':plain(draft.payload['configuration'])}]}
        def builder(draft,basis):
            return OwnerProposalInput(self.definition,self.offers.owner_ref,self.offers.descriptor_revision,
                mapped(draft),(self.definition,),
                tuple({'obligationId':o.obligation_id,'requirement':o.requirement,
                    'checkerId':o.validator_kind,'checkerVersion':o.version_constraint}
                    for o in draft.required_validation_obligations))
        def verifier(draft,basis,value):
            return (draft.payload['action']==candidate.capability_claims['action']
                and draft.payload['configuration_kind']==offer.configuration_kind
                and safe_json(value.proposal_data)==safe_json(mapped(draft))
                and safe_json({'refs':value.source_refs})==safe_json({'refs':(self.definition,)})
                and safe_json(value.provider_ref)==safe_json(self.offers.owner_ref))
        actual=OwnerProposalValidator(self.api.providers,input_builder=builder,input_verifier=verifier,read_context=context)
        binding=self
        class Validator:
            async def validate(self,draft,basis,read_context):
                receipt=await actual.validate(draft,basis,read_context)
                row['validate_calls'].append(plain(receipt));row['native_effects']=len(binding.effects);save()
                if binding.effects: raise edge.EvaluationError('native_effect_forbidden')
                checked={v.obligation_id:v for v in receipt.obligation_results}
                if (receipt.status!='unverifiable'
                        or receipt.validation_scope!='codex.defaults.declaration-compile/'+native.DEFAULTS_SCHEMA
                        or checked['native_compile'].status!='passed' or checked['configuration'].status!='unknown'):
                    raise edge.EvaluationError('native_scope_evidence_mismatch')
                return receipt
        row['port_binding']={'owner':'actual CodexRuntimeProvider','scope':'declaration_compile_only',
            'offer':self.offers.to_dict(),'composed_proposal':plain(draft),
            'candidate_scope':'controlled synthetic candidate; no native unit or installation proof',
            'owner_input_scope':'original public core routing and actual native compiler; no native process'}
        row['native_effects']=len(self.effects)
        values=(settings,policy,kind,candidate,draft,offer,flow,request)
        services=edge._services(values,fixture,provider,sink,context,row,save,mode)
        return replace(services,validator=Validator())

    def close(self): self.env.close()


async def prepare(plan):
    binding=NativeBinding(plan)
    try:
        return await edge.prepare(plan,binding_digest=binding_digest(),services_factory=binding.services)
    finally: binding.close()


async def run_plan(plan,output,credential_file,authorize_live=False,*,ledger_path,transport=None):
    # The existing collector owns finite budgets, SDK/permit, ledger, redaction,
    # cancellation and durable terminal. No alternative executor is introduced.
    binding=NativeBinding(plan)
    try:
        receipt=await edge.run_plan(plan,output,credential_file,authorize_live,ledger_path=ledger_path,
            transport=transport,binding_digest=binding_digest(),services_factory=binding.services)
        receipt['owner_scope']='actual CodexRuntimeProvider pure compiler, temporary core, controlled candidate'
        receipt['native_effects']=len(binding.effects)
        edge.live.atomic_write(Path(output)/'receipt.json',receipt)
        return receipt
    finally: binding.close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=('prepare','run'))
    parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ledger',type=Path);parser.add_argument('--credential-file',type=Path)
    parser.add_argument('--authorize-live',action='store_true');args=parser.parse_args()
    try:
        plan=json.loads(args.plan.read_text())
        if args.mode=='prepare': edge.live.atomic_write(args.output/'prepared.json',asyncio.run(prepare(plan)))
        else:
            if args.ledger is None or args.credential_file is None: raise edge.EvaluationError('live_arguments_required')
            asyncio.run(run_plan(plan,args.output,args.credential_file,args.authorize_live,ledger_path=args.ledger))
    except BaseException: print('evaluation_failed');return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
