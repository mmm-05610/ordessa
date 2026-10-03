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
} from '../../../contracts/foundation/src/open-environment/f5/types'

export interface StateStoreOptions<S> {
  equals?: (a: S, b: S) => boolean
  /** Diagnostics sink for throwing subscribers (never breaks publication). */
  onSubscriberError?: (cause: unknown) => void
}

function deepFreeze<T>(value: T): T {
  if (value === null || typeof value !== 'object') return value
  Object.freeze(value)
  for (const key of Reflect.ownKeys(value as object)) {
    const child = (value as Record<string | symbol, unknown>)[key]
    if (child !== null && typeof child === 'object' && !Object.isFrozen(child)) {
      deepFreeze(child)
    }
  }
  return value
}

class StateStore<S> implements StateStoreOwner<S> {
  private current: S
  private readonly listeners = new Set<() => void>()
  private readonly equals: (a: S, b: S) => boolean

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
    let next = this.current
    for (const recipe of recipes) next = recipe(next)
    if (this.equals(this.current, next)) return // no-op: no publish, same ref
    this.current = deepFreeze(next) // exactly one complete snapshot
    for (const listener of [...this.listeners]) {
      try {
        listener()
      } catch (cause) {
        try {
          this.options.onSubscriberError?.(cause)
        } catch { /* a throwing diagnostics sink must not break publication */ }
      }
    }
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
