/**
 * T008-16/17 gates: edit-session ABA safety, conflict keeping, unknown
 * retention and secret-shape refusal; UI storage conditional writes,
 * unknown-schema refusal, namespace isolation and honest session-only
 * absence (F5 §5/§6).
 */
import { describe, expect, it, vi } from 'vitest'

import { createEditSession, settingsContribution } from '../src/state/editing'
import {
  assertSafeUiValue,
  fileBackedUiStore,
  sessionOnlyUiStore,
  UI_STORAGE_ABSENCE_REASON,
} from '../src/state/uiStorage'
import {
  EditConflictError,
  UiSchemaUnknownError,
} from '../../contracts/foundation/src/open-environment/f5/errors'

const ns = {
  pluginNamespace: 'demo.plugin',
  workspace: 'ws-1',
  windowOrSharedPurpose: 'window-1',
  schemaVersion: 1,
}

describe('F5 edit sessions', () => {
  it('late success never clears a newer edit (ABA safe, even with identical text)', async () => {
    let captured: { editRevision: number; values: Record<string, unknown> } | null = null
    const session = createEditSession<{ note: string }>({
      editId: 'e-1', baseRevision: 'rev-1', initial: { note: '' },
      commitHandler: async capture => {
        captured = { editRevision: capture.editRevision, values: { ...capture.values } }
        // The domain save resolves LATE; by then the user has re-edited.
        await new Promise(r => setTimeout(r, 5))
        return { kind: 'saved', consumedFields: [...capture.fields] }
      },
    })
    session.setValue('note', 'first')
    const commitPromise = session.commit()
    session.setValue('note', 'second-edit') // the newer edit (before the late success)
    await commitPromise
    expect(session.dirtyFields().has('note')).toBe(true) // new edit survives
    expect(session.current.note).toBe('second-edit')
    expect(captured).not.toBeNull()
  })

  it('same-text ABA does not clear the newer edit either', async () => {
    const session = createEditSession<{ note: string }>({
      editId: 'e-2', baseRevision: 'rev-1', initial: { note: '' },
      commitHandler: async capture => {
        await new Promise(r => setTimeout(r, 5))
        return { kind: 'saved', consumedFields: [...capture.fields] }
      },
    })
    session.setValue('note', 'same')
    const p = session.commit()
    session.setValue('note', 'same') // identical text, NEW edit
    await p
    expect(session.dirtyFields().has('note')).toBe(true) // ABA kept
  })

  it('unchanged fields are cleared on successful save', async () => {
    const session = createEditSession<{ a: string; b: string }>({
      editId: 'e-3', baseRevision: 'rev-1', initial: { a: '', b: '' },
      commitHandler: async capture => ({ kind: 'saved', consumedFields: [...capture.fields] }),
    })
    session.setValue('a', 'x')
    session.setValue('b', 'y')
    await session.commit()
    expect(session.dirtyFields().size).toBe(0) // both unchanged since capture
  })

  it('conflicts keep local values and notify', async () => {
    const onConflict = vi.fn()
    const session = createEditSession<{ note: string }>({
      editId: 'e-4', baseRevision: 'rev-1', initial: { note: '' },
      commitHandler: async () => ({ kind: 'conflict', field: 'note', theirRevision: 'rev-9' }),
    })
    const handle = session.onConflict(onConflict)
    session.setValue('note', 'mine')
    const outcome = await session.commit()
    expect(outcome.kind).toBe('conflict')
    expect(session.current.note).toBe('mine') // local values kept
    expect(onConflict).toHaveBeenCalledWith({ field: 'note', theirRevision: 'rev-9' })
    handle.release()
  })

  it('unknown outcomes keep their query hint and never auto-retry', async () => {
    const handler = vi.fn(async () => ({ kind: 'unknown' as const, queryHint: 'query://e-5' }))
    const session = createEditSession<{ note: string }>({
      editId: 'e-5', baseRevision: 'rev-1', initial: { note: '' },
      commitHandler: handler,
    })
    session.setValue('note', 'x')
    const outcome = await session.commit()
    expect(outcome).toEqual({ kind: 'unknown', queryHint: 'query://e-5' })
    expect(handler).toHaveBeenCalledTimes(1) // exactly one attempt
  })

  it('counterexample: plaintext in a sensitive field is refused', () => {
    const session = createEditSession<{ apiKey: unknown }>({
      editId: 'e-6', baseRevision: 'rev-1', initial: { apiKey: null },
      sensitiveFields: ['apiKey'],
      commitHandler: async () => ({ kind: 'saved', consumedFields: [] }),
    })
    expect(() => session.setValue('apiKey', 'sk-PLAINTEXT'))
      .toThrow(EditConflictError)
    // SecretRef shapes pass
    session.setValue('apiKey', { ref: 'sec-1', revision: 'r-1' })
  })

  it('counterexample: cancel drops only this edit', async () => {
    const session = createEditSession<{ note: string }>({
      editId: 'e-7', baseRevision: 'rev-1', initial: { note: '' },
      commitHandler: async () => ({ kind: 'saved', consumedFields: ['note'] }),
    })
    session.setValue('note', 'x')
    session.cancel()
    expect(session.dirtyFields().size).toBe(0)
  })

  it('settingsContribution guards sensitive fields in validate()', () => {
    const guarded = settingsContribution({
      id: 'api-key', label: 'API key', defaultValueSource: 'domain-owner',
      editableScope: 'user', validate: () => null,
      read: async () => null, submit: async () => ({ kind: 'saved', consumedFields: [] }),
      sensitive: true,
    })
    expect(guarded.validate('plaintext')).not.toBeNull()
    expect(guarded.validate({ ref: 'sec-1', revision: 'r-1' })).toBeNull()
  })
})

