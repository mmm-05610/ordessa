/**
 * T010-02/12 gates: the AgentOwnerPort is the public dispatch face —
 * three-state wire mapping, unknown keeps query hints (no resend invites),
 * and the absent port is typed unavailable (never a silent local store).
 */
import { describe, expect, it } from 'vitest'

import { createAbsentAgentOwnerPort, createAgentOwnerPort, type WireCall } from '../src/owner-port'

describe('A1 AgentOwnerPort', () => {
  it('maps accepted wire answers onto owner views', async () => {
    const call: WireCall = async method => ({
      kind: 'Accepted',
      result: method === 'agent.config.read'
        ? { ownerRef: 'agent-config:t', revision: 1, observedEvidence: 'unset', fields: {}, resolved: {} }
        : { operationId: 'op-1', patchKinds: ['present'], state: 'pending' },
    })
    const port = createAgentOwnerPort(call)
    expect((await port.readConfig('t')).kind).toBe('ok')
    expect((await port.submitConfigOperation('t', { model: 'm' })).kind).toBe('ok')
  })

  it('counterexample: unknown wire answers keep a query hint and never invite a resend', async () => {
    const port = createAgentOwnerPort(async () => ({ kind: 'Unknown', reason: 'result-unknown' }))
    const outcome = await port.submitInput('t', 1, {})
    expect(outcome.kind).toBe('unknown')
    expect(JSON.stringify(outcome)).toContain('queryHint')
    expect(JSON.stringify(outcome)).not.toContain('resend')
  })

  it('counterexample: absent wiring is typed unavailable, never a local store', async () => {
    const port = createAbsentAgentOwnerPort()
    for (const answer of [
      await port.readConfig('t'),
      await port.submitConfigOperation('t', {}),
      await port.submitInput('t', 1, {}),
      await port.listSessions('t'),
      await port.queryRun('t', 'r'),
    ]) {
      expect(answer.kind).toBe('unavailable')
    }
  })

  it('refused wire answers carry the reason without inventing a verdict', async () => {
    const port = createAgentOwnerPort(async () => ({ kind: 'Refused', reason: 'server-refused' }))
    const answer = await port.listSessions('t')
    expect(answer).toEqual({ kind: 'unavailable', reason: 'server-refused' })
  })
})
