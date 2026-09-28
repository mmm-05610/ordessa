// The Settings region may only render what `sandbox.describe@1` reports: this
// suite pins the TypeScript mirror of the wire DTO and proves the menu filter
// is "supported only" (matrix.py CellStatus + describe.py options_for_ui()),
// so an unproven cell can never be clicked into existence.
import { describe, expect, it } from 'vitest'
import {
  SANDBOX_DESCRIBE_API_VERSION,
  SANDBOX_STABLE_ERROR_CODES,
  sandboxMenuOptions,
  type SandboxDescribeResult,
  type SandboxOption,
} from '../src/contract'
import { codexDescribe, describeResult, option } from './fixtures'

describe('sandbox describe TypeScript mirror (FR-05)', () => {
  it('names the api version the backend answers with', () => {
    expect(SANDBOX_DESCRIBE_API_VERSION).toBe('sandbox.describe@1')
    expect(describeResult({}).apiVersion).toBe(SANDBOX_DESCRIBE_API_VERSION)
  })

  it('carries the six stable sandbox refusal codes, unique and unmutable', () => {
    expect(new Set(SANDBOX_STABLE_ERROR_CODES).size).toBe(6)
    expect([...SANDBOX_STABLE_ERROR_CODES].sort()).toEqual([
      'PROVIDER_BUSY',
      'SANDBOX_CONFIG_CONFLICT',
      'SANDBOX_COVERAGE_UNPROVEN',
      'SANDBOX_EFFECT_UNKNOWN',
      'SANDBOX_NATIVE_UNSUPPORTED',
      'SANDBOX_PLATFORM_UNSUPPORTED',
    ])
    expect(Object.isFrozen(SANDBOX_STABLE_ERROR_CODES)).toBe(true)
  })

  it('an option mirrors source / platform / coverage / status / lockedByAdministrator', () => {
    const sample: SandboxOption = option({
      optionId: 'sandbox_mode=read-only', status: 'supported',
      source: 'pinned vocabulary (posture_config._SANDBOX_STRICTNESS)',
      platforms: ['linux', 'macos', 'windows'], coverage: ['bash', 'read', 'edit'],
      lockedByAdministrator: true,
    })
    expect(sample).toMatchObject({
      source: expect.any(String), platforms: ['linux', 'macos', 'windows'],
      coverage: ['bash', 'read', 'edit'], status: 'supported', lockedByAdministrator: true,
    })
  })
})

describe('the menu comes from describe evidence only (FR-06)', () => {
  it('offers only supported options; unsupported and unknown stay out of the menu', () => {
    const result: SandboxDescribeResult = codexDescribe()
    expect(result.options.map(o => o.optionId)).toEqual([
      'sandbox_mode=read-only', 'sandbox_mode=workspace-write', 'sandbox_mode=danger-full-access',
    ])
    expect(sandboxMenuOptions(result).map(o => o.optionId)).toEqual([
      'sandbox_mode=read-only', 'sandbox_mode=workspace-write',
    ])
  })

  it('an unknown-pin describe yields an empty menu: no default list is ever invented', () => {
    const empty: SandboxDescribeResult = describeResult({ status: 'unknown', options: [] })
    expect(sandboxMenuOptions(empty)).toEqual([])
    expect(empty.options).toEqual([])
  })
})
