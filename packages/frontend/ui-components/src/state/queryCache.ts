/**
 * F5 query cache (R7/M14 `oe-f5/1`, T008-14) — the frozen QueryCache/
 * QueryDeclaration/QueryEntry/QueryKey signatures.
 *
 * Ordinary reads only: an effectful declaration is refused at the door
 * (QueryEffectMismatchError) — non-idempotent effects never masquerade as
 * queries. Keys group by all seven QueryKey fields: results never cross
 * authorization scopes, connection generations or service targets.
 * Refresh/retry/persist policies are explicitly opt-in and default OFF
 * (F5 §8). The cache is bounded (LRU) and never a full history.
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
}

class Entry<T> implements QueryEntry<T> {
  constructor(private readonly store: Map<string, EntryState<T>>, private readonly id: string) {}

  private get s(): EntryState<T> {
    const s = this.store.get(this.id)
    if (s === undefined) throw new QueryEffectMismatchError('entry was evicted')
    return s
  }

  get state() { return this.s.state }
  get data() { return this.s.data }
  get freshness() { return this.s.freshness }

  subscribe(listener: () => void): ReleaseHandle {
    const s = this.s
    s.listeners.add(listener)
    let released = false
    return {
      release: () => {
        if (released) return
        released = true
        s.listeners.delete(listener)
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
  const maxEntries = options.maxEntries ?? 64
  const states = new Map<string, EntryState<unknown>>()
  const decls = new Map<string, QueryDeclaration<unknown>>()
  const order: string[] = [] // LRU: oldest first

  function touch(id: string): void {
    const at = order.indexOf(id)
    if (at >= 0) order.splice(at, 1)
    order.push(id)
    while (order.length > maxEntries) {
      const evicted = order.shift()!
      states.delete(evicted)
      decls.delete(evicted)
    }
  }

  function notify(id: string): void {
    const s = states.get(id)
    if (s === undefined) return
    for (const listener of [...s.listeners]) {
      try {
        listener()
      } catch { /* a throwing listener cannot break the cache */ }
    }
  }

  function ensure<T>(decl: QueryDeclaration<T>): [string, EntryState<T>] {
    const id = keyString(decl.key)
    let s = states.get(id) as EntryState<T> | undefined
    if (s === undefined) {
      s = { state: 'idle', data: undefined, freshness: 'fresh', listeners: new Set(), inflight: null }
      states.set(id, s as EntryState<unknown>)
    }
    decls.set(id, decl as QueryDeclaration<unknown>)
    touch(id)
    return [id, s]
  }

  async function run<T>(decl: QueryDeclaration<T>, id: string, s: EntryState<T>): Promise<void> {
    if (s.inflight !== null) return s.inflight // same-key in-flight merge
    const controller = new AbortController()
    s.state = 'loading'
    notify(id)
    const promise = (async () => {
      try {
        const data = await decl.run(controller.signal)
        s.data = data
        s.state = 'success'
        s.freshness = 'fresh'
      } catch {
        s.state = 'error'
      } finally {
        s.inflight = null
        notify(id)
      }
    })()
    s.inflight = promise
    return promise
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
      const [id, s] = ensure<T>(decl)
      if (s.state === 'idle') void run(decl, id, s)
      return new Entry<T>(states as Map<string, EntryState<T>>, id)
    },

    invalidate(key: QueryKey): void {
      const id = keyString(key)
      const s = states.get(id)
      if (s === undefined) return
      s.state = 'stale'
      s.freshness = 'stale'
      notify(id)
    },

    async refresh(key: QueryKey): Promise<void> {
      // Explicit refresh is an authorized action: it re-runs the declaration
      // the key was first read with (never an undeclared effect).
      const id = keyString(key)
      const s = states.get(id) as EntryState<unknown> | undefined
      const decl = decls.get(id)
      if (s === undefined || decl === undefined) return
      s.state = 'stale'
      notify(id)
      await run(decl, id, s)
    },

    clearScope(scope: string): void {
      // Authorization revocation / scope exit: accessible snapshots are
      // dropped; data already handed to consumers is not retracted (F5 §2).
      for (const id of [...states.keys()]) {
        const parsed = JSON.parse(id) as [string, number, string, number, string, string, unknown]
        if (parsed[2] === scope) {
          states.delete(id)
          decls.delete(id)
          const at = order.indexOf(id)
          if (at >= 0) order.splice(at, 1)
        }
      }
    },
  }
}
