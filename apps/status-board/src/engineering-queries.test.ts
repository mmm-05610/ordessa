import { expect, it, vi } from 'vitest'
import { engineeringQueries } from './engineering-queries'
import type { WireResult } from '@ordessa/system-access-client'
const scope = { realm_id: 'r', project_id: 'p' }
const accepted = (result: Record<string, unknown>): WireResult => ({kind:'Accepted',requestId:'test',result})
it('builds exact query envelope and retains real raw Artifact data', async () => {
  let sent: any
  const access = engineeringQueries({call:async (method,params) => {sent={method,params};return accepted({contract_version:'engineering-wire/1',scope,query:method,record_type:'Artifact',data:{artifact_id:'a',version:3}})}})
  const client=access.createQuery('engineering.artifacts.get',scope,{artifact_id:'a'});await client.refresh()
  expect(sent.method).toBe('engineering.artifacts.get');expect(sent.params).toMatchObject({scope,parameters:{artifact_id:'a'}});expect(sent.params.requestId).toMatch(/^board-query-/)
  expect(client.getSnapshot().stale).toBe(false);expect(client.getSnapshot().data?.data).toEqual({artifact_id:'a',version:3})
})
it('capabilities omits parameters as required by actual descriptor', async () => {
  let sent:any
  const access=engineeringQueries({call:async (_,params)=>{sent=params;return accepted({contract_version:'engineering-wire/1',scope,queries:[],supports:{work_projection:false,durable_events:false,consent:false}})}})
  const client=access.createQuery('engineering.capabilities',scope,{});await client.refresh()
  expect(sent).not.toHaveProperty('parameters');expect(client.getSnapshot().data?.supports).toEqual({work_projection:false,durable_events:false,consent:false})
})
it('rejects mutations and wrong parameter keys before transport', () => {
  const access=engineeringQueries({call:async()=>{throw Error('must not call')}})
  expect(()=>access.createQuery('engineering.proposals.create',scope,{})).toThrow()
  expect(()=>access.createQuery('engineering.artifacts.get',scope,{change_id:'a'})).toThrow()
  expect(()=>access.createQuery('engineering.artifacts.get',{...scope,realm_id:''},{artifact_id:'a'})).toThrow()
})
it('forwards ProposalRef unchanged and does not infer Work or approval', async () => {
  const ref={realm_id:'r',project_id:'p',change_id:'c',proposal_id:'p1',digest:{algorithm:'sha256',hex:'a'.repeat(64)}};let sent:any
  const access=engineeringQueries({call:async(method,params)=>{sent=params;return accepted({contract_version:'engineering-wire/1',scope,query:method,record_type:'Proposal',data:{proposal_id:'p1',intent:'discussion',evidence_links:[]}})}})
  const client=access.createQuery('engineering.proposals.get',scope,{proposal_ref:ref});await client.refresh()
  expect(sent.parameters.proposal_ref).toEqual(ref);expect(client.getSnapshot().data).not.toHaveProperty('works');expect(client.getSnapshot().data).not.toHaveProperty('approval')
})
it.each(['scope','contract','query','data'])('rejects mismatched %s envelope instead of empty success', async type => {
  const record:any={contract_version:'engineering-wire/1',scope,query:'engineering.artifacts.get',record_type:'Artifact',data:{artifact_id:'a'}}
  if(type==='scope')record.scope={realm_id:'other',project_id:'p'}
  if(type==='contract')record.contract_version='wrong'
  if(type==='query')record.query='engineering.changes.get'
  if(type==='data')record.data=null
  const client=engineeringQueries({call:async()=>accepted(record)}).createQuery('engineering.artifacts.get',scope,{artifact_id:'a'});await client.refresh()
  expect(client.getSnapshot().stale).toBe(true);expect(client.getSnapshot().data).toBeUndefined();expect(client.getSnapshot().result?.kind).toBe('Unknown')
})
it('not-found/refused is not accepted empty; later failure preserves old exact record', async () => {
  let refuse=true
  const client=engineeringQueries({call:async(method)=>refuse?{kind:'Refused',requestId:'test',reason:'NOT_FOUND',retryable:false}:accepted({contract_version:'engineering-wire/1',scope,query:method,record_type:'Artifact',data:{artifact_id:'a'}})}).createQuery('engineering.artifacts.get',scope,{artifact_id:'a'})
  await client.refresh();expect(client.getSnapshot().data).toBeUndefined();refuse=false;await client.refresh();const time=client.getSnapshot().lastUpdated
  refuse=true;await client.refresh();expect(client.getSnapshot().stale).toBe(true);expect(client.getSnapshot().data?.data).toEqual({artifact_id:'a'});expect(client.getSnapshot().lastUpdated).toBe(time)
})
it('preserves the last accepted wire envelope while disconnected and replaces it on explicit recovery read', async () => {
  let state: 'first' | 'offline' | 'recovered' = 'first'
  let calls = 0
  const envelopes = {
    first: { contract_version: 'engineering-wire/1', scope, query: 'engineering.artifacts.get', record_type: 'Artifact', data: { artifact_id: 'a', version: 1 } },
    recovered: { contract_version: 'engineering-wire/1', scope, query: 'engineering.artifacts.get', record_type: 'Artifact', data: { artifact_id: 'a', version: 2 } },
  }
  const client = engineeringQueries({ call: async () => {
    calls++
    if (state === 'offline') return { kind: 'Unknown', requestId: `call-${calls}`, reason: 'result-unknown' }
    return { kind: 'Accepted', requestId: `call-${calls}`, result: envelopes[state] }
  } }).createQuery('engineering.artifacts.get', scope, { artifact_id: 'a' })

  vi.useFakeTimers()
  try {
    vi.setSystemTime(new Date('2026-10-12T10:00:00.000Z'))
    await client.refresh()
    const firstRead = client.getSnapshot()
    expect(firstRead.result?.kind).toBe('Accepted')
    expect(firstRead.data).toEqual(envelopes.first)
    expect(firstRead.stale).toBe(false)
    expect(firstRead.lastUpdated).toBe('2026-10-12T10:00:00.000Z')
    expect(calls).toBe(1)

    state = 'offline'
    vi.setSystemTime(new Date('2026-10-12T10:01:00.000Z'))
    await client.refresh()
    const disconnected = client.getSnapshot()
    expect(disconnected.result).toMatchObject({ kind: 'Unknown', reason: 'result-unknown' })
    expect(disconnected.data).toEqual(envelopes.first)
    expect(disconnected.lastUpdated).toBe(firstRead.lastUpdated)
    expect(disconnected.stale).toBe(true)
    expect(calls).toBe(2)

    state = 'recovered'
    vi.setSystemTime(new Date('2026-10-12T10:02:00.000Z'))
    await client.refresh()
    const recovered = client.getSnapshot()
    expect(recovered.result?.kind).toBe('Accepted')
    expect(recovered.data).toEqual(envelopes.recovered)
    expect(recovered.stale).toBe(false)
    expect(recovered.lastUpdated).toBe('2026-10-12T10:02:00.000Z')
    expect(recovered.lastUpdated).not.toBe(firstRead.lastUpdated)
    expect(calls).toBe(3)
  } finally {
    vi.useRealTimers()
  }
})
it.each([
  ['engineering.work.get', 'MethodWork'],
  ['engineering.work.current_condition', 'CurrentCondition'],
  ['engineering.runs.get_wait', 'RunWait'],
])('sends the exact run_id envelope for %s and retains its actual record type', async (method, recordType) => {
  let sent: { method: string; params: Record<string, unknown> } | undefined
  const envelope = { contract_version: 'engineering-wire/1', scope, query: method, record_type: recordType, data: { run_id: 'run-42', fixture: true } }
  const client = engineeringQueries({ call: async (actualMethod, params) => { sent = { method: actualMethod, params }; return accepted(envelope) } })
    .createQuery(method, scope, { run_id: 'run-42' })
  await client.refresh()
  expect(sent?.method).toBe(method)
  expect(sent?.params).toMatchObject({ scope, parameters: { run_id: 'run-42' } })
  expect(client.getSnapshot().data).toEqual(envelope)
  expect(client.getSnapshot().data?.record_type).toBe(recordType)
})
it.each(['engineering.work.get', 'engineering.work.current_condition', 'engineering.runs.get_wait'])('keeps an unbound %s query explicitly Refused', async method => {
  const refusal = { kind: 'Refused' as const, requestId: 'test-unbound', reason: 'NOT_FOUND', retryable: false }
  const client = engineeringQueries({ call: async () => refusal }).createQuery(method, scope, { run_id: 'run-unbound' })
  await client.refresh()
  expect(client.getSnapshot().result).toEqual(refusal)
  expect(client.getSnapshot().data).toBeUndefined()
  expect(client.getSnapshot().stale).toBe(true)
})
it('commands.get preserves original request and actual command_result without inferring completion', async () => {
  const data={contract_version:'engineering-wire/1',scope,record_type:'command_result',request_id:'original',authority_id:'auth',operation_id:'op',status:'accepted',result:{artifact_id:'a'},status_query:{method:'engineering.commands.get',parameters:{request_id:'original'}}}
  const access=engineeringQueries({call:async()=>accepted(data)})
  const client=access.createQuery('engineering.commands.get',scope,{request_id:'original'});await client.refresh();expect(client.getSnapshot().data).toEqual(data)
  const wrong=access.createQuery('engineering.commands.get',scope,{request_id:'different'});await wrong.refresh();expect(wrong.getSnapshot().stale).toBe(true)
})

