/**
 * T010-02 gates for the local owner port: it is the frontend's F5-allowed
 * UI-local state served through the SAME dispatch face as the wire owner —
 * frozen projections, per-operation revision stamps, three-way submission
 * receipts with unknown keeping a query key (never a resend), and the
 * single-writer registry refusing a second owner for one canonical target.
 * Swap-in parity with the wire face is asserted side by side.
 */
import { describe, expect, it } from 'vitest'

import { createAgentOwnerPort, createLocalAgentOwnerPort, type WireCall } from '../src/owner-port'

const isolated = () => createLocalAgentOwnerPort({ ownerRegistry: new Set() })

describe('local Agent owner port (T010-02)', () => {
  it('routes writes through operations and reads through frozen projections', async () => {
    const port = isolated()
    const first = await port.submitConfigOperation('chat', { model: 'm1' }, { sourceRef: 'glue:select' })
    expect(first).toEqual({
      kind: 'ok',
      value: { operationId: expect.any(String), patchKinds: ['present'], state: 'pending' },
    })
    const snapshot = await port.readConfig('chat')
    if (snapshot.kind !== 'ok') throw new Error('expected ok snapshot')
    expect(snapshot.value.revision).toBe(1)
    expect(snapshot.value.resolved).toEqual({ model: 'm1' })
    expect(snapshot.value.fields).toEqual({ model: 'known' })
    expect(Object.isFrozen(snapshot.value.fields)).toBe(true)
    expect(Object.isFrozen(snapshot.value.resolved)).toBe(true)
  })

  it('counts a same-value re-select as a NEW operation (never a no-op id reuse)', async () => {
    const port = isolated()
    const a = await port.submitConfigOperation('chat', { model: 'm' })
    const b = await port.submitConfigOperation('chat', { model: 'm' })
    if (a.kind !== 'ok' || b.kind !== 'ok') throw new Error('expected ok receipts')
    expect(a.value.operationId).not.toBe(b.value.operationId)
    const snapshot = await port.readConfig('chat')
    if (snapshot.kind !== 'ok') throw new Error('expected ok snapshot')
    expect(snapshot.value.revision).toBe(2) // two operations, even for identical values
  })

  it('accepts present+unset patches as one operation receipt', async () => {
    const port = isolated()
    await port.submitConfigOperation('chat', { model: 'm' })
    const receipt = await port.submitConfigOperation('chat', { temp: 0.2 }, { unset: ['model'] })
    if (receipt.kind !== 'ok') throw new Error('expected ok receipt')
    expect(receipt.value.patchKinds).toEqual(['present', 'unset'])
    const snapshot = await port.readConfig('chat')
    if (snapshot.kind !== 'ok') throw new Error('expected ok snapshot')
    expect(snapshot.value.resolved).toEqual({ temp: 0.2 })
    expect(snapshot.value.fields).toEqual({ temp: 'known', model: 'unset' })
  })

  it('counterexample: a second owner registration for one target is refused, never a silent second store', async () => {
    const registry = new Set<string>()
    const first = createLocalAgentOwnerPort({ ownerRegistry: registry })
    const second = createLocalAgentOwnerPort({ ownerRegistry: registry })
    const ok = await first.submitConfigOperation('chat', { model: 'm' })
    expect(ok.kind).toBe('ok')
    for (const answer of [
      await second.readConfig('chat'),
      await second.submitConfigOperation('chat', {}),
    ]) {
      expect(answer.kind).toBe('unavailable')
      expect(JSON.stringify(answer)).toContain('AUTHORITY_CONFLICT')
    }
  })

  it('returns three-way submission receipts and keeps unknown queryable without a resend', async () => {
    const port = isolated()
    const accepted = await port.submitInput('chat', 3, { outcome: 'accepted' })
    const rejected = await port.submitInput('chat', 4, { outcome: 'known-rejected' })
    const unknown = await port.submitInput('chat', 5, { outcome: 'unknown' })
    if (accepted.kind !== 'ok' || rejected.kind !== 'ok' || unknown.kind !== 'ok') {
      throw new Error('expected ok receipts')
    }
    expect(accepted.value).toMatchObject({ outcome: 'accepted', consumedDraftRevision: 3 })
    expect(rejected.value).toMatchObject({ outcome: 'known-rejected', consumedDraftRevision: 4 })
    expect(unknown.value).toEqual({
      submissionId: expect.any(String),
      outcome: 'unknown',
      queryRequestKey: expect.any(String),
      resend: false,
    })
  })

  it('counterexample: unknown outcomes are dispatched exactly once and never replayed', async () => {
    const port = isolated()
    const first = await port.submitInput('chat', 1, { outcome: 'unknown' })
    if (first.kind !== 'ok' || first.value.outcome !== 'unknown') throw new Error('expected unknown')
    const firstId = first.value.submissionId
    expect(port.dispatchCount('chat', firstId)).toBe(1)
    // the consumer's only move is to QUERY the same key; nothing auto-resends —
    // even a deliberate second submit is a NEW submission on a NEW key
    const second = await port.submitInput('chat', 1, { outcome: 'unknown' })
    if (second.kind !== 'ok' || second.value.outcome !== 'unknown') throw new Error('expected unknown')
    expect(second.value.submissionId).not.toBe(firstId)
    expect(second.value.queryRequestKey).not.toBe(first.value.queryRequestKey)
    expect(port.dispatchCount('chat', firstId)).toBe(1) // untouched by the second submit
    expect(port.dispatchCount('chat', second.value.submissionId)).toBe(1)
  })

  it('reports run states and mirrors the wire queryHint for an undecided run', async () => {
    const port = isolated()
    const missing = await port.queryRun('chat', 'r1')
    expect(missing).toEqual({ kind: 'unknown', queryHint: 'run:r1' })
    port.reportRun('chat', 'r1', 'completed')
    expect(await port.queryRun('chat', 'r1')).toEqual({ kind: 'ok', value: { state: 'completed', reason: null } })
  })

  it('counterexample: a repeated identical evidence observation never unlocks a pending unknown', async () => {
    const port = isolated()
    port.reportEvidence('chat', 'unknown', { model: 'unknown' })
    port.reportEvidence('chat', 'unknown', { model: 'unknown' }) // identical re-observation
    const snapshot = await port.readConfig('chat')
    if (snapshot.kind !== 'ok') throw new Error('expected ok snapshot')
    expect(snapshot.value.fields.model).toBe('unknown') // still unknown, no unlock
    expect(snapshot.value.observedEvidence).toBe('unknown')
    expect(snapshot.value.revision).toBe(0) // evidence observes, it does not operate
    port.reportEvidence('chat', 'native', { model: 'known' }) // a NEW complete snapshot
    const unlocked = await port.readConfig('chat')
    if (unlocked.kind !== 'ok') throw new Error('expected ok snapshot')
    expect(unlocked.value.fields.model).toBe('known')
    expect(unlocked.value.revision).toBe(0)
  })

  it('rejects evidence outside the known/unset/unknown vocabulary', async () => {
    const port = isolated()
    expect(() => port.reportEvidence('chat', 'maybe' as 'native')).toThrow(/bad observed evidence/)
    expect(() => port.reportEvidence('chat', 'native', { model: 'probably' as 'known' })).toThrow(/bad field state/)
    expect(() => port.reportRun('chat', 'r', 'stuck' as 'running')).toThrow(/bad run state/)
  })

  it('merges session upserts per id and freezes each record', async () => {
    const port = isolated()
    port.reportSessions('chat', { s1: { title: 'a' } })
    port.reportSessions('chat', { s1: { pinned: true }, s2: { title: 'b' } })
    const sessions = await port.listSessions('chat')
    if (sessions.kind !== 'ok') throw new Error('expected ok sessions')
    expect(sessions.value).toEqual([{ title: 'a', pinned: true }, { title: 'b' }])
    expect(Object.isFrozen(sessions.value[0])).toBe(true)
  })

  it('swap-in parity: the wire face maps the server unknown-outcome run record onto the same unknown arm', async () => {
    const call: WireCall = async method => ({
      kind: 'Accepted',
      result: method === 'agent.run.query'
        ? { outcome: 'unknown', queryHint: 'run:r1', resend: false }
        : {},
    })
    const wire = createAgentOwnerPort(call)
    const local = createLocalAgentOwnerPort({ ownerRegistry: new Set() })
    expect(await wire.queryRun('chat', 'r1')).toEqual(await local.queryRun('chat', 'r1'))
  })
})

describe('local owner session lifecycle (T010-02 glue)', () => {
  it('merges session records by id and drops them wholesale on UI teardown', () => {
    const port = createLocalAgentOwnerPort({ ownerRegistry: new Set() })
    port.reportSessions('chat.bindings', { i1: { identity: 'i1', selection: 'A' } })
    port.reportSessions('chat.bindings', { i1: { selection: 'B' }, i2: { identity: 'i2' } })
    expect(port.listSessionsSync('chat.bindings')).toEqual([
      { identity: 'i1', selection: 'B' }, { identity: 'i2' },
    ])
    port.dropSessions('chat.bindings')
    expect(port.listSessionsSync('chat.bindings')).toEqual([])
  })
})
