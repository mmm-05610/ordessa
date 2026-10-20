"""Detached descriptions of original owner operations; never auto-registered."""
from copy import deepcopy

from ...methods.definitions.models.capabilities import CapabilityDescriptor
from ...methods.definitions.models.identity import method_digest


def _obj(fields, required=None):
    return {'type':'object','additionalProperties':False,'required':list(fields if required is None else required),
            'properties':{name: schema for name, schema in fields.items()}}


def _array(item={}):
    return {'type':'array','items':item}


_DIGEST = _obj({'algorithm':{'const':'sha256'},'hex':{'type':'string','pattern':'^[0-9a-f]{64}$'}})
_SCOPE = _obj({'realm_id':{'type':'string'},'project_id':{'type':'string'}})
_BLOB = _obj({'digest':_DIGEST,'byte_length':{'type':'integer','minimum':0},'media_type':{'type':'string'},'storage_object_id':{'type':'string'}})
_ARTIFACT_REF = _obj({'realm_id':{'type':'string'},'project_id':{'type':'string'},'artifact_id':{'type':'string'},'revision_id':{'type':'string'},'digest':_DIGEST,'kind':{'const':'artifact_revision'}})
_PROPOSAL_REF = _obj({'realm_id':{'type':'string'},'project_id':{'type':'string'},'change_id':{'type':'string'},'proposal_id':{'type':'string'},'digest':_DIGEST,'kind':{'const':'proposal'}})
_APPROVAL_REF = _obj({'realm_id':{'type':'string'},'project_id':{'type':'string'},'approval_id':{'type':'string'},'grant_digest':_DIGEST,'kind':{'const':'approval'}})
_PACKAGE_REF = _obj({'realm_id':{'type':'string'},'project_id':{'type':'string'},'package_id':{'type':'string'},'digest':_DIGEST,'kind':{'const':'implementation_package'}})
_REPOSITORY_REF = _obj({'realm_id':{'type':'string'},'project_id':{'type':'string'},'repository_id':{'type':'string'},'vcs':{'enum':['git','none']},'commit_id':{'type':['string','null']},'tree_digest':_DIGEST,'dirty_overlay_digest':{'oneOf':[_DIGEST,{'type':'null'}]},'kind':{'const':'repository_snapshot'}})
_METHOD_REF = _obj({'method_id':{'type':'string'},'release_version':{'type':'string'},'schema_version':{'type':'integer','minimum':1},'snapshot_digest':_DIGEST})
_EXACT_RESOURCE = _obj({'method_ref':_METHOD_REF,'logical_path':{'type':'string'},'resource_digest':_DIGEST,'resource_id':{'type':'string'}})
_REVIEW_REF = _obj({'realm_id':{'type':'string'},'project_id':{'type':'string'},'review_id':{'type':'string'},'digest':_DIGEST,'kind':{'const':'review'}})
_TEMPLATE_REF = _obj({'scope':_SCOPE,'template_id':{'type':'string'},'template_version':{'type':'integer','minimum':1},'digest':_DIGEST})
_ENVIRONMENT_REF = _obj({'environment_id':{'type':'string'},'profile_id':{'type':'string'},'profile_digest':_DIGEST})
_METHOD_CONTENT = _obj({'schema_ref':_EXACT_RESOURCE,'value':{},'rendered_body_ref':{'oneOf':[_BLOB,{'type':'null'}]}})
_OUTPUT_REF = {'oneOf':[_obj({'kind':{'const':'blob'},'digest':_DIGEST,
    'byte_length':{'type':'integer','minimum':0},'media_type':{'type':'string'},
    'storage_object_id':{'type':'string'}}),_ARTIFACT_REF]}
_JSON_OBJECT = {'type':'object'}
_SOURCE_LOCATOR = _obj({'kind':{'enum':['chat_message','agents_file','code','document','artifact','tool_observation']},
    'provider':{'type':['string','null']},'conversation_id':{'type':['string','null']},
    'message_id':{'type':['string','null']},'repository_id':{'type':['string','null']},
    'path':{'type':['string','null']},'document_id':{'type':['string','null']},
    'artifact_ref':{'oneOf':[_ARTIFACT_REF,{'type':'null'}]},'observation_id':{'type':['string','null']}})
_SELECTOR = _obj({'kind':{'enum':['whole_capture','byte_range','json_pointer']},
    'start':{'type':['integer','null']},'end':{'type':['integer','null']},
    'pointer':{'type':['string','null']},'schema_version':{'const':1}})
