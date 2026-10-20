/**
 * Acceptance closeout regressions for F5 snapshot safety and notification
 * semantics. These are intentionally separate from the original F5 checks so
 * the newly discovered counterexamples stay visible in closeout evidence.
 */
import { describe, expect, it, vi } from 'vitest'

import { stateStoreFactory } from '../src/state/stateStore'

describe('F5 closeout state-store regressions', () => {
  it('deep-freezes descendants even when an ancestor was already shallow-frozen', () => {
    const child = Object.freeze({ nested: { value: 1 } })
    const store = stateStoreFactory.createOwned({ child })
    const notifications = vi.fn()
    store.subscribe(notifications)

    const snapshot = store.getSnapshot()
    expect(Object.isFrozen(snapshot.child.nested)).toBe(true)
    expect(() => {
      ;(snapshot.child.nested as { value: number }).value = 2
    }).toThrow()
    expect(snapshot.child.nested.value).toBe(1)
    expect(notifications).not.toHaveBeenCalled()
  })

  it('supports cycles and shared references while freezing the whole object graph', () => {
    const shared = { nested: { value: 1 } }
    const initial: { left: typeof shared; right: typeof shared; self?: unknown } = {
      left: shared,
      right: shared,
    }
    initial.self = initial

    const store = stateStoreFactory.createOwned(initial)
    const snapshot = store.getSnapshot()

    expect(snapshot.self).toBe(snapshot)
    expect(snapshot.left).toBe(snapshot.right)
    expect(Object.isFrozen(snapshot)).toBe(true)
    expect(Object.isFrozen(snapshot.left)).toBe(true)
    expect(Object.isFrozen(snapshot.left.nested)).toBe(true)
    expect(() => { snapshot.left.nested.value = 2 }).toThrow()
  })

  it('keeps snapshot identity stable on reads and same-reference no-op updates', () => {
    const store = stateStoreFactory.createOwned({ value: 1 })
    const listener = vi.fn()
    store.subscribe(listener)
    const original = store.getSnapshot()

    expect(store.getSnapshot()).toBe(original)
    store.update(current => current)

    expect(store.getSnapshot()).toBe(original)
    expect(listener).not.toHaveBeenCalled()
  })

  it('publishes one complete snapshot for a batch', () => {
    const store = stateStoreFactory.createOwned({ left: 0, right: 0 })
    const seen: Array<[number, number]> = []
    store.subscribe(() => {
      const snapshot = store.getSnapshot()
      seen.push([snapshot.left, snapshot.right])
    })

    store.updateBatched([
      current => ({ ...current, left: 1 }),
      current => ({ ...current, right: 2 }),
    ])

    expect(seen).toEqual([[1, 2]])
  })

  it('isolates subscriber errors and reports them without blocking later listeners', () => {
    const error = new Error('subscriber failed')
    const errors: unknown[] = []
    const healthy = vi.fn()
    const store = stateStoreFactory.createOwned({ value: 0 }, {
      onSubscriberError: cause => errors.push(cause),
    })
    store.subscribe(() => { throw error })
    store.subscribe(healthy)

    store.update(current => ({ value: current.value + 1 }))

    expect(healthy).toHaveBeenCalledTimes(1)
    expect(errors).toEqual([error])
    expect(store.getSnapshot().value).toBe(1)
  })

  it('bounds reentrant publication instead of recursing without limit', () => {
    const errors: unknown[] = []
    const store = stateStoreFactory.createOwned({ value: 0 }, {
      onSubscriberError: cause => errors.push(cause),
    })
    let calls = 0
    let maxDepth = 0
    let depth = 0
    store.subscribe(() => {
      calls += 1
      depth += 1
      maxDepth = Math.max(maxDepth, depth)
      store.update(current => ({ value: current.value + 1 }))
      depth -= 1
    })

    store.update(current => ({ value: current.value + 1 }))

    expect(calls).toBeLessThanOrEqual(100)
    expect(maxDepth).toBe(1)
    expect(errors.some(cause => cause instanceof RangeError)).toBe(true)
  })

  it.each([
    ['Map', () => new Map([['key', 'value']])],
    ['Set', () => new Set(['value'])],
    ['Date', () => new Date(0)],
    ['class instance', () => new (class DomainValue { value = 1 })()],
  ])('rejects unsupported %s values instead of presenting a shallow freeze as safe', (_name, makeValue) => {
    expect(() => stateStoreFactory.createOwned({ value: makeValue() })).toThrow(TypeError)
  })

  it('does not replace a valid snapshot when an update introduces an unsupported shape', () => {
    const store = stateStoreFactory.createOwned({ value: 1 })
    const original = store.getSnapshot()
    const listener = vi.fn()
    store.subscribe(listener)

    expect(() => store.update(() => ({ value: new Map() as unknown as number }))).toThrow(TypeError)
    expect(store.getSnapshot()).toBe(original)
    expect(store.getSnapshot().value).toBe(1)
    expect(listener).not.toHaveBeenCalled()
  })
})