it.each([
 ['engineering.notices.get','notice_ref','ConversationNotice'],
 ['engineering.approvals.get','approval_ref','ApprovalGrant'],
 ['engineering.approvals.get_control','approval_ref','ApprovalControl'],
 ['engineering.approvals.get_intent','intent_id','AuthorizationIntent'],
 ['engineering.approvals.get_challenge','challenge_id','ApprovalChallenge'],
])('reads %s without admitting mutations or inferring consent', async (method,key,recordType) => {
 let sent:any
 const access=engineeringQueries({call:async(_,params)=>{sent=params;return accepted({contract_version:'engineering-wire/1',scope,query:method,record_type:recordType,data:{fixture:true}})}})
 const parameters={[key]:key.endsWith('_ref')?{fixture:true}:'fixture-id'}
 const client=access.createQuery(method,scope,parameters);await client.refresh()
 expect(sent.parameters).toEqual(parameters);expect(client.getSnapshot().data?.record_type).toBe(recordType)
})
it('pending approvals uses explicit pagination and never becomes a Work projection',async()=>{
 let sent:any
 const access=engineeringQueries({call:async(method,params)=>{sent=params;return accepted({contract_version:'engineering-wire/1',scope,query:method,record_type:'PendingApprovals',data:{items:[],next_after_challenge_id:null}})}})
 const client=access.createQuery('engineering.approvals.list_pending',scope,{parameters:{limit:20,after_challenge_id:null}});await client.refresh()
 expect(sent.parameters).toEqual({limit:20,after_challenge_id:null});expect(client.getSnapshot().data).not.toHaveProperty('works')
 expect(()=>access.createQuery('engineering.approvals.list_pending',scope,{parameters:{limit:101,after_challenge_id:null}})).toThrow()
})