_SOURCE_CAPTURE = {'oneOf':[
    _obj({'upstream_version':{'type':'string'},'content_digest':_DIGEST,'kind':{'const':'immutable_version'}}),
    _obj({'blob_ref':_BLOB,'excerpt_digest':_DIGEST,'selector':_SELECTOR,
          'upstream_version':{'type':['string','null']},'kind':{'const':'immutable_excerpt'}})]}
_SOURCE_REF = _obj({'source_id':{'type':'string'},'kind':_SOURCE_LOCATOR['properties']['kind'],
    'locator':_SOURCE_LOCATOR,'capture':_SOURCE_CAPTURE,'captured_at':{'type':'string'},
    'captured_by':_obj({'actor_id':{'type':'string'},'actor_kind':{'enum':['human','agent','checker','service']},'issuer':{'type':'string'}}),
    'media_type':{'type':'string'},'byte_length':{'type':'integer','minimum':0,'maximum':16777216},
    'original_url':{'type':['string','null']}})
_PACKAGE_PAYLOAD = _obj({
    'implementation_intent_id':{'type':'string'}, 'change_set':_obj({'proposal_refs':_array(_PROPOSAL_REF),'digest':_DIGEST}),
    'design_targets':_array(_ARTIFACT_REF), 'authorization_refs':_array(_APPROVAL_REF), 'method_ref':_METHOD_REF,
    'required_review_refs':_array(_REVIEW_REF), 'baseline_snapshots':_array(_REPOSITORY_REF),
    'resolved_file_manifest':_array(_obj({'repository_id':{'type':'string'},'path':{'type':'string'},
        'operation':{'enum':['add','modify','delete','rename']},'before_blob_digest':{'oneOf':[_DIGEST,{'type':'null'}]},
        'rename_from':{'type':['string','null']},'proposal_refs':_array(_PROPOSAL_REF),'purpose':{'type':'string'}})),
    'instructions_ref':_BLOB, 'skill_snapshot_refs':_array(_EXACT_RESOURCE), 'execution_profile_ref':_ENVIRONMENT_REF,
    'allowed_actions':_array({'type':'string'}), 'acceptance_requirements':_array(_TEMPLATE_REF),
    'proposal_coverage':_array(_obj({'proposal_ref':_PROPOSAL_REF,'instructions':_array(_BLOB),'files':_array({'type':'string'}),
        'acceptance_requirements':_array(_TEMPLATE_REF),'basis_refs':_array(_ARTIFACT_REF)})),
    'method_content':{'oneOf':[_METHOD_CONTENT,{'type':'null'}]}, 'derivation':_obj({'intent_digest':_DIGEST,'input_refs':_array(_BLOB),
        'generator_id':{'type':'string'},'generator_version':{'type':'string'},'output_manifest_digest':_DIGEST}),
    'package_schema':{'const':'ordessa.implementation-package/v1'},
})
_PREPARED_PACKAGE_PAYLOAD = _obj({
    'baseline':_SOURCE_REF,'candidate':_SOURCE_REF,'change_ref':_PROPOSAL_REF,
    'review_refs':_array(_REVIEW_REF),'method_ref':_METHOD_REF,
    'method_resource_refs':_array(_EXACT_RESOURCE),
    'documents':_array(_obj({'role':{'type':'string','minLength':1,'maxLength':128},
                             'source_ref':_SOURCE_REF})),
    'package_schema':{'const':'ordessa.implementation-package/v2'},
})
_PACKAGE_RECORD = _obj({'scope':_obj({'realm_id':{'type':'string'},'project_id':{'type':'string'}}),
    'package_id':{'type':'string','minLength':1,'maxLength':512},'created_at':{'type':'string'},
    'created_by':_obj({'actor_id':{'type':'string'},'actor_kind':{'enum':['human','agent','checker','service']},'issuer':{'type':'string'}}),
    'payload':{'oneOf':[_PACKAGE_PAYLOAD,_PREPARED_PACKAGE_PAYLOAD]},'digest':_DIGEST})

_EXECUTION_RECORD_REF = _obj({'environment_namespace':{'type':'string'},'unit_id':{'type':'string'},
    'owner_provider_ref_bytes':_JSON_OBJECT,'source_revision':{'type':'string'},'operation_ref':{'type':'string'},
    'prompt_input_digest':_DIGEST,'captured_observation_ref':_BLOB})
