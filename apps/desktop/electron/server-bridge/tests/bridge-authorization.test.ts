import type { WirePort, WireResult } from '@ordessa/interface-contracts'
/**
 * T009-03 — bridge authorization semantics that exist today, pinned without
 * faking the parts that do not.
 *
 * The contract (docs/implementation/specifications/026-open-environment-migration/contracts/frontend.md,
 * "Bridge API" paragraph) requires every IPC call to check
 * caller/lease/activation/target/commit and to RE-CHECK revocation after an
 * await. That implementation does not exist in this package — or anywhere the
 * bridge's public seam reaches (extension-host is a thin shell over
 * extension-host) — as of this file: `WirePort.call` encodes only
 * (method, params) and there is no lease/target/activation to revoke. The last
 * describe records that absence explicitly
 * (UNKNOWN-on-T009-03-implementation) instead of asserting a guarantee the
 * tree cannot make.
 *
 * What IS implemented is pinned here:
 * - the three-state result (Accepted/Refused/Unknown) stays discriminated and
 *   is never collapsed;
 * - Unknown is never auto-resent; `retryable` is a reported server fact, not
 *   an instruction (wire-port.ts §3 rules 1 and 2);
 * - AbsentWirePort is a real object answering Unknown/port-absent forever.
 */

import { describe, expect, it, vi } from 'vitest'

import * as serverBridge from '../src/index.js'
import {
  AbsentWirePort,
  HttpWirePort,
  PendingWirePort,
} from '../src/wire-port.js'

const ORIGIN = 'http://127.0.0.1:41207'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

/** A wire/1 success envelope, as `envelope.py:encode_result` emits it. */
function resultEnvelope(result: Record<string, unknown>, id: unknown = 'srv-1'): Response {
  return jsonResponse(200, { jsonrpc: '2.0', id, result })
}

/** A wire/1 error envelope, as `envelope.py:encode_error` emits it. */
function errorEnvelope(error: Record<string, unknown>, status = 200, id: unknown = 'srv-1'): Response {
  return jsonResponse(status, { jsonrpc: '2.0', id, error })
}

function portWith(
  fetchImpl: typeof fetch,
  overrides: Partial<ConstructorParameters<typeof HttpWirePort>[0]> = {},
): HttpWirePort {
  return new HttpWirePort({
    origin: ORIGIN,
    scope: `${ORIGIN}|server_abc`,
    readToken: async () => 'test-token-not-a-credential',
    fetchImpl,
    ...overrides,
  })
}

const keys = (value: object) => Object.keys(value).sort()

/** Compile-time exhaustiveness guard: a fourth state cannot be ignored. */
function assertNever(value: never): never {
  throw new Error(`unexpected wire state: ${JSON.stringify(value)}`)
}

// ---------------------------------------------------------------------------
// Positive: the three states stay discriminated, never collapsed.
// ---------------------------------------------------------------------------

describe('T009-03 §3 — Accepted/Refused/Unknown stay discriminated', () => {
  it('each state carries exactly its own members and lands in exactly one branch', async () => {
    const accepted = await portWith(async () => resultEnvelope({ value: 42 })).call('some.method', {})
    expect(accepted.kind).toBe('Accepted')
    expect(keys(accepted)).toEqual(['kind', 'requestId', 'result'])
    expect(accepted).not.toHaveProperty('reason')
    expect(accepted).not.toHaveProperty('retryable')

    const refused = await portWith(async () =>
      errorEnvelope({ code: 'LOCKED', message: 'profile is locked', details: { retryable: true } }),
    ).call('some.method', {})
    expect(refused.kind).toBe('Refused')
    expect(keys(refused)).toEqual(['kind', 'reason', 'requestId', 'retryable'])
    expect(refused).not.toHaveProperty('result')

    const unknown = await portWith(async () => {
      throw new Error('ECONNRESET')
    }).call('some.method', {})
    expect(unknown.kind).toBe('Unknown')
    expect(keys(unknown)).toEqual(['kind', 'reason', 'requestId'])
    expect(unknown).not.toHaveProperty('result')
    // Unknown is not "a Refused with the retry bit missing": no retryable at all.
    expect(unknown).not.toHaveProperty('retryable')

    const seen: string[] = []
    for (const result of [accepted, refused, unknown] as WireResult[]) {
      switch (result.kind) {
        case 'Accepted': seen.push(`accepted:${String(result.result['value'])}`); break
        case 'Refused': seen.push(`refused:${String(result.retryable)}`); break
        case 'Unknown': seen.push(`unknown:${result.reason}`); break
        default: assertNever(result)
      }
    }
    expect(seen).toEqual(['accepted:42', 'refused:true', 'unknown:result-unknown'])
  })

  it('a dead transport is Unknown/result-unknown even with a readable token, never a disguised success', async () => {
    const result = await portWith(async () => {
      throw new Error('socket hang up')
    }).call('some.method', {})
    expect(result).toEqual({ kind: 'Unknown', requestId: expect.any(String), reason: 'result-unknown' })
    expect((result as { kind: string }).kind).not.toBe('Accepted')
  })

  it('a 200 whose result is a primitive is Unknown rather than a dressed-up Accepted', async () => {
    const result = await portWith(async () => resultEnvelope({})).call('some.method', {})
    expect(result.kind).toBe('Accepted')

    const primitive = await portWith(async () =>
      jsonResponse(200, { jsonrpc: '2.0', id: 'srv-2', result: 42 }),
    ).call('some.method', {})
    expect(primitive).toMatchObject({ kind: 'Unknown', reason: 'result-unknown' })
  })
})

// ---------------------------------------------------------------------------
// Positive/counterexample: Unknown is not retried; `retryable` is a fact only.
// ---------------------------------------------------------------------------

