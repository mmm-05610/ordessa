/** Headless state-machine tests for the chat glue (PV-10, G20). */
import { describe, expect, it } from 'vitest'
import type { AppliedReceiptDto, ProfileCatalogGroup, SessionConfigDto, SessionRef } from '@ordessa/plugin-profile-api'
import { catalogForLocation, ProfileSelectionStore } from '../src/selection'
import { pickerKeyFor } from '../src/glue'

const A = { harnessId: 'pi', profileId: 'p1', displayName: '开发助手', archived: false }
const B = { harnessId: 'pi', profileId: 'p2', displayName: '代码审阅', archived: false }
const C = { harnessId: 'pi', profileId: 'p3', displayName: '日常', archived: false }
const REF: SessionRef = { realm: 'r', harnessId: 'pi', nativeSessionKey: 'n', sessionUid: 'S1' }

function confirmedConfig(): SessionConfigDto {
  const receipt: AppliedReceiptDto = {
    operationId: 'op1', sessionRef: REF, runtimeGeneration: 'gen-1', configDigest: 'digest',
    profileId: C.profileId, profileRevision: 1, overlayRevision: null, policyRevision: 1,
    providerGenerations: {}, evidenceKind: 'harness-api-confirmed', confirmedAt: '2026-09-30T00:00:00Z',
  }
  return {
    sessionRef: REF, switchState: 'settled', current: { ...C, revision: 1 }, pending: null,
    items: [], unavailable: [], blockers: null,
    evidence: { receipt, evidenceKind: receipt.evidenceKind, journal: {
      operationId: 'op1', state: 'confirmed', profileId: C.profileId, profileRevision: 1,
      planDigest: 'digest', detailRefs: [], createdAt: receipt.confirmedAt, updatedAt: receipt.confirmedAt,
    } },
  }
}

const GROUPS: readonly ProfileCatalogGroup[] = [
  { harnessId: 'pi', harnessTitle: 'Pi', profiles: [A, B, C] },
  { harnessId: 'codex', harnessTitle: 'Codex', profiles: [{ harnessId: 'codex', profileId: 'cx1', displayName: 'Codex 默认', archived: false }] },
]

function makeClient(applied: boolean, failFirst = false) {
  const calls: Array<{ appliedSwitch: boolean }> = []
  const selections: string[] = []
  const order: string[] = []
  const client = {
    calls, selections, order,
    async selectForSession(_key: string, input: { sessionRef: SessionRef; profileId: string }) {
      order.push('select')
      selections.push(input.profileId)
      return { sessionRef: input.sessionRef, pendingProfileId: input.profileId, pendingSeq: 1, switchState: 'pending' as const }
    },
    async inspectSessionConfig() { order.push('inspect'); return confirmedConfig() },
    async beginTurnApplication(_key: string, _ref: unknown) {
      order.push('begin')
      calls.push({ appliedSwitch: applied })
      if (failFirst && calls.length === 1) throw new Error('SWITCH_BLOCKED: reset unsupported')
      return { turnId: 't1', appliedSwitch: applied, receipt: applied ? confirmedConfig().evidence.receipt : undefined }
    },
  }
  return client
}

