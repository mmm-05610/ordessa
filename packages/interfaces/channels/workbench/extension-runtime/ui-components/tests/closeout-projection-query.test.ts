/**
 * T013 closeout regressions for projection close/credit/overflow handling and
 * query invalidation/lifecycle isolation. These deliberately exercise the
 * public adapters with delayed callbacks and reads.
 */
import { describe, expect, it, vi } from 'vitest'

import { projectionFromObservable, type ObservableSource } from '../src/state/projection'
import { createQueryCache } from '../src/state/queryCache'

const key = {
  environment: 'env',
  connectionGeneration: 1,
  authorizationScope: 'scope',
  authorizationGeneration: 1,
  serviceTarget: 'service',
  contractVersion: 'v1',
  params: {},
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(r => { resolve = r })
  return { promise, resolve }
}

function sourceWithQueuedSink() {
  let queued: Parameters<ObservableSource<string>['attach']>[0] | undefined
  const detach = vi.fn()
  const source: ObservableSource<string> = {
    attach(sink) {
      queued = sink
      return { detach }
    },
  }
  return {
    source,
    queued: () => queued!,
    detach,
  }
}

describe('T013 projection closeout', () => {
  it('close is idempotent and queued snapshot, delta, and gap callbacks cannot change the projection', () => {
    const source = sourceWithQueuedSink()
    const projection = projectionFromObservable(source.source, { scope: 'scope', generation: 1 })
    source.queued().snapshot('r1', 'one')

    projection.close()
    projection.close()
    source.queued().snapshot('r2', 'two')
    source.queued().delta('r3', { value: 'three' })
    source.queued().gap('gap')

    expect(source.detach).toHaveBeenCalledTimes(1)
    expect(projection.observe(null, 8)).toEqual({
      kind: 'snapshot', revision: 'r1', value: 'one', cursor: 'c-1',
    })
  })

  it('synchronous revocation during attach detaches once and remains revoked after close', () => {
    const detach = vi.fn()
    const source: ObservableSource<string> = {
      attach(sink) {
        sink.revoked()
        return { detach }
      },
    }

    const projection = projectionFromObservable(source, { scope: 'scope', generation: 1 })
    expect(detach).toHaveBeenCalledTimes(1)
    projection.close()
    expect(detach).toHaveBeenCalledTimes(1)
    expect(projection.observe(null, 8)).toEqual({ kind: 'revoked' })
  })

  it('overflow requires resync instead of returning a snapshot with a truncated delta chain', () => {
    const source = sourceWithQueuedSink()
    const projection = projectionFromObservable(source.source, {
      scope: 'scope', generation: 1, bufferLimit: 2,
    })
    source.queued().snapshot('r1', 'one')
    source.queued().delta('r2', { value: 2 })
    source.queued().delta('r3', { value: 3 })

    expect(projection.observe(null, 8)).toEqual({ kind: 'resync-required', reason: 'overflow' })
    projection.close()
  })

  it('zero credit does not deliver or advance past the supplied cursor', () => {
    const source = sourceWithQueuedSink()
    const projection = projectionFromObservable(source.source, { scope: 'scope', generation: 1 })
    source.queued().snapshot('r1', 'one')
    source.queued().delta('r2', { value: 2 })

    expect(projection.observe('c-1', 0)).not.toEqual({
      kind: 'delta', revision: 'r2', patch: { value: 2 }, cursor: 'c-2',
    })
    expect(projection.observe('c-1', 1)).toEqual({
      kind: 'delta', revision: 'r2', patch: { value: 2 }, cursor: 'c-2',
    })
    projection.close()
  })

  it('an expired cursor reports a gap after the bounded history rolls forward', () => {
    const source = sourceWithQueuedSink()
    const projection = projectionFromObservable(source.source, {
      scope: 'scope', generation: 1, bufferLimit: 2,
    })
    source.queued().snapshot('r1', 'one')
    source.queued().delta('r2', { value: 2 })
    source.queued().delta('r3', { value: 3 })

    expect(projection.observe('c-1', 2)).toEqual({ kind: 'resync-required', reason: 'gap' })
    projection.close()
  })
})

describe('T013 query cache closeout', () => {
  it('an invalidation during an in-flight read is not overwritten as fresh by that result', async () => {
    const cache = createQueryCache()
    const result = deferred<string>()
    const entry = cache.read(cache.declaration({ key, run: () => result.promise }))

    cache.invalidate(key)
    result.resolve('old result')
    await Promise.resolve()
    await Promise.resolve()

    expect(entry.freshness).toBe('stale')
    expect(entry.state).toBe('stale')
  })

  it('a cleared scope late result neither changes nor notifies the replacement entry', async () => {
    const cache = createQueryCache()
    const oldResult = deferred<string>()
    const replacementResult = deferred<string>()
    cache.read(cache.declaration({ key, run: () => oldResult.promise }))

    cache.clearScope('scope')
    const replacement = cache.read(cache.declaration({ key, run: () => replacementResult.promise }))
    const listener = vi.fn()
    replacement.subscribe(listener)
    listener.mockClear()

    oldResult.resolve('old scope')
    await Promise.resolve()
    await Promise.resolve()

    expect(replacement.data).toBeUndefined()
    expect(replacement.state).toBe('loading')
    expect(listener).not.toHaveBeenCalled()
    replacementResult.resolve('new scope')
  })

  it('an evicted request late result neither changes nor notifies a re-created entry', async () => {
    const cache = createQueryCache({ maxEntries: 1 })
    const oldResult = deferred<string>()
    const replacementResult = deferred<string>()
    cache.read(cache.declaration({ key, run: () => oldResult.promise }))
    cache.read(cache.declaration({
      key: { ...key, params: { other: true } }, run: async () => 'evictor',
    }))

    const replacement = cache.read(cache.declaration({ key, run: () => replacementResult.promise }))
    const listener = vi.fn()
    replacement.subscribe(listener)
    listener.mockClear()

    oldResult.resolve('evicted result')
    await Promise.resolve()
    await Promise.resolve()

    expect(replacement.data).toBeUndefined()
    expect(replacement.state).toBe('loading')
    expect(listener).not.toHaveBeenCalled()
    replacementResult.resolve('current result')
  })
})
