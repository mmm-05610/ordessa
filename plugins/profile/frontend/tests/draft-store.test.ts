/** Draft save gates (PM04/PV-09, G05): explicit save, conflict retention. */
import { describe, expect, it } from 'vitest'
import type { ProfileIdentityDto, ProfileServiceClient } from '@ordessa/plugin-profile-api'
import { ProfileDraftStore } from '../src/stores'
import { beforeLeave, filterProfiles } from '../src/management-view'

const PROFILE: ProfileIdentityDto = {
  profileId: 'p1', version: 4, displayName: '开发助手', harnessId: 'pi',
  currentRevision: 7, archivedAt: null, createdAt: 't', updatedAt: 't',
  realm: 'local',
}

function makeClient(failWith?: unknown) {
  const saves: Array<{ expectedVersion: number; patches: unknown }> = []
  return {
    saves,
    client: {
      async saveProfile(_key: string, input: { expectedVersion: number; patches: unknown }) {
        saves.push({ expectedVersion: input.expectedVersion, patches: input.patches })
        if (failWith) throw failWith
        return { profile: { ...PROFILE, version: PROFILE.version + 1, currentRevision: PROFILE.currentRevision + 1 } }
      },
    } as unknown as ProfileServiceClient,
  }
}

describe('profile draft store (PM04)', () => {
  it('buffers edits and saves one patch list with the loaded version', async () => {
    const { saves, client } = makeClient()
    const draft = new ProfileDraftStore(client, PROFILE)
    expect(beforeLeave(draft)).toBe('allow')
    draft.edit({ facetId: 'model', itemId: 'model', op: 'set', value: 'm2' })
    draft.edit({ facetId: 'model', itemId: 'model', op: 'set', value: 'm3' }) // same item replaces
    draft.edit({ facetId: 'skills', itemId: 'set', op: 'unset' })
    expect(draft.dirty).toBe(true)
    expect(beforeLeave(draft)).toBe('ask')
    const outcome = await draft.save('k1')
    expect(outcome).toEqual({ ok: true, revision: 8 })
    expect(saves[0]?.expectedVersion).toBe(4)
    expect(saves[0]?.patches).toEqual([
      { facetId: 'model', itemId: 'model', op: 'set', value: 'm3' },
      { facetId: 'skills', itemId: 'set', op: 'unset' },
    ])
    expect(draft.dirty).toBe(false)
  })

  it('a version conflict keeps every local patch and no auto-overwrite', async () => {
    const remote = { ...PROFILE, version: 9 }
    const { client } = makeClient(
      Object.assign(new Error('PROFILE_VERSION_CONFLICT: stale'), { code: 'PROFILE_VERSION_CONFLICT', current: remote }))
    const draft = new ProfileDraftStore(client, PROFILE)
    draft.edit({ facetId: 'model', itemId: 'model', op: 'set', value: 'm3' })
    const outcome = await draft.save('k1')
    expect(outcome).toMatchObject({ ok: false, conflict: true })
    if (!outcome.ok && outcome.conflict) {
      expect(outcome.localPatches).toHaveLength(1)
      expect(outcome.localPatches[0]).toMatchObject({ itemId: 'model', value: 'm3' })
    }
    expect(draft.lastConflictRemote?.version).toBe(9)
    expect(draft.dirty).toBe(true) // local input survives for compare/reload
  })
})

describe('navigator filtering (PM01/PM05)', () => {
  const profiles = [
    { profileId: '1', displayName: '开发助手', harnessId: 'pi', archivedAt: null },
    { profileId: '2', displayName: '旧配置', harnessId: 'pi', archivedAt: 't' },
    { profileId: '3', displayName: '默认', harnessId: 'codex', archivedAt: null },
  ]

  it('archives stay hidden unless asked; search keeps harness grouping input', () => {
    expect(filterProfiles(profiles, '', false)).toHaveLength(2)
    expect(filterProfiles(profiles, '', true)).toHaveLength(3)
    expect(filterProfiles(profiles, '开', false)[0]?.profileId).toBe('1')
    expect(filterProfiles(profiles, 'codex', false)[0]?.profileId).toBe('3')
  })
})
