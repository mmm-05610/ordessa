import { describe, expect, it } from 'vitest'
import {
  fileBackedUiStore,
  readUiRevision,
  type HostUiAdapter,
} from '../src/state/uiStorage'
import { UiSchemaUnknownError } from '../../../extension-api/contracts/foundation/src/open-environment/f5/errors'

const ns = {
  pluginNamespace: 'example.layout',
  workspace: 'workspace-a',
  windowOrSharedPurpose: 'shared-layout',
  schemaVersion: 1,
}

type StoredRecord = { revision: string; schemaVersion: number; value: unknown }
type WriteRecord = Omit<StoredRecord, 'revision'>
type CompareAndSwapResult =
  | { status: 'written'; revision: string }
  | { status: 'conflict' }

function nsKeyOf(namespace: typeof ns): string {
  return `${namespace.pluginNamespace}|${namespace.workspace ?? '-'}|${namespace.windowOrSharedPurpose}|${namespace.schemaVersion}`
}

function recordKey(nsKey: string, key: string): string {
  return `${nsKey}|${key}`
}

function memoryAdapter() {
  const records = new Map<string, StoredRecord>()
  let revision = 0
  let failNextWrite = false
  let failNextRemove = false
  const adapter: HostUiAdapter = {
    async read(nsKey, key) {
      return records.get(recordKey(nsKey, key))
    },
    async compareAndSwap(
      nsKey: string,
      key: string,
      expectedRevision: string | undefined,
      next: WriteRecord,
    ): Promise<CompareAndSwapResult> {
      if (failNextWrite) {
        failNextWrite = false
        throw new Error('simulated storage write failure')
      }
      const id = recordKey(nsKey, key)
      const current = records.get(id)
      if (expectedRevision !== undefined
          && (current === undefined || current.revision !== expectedRevision)) {
        return { status: 'conflict' }
      }
      const nextRevision = `fixture-${++revision}`
      records.set(id, { ...next, revision: nextRevision })
      return { status: 'written', revision: nextRevision }
    },
    async remove(nsKey, key) {
      if (failNextRemove) {
        failNextRemove = false
        throw new Error('simulated storage deletion failure')
      }
      records.delete(recordKey(nsKey, key))
    },
  }
  return {
    adapter,
    records,
    failWrite() { failNextWrite = true },
    failRemove() { failNextRemove = true },
  }
}

describe('013 F5 UI storage closeout regressions', () => {
  it('allows exactly one of two independent clients to commit the same revision', async () => {
    const backing = memoryAdapter()
    const first = fileBackedUiStore(backing.adapter)
    const second = fileBackedUiStore(backing.adapter)
    expect(await first.write(ns, 'layout', { width: 100 }, {})).toBe('written')
    const baseRevision = await readUiRevision(backing.adapter, ns, 'layout')
    expect(baseRevision).toBeTruthy()

    const results = await Promise.all([
      first.write(ns, 'layout', { width: 200 }, { ifRevision: baseRevision! }),
      second.write(ns, 'layout', { width: 300 }, { ifRevision: baseRevision! }),
    ])

    expect(results.filter(result => result === 'written')).toHaveLength(1)
    expect(results.filter(result => result === 'conflict')).toHaveLength(1)
  })

  it('uses globally unique revisions observable through the host adapter', async () => {
    const backing = memoryAdapter()
    const first = fileBackedUiStore(backing.adapter)
    const second = fileBackedUiStore(backing.adapter)
    await first.write(ns, 'layout-a', { width: 100 }, {})
    await second.write(ns, 'layout-b', { width: 100 }, {})

    const revisions = [
      await readUiRevision(backing.adapter, ns, 'layout-a'),
      await readUiRevision(backing.adapter, ns, 'layout-b'),
    ]
    expect(revisions.every(Boolean)).toBe(true)
    expect(new Set(revisions).size).toBe(2)
  })

  it('refuses an unsupported schema without changing its existing record', async () => {
    const backing = memoryAdapter()
    const store = fileBackedUiStore(backing.adapter)
    await store.write(ns, 'layout', { width: 100 }, {})
    const before = await readUiRevision(backing.adapter, ns, 'layout')
    const unsupportedNs = { ...ns, schemaVersion: 99 }
    const unsupportedRecord: StoredRecord = {
      revision: 'fixture-preexisting-unknown-schema',
      schemaVersion: 99,
      value: { width: 50 },
    }
    backing.records.set(recordKey(nsKeyOf(unsupportedNs), 'layout'), unsupportedRecord)

    await expect(store.write(
      unsupportedNs, 'layout', { width: 999 }, {},
    )).rejects.toThrow(UiSchemaUnknownError)

    expect(await readUiRevision(backing.adapter, ns, 'layout')).toBe(before)
    expect(backing.records.get(recordKey(nsKeyOf(unsupportedNs), 'layout'))).toEqual(unsupportedRecord)
    expect(await store.read(ns, 'layout')).toEqual({ width: 100 })
  })

  it('does not report migration when it has not transformed a stored record', async () => {
    const backing = memoryAdapter()
    const store = fileBackedUiStore(backing.adapter)
    await store.write(ns, 'layout', { width: 100 }, {})
    const before = await readUiRevision(backing.adapter, ns, 'layout')

    expect(await store.migrate(ns, 2)).toBe('refused')

    expect(await readUiRevision(backing.adapter, ns, 'layout')).toBe(before)
    expect(await store.read(ns, 'layout')).toEqual({ width: 100 })
  })

  it('keeps the prior value when persistence fails', async () => {
    const backing = memoryAdapter()
    const store = fileBackedUiStore(backing.adapter)
    await store.write(ns, 'layout', { width: 100 }, {})
    backing.failWrite()

    await expect(store.write(ns, 'layout', { width: 200 }, {}))
      .rejects.toThrow('simulated storage write failure')
    expect(await store.read(ns, 'layout')).toEqual({ width: 100 })
  })

  it('does not claim deletion when host storage removal fails', async () => {
    const backing = memoryAdapter()
    const store = fileBackedUiStore(backing.adapter)
    await store.write(ns, 'layout', { width: 100 }, {})
    backing.failRemove()

    await expect(store.remove(ns, 'layout'))
      .rejects.toThrow('simulated storage deletion failure')
    expect(await store.read(ns, 'layout')).toEqual({ width: 100 })
  })

  it('isolates plugin and window namespaces when writing and deleting', async () => {
    const backing = memoryAdapter()
    const store = fileBackedUiStore(backing.adapter)
    const otherPlugin = { ...ns, pluginNamespace: 'other.layout' }
    const otherWindow = { ...ns, windowOrSharedPurpose: 'window-local' }
    await store.write(ns, 'filter', 'shared', {})
    await store.write(otherPlugin, 'filter', 'plugin', {})
    await store.write(otherWindow, 'filter', 'window', {})

    await store.remove(ns, 'filter')

    expect(await store.read(ns, 'filter')).toBeUndefined()
    expect(await store.read(otherPlugin, 'filter')).toBe('plugin')
    expect(await store.read(otherWindow, 'filter')).toBe('window')
  })

  it('applies the safety guard on the write path before persistence', async () => {
    const backing = memoryAdapter()
    const store = fileBackedUiStore(backing.adapter)

    await expect(store.write(ns, 'layout', { nested: { accessToken: 'private' } }, {}))
      .rejects.toThrow(UiSchemaUnknownError)
    expect(await store.read(ns, 'layout')).toBeUndefined()
    expect(backing.records.size).toBe(0)
  })
})