it('reads the original review request/plan and preserves requested version zero, fence and full keys', async()=>{
 let sent:any
 const data={request:{scope,review_id:'review-original',state:'requested',version:0,fence:1},plan:{review_id:'review-original',plan_digest:{algorithm:'sha256',hex:'a'.repeat(64)},check_policies:[{key:{criterion_id:'claim_support',claim_id:'claim-one',target:{role:'primary',ref:{kind:'artifact_revision',revision_id:'original'}}}}]}}
 const access=engineeringQueries({call:async(method,params)=>{sent={method,params};return accepted({contract_version:'engineering-wire/1',query:method,scope,record_type:'ReviewRequest',data})}})
 const client=access.createQuery('engineering.reviews.get_request',scope,{review_id:'review-original'});await client.refresh()
 expect(sent.params.parameters).toEqual({review_id:'review-original'});expect(client.getSnapshot().data?.data).toEqual(data);expect(client.getSnapshot().data).not.toHaveProperty('works');expect(client.getSnapshot().data).not.toHaveProperty('grant')
 expect(access.queries.find(q=>q.method==='engineering.reviews.get_request')?.note).toContain('quarantine 不是 accepted')
})
it.each(['request','plan','record_type'])('rejects mismatched review %s rather than showing another original request', async key=>{
 const reply:any={contract_version:'engineering-wire/1',scope,query:'engineering.reviews.get_request',record_type:'ReviewRequest',data:{request:{review_id:'original'},plan:{review_id:'original'}}}
 if(key==='record_type')reply.record_type='Artifact';else reply.data[key]={review_id:'other'}
 const client=engineeringQueries({call:async()=>accepted(reply)}).createQuery('engineering.reviews.get_request',scope,{review_id:'original'});await client.refresh()
 expect(client.getSnapshot().result?.kind).toBe('Unknown');expect(client.getSnapshot().data).toBeUndefined()
})
it('does not expand a machine grant when the original review read is refused',async()=>{
 const client=engineeringQueries({call:async()=>({kind:'Refused',requestId:'test',reason:'FORBIDDEN',retryable:false})}).createQuery('engineering.reviews.get_request',scope,{review_id:'original'})
 await client.refresh();expect(client.getSnapshot().result?.kind).toBe('Refused');expect(client.getSnapshot().data).toBeUndefined()
})