describe('selection store (PV-10)', () => {
  it('selecting never calls the service and updates the label immediately', () => {
    const store = new ProfileSelectionStore()
    const client = makeClient(true)
    store.select('draft:1', B)
    store.select('draft:1', C)
    expect(store.currentLabel('draft:1')).toBe(C.displayName)
    expect(client.calls).toHaveLength(0)
    expect(client.selections).toHaveLength(0)
    expect(store.counters).toMatchObject({ selections: 2, applyAttempts: 0 })
  })

  it('B then C applies only C, once, at submit', async () => {
    const store = new ProfileSelectionStore()
    const client = makeClient(true)
    store.select('session:S1', B)
    store.select('session:S1', C)
    const outcome = await store.applyOnSubmit('session:S1',
      { realm: 'r', harnessId: 'pi', nativeSessionKey: 'n', sessionUid: 'S1' }, client)
    expect(outcome).toMatchObject({ ok: true, applied: C })
    expect(client.calls).toHaveLength(1)
    expect(client.selections).toEqual([C.profileId])
    expect(client.order).toEqual(['select', 'begin'])
    expect(store.counters).toMatchObject({ applyAttempts: 1, applyConfirmed: 1 })
    expect(store.peek('session:S1')).toBeNull() // consumed after success
  })

  it('a failed application keeps the selection and reports the reason', async () => {
    const store = new ProfileSelectionStore()
    const client = makeClient(true, true)
    store.select('session:S1', C)
    const first = await store.applyOnSubmit('session:S1',
      { realm: 'r', harnessId: 'pi', nativeSessionKey: 'n', sessionUid: 'S1' }, client)
    expect(first.ok).toBe(false)
    if (!first.ok) expect(first.selection).toEqual(C)
    expect(store.peek('session:S1')).toEqual(C) // retained for retry/re-pick
    const second = await store.applyOnSubmit('session:S1',
      { realm: 'r', harnessId: 'pi', nativeSessionKey: 'n', sessionUid: 'S1' }, client)
    expect(second).toMatchObject({ ok: true, applied: C })
    expect(client.calls).toHaveLength(2)
  })

  it('no selection means the submit passes through untouched', async () => {
    const store = new ProfileSelectionStore()
    const client = makeClient(true)
    const outcome = await store.applyOnSubmit('session:S1',
      { realm: 'r', harnessId: 'pi', nativeSessionKey: 'n', sessionUid: 'S1' }, client)
    expect(outcome.ok).toBe(true)
    expect(client.calls).toHaveLength(0)
  })

  it('forgetting a UI key never aborts anything and clears only the pick', () => {
    const store = new ProfileSelectionStore()
    store.select('session:S1', B)
    store.forget('session:S1')
    expect(store.peek('session:S1')).toBeNull()
    expect(store.counters.applyAttempts).toBe(0)
  })

  it('refuses missing selection registration before beginning a turn', async () => {
    const store = new ProfileSelectionStore()
    const client = makeClient(true)
    store.select('session:S1', C)
    const outcome = await store.applyOnSubmit('session:S1', REF, { beginTurnApplication: client.beginTurnApplication })
    expect(outcome).toMatchObject({ ok: false, reason: 'Profile selection registration is unavailable' })
    expect(client.calls).toHaveLength(0)
    expect(store.peek('session:S1')).toEqual(C)
  })

  it('verifies backend current identity and evidence when no switch was applied', async () => {
    const store = new ProfileSelectionStore()
    const client = makeClient(false)
    store.select('session:S1', C)
    const outcome = await store.applyOnSubmit('session:S1', REF, client)
    expect(outcome).toMatchObject({ ok: true, applied: C, receipt: { profileId: C.profileId } })
    expect(client.order).toEqual(['select', 'begin', 'inspect'])
    expect(store.peek('session:S1')).toBeNull()
  })

  it('keeps the selection when no-switch inspection is unavailable', async () => {
    const store = new ProfileSelectionStore()
    const client = makeClient(false)
    store.select('session:S1', C)
    const outcome = await store.applyOnSubmit('session:S1', REF, {
      selectForSession: client.selectForSession, beginTurnApplication: client.beginTurnApplication,
    })
    expect(outcome).toMatchObject({ ok: false, reason: 'Profile current configuration verification is unavailable' })
    expect(store.peek('session:S1')).toEqual(C)
  })

  it.each(['wrong-profile', 'wrong-session', 'missing-receipt', 'legacy', 'unknown', 'pending'])(
    'rejects unproven no-switch result: %s', async reason => {
      const store = new ProfileSelectionStore()
      const client = makeClient(false)
      const config = confirmedConfig()
      const inspected: SessionConfigDto = reason === 'wrong-profile'
        ? { ...config, current: { ...config.current, profileId: B.profileId } }
        : reason === 'wrong-session' ? { ...config, sessionRef: { ...REF, nativeSessionKey: 'other' } }
        : reason === 'missing-receipt' ? { ...config, evidence: { ...config.evidence, receipt: null } }
        : reason === 'legacy' ? { ...config, evidence: { ...config.evidence, evidenceKind: 'legacy-unverified' } }
        : reason === 'unknown' ? { ...config, evidence: { ...config.evidence, journal: { ...config.evidence.journal!, state: 'unknown' } } }
        : { ...config, pending: { profileId: C.profileId, revision: 1, seq: 1 } }
      client.inspectSessionConfig = async () => inspected
      store.select('session:S1', C)
      expect(await store.applyOnSubmit('session:S1', REF, client)).toMatchObject({ ok: false })
      expect(store.peek('session:S1')).toEqual(C)
      expect(store.counters.applyConfirmed).toBe(0)
    },
  )
})

describe('catalog scoping (PA07)', () => {
  it('drafts see every group; sessions only their own Harness', () => {
    expect(catalogForLocation(GROUPS, { kind: 'draft', draftId: 'd1' })).toHaveLength(2)
    const own = catalogForLocation(GROUPS, { kind: 'session', sessionUid: 'S1', harnessId: 'pi' })
    expect(own).toHaveLength(1)
    expect(own[0]?.harnessId).toBe('pi')
  })

  it('a session whose Harness has no profiles shows no picker groups', () => {
    expect(catalogForLocation(GROUPS, { kind: 'session', sessionUid: 'S2', harnessId: 'claude-code' })).toHaveLength(0)
  })

  it('uses the real Chat session location without falling back to an unbound draft', () => {
    const projected = pickerKeyFor({ kind: 'session', sessionId: 'native-session-7',
      connectionId: 'channel-1', serverInstanceId: 'server-1', harnessId: 'pi', contextRevision: 1 })
    expect(projected.key).toBe('session:native-session-7')
    expect(projected.scope).toEqual({ kind: 'session', harnessId: 'pi' })
    expect(catalogForLocation(GROUPS, projected.scope).map(group => group.harnessId)).toEqual(['pi'])
  })
})