describe('T009-03 §3 — Unknown is never auto-resent; retryable is only reported', () => {
  it('a failing transport is attempted exactly once; an explicit caller retry is a new call with a fresh requestId', async () => {
    // The source comment pins it: "One request id per call, so a caller can
    // correlate its own retry by hand" — the port itself never resends, because
    // a blind resend of a mutating call is how one action happens twice.
    const fetchImpl = vi.fn()
      .mockRejectedValueOnce(new Error('socket hang up'))
      .mockResolvedValueOnce(resultEnvelope({ ok: true }))
    const subject = portWith(fetchImpl as unknown as typeof fetch)

    const first = await subject.call('mutating.method', { id: 7 })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
    expect(first).toMatchObject({ kind: 'Unknown', reason: 'result-unknown' })

    const second = await subject.call('mutating.method', { id: 7 })
    expect(fetchImpl).toHaveBeenCalledTimes(2)
    expect(second.kind).toBe('Accepted')
    // A caller-driven retry correlates itself; the unknown attempt's id is not reused.
    expect(second.requestId).not.toBe(first.requestId)
  })

  it('a 5xx is one attempt and result-unknown, never a retry loop', async () => {
    const fetchImpl = vi.fn(async () =>
      jsonResponse(500, { jsonrpc: '2.0', id: null, error: { code: 'UNAVAILABLE', message: 'nope' } }))
    const result = await portWith(fetchImpl as unknown as typeof fetch).call('some.method', {})
    expect(result).toMatchObject({ kind: 'Unknown', reason: 'result-unknown' })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('Refused(retryable:true) stays one attempt and one Refused; the port does not act on the flag', async () => {
    const fetchImpl = vi.fn(async () =>
      errorEnvelope({ code: 'BUSY', message: 'busy', details: { retryable: true } }))
    const result = await portWith(fetchImpl as unknown as typeof fetch).call('some.method', {})
    expect(result).toEqual({
      kind: 'Refused', requestId: 'srv-1', reason: 'busy', retryable: true,
    })
    expect(result).not.toHaveProperty('result')
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })

  it('a non-retryable refusal reports the fact as false and still performs one attempt', async () => {
    const fetchImpl = vi.fn(async () =>
      errorEnvelope({ code: 'INVALID_REQUEST', message: 'bad input', details: { retryable: false } }))
    const result = await portWith(fetchImpl as unknown as typeof fetch).call('some.method', {})
    expect(result).toMatchObject({ kind: 'Refused', retryable: false })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })
})

// ---------------------------------------------------------------------------
// Counterexample: the absent port is a permanent, real Unknown.
// ---------------------------------------------------------------------------

describe('T009-03 §5/§6 — the absent port is permanently Unknown', () => {
  it('answers Unknown/port-absent on every call, never Accepted/Refused, never throws', async () => {
    const absent: WirePort = new AbsentWirePort()
    expect(absent.ready).toBe(false)
    const kinds = new Set<string>()
    for (let attempt = 0; attempt < 3; attempt += 1) {
      const result = await absent.call('anything.at.all', {})
      expect(result).toEqual({ kind: 'Unknown', requestId: expect.any(String), reason: 'port-absent' })
      expect(result).not.toHaveProperty('result')
      expect(result).not.toHaveProperty('retryable')
      kinds.add(result.kind)
    }
    // Absence is never upgraded into a success or a refusal, no matter how
    // many times a consumer asks.
    expect([...kinds]).toEqual(['Unknown'])
  })

  it('keeps its scope label but exposes no token/origin/fetch surface to reach the Server', () => {
    const scope = `${ORIGIN}|server_abc`
    const absent = new AbsentWirePort(scope)
    expect(absent.scope).toBe(scope)
    expect(absent).not.toHaveProperty('token')
    expect(absent).not.toHaveProperty('origin')
    expect(absent).not.toHaveProperty('readToken')
    expect(Object.getOwnPropertyNames(absent)).toEqual([])
    expect(JSON.stringify(absent)).toBe('{}')
  })

  it('does not collapse into host-not-ready: pending and absent answer different reasons', async () => {
    expect(await new AbsentWirePort().call('m', {})).toMatchObject({ kind: 'Unknown', reason: 'port-absent' })
    const pending: WirePort = new PendingWirePort()
    expect(pending.ready).toBe(false)
    expect(await pending.call('m', {})).toMatchObject({ kind: 'Unknown', reason: 'host-not-ready' })
  })
})

// ---------------------------------------------------------------------------
// Missing condition — await-then-recheck (caller/lease/activation/target).
// ---------------------------------------------------------------------------

describe('T009-03 await-recheck — UNKNOWN on implementation', () => {
  it('UNKNOWN: server-bridge exposes no caller/lease/activation/target re-check surface to pin', () => {
    // docs/implementation/specifications/026-open-environment-migration/contracts/frontend.md requires every
    // IPC call to authorize caller/lease/activation/target/commit and to
    // re-check revocation after an await. No such implementation exists in
    // server-bridge (or in extension-host, a thin shell over
    // extension-host): WirePort encodes (method, params) only, so
    // "await -> revoke -> refuse" cannot be exercised without inventing a
    // private channel. This pin records the absence; T009-03 must replace it
    // with structure assertions when the authorization implementation lands.
    const names = Object.keys(serverBridge)
    const authorizationSurface = names.filter(name =>
      /authoriz|revalidat|recheck|revoke|lease|activation|caller|target/i.test(name))
    expect(authorizationSurface).toEqual([])
    // The shipped call shape carries no authorization envelope to re-check.
    expect(HttpWirePort.prototype.call.length).toBe(2)
    expect(AbsentWirePort.prototype.call.length).toBe(0)
  })
})
