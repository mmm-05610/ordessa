import { describe, expect, it } from 'vitest'
import { createSubmissionConditionsCache } from '../src/capture-conditions'

type LocationBinding = {
  readonly wireScope: string
  readonly generation: string | number
  readonly target: string
}

type ProjectionFacts = LocationBinding & {
  readonly ownerRef: string
  readonly revision: string | number
}

function descriptor(overrides: Record<string, unknown> = {}) {
  return {
    binding: {
      ownerRef: 'native-owner:1',
      surfaceId: 'agent.native-submit',
      environment: 'environment:1',
      environmentContextRevision: 'context:8',
      providerActivation: 'provider:3',
    },
    baseRevision: 'native-base:11',
    sourceRevision: '7',
    configOwnerRef: 'config-owner:1',
    ...overrides,
  }
}

const location: LocationBinding = {
  wireScope: 'wire:1', generation: 4, target: 'canonical:session:1',
}

const projection: ProjectionFacts = {
  ...location, ownerRef: 'config-owner:1', revision: 7,
}

describe('submission conditions cache', () => {
  it('accepts the latest backend descriptor and returns an immutable matching capture', () => {
    const cache = createSubmissionConditionsCache()
    const token = cache.begin('session:1', location)

    expect(cache.complete(token, descriptor())).toBe(true)
    const captured = cache.capture('session:1', projection)

    expect(captured).toEqual(descriptor())
    expect(Object.isFrozen(captured)).toBe(true)
    expect(Object.isFrozen(captured.binding)).toBe(true)
  })

  it('invalidates the previous descriptor as soon as a newer read begins', () => {
    const cache = createSubmissionConditionsCache()
    const first = cache.begin('session:1', location)
    expect(cache.complete(first, descriptor())).toBe(true)

    const latest = cache.begin('session:1', { ...location, generation: 5 })
    expect(() => cache.capture('session:1', projection)).toThrow()
    expect(cache.complete(first, descriptor({ baseRevision: 'stale' }))).toBe(false)
    expect(cache.complete(latest, descriptor({ baseRevision: 'native-base:12' }))).toBe(true)
    expect(cache.capture('session:1', { ...projection, generation: 5 })).toMatchObject({
      baseRevision: 'native-base:12',
    })
  })

  it('refuses a descriptor whose binding or revision fields are incomplete', () => {
    const invalidDescriptors = [
      descriptor({ binding: { ...descriptor().binding, surfaceId: '' } }),
      descriptor({ binding: { ...descriptor().binding, environment: '' } }),
      descriptor({ binding: { ...descriptor().binding, providerActivation: '' } }),
      descriptor({ baseRevision: '' }),
      descriptor({ sourceRevision: '' }),
      descriptor({ configOwnerRef: '' }),
      descriptor({ binding: undefined }),
    ]

    for (const invalid of invalidDescriptors) {
      const cache = createSubmissionConditionsCache()
      const token = cache.begin('session:1', location)
      expect(() => cache.complete(token, invalid)).toThrow()
      expect(() => cache.capture('session:1', projection)).toThrow()
    }
  })

  it('requires the same location, transport, generation, target, config owner and source revision', () => {
    const cache = createSubmissionConditionsCache()
    const token = cache.begin('session:1', location)
    expect(cache.complete(token, descriptor())).toBe(true)

    const mismatches: ProjectionFacts[] = [
      { ...projection, wireScope: 'wire:2' },
      { ...projection, generation: 5 },
      { ...projection, target: 'canonical:session:2' },
      { ...projection, ownerRef: 'config-owner:2' },
      { ...projection, revision: 8 },
    ]
    for (const mismatch of mismatches) {
      expect(() => cache.capture('session:1', mismatch)).toThrow()
    }
    expect(() => cache.capture('session:2', projection)).toThrow()
  })

  it('does not let a late completion restore a cache after invalidation', () => {
    const cache = createSubmissionConditionsCache()
    const token = cache.begin('session:1', location)

    cache.invalidate('session:1')

    expect(cache.complete(token, descriptor())).toBe(false)
    expect(() => cache.capture('session:1', projection)).toThrow()
  })

  it('invalidates one location or the entire cache without affecting completed captures', () => {
    const cache = createSubmissionConditionsCache()
    const first = cache.begin('session:1', location)
    const second = cache.begin('session:2', { ...location, target: 'canonical:session:2' })
    expect(cache.complete(first, descriptor())).toBe(true)
    expect(cache.complete(second, descriptor({
      binding: { ...descriptor().binding, ownerRef: 'native-owner:2' },
      configOwnerRef: 'config-owner:2',
    }))).toBe(true)

    cache.invalidate('session:1')
    expect(() => cache.capture('session:1', projection)).toThrow()
    expect(cache.capture('session:2', {
      ...location, target: 'canonical:session:2', ownerRef: 'config-owner:2', revision: 7,
    })).toMatchObject({ configOwnerRef: 'config-owner:2' })

    cache.invalidate()
    expect(() => cache.capture('session:2', {
      ...location, target: 'canonical:session:2', ownerRef: 'config-owner:2', revision: 7,
    })).toThrow()
  })
})
