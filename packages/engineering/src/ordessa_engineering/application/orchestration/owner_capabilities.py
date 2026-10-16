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
            'params':{'type':'object','x-maxCanonicalBytes':262144,
                'description':'Canonical JSON object; callback keys are forbidden recursively; the session is fixed by the original Unit session.'},
            'actions':{'type':'array','items':{'type':'string','enum':['edit_repository','run_checks','create_local_commit','export_bundle','publish_branch','deploy']},
                'minItems':1,'uniqueItems':True},
            'timeout':{'type':'number','exclusiveMinimum':0,'maximum':60}}}},
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
            limits={'unit_ref_canonical_bytes_max':4096,'prompt_canonical_bytes_max':262144,
                    'attempt_min':1,'attempt_max':4096,'timeout_max_seconds':60},
            note='Outcome is only the original native RPC record status; engineering_completed is always false.'),
        _descriptor('engineering.submissions.record_report',
            {'type':'object','additionalProperties':False,'required':['record'],
             'properties':{'record':_SUBMISSION_RECORD},'x-maxCanonicalBytes':2097152}, ['submitted','unknown'],
            guards=['original UnitRecords capture','same-authority BlobStore',
                    'selected Method schema and actual report response','trusted original work/step/attempt binding',
                    'current package Grant and complete review gates','original Submission graph and UoW'],
            effect='Persist immutable authored report Submission; workflow_state submitted, review_status pending_review, accepted false.',
            idempotency='Original CommandContext key plus exact report-mode Submission digest; no replay as legacy record.',
            limits={'record_canonical_bytes_max':2097152,'report_observation_bytes_max':262144},
            note='Only fixed Artifact outputs and MethodContent reports. File/test/effect claims remain asserted report data, never verified facts or pass.'),
    )


def detached_owner_capabilities():
    """Convenience copy for consumers that retain mutable schema mappings."""
    return tuple(CapabilityDescriptor(item.capability_id, item.kind, item.interface_version,
                                      item.contract_digest, deepcopy(dict(item.contract)))
                 for item in owner_capabilities())
