import { describe, expect, it, vi } from 'vitest'
import type { ProfileIdentityDto, ProfileServiceClient } from '@ordessa/plugin-profile-api'
import { ProfileCatalogStore, ProfileDraftStore } from '../src/stores'

const PROFILE: ProfileIdentityDto = {
  profileId: 'p1', version: 4, displayName: '开发助手', harnessId: 'pi',
  currentRevision: 7, archivedAt: null, createdAt: 't', updatedAt: 't', realm: 'local',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

describe('Profile resource editing closeout', () => {
  it('keeps a same-value edit made during a late save (ABA)', async () => {
    const saveResult = deferred<{ profile: ProfileIdentityDto }>()
    const saveProfile = vi.fn(() => saveResult.promise)
    const client = { saveProfile } as unknown as ProfileServiceClient
    const draft = new ProfileDraftStore(client, PROFILE)
    const patch = { facetId: 'model', itemId: 'choice', op: 'set' as const, value: 'm2' }
    draft.edit(patch)

    const saving = draft.save('operation-1')
    // The edit event matters even when its value is identical to the captured value.
    draft.edit({ ...patch })
    saveResult.resolve({ profile: { ...PROFILE, version: 5, currentRevision: 8 } })
    await saving

    expect(saveProfile).toHaveBeenCalledTimes(1)
    expect(draft.dirty).toBe(true)
    expect(draft.localPatches).toEqual([patch])
  })

  it('anchors the public edit session to the loaded profile revision', () => {
    const draft = new ProfileDraftStore({} as ProfileServiceClient, PROFILE)
    expect(draft.baseRevision).toBe('7')
  })
})

describe('Profile catalog read coordination', () => {
  it('merges same-key concurrent catalog reads and publishes the newest waiter result', async () => {
    const response = deferred<readonly ProfileIdentityDto[]>()
    const listProfiles = vi.fn(() => response.promise)
    const describeFacets = vi.fn(async () => [])
    const client = { listProfiles, describeFacets } as unknown as ProfileServiceClient
    const catalog = new ProfileCatalogStore(client)

    const first = catalog.refresh('local', false)
    const second = catalog.refresh('local', false)
    await Promise.resolve()
    expect(listProfiles).toHaveBeenCalledTimes(1)
    expect(describeFacets).toHaveBeenCalledTimes(1)

    response.resolve([PROFILE])
    await Promise.all([first, second])
    expect(catalog.state.profiles).toEqual([PROFILE])
    expect(catalog.state.online).toBe(true)
  })
})