_FILE_CHANGE = _obj({'change_id':{'type':'string'},'repository_id':{'type':'string'},
    'normalized_path':{'type':'string'},'operation':{'enum':['add','modify','delete','rename']},
    'before_blob_digest':{'oneOf':[_DIGEST,{'type':'null'}]},'after_blob_digest':{'oneOf':[_DIGEST,{'type':'null'}]},
    'rename_from':{'type':['string','null']},'proposal_refs':_array(_PROPOSAL_REF)})
_TEST_EVIDENCE = _obj({'check_id':{'type':'string'},'requirement_id':{'type':'string'},
    'subject_snapshot':_REPOSITORY_REF,'execution_ref':_EXECUTION_RECORD_REF,
    'result':{'enum':['pass','fail','unknown','not_run']},'observation_ref':_BLOB,
    'tool_version':{'type':'string'},'measured_at':{'type':'string'}})
_EFFECT = _obj({'effect_id':{'type':'string'},'action':{'type':'string'},
    'target_ref':_obj({'target_id':{'type':'string'},'constraint_digest':_DIGEST}),
    'observed_state':{'enum':['not_started','applied','reverted','unknown']},'evidence_refs':_array(_BLOB),
    'reversible':{'type':'boolean'},'compensation_ref':{'oneOf':[_BLOB,{'type':'null'}]}})
_SUBMISSION_RECORD = _obj({
    # submission_projection/decode_submission wire fields (scope is expanded as ids).
    'realm_id':{'type':'string'},'project_id':{'type':'string'},'submission_id':{'type':'string'},
    'created_at':{'type':'string'},'created_by':_obj({'actor_id':{'type':'string'},'actor_kind':{'enum':['human','agent','checker','service']},'issuer':{'type':'string'}}),
    'change_set':_obj({'proposal_refs':_array(_PROPOSAL_REF),'digest':_DIGEST}),
    'authorization_refs':_array(_APPROVAL_REF),'package_ref':_PACKAGE_REF,'execution_ref':_EXECUTION_RECORD_REF,
    'baseline_snapshots':_array(_REPOSITORY_REF),'resulting_snapshots':_array(_REPOSITORY_REF),'commit_refs':_array(_obj({'repository_id':{'type':'string'},'commit_id':{'type':'string','pattern':'^([0-9a-f]{40}|[0-9a-f]{64})$'},'tree_digest':_DIGEST})),
    'file_changes':_array(_FILE_CHANGE),'output_refs':_array(_OUTPUT_REF),'test_evidence':_array(_TEST_EVIDENCE),
    'effect_observations':_array(_EFFECT),
    'coverage':_array(_obj({'proposal_ref':_PROPOSAL_REF,'output_refs':_array(_OUTPUT_REF),'file_change_ids':_array({'type':'string'}),
        'evidence_refs':_array(_OUTPUT_REF),'disposition':{'enum':['implemented','unchanged_with_reason','not_implemented']},
        'reason':{'type':['string','null']}})),
    'source_refs':_array(_SOURCE_REF),'method_content':{'oneOf':[_METHOD_CONTENT,{'type':'null'}]},
    'checkpoint_ref':{'oneOf':[_BLOB,{'type':'null'}]},'digest':_DIGEST,
})
_SUBMISSION_RECORD_V2 = deepcopy(_SUBMISSION_RECORD)
_SUBMISSION_RECORD_V2['properties']['schema_version'] = {'const': 2}
_SUBMISSION_RECORD_V2['required'].append('schema_version')
for _field in ('baseline_snapshots', 'resulting_snapshots', 'commit_refs',
               'file_changes', 'test_evidence', 'effect_observations'):
    _SUBMISSION_RECORD_V2['properties'][_field]['maxItems'] = 0
_SUBMISSION_RECORD_V2['properties']['checkpoint_ref'] = {'type': 'null'}
_SUBMISSION_RECORD_V2['properties']['output_refs'] = {
    'type': 'array', 'minItems': 1, 'maxItems': 1, 'items': _OUTPUT_REF['oneOf'][0]}
