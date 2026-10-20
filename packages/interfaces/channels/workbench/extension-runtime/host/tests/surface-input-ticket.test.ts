/**
 * T009-01/06 structural gates: the SurfaceAPI now EXISTS (DRIFT-1 closed)
 * and input tickets carry target/epoch/lease. The former absence pin is
 * replaced by structure assertions — per the test-author's instruction this
 * file must go red if the API shape regresses, never weaken to pass.
 */
import { describe, expect, it } from 'vitest'

import * as surfaceApi from '@ordessa/extension-api/surface'
import { createSurfaceRegistry } from '../src/services/surface'

describe('F1 SurfaceAPI structure (T009-01)', () => {
  it('the contract surface exports the frozen operations and ticket types', () => {
    expect(surfaceApi.StaleTicketError).toBeDefined()
    const registry = createSurfaceRegistry()
    for (const method of ['registerSurface', 'attach'] as const) {
      expect(typeof registry[method]).toBe('function')
    }
  })

  it('input tickets bind target/epoch/lease; stale tickets never write', async () => {
    const registry = createSurfaceRegistry()
    const handle = registry.registerSurface({
      surfaceId: 'surface-1', source: 'sample', executionDomain: 'frontend',
      schemaVersion: 'sample/1', budget: { maxFrameBytes: 4096, maxFrames: 16 },
      capabilities: { raw: true, reliable: false, writable: true },
      unknownKindPolicy: 'raw-degrade',
    })
    const target = { kind: 'terminal', ref: 'term-1', epoch: 2 }
    const attachment = registry.attach('surface-1', target)!
    // a fresh ticket with the right lease/epoch writes
    const ok = await attachment.write({
      target, lease: attachment.lease,
      epoch: 2, sequence: 1, bytes: { kind: 'data', text: 'x' },
    })
    expect(ok.status).toBe('accepted')
    // stale epoch: refused with the typed vocabulary
    await expect(attachment.write({
      target, lease: attachment.lease, epoch: 1, sequence: 2, bytes: { kind: 'data' },
    })).rejects.toThrow(surfaceApi.StaleTicketError)
    handle.detach()
  })

  it('a read-only surface never accepts writes (control requests refused)', async () => {
    const registry = createSurfaceRegistry()
    registry.registerSurface({
      surfaceId: 'readonly-1', source: 'sample', executionDomain: 'frontend',
      schemaVersion: 'sample/1', budget: { maxFrameBytes: 1024, maxFrames: 8 },
      capabilities: { raw: true, reliable: false, writable: false },
      unknownKindPolicy: 'raw-degrade',
    })
    const target = { kind: 'doc', ref: 'doc-1', epoch: 1 }
    const attachment = registry.attach('readonly-1', target)!
    expect((await attachment.write({
      target, lease: attachment.lease, epoch: 1, sequence: 1, bytes: { kind: 'input' },
    })).status).toBe('read-only')
  })

  it('reliable requests on a raw-only surface are typed-refused, never downgraded', async () => {
    const registry = createSurfaceRegistry()
    registry.registerSurface({
      surfaceId: 'raw-1', source: 'sample', executionDomain: 'frontend',
      schemaVersion: 'sample/1', budget: { maxFrameBytes: 1024, maxFrames: 8 },
      capabilities: { raw: true, reliable: false, writable: true },
      unknownKindPolicy: 'raw-degrade',
    })
    const target = { kind: 'doc', ref: 'doc-2', epoch: 1 }
    const attachment = registry.attach('raw-1', target)!
    expect(await attachment.write({
      target, lease: attachment.lease, epoch: 1, sequence: 1,
      bytes: { kind: 'input', reliable: true },
    })).toEqual({ status: 'rejected', reason: 'guarantee-unavailable' })
  })

  it('the F5 stale-generation vocabulary exists for old-epoch refusals', () => {
    const err = new surfaceApi.StaleTicketError({ reason: 'stale-epoch' })
    expect(err.code).toBe('F5_STALE_GENERATION')
    expect(err.details).toEqual({ reason: 'stale-epoch' })
  })
})
