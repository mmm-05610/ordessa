/**
 * F5 React selection binding (R7/M14 `oe-f5/1`, T008-13).
 *
 * Uses the same `useSyncExternalStore` instance as the rest of the
 * platform's React layer. Unmount releases the subscription; unrelated
 * selector results never re-render. The binding reads from the SAME
 * snapshot source as the non-React side — one store, one authority.
 */
import { useCallback, useSyncExternalStore } from 'react'

import type {
  ReadonlyStateStore,
  Selector,
} from '../../contracts/foundation/src/open-environment/f5/types'

export function useStoreSelection<T, V>(
  store: ReadonlyStateStore<T>,
  selector: Selector<T, V>,
): V {
  const equals = selector.equals ?? Object.is
  // Cache the selected value so useSyncExternalStore sees a stable snapshot
  // across unrelated notifications (identity-stable reads, zero re-renders).
  let cachedValue: V = selector(store.getSnapshot())
  const subscribe = useCallback((onChange: () => void) => {
    const handle = store.subscribe(onChange)
    return () => handle.release() // uSES wants a destroy function, the store hands a ReleaseHandle
  }, [store])
  const getSnapshot = useCallback(() => {
    const next = selector(store.getSnapshot())
    if (!equals(cachedValue, next)) cachedValue = next
    return cachedValue
  }, [store, selector])
  const getServerSnapshot = useCallback(() => cachedValue, [])
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)
}