_SUBMISSION_RECORD_V2['properties']['method_content'] = deepcopy(_METHOD_CONTENT)
_SUBMISSION_RECORD_V2['properties']['method_content']['properties']['rendered_body_ref'] = _BLOB
_SUBMISSION_RECORD = {'oneOf': [_SUBMISSION_RECORD, _SUBMISSION_RECORD_V2]}
_UNIT_REF = {
    'type':'object','additionalProperties':False,
    'required':['environmentNamespace','unitId','ownerProviderRef','sourceRevision'],
            'properties': {'environmentNamespace':{'type':'string','minLength':1,'maxLength':512},
        'unitId':{'type':'string','minLength':1,'maxLength':512},
        'ownerProviderRef':{'type':'object'},
        'sourceRevision':{'type':'string','minLength':1,'maxLength':512}},
}
_UNIT_REF['x-maxCanonicalBytes'] = 4096
_DISPATCH = {
    'type':'object','additionalProperties':False,'required':['dispatch'],
    # The declared Work's own identity, exactly as the working entry accepts it
    # (`EngineeringOwnerOperations._WORK_DISPATCH_FORM`). There is no `run_id`:
    # `additionalProperties` is false, so a run-shaped dispatch request is
    # refused by the schema itself.
    'properties': {'dispatch': {'type':'object','additionalProperties':False,
        'description':'One declared Work step (schema-17 work_step_log); never a run.',
        'required':['work_id','action_id','step_id','attempt','unit_ref','params','actions','timeout'],
        'properties': {'work_id':{'type':'string','minLength':1,'maxLength':512},
            'action_id':{'type':'string','minLength':1,'maxLength':512},
            'step_id':{'type':'string','minLength':1,'maxLength':512},
            'attempt':{'type':'integer','minimum':1,'maximum':4096},'unit_ref':_UNIT_REF,
            'params':{'type':'object','x-maxCanonicalBytes':589824,
                'description':'Canonical JSON object; callback keys are forbidden recursively; the session is fixed by the original Unit session.'},
            'actions':{'type':'array','items':{'type':'string','enum':['edit_repository','run_checks','create_local_commit','export_bundle','publish_branch','deploy']},
                'minItems':1,'uniqueItems':True},
            'timeout':{'type':'number','exclusiveMinimum':0,'maximum':3600}}}},
}
_DISPATCH['x-maxCanonicalBytes'] = 2097152


def _descriptor(capability_id, input_schema, outcomes, *, guards, effect, idempotency, limits, note,
                interface_version='1', input_schema_id=None):
    contract = {
        'contract_version':'ordessa.engineering-owner-operation/1',
        'input_schema_id':input_schema_id or f'urn:ordessa:engineering:owner-operation:{capability_id}:input:1',
        'input_schema':input_schema,
        'workflow_outcomes':list(outcomes),
        'throws':'Original owner exceptions propagate; the adapter does not translate refusals.',
        'factory_contract':'All owners share one SQLiteUoWFactory/authority; Records and BlobStore are composition-owned.',
        'required_original_guards':list(guards), 'effect':effect,
        'idempotency':idempotency, 'limits':limits, 'completion_semantics':note,
        'registered':False,
    }
    if capability_id=='engineering.executions.dispatch':
        contract['method_config_schema']={'type':'object','additionalProperties':False,
            'required':['package_slot','task_prompt'],'properties':{
                'package_slot':{'type':'string','minLength':1},
                'task_prompt':{'type':'object','additionalProperties':False,
                    'required':['template_resource','bindings','actions','timeout'],
                    'properties':{
                        'template_resource':{'type':'string','minLength':1},
                        'bindings':{'type':'object','minProperties':1,'maxProperties':32,
                            'propertyNames':{'type':'string','pattern':'^[A-Za-z_][A-Za-z0-9_]*$'},
                            'additionalProperties':{'type':'string','enum':[
                                'work_id','action_id','step_id','attempt','package_id',
                                'implementation_intent_id',
                                'package_ref','method_ref','change_set','design_targets',
                                'resolved_file_manifest','proposal_coverage','baseline_snapshots',
                                'allowed_actions','execution_profile_ref','instructions_ref','skill_snapshot_refs']}},
                        'actions':_DISPATCH['properties']['dispatch']['properties']['actions'],
                        'timeout':{'type':'number','exclusiveMinimum':0,'maximum':60}}}}}
    return CapabilityDescriptor(capability_id, 'operation', interface_version,
                                method_digest('capability-contract', contract), contract)


