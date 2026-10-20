import { describe, expect, it } from 'vitest'
import {
  fileBackedUiStore,
  sessionOnlyUiStore,
  type HostUiAdapter,
} from '../src/state/uiStorage'
import { UiSchemaUnknownError } from '../../../extension-api/contracts/foundation/src/open-environment/f5/errors'

const ns = {
  pluginNamespace: 'example.layout',
  workspace: 'workspace-a',
  windowOrSharedPurpose: 'shared-layout',
  schemaVersion: 1,
}

type VersionedUiStore = {
  readonly capability: 'available' | 'session-only' | 'unavailable'
  readonly versionedCapability: 'available' | 'session-only' | 'unavailable'
  readVersioned<T>(namespace: typeof ns, key: string): Promise<{
    value: T | undefined
    revision: string | null
  }>
  writeVersioned<T>(
    namespace: typeof ns,
    key: string,
    value: T,
    expectedRevision: string | null,
  ): Promise<'written' | 'conflict'>
  read<T>(namespace: typeof ns, key: string): Promise<T | undefined>
  write<T>(
    namespace: typeof ns,
    key: string,
    value: T,
    options: { ifRevision?: string },
  ): Promise<'written' | 'conflict'>
}

// Red-first cast: this pins the approved additive public shape before its
// production type lands, without supplying a test-only implementation.
function versioned(store: unknown): VersionedUiStore {
  return store as VersionedUiStore
}

type Envelope = { revision: string; schemaVersion: number; value: unknown }
type EnvelopeInput = Omit<Envelope, 'revision'>
type CasResult = { status: 'written'; revision: string } | { status: 'conflict' }

function adapterFixture(options: { absentCas?: boolean } = {}) {
  const records = new Map<string, Envelope>()
  const casExpectations: Array<string | null | undefined> = []
  let revision = 0
  const adapter = {
    ...(options.absentCas ? { supportsAbsentCompareAndSwap: true as const } : {}),
    async read(nsKey: string, key: string): Promise<Envelope | undefined> {
      const found = records.get(`${nsKey}|${key}`)
      return found && { ...found, value: structuredClone(found.value) }
    },
    async compareAndSwap(
      nsKey: string,
      key: string,
      expectedRevision: string | null | undefined,
      next: EnvelopeInput,
    ): Promise<CasResult> {
      casExpectations.push(expectedRevision)
      const id = `${nsKey}|${key}`
      const current = records.get(id)
      if (expectedRevision === null && current !== undefined) return { status: 'conflict' }
      if (typeof expectedRevision === 'string'
          && (current === undefined || current.revision !== expectedRevision)) {
        return { status: 'conflict' }
      }
      const nextRevision = `fixture-${++revision}`
      records.set(id, { ...next, value: structuredClone(next.value), revision: nextRevision })
      return { status: 'written', revision: nextRevision }
    },
    async remove(nsKey: string, key: string): Promise<void> {
      records.delete(`${nsKey}|${key}`)
    },
  } as unknown as HostUiAdapter
  return { adapter, records, casExpectations }
}

describe('F5 versioned UI storage increment', () => {
  it('returns value and opaque revision from one public snapshot, with null for absence', async () => {
    const store = versioned(sessionOnlyUiStore())

    expect(await store.readVersioned(ns, 'layout')).toEqual({ value: undefined, revision: null })
    expect(await store.writeVersioned(ns, 'layout', { width: 320 }, null)).toBe('written')

    const snapshot = await store.readVersioned<{ width: number }>(ns, 'layout')
    expect(snapshot.value).toEqual({ width: 320 })
    expect(typeof snapshot.revision).toBe('string')
    expect(snapshot.revision).not.toBe('')
  })

  it('only creates when the captured absence is still current', async () => {
    const store = versioned(sessionOnlyUiStore())
    expect(await store.writeVersioned(ns, 'layout', { width: 320 }, null)).toBe('written')

    expect(await store.writeVersioned(ns, 'layout', { width: 640 }, null)).toBe('conflict')
    expect(await store.read(ns, 'layout')).toEqual({ width: 320 })
  })

  it('retains legacy write semantics where an omitted revision is unconditional', async () => {
    const backing = adapterFixture({ absentCas: true })
    const store = versioned(fileBackedUiStore(backing.adapter))

    expect(await store.write(ns, 'layout', { width: 320 }, {})).toBe('written')
    expect(await store.write(ns, 'layout', { width: 640 }, { ifRevision: undefined })).toBe('written')
    expect(await store.read(ns, 'layout')).toEqual({ width: 640 })
    expect(backing.casExpectations).toEqual([undefined, undefined])
  })

  it('deeply isolates the returned versioned snapshot from stored values', async () => {
    const store = versioned(sessionOnlyUiStore())
    await store.writeVersioned(ns, 'layout', { panes: { left: { width: 320 } } }, null)

    const first = await store.readVersioned<{ panes: { left: { width: number } } }>(ns, 'layout')
    first.value!.panes.left.width = 1

    expect((await store.readVersioned<{ panes: { left: { width: number } } }>(ns, 'layout'))
      .value?.panes.left.width).toBe(320)
  })

  it('refuses unsupported schemas and secret-shaped values on the versioned path', async () => {
    const store = versioned(sessionOnlyUiStore())

    await expect(store.writeVersioned({ ...ns, schemaVersion: 99 }, 'layout', { width: 1 }, null))
      .rejects.toThrow(UiSchemaUnknownError)
    await expect(store.writeVersioned(ns, 'layout', { accessToken: 'private' }, null))
      .rejects.toThrow(UiSchemaUnknownError)
    expect(await store.readVersioned(ns, 'layout')).toEqual({ value: undefined, revision: null })
  })

  it('does not emulate absent-only creation for an adapter without that atomic capability', async () => {
    const backing = adapterFixture()
    const store = versioned(fileBackedUiStore(backing.adapter))

    expect(store.versionedCapability).toBe('unavailable')
    const result = await store.writeVersioned(ns, 'layout', { width: 320 }, null).catch(() => 'rejected')
    expect(result).not.toBe('written')
    expect(backing.casExpectations).toEqual([])
    expect(await store.readVersioned(ns, 'layout')).toEqual({ value: undefined, revision: null })
  })
})

// JS consumers must not accidentally reinterpret an absent argument as unconditional authorization.
it('refuses an omitted version on the versioned method instead of falling back to unconditional write', async () => {
  const store = sessionOnlyUiStore()
  await expect(store.writeVersioned(ns, 'layout', { width: 800 }, undefined as never)).rejects.toThrow(UiSchemaUnknownError)
  expect(await store.readVersioned(ns, 'layout')).toEqual({ value: undefined, revision: null })
})

it('rejects a malformed stored revision rather than publishing an unusable CAS snapshot', async () => {
  const adapter = {
    supportsAbsentCompareAndSwap: true as const,
    read: async () => ({ schemaVersion: 1, value: { width: 800 }, revision: undefined }),
    compareAndSwap: async () => ({ status: 'conflict' as const }),
    remove: async () => undefined,
  } as unknown as HostUiAdapter
  await expect(fileBackedUiStore(adapter).readVersioned(ns, 'layout')).rejects.toThrow(UiSchemaUnknownError)
})
