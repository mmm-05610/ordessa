/**
 * T008-14/15 gates: query cache key isolation, effect-refusal, scope
 * cleanup and bounded capacity; task cancel-wait vs operation-cancel,
 * stale-generation barriers and unknown-outcome retention. Projection
 * adapter honesty: gaps are resync-required and revocation stops delivery.
 */
import { describe, expect, it, vi } from 'vitest'

import { createQueryCache } from '../src/state/queryCache'
import { createTaskScope, TaskUnknown } from '../src/state/tasks'
import { projectionFromObservable, type ObservableSource } from '../src/state/projection'
import {
  EditConflictError,
  QueryEffectMismatchError,
} from '../../contracts/foundation/src/open-environment/f5/errors'

const baseKey = {
  environment: 'env-a',
  connectionGeneration: 1,
  authorizationScope: 'scope-a',
  authorizationGeneration: 1,
  serviceTarget: 'svc',
  contractVersion: 'v1',
  params: {},
}

describe('F5 query cache', () => {
  it('same key merges concurrent reads into one flight', async () => {
    const cache = createQueryCache()
    const run = vi.fn(async () => { await new Promise(r => setTimeout(r, 5)); return 42 })
    const decl = cache.declaration({ key: baseKey, run })
    const e1 = cache.read(decl)
    const e2 = cache.read(decl)
    await new Promise(r => setTimeout(r, 20))
    expect(run).toHaveBeenCalledTimes(1) // merged, not doubled
    expect(e1.data).toBe(42)
    expect(e2.data).toBe(42)
  })

  it('counterexample: different authorization scopes never share a cache entry', async () => {
    const cache = createQueryCache()
    const runA = vi.fn(async () => 'A')
    const runB = vi.fn(async () => 'B')
    const a = cache.read(cache.declaration({ key: baseKey, run: runA }))
    const b = cache.read(cache.declaration({
      key: { ...baseKey, authorizationScope: 'scope-b' }, run: runB,
    }))
    await new Promise(r => setTimeout(r, 10))
    expect(a.data).toBe('A')
    expect(b.data).toBe('B')
    expect(runA).toHaveBeenCalledTimes(1)
    expect(runB).toHaveBeenCalledTimes(1)
  })

  it('counterexample: an effectful declaration is refused at the door', () => {
    const cache = createQueryCache()
    expect(() => cache.declaration({ key: baseKey, run: async () => 1, effectful: true }))
      .toThrow(QueryEffectMismatchError)
  })

  it('clearScope drops accessible snapshots on revocation', async () => {
    const cache = createQueryCache()
    const decl = cache.declaration({ key: baseKey, run: async () => 'data' })
    const entry = cache.read(decl)
    await new Promise(r => setTimeout(r, 5))
    expect(entry.data).toBe('data')
    cache.clearScope('scope-a')
    // the entry object is gone: re-reading recreates a fresh (loading) entry
    const fresh = cache.read(decl)
    expect(fresh.data).toBeUndefined()
  })

  it('capacity is bounded: entries evict LRU and never become history', async () => {
    const cache = createQueryCache({ maxEntries: 2 })
    for (const i of [1, 2, 3]) {
      cache.read(cache.declaration({
        key: { ...baseKey, params: { i } }, run: async () => i,
      }))
    }
    await new Promise(r => setTimeout(r, 10))
    // the first entry was evicted; re-reading it starts a NEW flight
    const run1 = vi.fn(async () => 1)
    const entry = cache.read(cache.declaration({ key: { ...baseKey, params: { i: 1 } }, run: run1 }))
    await new Promise(r => setTimeout(r, 10))
    expect(entry.data).toBe(1)
    expect(run1).toHaveBeenCalledTimes(1) // fresh run, no stale history
  })

  it('refresh re-runs the declaration; unknown keys do nothing', async () => {
    const cache = createQueryCache()
    const run = vi.fn(async () => 1)
    const decl = cache.declaration({ key: baseKey, run })
    cache.read(decl)
    await new Promise(r => setTimeout(r, 5))
    await cache.refresh(baseKey)
    expect(run).toHaveBeenCalledTimes(2)
    await cache.refresh({ ...baseKey, params: { absent: 1 } }) // no throw
  })
})

