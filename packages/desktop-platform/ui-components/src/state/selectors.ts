/**
 * F5 selectors (R7/M14 `oe-f5/1`, T008-12/13).
 *
 * Pure selection over an already-authorized snapshot; `equal` results never
 * notify. Derivations only COMPUTE — they never create a second writer.
 * The React binding lives in `react/state.ts` (same underlying snapshot
 * source; the non-React side carries no React import).
 */
import type {
  ReadonlyStateStore,
  ReleaseHandle,
  Selector,
} from '../../../contracts/foundation/src/open-environment/f5/types'

export function createSelector<T, V>(
  select: (snapshot: T) => V,
  equals: (a: V, b: V) => boolean = Object.is,
): Selector<T, V> {
  const selector = ((snapshot: T) => select(snapshot)) as Selector<T, V>
  selector.equals = equals
  return selector
}

export interface SelectionReader<T, V> {
  /** Current selection from the store's snapshot; cached per selector result. */
  get(): V
  /** Subscribe to selection CHANGES only (equal results never notify). */
  subscribe(listener: () => void): ReleaseHandle
}

/**
 * A selection reader over a read-only store. Field selection happens on the
 * already-authorized snapshot; the reader never writes and never exposes the
 * store's mutable internals (there are none — snapshots are deeply frozen).
 */
export function selectionReader<T, V>(
  store: ReadonlyStateStore<T>,
  selector: Selector<T, V>,
): SelectionReader<T, V> {
  const equals = selector.equals ?? Object.is
  let last = selector(store.getSnapshot())
  let lastPublished = last
  return {
    get(): V {
      const next = selector(store.getSnapshot())
      if (!equals(last, next)) last = next
      return last
    },
    subscribe(listener: () => void): ReleaseHandle {
      return store.subscribe(() => {
        const next = selector(store.getSnapshot())
        if (equals(lastPublished, next)) return // unrelated field: zero notify
        lastPublished = next
        last = next
        listener()
      })
    },
  }
}
