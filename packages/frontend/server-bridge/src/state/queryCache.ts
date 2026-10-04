/**
 * F5 query cache (R7/M14 `oe-f5/1`, T008-14) — the frozen QueryCache/
 * QueryDeclaration/QueryEntry/QueryKey signatures.
 *
 * Ordinary reads only. Keys include authorization, connection, target, and
 * contract identity. Retry, focus refresh, and persistence remain opt-in and
 * are not implemented as implicit behavior here.
 */
import type {
  QueryCache,
  QueryDeclaration,
  QueryEntry,
  QueryKey,
  ReleaseHandle,
} from '../../../contracts/foundation/src/open-environment/f5/types'
import { QueryEffectMismatchError } from '../../../contracts/foundation/src/open-environment/f5/errors'

/** Augments the frozen declaration with the effect flag the gate checks. */
export interface GatedQueryDeclaration<T> extends QueryDeclaration<T> {
  /** Set only for genuinely effect-free reads; effectful declarations are refused. */
  effectful?: boolean
}

function keyString(key: QueryKey): string {
  return JSON.stringify([
    key.environment,
    key.connectionGeneration,
    key.authorizationScope,
    key.authorizationGeneration,
    key.serviceTarget,
    key.contractVersion,
    Object.entries(key.params).sort(),
  ])
}

interface EntryState<T> {
  state: QueryEntry<T>['state']
  data: T | undefined
  freshness: QueryEntry<T>['freshness']
  listeners: Set<() => void>
  inflight: Promise<void> | null
  epoch: number
  active: boolean
}

class Entry<T> implements QueryEntry<T> {
  constructor(
    private readonly store: Map<string, EntryState<unknown>>,
    private readonly id: string,
    private readonly captured: EntryState<T>,
  ) {}

  private get isActive(): boolean {
    return this.captured.active && this.store.get(this.id) === this.captured
  }

  get state(): QueryEntry<T>['state'] { return this.isActive ? this.captured.state : 'stale' }
  get data(): T | undefined { return this.isActive ? this.captured.data : undefined }
  get freshness(): QueryEntry<T>['freshness'] {
    return this.isActive ? this.captured.freshness : 'stale'
  }

  subscribe(listener: () => void): ReleaseHandle {
    if (!this.isActive) return { release() {} }
    const listeners = this.captured.listeners
    listeners.add(listener)
    let released = false
    return {
      release: () => {
        if (released) return
        released = true
        listeners.delete(listener)
      },
    }
  }
}

export interface QueryCacheOptions {
  maxEntries?: number
}

export function createQueryCache(options: QueryCacheOptions = {}): QueryCache & {
  declaration<T>(decl: GatedQueryDeclaration<T>): QueryDeclaration<T>
} {
  const requestedMax = options.maxEntries ?? 64
  const maxEntries = Number.isFinite(requestedMax) ? Math.max(1, Math.floor(requestedMax)) : 64
  const states = new Map<string, EntryState<unknown>>()
  const decls = new Map<string, QueryDeclaration<unknown>>()
  const order: string[] = [] // LRU: oldest first

  function retire(id: string, state: EntryState<unknown>): void {
    if (states.get(id) === state) states.delete(id)
    state.active = false
    state.epoch += 1
    state.data = undefined
    state.state = 'stale'
    state.freshness = 'stale'
    state.inflight = null
    state.listeners.clear()
    decls.delete(id)
    const at = order.indexOf(id)
    if (at >= 0) order.splice(at, 1)
  }

  function touch(id: string): void {
    const at = order.indexOf(id)
    if (at >= 0) order.splice(at, 1)
    order.push(id)
    while (order.length > maxEntries) {
      const evicted = order.shift()!
      const state = states.get(evicted)
      if (state !== undefined) retire(evicted, state)
    }
  }

  function notify(id: string, expected: EntryState<unknown>): void {
    if (expected.active !== true || states.get(id) !== expected) return
    for (const listener of [...expected.listeners]) {
      try {
        listener()
      } catch { /* a throwing listener cannot break the cache */ }
    }
  }

  function ensure<T>(decl: QueryDeclaration<T>): [string, EntryState<T>] {
    const id = keyString(decl.key)
    let state = states.get(id) as EntryState<T> | undefined
    if (state === undefined) {
      state = {
        state: 'idle',
        data: undefined,
        freshness: 'fresh',
        listeners: new Set(),
        inflight: null,
        epoch: 0,
        active: true,
      }
      states.set(id, state as EntryState<unknown>)
    }
    decls.set(id, decl as QueryDeclaration<unknown>)
    touch(id)
    return [id, state]
  }

  function run<T>(decl: QueryDeclaration<T>, id: string, state: EntryState<T>): Promise<void> {
    if (state.inflight !== null) return state.inflight

    const epoch = state.epoch
    const controller = new AbortController()
    state.state = 'loading'
    notify(id, state as EntryState<unknown>)

    let flight!: Promise<void>
    flight = (async () => {
      try {
        // Let `state.inflight` receive this promise before invoking user code,
        // including declarations that throw synchronously.
        await Promise.resolve()
        const data = await decl.run(controller.signal)
        if (state.active && state.epoch === epoch && states.get(id) === state) {
          state.data = data
          state.state = 'success'
          state.freshness = 'fresh'
        }
      } catch {
        if (state.active && state.epoch === epoch && states.get(id) === state) {
          state.state = 'error'
        }
      } finally {
        // A superseded request cannot clear a newer flight or notify a
        // replacement entry that reused this key after clear/eviction.
        if (state.active && state.epoch === epoch && states.get(id) === state && state.inflight === flight) {
          state.inflight = null
          notify(id, state as EntryState<unknown>)
        }
      }
    })()
    state.inflight = flight
    return flight
  }

  return {
    declaration<T>(decl: GatedQueryDeclaration<T>): QueryDeclaration<T> {
      if (decl.effectful) {
        throw new QueryEffectMismatchError(
          'a non-idempotent effect must not be declared as an ordinary query')
      }
      return decl
    },

    read<T>(decl: QueryDeclaration<T>): QueryEntry<T> {
      const [id, state] = ensure<T>(decl)
      if (state.state === 'idle') void run(decl, id, state)
      return new Entry<T>(states, id, state)
    },

    invalidate(key: QueryKey): void {
      const id = keyString(key)
      const state = states.get(id)
      if (state === undefined) return
      // Invalidate the generation of any active read. Its eventual result may
      // not refresh this record; a later explicit refresh owns a new epoch.
      state.epoch += 1
      state.inflight = null
      state.state = 'stale'
      state.freshness = 'stale'
      notify(id, state)
    },

    async refresh(key: QueryKey): Promise<void> {
      const id = keyString(key)
      const state = states.get(id)
      const decl = decls.get(id)
      if (state === undefined || decl === undefined) return
      state.epoch += 1
      state.inflight = null
      state.state = 'stale'
      state.freshness = 'stale'
      notify(id, state)
      await run(decl, id, state)
    },

    clearScope(scope: string): void {
      // Revocation drops accessible data and retires request generations.
      // Existing handles become empty/stale, and late completions are ignored.
      for (const [id, state] of [...states]) {
        const parsed = JSON.parse(id) as [string, number, string, number, string, string, unknown]
        if (parsed[2] === scope) retire(id, state)
      }
    },
  }
}
