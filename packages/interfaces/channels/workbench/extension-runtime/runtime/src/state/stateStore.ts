/**
 * F5 state store (R7/M14 `oe-f5/1`, T008-12) — the frozen `StateStoreOwner`
 * / `ReadonlyStateStore` / `StateStoreFactory` signatures from
 * `contracts/foundation/src/open-environment/f5/types.ts`.
 *
 * Semantics merged from ServiceCore (ui-components/src/index.ts): change
 * comparison before notify, batched publication as exactly one complete
 * snapshot, and throwing-subscriber isolation. This is the convergence
 * point — new F5 consumers build stores here (the T010 migration moves the
 * existing hand-written stores); no parallel store implementation may be
 * introduced alongside this one (F5 §8).
 *
 * Rules enforced here:
 * - owner-only write: `create()` returns an owner object; consumers receive
 *   only the read face (`ReadonlyStateStore`) — there is no generic
 *   `setState` on the consumer surface;
 * - identity-stable snapshots: a no-op update publishes nothing and
 *   `getSnapshot()` keeps returning the exact same object;
 * - published snapshots are deeply immutable (recursive freeze), never a
 *   shallow pretend;
 * - `updateBatched` publishes exactly ONE complete snapshot at the end;
 * - `subscribe` returns an idempotent release handle; a throwing listener
 *   cannot break the commit or other listeners.
 */
// Type-only, direct to the frozen contract module (no carrier cycle at
// runtime; the shared carrier re-exports the same f5 module for consumers).
import type {
  ReadonlyStateStore,
  ReleaseHandle,
  StateStoreFactory,
  StateStoreOwner,
} from '../../../../extension-api/contracts/foundation/src/open-environment/f5/types'

export interface StateStoreOptions<S> {
  equals?: (a: S, b: S) => boolean
  /** Diagnostics sink for throwing subscribers (never breaks publication). */
  onSubscriberError?: (cause: unknown) => void
}

/**
 * Snapshot values are deliberately limited to primitive values, arrays, and
 * plain/null-prototype records. Object.freeze does not make Map/Set contents,
 * accessors, or host/class instances immutable, so accepting those shapes
 * would give consumers a false read-only guarantee.
 */
function deepFreeze<T>(value: T): T {
  const seen = new WeakSet<object>()

  const validate = (item: unknown): void => {
    if (item === null || (typeof item !== 'object' && typeof item !== 'function')) return
    if (typeof item === 'function') {
      throw new TypeError('State snapshots cannot contain functions')
    }
    if (seen.has(item)) return
    seen.add(item)

    const prototype = Object.getPrototypeOf(item)
    const isArray = Array.isArray(item)
    if (isArray ? prototype !== Array.prototype : prototype !== Object.prototype && prototype !== null) {
      throw new TypeError('State snapshots support only arrays and plain objects')
    }

    for (const key of Reflect.ownKeys(item)) {
      const descriptor = Object.getOwnPropertyDescriptor(item, key)
      if (!descriptor || !('value' in descriptor)) {
        throw new TypeError('State snapshots cannot contain accessor properties')
      }
      validate(descriptor.value)
    }
  }

  const freeze = (item: unknown, visited: WeakSet<object>): void => {
    if (item === null || (typeof item !== 'object' && typeof item !== 'function')) return
    if (typeof item === 'function' || visited.has(item)) return
    visited.add(item)
    for (const key of Reflect.ownKeys(item)) {
      const descriptor = Object.getOwnPropertyDescriptor(item, key)
      if (descriptor && 'value' in descriptor) freeze(descriptor.value, visited)
    }
    Object.freeze(item)
  }

  validate(value)
  freeze(value, new WeakSet<object>())
  return value
}

const MAX_REENTRANT_PUBLICATIONS = 100

class StateStore<S> implements StateStoreOwner<S> {
  private current: S
  private readonly listeners = new Set<() => void>()
  private readonly equals: (a: S, b: S) => boolean
  private publishing = false
  private reentrantBudget = 0
  private readonly queuedBatches: Array<ReadonlyArray<(current: S) => S>> = []

  constructor(initial: S, private readonly options: StateStoreOptions<S> = {}) {
    this.equals = options.equals ?? Object.is
    this.current = deepFreeze(initial)
  }

  getSnapshot = (): S => this.current

  subscribe = (listener: () => void): ReleaseHandle => {
    let released = false
    const wrapped = () => { if (!released) listener() }
    this.listeners.add(wrapped)
    return {
      release: () => {
        if (released) return // idempotent
        released = true
        this.listeners.delete(wrapped)
      },
    }
  }

  update(recipe: (current: S) => S): void {
    this.updateBatched([recipe])
  }

  updateBatched(recipes: ReadonlyArray<(current: S) => S>): void {
    if (this.publishing) {
      if (this.reentrantBudget <= 0) {
        throw new RangeError(`State store reentrant publication limit (${MAX_REENTRANT_PUBLICATIONS}) exceeded`)
      }
      this.reentrantBudget -= 1
      this.queuedBatches.push(recipes)
      return
    }

    if (!this.commit(recipes)) return
    this.publishAndDrain()
  }

  private commit(recipes: ReadonlyArray<(current: S) => S>): boolean {
    const previous = this.current
    let next = previous
    for (const recipe of recipes) next = recipe(next)
    if (this.equals(previous, next)) return false
    const frozen = deepFreeze(next)
    this.current = frozen
    return true
  }

  private publishAndDrain(): void {
    this.publishing = true
    this.reentrantBudget = MAX_REENTRANT_PUBLICATIONS - 1
    try {
      this.notifyListeners()
      while (this.queuedBatches.length > 0) {
        const batch = this.queuedBatches.shift()!
        try {
          if (!this.commit(batch)) continue
        } catch (cause) {
          this.reportSubscriberError(cause)
          continue
        }
        this.notifyListeners()
      }
    } finally {
      this.publishing = false
      this.reentrantBudget = 0
    }
  }

  private notifyListeners(): void {
    for (const listener of [...this.listeners]) {
      try {
        listener()
      } catch (cause) {
        this.reportSubscriberError(cause)
      }
    }
  }

  private reportSubscriberError(cause: unknown): void {
    try {
      this.options.onSubscriberError?.(cause)
    } catch { /* a throwing diagnostics sink must not break publication */ }
  }
}

/** Owner face of a store created here; keep it inside the owning domain. */
export interface OwnedState<S> extends StateStoreOwner<S> {
  /** The read face handed to consumers — carries no write method. */
  reader(): ReadonlyStateStore<S>
}

function readerOf<S>(store: StateStore<S>): ReadonlyStateStore<S> {
  return { getSnapshot: store.getSnapshot, subscribe: store.subscribe }
}

export const stateStoreFactory: StateStoreFactory & {
  createOwned<S>(initial: S, options?: StateStoreOptions<S>): OwnedState<S>
} = {
  create<S>(initial: S, options?: { equals?: (a: S, b: S) => boolean }): StateStoreOwner<S> {
    return new StateStore(initial, options)
  },
  createOwned<S>(initial: S, options?: StateStoreOptions<S>): OwnedState<S> {
    const store = new StateStore(initial, options)
    return Object.assign(store, { reader: () => readerOf(store) })
  },
}