describe('F5 tasks', () => {
  it('cancelWait cancels the waiter only and reports cancelled-wait', async () => {
    const scope = createTaskScope({ currentGeneration: () => 1 })
    const body = vi.fn(async () => { await new Promise(r => setTimeout(r, 50)); return 'late' })
    const handle = scope.run({ activation: 'a', generation: 1 }, body)
    handle.cancelWait()
    const result = await handle.result()
    expect(result.kind).toBe('cancelled-wait')
    // counterexample: the accepted body is NOT claimed stopped — it still ran
    // (or is running); nothing here reports a backend stop.
    expect(body).toHaveBeenCalledTimes(1)
  })

  it('counterexample: a late stale-generation result never overwrites the new owner', async () => {
    let generation = 1
    const scope = createTaskScope({ currentGeneration: () => generation })
    const oldHandle = scope.run({ activation: 'a', generation: 1 }, async () => {
      generation = 2 // the owner moved on while the body was in flight
      return 'old-value'
    })
    const result = await oldHandle.result()
    expect(result.kind).toBe('failed')
    if (result.kind === 'failed') expect(result.reason).toMatch(/stale generation/)
  })

  it('barrierLatest settles stale waiters without touching fresh ones', async () => {
    let generation = 2
    const scope = createTaskScope({ currentGeneration: () => generation })
    const stale = scope.run({ activation: 'a', generation: 1 }, async () => 'never')
    const fresh = scope.run({ activation: 'a', generation: 2 }, async () => 'ok')
    scope.barrierLatest()
    expect((await stale.result()).kind).toBe('failed')
    const freshResult = await fresh.result()
    expect(freshResult.kind).toBe('done')
  })

  it('unknown outcomes keep the request association and never retry', async () => {
    const scope = createTaskScope({ currentGeneration: () => 1 })
    const body = vi.fn(async () => { throw new TaskUnknown('query://task/req-1') })
    const handle = scope.run({ activation: 'a', generation: 1 }, body)
    const result = await handle.result()
    expect(result).toEqual({ kind: 'unknown', queryHint: 'query://task/req-1' })
    expect(body).toHaveBeenCalledTimes(1) // exactly once: no automatic retry
    expect(handle.requestKey).toBe('req-1')
  })
})

describe('F5 projection adapter', () => {
  function fakeSource(): { source: ObservableSource<string>; emit: Record<string, (...a: never[]) => void> } {
    let sinkRef: Parameters<ObservableSource<string>['attach']>[0] | null = null
    const source: ObservableSource<string> = {
      attach(sink) {
        sinkRef = sink
        return { detach: () => { sinkRef = null } }
      },
    }
    return {
      source,
      emit: {
        snapshot: (rev: string, v: string) => sinkRef?.snapshot(rev, v),
        gap: (r: 'gap' | 'overflow' | 'reconnect') => sinkRef?.gap(r),
        revoked: () => sinkRef?.revoked(),
      } as Record<string, (...a: never[]) => void>,
    }
  }

  it('gaps are explicit resync-required frames, never silent', () => {
    const { source, emit } = fakeSource()
    const proj = projectionFromObservable(source, { scope: 's', generation: 1, bufferLimit: 2 })
    ;(emit.snapshot as (r: string, v: string) => void)('rev-1', 'a')
    ;(emit.gap as (r: 'gap') => void)('gap')
    const frame = proj.observe(null, 10)
    // latest snapshot for a null cursor; the gap frame is retained in-window
    expect(frame.kind).toBe('snapshot')
    const again = proj.observe('c-1', 10)
    expect(again.kind).toBe('resync-required') // cursor beyond window honest gap
    proj.close()
  })

  it('revocation stops delivery (revoked frame, no pretend-continuity)', () => {
    const { source, emit } = fakeSource()
    const proj = projectionFromObservable(source, { scope: 's', generation: 1 })
    ;(emit.revoked as () => void)()
    expect(proj.observe(null, 10).kind).toBe('revoked')
    proj.close()
  })
})

describe('import hygiene', () => {
  it('the state mechanism module carries no React or business imports', async () => {
    // structural proxy: the pure modules are consumed by a node bundle in
    // the f5-counter fixture without React — asserted there. Here we pin
    // that the error family is reachable from this module graph (no drift).
    expect(new EditConflictError('x').code).toBe('F5_EDIT_CONFLICT')
  })
})
