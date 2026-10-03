/**
 * T008-01 identity gate: the historical package names resolve to the SAME
 * module objects as the merged runtime (thin shells, one source). A second
 * implementation behind an old name would be the "两套权威" counterexample.
 */
import { describe, expect, it } from 'vitest'

import * as runtimeLoader from '../loader/src/index'
import * as shellLoader from '@ordessa/extension-loader'
import * as runtimeHost from '../host/src/index'
import * as shellHost from '@ordessa/extension-host'

describe('extension-runtime merge identity', () => {
  it('the loader shell re-exports the same bindings as the runtime', () => {
    const runtimeKeys = Object.keys(runtimeLoader).sort()
    const shellKeys = Object.keys(shellLoader).sort()
    expect(shellKeys).toEqual(runtimeKeys)
    for (const key of runtimeKeys) {
      // every exported binding is the same object/function, not a copy
      expect((shellLoader as Record<string, unknown>)[key])
        .toBe((runtimeLoader as Record<string, unknown>)[key])
    }
  })

  it('the host shell re-exports the same bindings as the runtime', () => {
    const runtimeKeys = Object.keys(runtimeHost).sort()
    const shellKeys = Object.keys(shellHost).sort()
    expect(shellKeys).toEqual(runtimeKeys)
    for (const key of runtimeKeys) {
      expect((shellHost as Record<string, unknown>)[key])
        .toBe((runtimeHost as Record<string, unknown>)[key])
    }
  })
})
