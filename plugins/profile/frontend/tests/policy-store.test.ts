/** Headless store gates for the settings page (PV-08, PS01-PS05, G03/G04). */
import { describe, expect, it } from 'vitest'
import type { ProfileServiceClient } from '@ordessa/plugin-profile-api'
import { MechanismPolicyStore } from '../src/stores'

function makeClient() {
  const calls: Array<{ op: string; payload: Record<string, unknown> }> = []
  const server: { revision: number } = { revision: 1 }
  let revision = 1
  const policy = {
    realm: 'local', revision,
    facetEnabled: {} as Record<string, boolean>,
    allowUserOverrideWritesGlobal: true,
    allowUserOverrideWrites: {} as Record<string, boolean>,
  }
  const policy_ = policy
  const client = {
    calls,
    async getMechanismPolicy() {
      calls.push({ op: 'getMechanismPolicy', payload: {} })
      return { ...policy, facetEnabled: { ...policy.facetEnabled }, allowUserOverrideWrites: { ...policy.allowUserOverrideWrites } }
    },
    async previewMechanismPolicy(_key: string, input: { expectedRevision: number; patch: Record<string, unknown> }) {
      calls.push({ op: 'previewMechanismPolicy', payload: { ...input.patch } })
      if (input.expectedRevision !== server.revision) {
        throw Object.assign(new Error('POLICY_REVISION_CONFLICT: stale'), { code: 'POLICY_REVISION_CONFLICT' })
      }
      return { policy: { ...policy }, impact: { disabling: { f1: { profilesWithValues: 0, sessionsWithOverlays: 0 } } }, preview: true }
    },
    async updateMechanismPolicy(_key: string, input: { expectedRevision: number; patch: Record<string, unknown> }) {
      calls.push({ op: 'updateMechanismPolicy', payload: { ...input.patch } })
      if (input.expectedRevision !== server.revision) {
        throw Object.assign(new Error('POLICY_REVISION_CONFLICT: stale'), { code: 'POLICY_REVISION_CONFLICT' })
      }
      const p = input.patch as {
        facetEnabled?: Record<string, boolean>
        allowUserOverrideWritesGlobal?: boolean
        allowUserOverrideWrites?: Record<string, boolean>
      }
      let impact = { disabling: {} as Record<string, { profilesWithValues: number; sessionsWithOverlays: number }> }
      if (p.facetEnabled) {
        for (const [facetId, enabled] of Object.entries(p.facetEnabled)) {
          if (!enabled) {
            impact = { disabling: { [facetId]: { profilesWithValues: 3, sessionsWithOverlays: 2 } } }
            policy.facetEnabled[facetId] = false
          } else {
            policy.facetEnabled[facetId] = true
          }
        }
      }
      if (typeof p.allowUserOverrideWritesGlobal === 'boolean') policy.allowUserOverrideWritesGlobal = p.allowUserOverrideWritesGlobal
      if (p.allowUserOverrideWrites) policy.allowUserOverrideWrites = { ...policy.allowUserOverrideWrites, ...p.allowUserOverrideWrites }
      server.revision += 1
      revision = server.revision
      return { policy: { ...policy, facetEnabled: { ...policy.facetEnabled }, allowUserOverrideWrites: { ...policy.allowUserOverrideWrites } }, impact }
    },
  } as unknown as ProfileServiceClient & { calls: typeof calls }
  Object.defineProperty(client, 'revision', {
    get: () => server.revision,
    set: (v: number) => { server.revision = v },
  })
  return client
}

describe('mechanism policy store (PV-08 backend-for-UI)', () => {
  it('loads the policy for the selected realm', async () => {
    const client = makeClient()
    const store = new MechanismPolicyStore(client)
    await store.load('local')
    expect(store.state.policy?.revision).toBe(1)
    expect(store.state.error).toBeNull()
  })

  it('disable shows the impact preview first and honours the cancel answer', async () => {
    const client = makeClient()
    const store = new MechanismPolicyStore(client)
    await store.load('local')
    let asked = false
    await store.setFacetEnabled('local', 'model_selection', false, () => {
      asked = true
      return false // user cancels after reading the impact
    })
    expect(asked).toBe(true)
    // the dry run consumed no revision: only the confirmed write mutates
    expect(store.state.policy?.revision).toBe(1)
    expect(store.state.policy?.facetEnabled['model_selection']).not.toBe(false)
    await store.setFacetEnabled('local', 'model_selection', false, () => true)
    expect(store.state.policy?.facetEnabled['model_selection']).toBe(false)
    expect(store.state.lastImpact?.disabling['model_selection']).toEqual({
      profilesWithValues: 3, sessionsWithOverlays: 2,
    })
  })

  it('a stale CAS write surfaces the conflict instead of overwriting', async () => {
    const client = makeClient()
    const store = new MechanismPolicyStore(client)
    await store.load('local')
    // a concurrent writer moves the policy forward between load and write
    ;(client as unknown as { revision: number }).revision = 42
    await expect(store.setFacetEnabled('local', 'f1', false, () => true)).rejects.toMatchObject({
      code: 'POLICY_REVISION_CONFLICT',
    })
    expect(store.state.error).toContain('POLICY_REVISION_CONFLICT')
    expect(store.state.policy?.facetEnabled['f1']).not.toBe(false)
  })

  it('per-facet override rule writes are namespace-scoped', async () => {
    const client = makeClient()
    const store = new MechanismPolicyStore(client)
    await store.load('local')
    await store.setOverrideWrites('local', 'skills', false)
    expect(store.state.policy?.allowUserOverrideWrites['skills']).toBe(false)
    expect(store.state.policy?.allowUserOverrideWritesGlobal).toBe(true)
  })
})
