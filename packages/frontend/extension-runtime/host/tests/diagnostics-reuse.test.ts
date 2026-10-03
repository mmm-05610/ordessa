/**
 * T009-09 gates: diagnostics reuse the 013 faces — collection is read-only
 * (observe only, never probe/apply), sinks redact, late fragments report
 * honest unknowns under the budget, secrets-dir contents never cross the
 * log, and logs never become the receipt ledger.
 */
import { describe, expect, it } from 'vitest'

import { createLogService, redactValue } from '../src/services/logging'
import { collectDiagnostics } from '../src/services/diagnostics'

function input(overrides: Partial<Parameters<typeof collectDiagnostics>[0]> = {}) {
  return {
    dataRoot: '/tmp/t009-data',
    secretsDir: '/tmp/t009-data/secrets',
    logsDir: '/tmp/t009-data/logs',
    meta: {
      appVersion: '0.1.0', build: 'test', builtAt: '2026-10-04',
      platform: 'linux', productManifestSha256: '0'.repeat(64),
    },
    environment: {},
    ...overrides,
  } as Parameters<typeof collectDiagnostics>[0]
}

describe('T009-09 diagnostics reuse', () => {
  it('collection is read-only: providers observe once, never probe or apply', async () => {
    const calls: string[] = []
    const provider = {
      id: 'observer-only',
      async collect() {
        calls.push('collect') // the ONLY entry the host calls
        return { observed: 'value' }
      },
    }
    const result = await collectDiagnostics(input({ providers: [provider] }))
    expect(calls).toEqual(['collect'])
    expect(JSON.stringify(result.fragments)).toContain('observer-only')
  })

  it('a late/hung fragment reports honest unknown under the budget', async () => {
    const hung = {
      id: 'hung-provider',
      collect: () => new Promise<Record<string, unknown>>(() => undefined), // never settles
    }
    const result = await collectDiagnostics(input({ providers: [hung] }))
    const text = JSON.stringify(result.fragments)
    expect(text).toContain('unknown')
    expect(text).toContain('timeout') // never a fake healthy fragment
  })

  it('sinks redact secret-shaped keys; listed secrets and secrets-dir paths never cross', () => {
    const redacted = redactValue(
      { message: 'x', token: 'sk-SECRET-VALUE', nested: { apiKey: 'k-1' }, home: '/tmp/t009-data/secrets/a' },
      { secretsDir: '/tmp/t009-data/secrets', secrets: ['listed-secret'] },
    )
    const text = JSON.stringify(redacted)
    expect(text).not.toContain('sk-SECRET-VALUE')
    expect(text).not.toContain('k-1')
    expect(text).not.toContain('listed-secret')
    expect(text).not.toContain('/tmp/t009-data/secrets')
  })

  it('logs are not the receipt ledger', async () => {
    const service = createLogService({
      file: '/tmp/t009-data/logs/app.log', secretsDir: '/tmp/t009-data/secrets',
      onUnwritable: () => undefined,
    })
    const keys = Object.keys(service as unknown as Record<string, unknown>)
    expect(keys.length).toBeGreaterThan(0)
    expect(keys.every(key => !/receipt|confirm|verdict|approve/i.test(key))).toBe(true)
  })

  it('diagnostics carry no probe/apply/execute capability names', async () => {
    // the export surface observes; effect verbs would be a contract breach
    const diag = await import('../src/services/diagnostics')
    const names = Object.keys(diag)
    expect(names.length).toBeGreaterThan(0)
    expect(names.every(name => !/probe|apply|execute/i.test(name))).toBe(true)
  })
})