describe('F5 UI storage', () => {
  it('session-only store is honest about its absence', async () => {
    const store = sessionOnlyUiStore()
    expect(store.capability).toBe('session-only')
    expect(store.persistenceNote).toBe(UI_STORAGE_ABSENCE_REASON)
    expect(UI_STORAGE_ABSENCE_REASON).toMatch(/not promised/)
  })

  it('unknown schema versions are refused, never overwriting records', async () => {
    const store = sessionOnlyUiStore()
    await store.write(ns, 'layout', { width: 300 }, {})
    await expect(store.write(
      { ...ns, schemaVersion: 0 }, 'layout', { width: 999 }, {},
    )).rejects.toThrow(UiSchemaUnknownError)
    expect(await store.read(ns, 'layout')).toEqual({ width: 300 }) // untouched
  })

  it('conditional writes conflict instead of last-write-wins', async () => {
    const store = sessionOnlyUiStore()
    await store.write(ns, 'layout', { width: 300 }, {})
    // a stale writer pins the wrong revision
    const result = await store.write(ns, 'layout', { width: 1 }, { ifRevision: 'r-stale' })
    expect(result).toBe('conflict')
    expect(await store.read(ns, 'layout')).toEqual({ width: 300 })
  })

  it('namespaces are isolated (another plugin/window sees nothing)', async () => {
    const store = sessionOnlyUiStore()
    await store.write(ns, 'filter', 'mine', {})
    expect(await store.read({ ...ns, pluginNamespace: 'other.plugin' }, 'filter')).toBeUndefined()
    expect(await store.read({ ...ns, windowOrSharedPurpose: 'window-2' }, 'filter')).toBeUndefined()
  })

  it('remove deletes only the namespace own record', async () => {
    const store = sessionOnlyUiStore()
    await store.write(ns, 'k', 1, {})
    await store.write({ ...ns, windowOrSharedPurpose: 'window-2' }, 'k', 2, {})
    await store.remove(ns, 'k')
    expect(await store.read(ns, 'k')).toBeUndefined()
    expect(await store.read({ ...ns, windowOrSharedPurpose: 'window-2' }, 'k')).toBe(2)
  })

  it('migration is explicit-only and refuses downgrades', async () => {
    const store = sessionOnlyUiStore()
    expect(await store.migrate(ns, 2)).toBe('migrated')
    expect(await store.migrate(ns, 1)).toBe('refused')
    expect(await store.migrate(ns, 0)).toBe('refused')
  })

  it('counterexample: secret-shaped UI values are refused', () => {
    expect(() => assertSafeUiValue({ layout: { apiKey: 'sk-x' } })).toThrow(UiSchemaUnknownError)
    expect(() => assertSafeUiValue({ layout: { width: 300 } })).not.toThrow()
  })

  it('file-backed adapter participates in conditional writes', async () => {
    const backing = new Map<string, { revision: string; schemaVersion: number; value: unknown }>()
    const store = fileBackedUiStore({
      async read(nsKey, key) { return backing.get(`${nsKey}|${key}`) },
      async write(nsKey, key, envelope) { backing.set(`${nsKey}|${key}`, envelope) },
      async remove(nsKey, key) { backing.delete(`${nsKey}|${key}`) },
    })
    expect(store.capability).toBe('available')
    await store.write(ns, 'x', 'v1', {})
    const current = backing.get(`${ns.pluginNamespace}|${ns.workspace}|${ns.windowOrSharedPurpose}|${ns.schemaVersion}|x`)
    expect(await store.write(ns, 'x', 'v2', { ifRevision: current!.revision })).toBe('written')
  })
})
