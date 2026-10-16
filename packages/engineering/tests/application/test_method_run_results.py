"""Result-routed non-loop stop outcomes preserve declared terminal state."""
from dataclasses import asdict

from ordessa_engineering.application.contracts.method_work import WORK_CONTRACT, WAIT_EVENT
from ordessa_engineering.application.contracts.run_waits import run_wait_row_digest
from test_method_work import adopt_workflow_variant, call, env, query


def test_accepted_result_route_stops_without_spending_loop_round(env):
    e=env
    workflow={'schema_version':1,'workflow_id':'accepted-route-does-not-loop','entry':'seed',
        'resume_contract':WORK_CONTRACT,
        'context_slots':['kind','initial','artifact_ref'],'wait_kinds':['owner_reconciliation'],
        'stop_outcomes':['accepted','rejected'],'outputs':{'primary_artifact':'artifact_ref'},
        'steps':[
            {'id':'seed','kind':'wait','event':WAIT_EVENT,
             'bind':{'artifact_ref':'event.artifact_ref'},'next':'capture'},
            {'id':'capture','kind':'operation','operation':'engineering.artifacts.create',
             'inputs':{'kind':'kind','initial':'initial'},
             'outcomes':{'completed':{'stop':'rejected'},'rejected':{'stop':'rejected'}},
             'result_routing':{'path':'/revision_ref/project_id',
                 'outcomes':{'project-1':{'next':'done'},'rework':{'next':'capture'}}}},
            {'id':'done','kind':'stop','outcome':'accepted'},
        ],
        'loops':[{'loop_id':'retry-capture','from_step':'capture','to_step':'capture',
                  'max_rounds':3,'on_exhausted':'rejected'}]}
    adopt_workflow_variant(e,workflow,'test.current-work-accepted-result')
    call(e,'engineering.work.start',{'run_id':'accepted-route-run'},'accepted-route-start')
    ready=query(e,WAIT_EVENT,{'run_id':'accepted-route-run'})
    call(e,'engineering.runs.resume',{'run_id':'accepted-route-run',
        'expected_row_digest':ready['row_digest'],
        'expected_condition_digest':ready['condition_digest'],
        'expected_next_step_ordinal':ready['next_step_ordinal']},'accepted-route-resume')
    row=query(e,'engineering.work.get',{'run_id':'accepted-route-run'})
    result=call(e,'engineering.artifacts.create',{
        'kind':row['inputs']['slots']['kind'],'initial':row['inputs']['slots']['initial']},
        'accepted-route-command')
    assert result.status=='completed'
    current=e['lib'].run_row('accepted-route-run')
    recorded=call(e,'engineering.work.record_command_step',{
        'run_id':'accepted-route-run','operation_request_id':'accepted-route-command',
        'expected_row_digest':asdict(run_wait_row_digest(current)),
        'expected_next_step_ordinal':0},'accepted-route-record')
    assert recorded.result['status']=='SLICE_DONE'
    final=e['lib'].run_row('accepted-route-run')
    assert final['status']=='SLICE_DONE' and final['inputs']['rounds']=={'retry-capture':1}
    steps=e['lib'].step_rows('accepted-route-run')
    assert len(steps)==1 and steps[0]['attempt']==1
    with e['factory'].begin(e['scope'],'read') as uow:
        receipt=uow.workflow.read(steps[0]['receipt_ref'])
    assert receipt['stop_outcome']=='accepted'
    assert receipt['result_outcome']=='project-1'