def owner_capabilities():
    """Return fresh, detached descriptors. Calling this does not register them."""
    return (
        _descriptor('engineering.packages.freeze',
            {'type':'object','additionalProperties':False,'required':['record'],
             'properties':{'record':_PACKAGE_RECORD},'x-maxCanonicalBytes':2097152}, ['completed','unknown'],
            guards=['Engineering access','exact source and method authorities','current review gates',
                    'original change/proposal/review links and source digests','original command journal'],
            effect='Persist immutable source-reference ImplementationPackage and command journal in original Engineering UoW.',
            idempotency='Original CommandContext key plus exact package-content request digest.',
            limits={'record_canonical_bytes_max':2097152},
            note='completed means package record and journal were reread and matched; it is not dispatch authorization.',
            interface_version='2',input_schema_id='urn:ordessa:engineering:implementation-content:2'),
        _descriptor('engineering.proposals.associate_review',
            {'$schema':'https://json-schema.org/draft/2020-12/schema',
             '$id':'urn:ordessa:engineering:operations:engineering.proposals.associate_review:input:1',
             'type':'object','additionalProperties':False,
             'required':['proposal_ref','expected_version','review_ref'],
             'properties':{'proposal_ref':_PROPOSAL_REF,'expected_version':{'type':'integer','minimum':0},
                           'review_ref':_REVIEW_REF}}, ['completed','rejected','unknown'],
            guards=['Engineering access','original Change CAS and proposal control','exact current completed review',
                    'reviewer trust and current source guards through original UoW COMMIT'],
            effect='Persist immutable successor Proposal on the same Change with the exact ReviewRef; no artifact mutation or grant.',
            idempotency='Original CommandContext key plus exact proposal/version/review request digest.',
            limits={'proposal_ref_canonical_bytes_max':4096,'review_ref_canonical_bytes_max':4096},
            note='This operation associates an existing actual review; it does not manufacture or certify one.'),
        _descriptor('engineering.executions.dispatch', _DISPATCH, ['completed','failed','unknown'],
            guards=['declared Work identity and its own records',
                    'original frozen/admitted package and grant/review/control guards',
                    'source snapshot guard','original UnitRecords query identity','native effect-write lease'],
            effect='One fixed declared Work step attempt reserves its original debit on the declared-Work relation before one native RPC call; no retry.',
            idempotency='Original Work identity/step/attempt and immutable operation binding; unknown sends are not retried.',
            limits={'unit_ref_canonical_bytes_max':4096,'prompt_canonical_bytes_max':589824,
                    'attempt_min':1,'attempt_max':4096,'timeout_max_seconds':3600},
            note='Outcome is only the original native RPC record status; engineering_completed is always false.'),
        _descriptor('engineering.submissions.record_report',
            {'type':'object','additionalProperties':False,'required':['record'],
             'properties':{'record':_SUBMISSION_RECORD},'x-maxCanonicalBytes':2097152}, ['submitted','unknown'],
            guards=['original UnitRecords capture','same-authority BlobStore',
                    'selected Method schema and actual report response','trusted original work/step/attempt binding',
                    'current package Grant and complete review gates','original Submission graph and UoW'],
            effect='Persist immutable authored report Submission; workflow_state submitted, review_status pending_review, accepted false.',
            idempotency='Original CommandContext key plus exact report-mode Submission digest; no replay as legacy record.',
            limits={'record_canonical_bytes_max':2097152,'report_observation_bytes_max':262144,
                    'declared_work_report_observation_bytes_max':2621440},
            note='Historical fixed Artifact reports or explicit v2 Work report Blob outputs. File/test/effect claims remain asserted report data, never verified facts or pass.'),
    )


def detached_owner_capabilities():
    """Convenience copy for consumers that retain mutable schema mappings."""
    return tuple(CapabilityDescriptor(item.capability_id, item.kind, item.interface_version,
                                      item.contract_digest, deepcopy(dict(item.contract)))
                 for item in owner_capabilities())


