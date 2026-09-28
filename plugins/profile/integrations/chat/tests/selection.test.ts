/** Headless state-machine tests for the chat glue (PV-10, G20). */
import { describe, expect, it } from 'vitest'
import type { ProfileCatalogGroup, ProfileServiceClient } from '@ordessa/plugin-profile-api'
import { catalogForLocation, ProfileSelectionStore } from '../src/selection'

const A = { harnessId: 'pi', profileId: 'p1', displayName: '开发助手', archived: false }
const B = { harnessId: 'pi', profileId: 'p2', displayName: '代码审阅', archived: false }
const C = { harnessId: 'pi', profileId: 'p3', displayName: '日常', archived: false }

const GROUPS: readonly ProfileCatalogGroup[] = [
  { harnessId: 'pi', harnessTitle: 'Pi', profiles: [A, B, C] },
  { harnessId: 'codex', harnessTitle: 'Codex', profiles: [{ harnessId: 'codex', profileId: 'cx1', displayName: 'Codex 默认', archived: false }] },
]

function makeClient(applied: boolean, failFirst = false) {
  const calls: Array<{ appliedSwitch: boolean }> = []
  const client = {
    calls,
    async beginTurnApplication(_key: string, _ref: unknown) {
      calls.push({ appliedSwitch: applied })
      if (failFirst && calls.length === 1) throw new Error('SWITCH_BLOCKED: reset unsupported')
      return { turnId: 't1', appliedSwitch: applied, receipt: applied ? { operationId: 'op1' } : undefined }
    },
  }
  return client as typeof client & Pick<ProfileServiceClient, 'beginTurnApplication'>
}

describe('selection store (PV-10)', () => {
  it('selecting never calls the service and updates the label immediately', () => {
    const store = new ProfileSelectionStore()
    const client = makeClient(true)
    store.select('draft:1', B)
    store.select('draft:1', C)
    expect(store.currentLabel('draft:1')).toBe(C.displayName)
    expect(client.calls).toHaveLength(0)
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
})
