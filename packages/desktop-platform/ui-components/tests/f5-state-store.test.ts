/**
 * T008-12 gates: the F5 state store implements the frozen contract and the
 * F5 §2 discipline. Counterexamples pinned: consumers cannot write, nested
 * mutation of a published snapshot fails, equal updates never notify,
 * batched updates publish exactly one complete snapshot, a throwing
 * listener cannot break others, and a released (old-generation) listener
 * never touches a new owner's publication.
 */
import { describe, expect, it, vi } from 'vitest'

import { stateStoreFactory } from '../src/state/stateStore'
import { createSelector, selectionReader } from '../src/state/selectors'

describe('F5 state store', () => {
  it('publishes identity-stable snapshots: unmodified getSnapshot returns the same object', () => {
    const store = stateStoreFactory.createOwned({ count: 0, label: 'a' })
    const first = store.getSnapshot()
    expect(store.getSnapshot()).toBe(first)
    store.update(s => ({ ...s, count: 1 }))
    const second = store.getSnapshot()
    expect(second).not.toBe(first)
    expect(store.getSnapshot()).toBe(second)
  })

  it('a no-op update publishes nothing and keeps the same reference', () => {
    const listener = vi.fn()
    const store = stateStoreFactory.createOwned({ count: 0 })
    store.subscribe(listener)
    store.update(s => ({ ...s })) // equal content, new object
    expect(listener).toHaveBeenCalledTimes(1) // new object identity publishes
    const before = store.getSnapshot()
    store.update(s => s) // true no-op
    expect(listener).toHaveBeenCalledTimes(1) // still once
    expect(store.getSnapshot()).toBe(before)
  })

  it('published snapshots are deeply immutable (nested values frozen)', () => {
    const store = stateStoreFactory.createOwned({ nested: { value: 1 }, list: [1, 2] })
    const snap = store.getSnapshot()
    expect(Object.isFrozen(snap)).toBe(true)
    expect(Object.isFrozen(snap.nested)).toBe(true)
    expect(() => { (snap.nested as { value: number }).value = 99 }).toThrow()
    expect(() => { (snap.list as number[]).push(3) }).toThrow()
  })

  it('updateBatched publishes exactly ONE complete snapshot', () => {
    const seen: number[] = []
    const store = stateStoreFactory.createOwned({ a: 0, b: 0 })
    store.subscribe(() => seen.push(store.getSnapshot().a + store.getSnapshot().b))
    store.updateBatched([
      s => ({ ...s, a: 1 }),
      s => ({ ...s, b: 1 }),
      s => ({ ...s, a: 2 }),
    ])
    expect(seen).toEqual([3]) // one notification, final complete state
  })

  it('release is idempotent and a released listener never fires again', () => {
    const listener = vi.fn()
    const store = stateStoreFactory.createOwned({ n: 0 })
    const handle = store.subscribe(listener)
    handle.release()
    handle.release() // idempotent
    store.update(s => ({ ...s, n: 1 }))
    expect(listener).not.toHaveBeenCalled()
  })

  it('a throwing listener cannot break the commit or other listeners', () => {
    const errors: unknown[] = []
    const good = vi.fn()
    const store = stateStoreFactory.createOwned({ n: 0 }, {
      onSubscriberError: cause => errors.push(cause),
    })
    store.subscribe(() => { throw new Error('boom') })
    store.subscribe(good)
    store.update(s => ({ ...s, n: 1 }))
    expect(good).toHaveBeenCalledTimes(1)
    expect(errors).toHaveLength(1)
    expect(store.getSnapshot().n).toBe(1) // the commit stands
  })

  it('counterexample: the consumer read face carries no write method', () => {
    const store = stateStoreFactory.createOwned({ n: 0 })
    const reader = store.reader()
    expect('update' in reader).toBe(false)
    expect('updateBatched' in reader).toBe(false)
  })

  it('counterexample: an old-generation release never touches a new owner', () => {
    const oldOwner = stateStoreFactory.createOwned({ n: 0 })
    const oldListener = vi.fn()
    const handle = oldOwner.subscribe(oldListener)
    handle.release() // old scope disposed
    const newOwner = stateStoreFactory.createOwned({ n: 100 })
    const newListener = vi.fn()
    newOwner.subscribe(newListener)
    newOwner.update(s => ({ ...s, n: 101 }))
    expect(oldListener).not.toHaveBeenCalled()
    expect(newListener).toHaveBeenCalledTimes(1)
    expect(oldOwner.getSnapshot().n).toBe(0) // old owner untouched
  })
})

describe('F5 selectors', () => {
  it('equal results never notify; unrelated fields are silent', () => {
    const store = stateStoreFactory.createOwned({ input: '', heavy: 0 })
    const reader = selectionReader(store, createSelector((s: { input: string }) => s.input))
    const listener = vi.fn()
    reader.subscribe(listener)
    store.update(s => ({ ...s, heavy: 1 })) // unrelated field
    expect(listener).not.toHaveBeenCalled()
    store.update(s => ({ ...s, input: 'x' }))
    expect(listener).toHaveBeenCalledTimes(1)
    expect(reader.get()).toBe('x')
  })

  it('counterexample: no per-keystroke input reset — the selection identity is stable', () => {
    const store = stateStoreFactory.createOwned({ input: '', cursor: 0 })
    const reader = selectionReader(store, createSelector((s: { input: string }) => s.input))
    const first = reader.get()
    store.update(s => ({ ...s, cursor: 1 }))
    expect(reader.get()).toBe(first) // same value, no invalidation storm
  })
})