def agent_dispatch_capability():
    """Explicit v2 Agent dispatch declaration; old v1 bytes remain historical.

    Composition must bind this descriptor with the actual Agent Work owner.
    Merely asking for the descriptor grants no authority or registration.
    """
    schema = deepcopy(_DISPATCH)
    request = schema['properties']['dispatch']
    request['required'] = [key if key != 'unit_ref' else 'agent_ref' for key in request['required']]
    request['properties'].pop('unit_ref')
    request['properties']['agent_ref'] = {
        'type':'object', 'additionalProperties':False,
        'required':['schemaVersion','namespace','instanceId','bindingDigest'],
        'properties':{'schemaVersion':{'const':'agent-instance/1'},
            'namespace':{'type':'string','minLength':1,'maxLength':512},
            'instanceId':{'type':'string','minLength':1,'maxLength':512},
            'bindingDigest':{'type':'string','pattern':'^sha256:[0-9a-f]{64}$'}},
        'x-maxCanonicalBytes':8192}
    request['properties']['params'] = {'type':'object','additionalProperties':False,
        'required':['sessionId'], 'properties':{'sessionId':{'type':'string','minLength':1,'maxLength':8192}},
        'description':'Explicit original fixed-session metadata. The Work owner assembles the authored prompt.'}
    request['properties']['timeout'] = {'type':'number','exclusiveMinimum':0,'maximum':60}
    return _descriptor('engineering.executions.dispatch', schema, ['completed','failed','unknown'],
        interface_version='2',
        input_schema_id='urn:ordessa:engineering:owner-operation:engineering.executions.dispatch:input:2',
        guards=['declared Work identity and exact frozen package subject',
            'original package Grant, method, review, control and action-consumption guards',
            'pinned Agent Profile and original source read',
            'explicit original workspace action-scope fence',
            'original Agent TurnRef/query/input binding and single-use physical effect handoff'],
        effect='One original declared Work/step/attempt reserves its immutable debit before the same original Agent recorded prompt; no retry.',
        idempotency='Original Work identity/step/attempt with fixed original Agent TurnRef; UNKNOWN never restores send rights.',
        limits={'agent_ref_canonical_bytes_max':8192,'prompt_canonical_bytes_max':262144,
                'attempt_min':1,'attempt_max':4096,'timeout_max_seconds':60},
        note='Only original recorded Agent outcome; engineering_completed and accepted remain false.')


def agent_owner_capabilities():
    """Trusted explicit v2 selection; never return two versions of one id."""
    descriptors = {item.capability_id: item for item in (agent_dispatch_capability(), agent_report_capability())}
    return tuple(descriptors.get(item.capability_id, item) for item in owner_capabilities())


def agent_report_capability():
    """Explicit Agent-only input2; original Unit input1 remains historical bytes."""
    properties = deepcopy(_SUBMISSION_RECORD['oneOf'][1]['properties'])
    fields = ('realm_id','project_id','submission_id','created_at','created_by','change_set',
        'authorization_refs','package_ref','output_refs','coverage','source_refs','method_content',
        'checkpoint_ref','digest')
    report = {name: properties[name] for name in fields}
    report['schemaVersion'] = {'const':'engineering-agent-submission-report/1'}
    agent = deepcopy(agent_dispatch_capability().contract['input_schema']['properties']['dispatch']['properties']['agent_ref'])
    turn = _obj({'schemaVersion':{'const':'agent-turn-ref/1'},'instanceRef':agent,'turnId':{'type':'string','minLength':1}})
    report['execution_ref'] = _obj({'schemaVersion':{'const':'engineering-agent-execution-ref/2'},
        'agent_ref_bytes':agent,'turn_ref_bytes':turn,'source_revision':{'type':'string','minLength':1},
        'operation_ref':{'type':'string','minLength':1},'engineering_attempt_ref':{'type':'string','minLength':1},
        'prompt_input_digest':_DIGEST,'query_digest':{'type':'string','pattern':'^sha256:[0-9a-f]{64}$'},
        'captured_observation_ref':_BLOB})
    return _descriptor('engineering.submissions.record_report', _obj({'record':_obj(report)}), ['submitted','unknown'],
        interface_version='2', input_schema_id='urn:ordessa:engineering:owner-operation:engineering.submissions.record_report:input:2',
        guards=['original authorized Agent TurnRef/query/input/operation capture and Profile provenance',
            'same-authority BlobStore','pinned selected Method report schema and Agent input2 contract',
            'original frozen package Grant, full review/control/action-consumption and Work binding',
            'original Submission graph, command journal and COMMIT UoW'],
        effect='Persist one immutable Agent authored report as submitted and pending_review; accepted false.',
        idempotency='Original CommandContext key and explicit input2 digest; replay performs no native read or send.',
        limits={'record_canonical_bytes_max':2097152,'report_observation_bytes_max':262144},
        note='Only ordinary first-attempt Agent Work reports. Checkpoint/continuation require their own new contracts; report file/test/effect text remains asserted.')
