/**
 * T009-08 gates: OS capability handles report selections without granting
 * access; cancel is null (zero-write); absent runtimes are typed
 * unavailable; non-http(s) external opens are refused.
 */
import { describe, expect, it, vi } from 'vitest'

import { createAbsentOsCapabilities, createOsCapabilities, OS_CAPABILITY_CHANNELS } from '../src/os-capabilities'

describe('F4 OS capabilities', () => {
  it('chooseFile reports a user selection and grants NO access right', async () => {
    const invoke = vi.fn(async (channel: string) => {
      if (channel === OS_CAPABILITY_CHANNELS.chooseFile) return { status: 'selected', path: '/tmp/picked.txt' }
      return { status: 'failed' }
    })
    const caps = createOsCapabilities(invoke)
    expect(await caps.chooseFile()).toBe('/tmp/picked.txt')
    // the handle is just a path string — no read/write handle, no token
    expect(invoke).toHaveBeenCalledWith(OS_CAPABILITY_CHANNELS.chooseFile, undefined)
  })

  it('counterexample: cancelled selections are null (zero-write)', async () => {
    const caps = createOsCapabilities(async () => ({ status: 'cancelled' }))
    expect(await caps.chooseFile()).toBeNull()
    expect(await caps.chooseDirectory()).toBeNull()
  })

  it('openExternal refuses non-http(s) urls', async () => {
    const caps = createOsCapabilities(async () => ({ status: 'refused' }))
    expect(await caps.openExternal('file:///etc/passwd')).toBe('unavailable')
  })

  it('counterexample: absent runtime is typed unavailable everywhere', async () => {
    const caps = createAbsentOsCapabilities()
    expect(caps.availability).toEqual({
      chooseFile: 'unavailable', chooseDirectory: 'unavailable',
      clipboardWrite: 'unavailable', openExternal: 'unavailable',
    })
    expect(await caps.chooseFile()).toBeNull()
    expect(await caps.clipboardWrite('x')).toBe('unavailable')
    expect(await caps.openExternal('https://example.com')).toBe('unavailable')
  })

  it('clipboard write reports written or unavailable, never silent', async () => {
    const caps = createOsCapabilities(async () => ({ status: 'written' }))
    expect(await caps.clipboardWrite('text')).toBe('written')
  })
})
