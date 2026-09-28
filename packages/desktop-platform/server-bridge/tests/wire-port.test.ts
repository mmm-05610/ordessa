/**
 * C-03 — the wire port: three states, no exceptions, no retry, no token.
 *
 * The canary at the bottom is the important one. It injects a known token
 * into the process and then walks everything a PLUGIN can see — the port
 * object, every result, and the error text — asserting the bytes appear in
 * none of them. A port that leaked its credential would still pass every
 * other test in this file.
 */
import { describe, expect, it, vi } from 'vitest'

import {
  AbsentWirePort,
  HttpWirePort,
  PendingWirePort,
  interpret,
  tokenReaderFor,
  type WirePort,
  type WireResult,
} from '../src/wire-port.js'

const ORIGIN = 'http://127.0.0.1:41207'
const CANARY = 'CANARY-TOKEN-BYTES-0123456789abcdef'

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function port(overrides: Partial<ConstructorParameters<typeof HttpWirePort>[0]> = {}): HttpWirePort {
  return new HttpWirePort({
    origin: ORIGIN,
    scope: `${ORIGIN}|server_abc`,
    readToken: async () => CANARY,
    ...overrides,
  })
}

describe('C-03 §3 — the three states', () => {
  it('reports a normal return as Accepted, without echoing the envelope', async () => {
    const fetchImpl = vi.fn(async () => jsonResponse(200, { requestId: 'r1', value: 42 }))
    const result = await port({ fetchImpl: fetchImpl as unknown as typeof fetch }).call('some.method', {})
    expect(result.kind).toBe('Accepted')
    if (result.kind === 'Accepted') {
      expect(result.result).toEqual({ value: 42 })
      // requestId is the envelope, not the payload: it must not appear twice.
      expect(result.result).not.toHaveProperty('requestId')
    }
  })

  it('reports a business refusal as Refused, on HTTP 200 as well as 4xx', async () => {
    const refused = jsonResponse(200, {
      requestId: 'r2',
      error: { code: 'X', message: 'profile is locked', status: 409, retryable: true },
    })
    const result = await port({
      fetchImpl: (async () => refused) as unknown as typeof fetch,
    }).call('some.method', {})
    expect(result).toMatchObject({ kind: 'Refused', reason: 'profile is locked', retryable: true })
  })

  it('marks a non-retryable refusal as such rather than guessing', async () => {
    const result = await port({
      fetchImpl: (async () =>
        jsonResponse(200, { requestId: 'r3', error: { message: 'bad input', retryable: false } })) as unknown as typeof fetch,
    }).call('some.method', {})
    expect(result).toMatchObject({ kind: 'Refused', retryable: false })
  })

  it('never folds a transport failure into a Refused', async () => {
    const result = await port({
      fetchImpl: (async () => {
        throw new Error('ECONNRESET')
      }) as unknown as typeof fetch,
    }).call('some.method', {})
    expect(result).toEqual({ kind: 'Unknown', requestId: expect.any(String), reason: 'result-unknown' })
  })

  it('treats a 5xx as result-unknown, because the call may still have applied', async () => {
    const result = await port({
      fetchImpl: (async () => jsonResponse(500, { requestId: 'r4' })) as unknown as typeof fetch,
    }).call('some.method', {})
    expect(result).toMatchObject({ kind: 'Unknown', reason: 'result-unknown' })
  })

  it('treats an unparsable body as result-unknown rather than inventing a result', async () => {
    const result = await port({
      fetchImpl: (async () => new Response('not json', { status: 200 })) as unknown as typeof fetch,
    }).call('some.method', {})
    expect(result).toMatchObject({ kind: 'Unknown', reason: 'result-unknown' })
  })
})

describe('C-03 §3 — a broken transport is NOT retried', () => {
  it('issues exactly one request, so a mutating call cannot happen twice', async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error('socket hang up')
    })
    await port({ fetchImpl: fetchImpl as unknown as typeof fetch }).call('some.method', { id: 7 })
    expect(fetchImpl).toHaveBeenCalledTimes(1)
  })
})

describe('C-03 §7 — typed reasons', () => {
  it('refuses a method name that could escape the path segment', async () => {
    for (const method of ['', '../../admin', 'a/b', 'has space', 'x'.repeat(200)]) {
      const result = await port().call(method, {})
      expect(result).toMatchObject({ kind: 'Unknown', reason: 'invalid-method' })
    }
  })

  it('answers transport-unreachable when the token cannot be read, and names no path', async () => {
    const result = await port({ readToken: async () => null }).call('some.method', {})
    expect(result).toMatchObject({ kind: 'Unknown', reason: 'transport-unreachable' })
    expect(JSON.stringify(result)).not.toContain('/')
  })

  it('answers transport-unreachable when reading the token throws', async () => {
    const result = await port({
      readToken: async () => {
        throw new Error('EACCES /home/someone/.ordessa/secrets/http-token')
      },
    }).call('some.method', {})
    expect(result).toMatchObject({ kind: 'Unknown', reason: 'transport-unreachable' })
    // The reader's own message must not ride along into a plugin-visible result.
    expect(JSON.stringify(result)).not.toContain('EACCES')
    expect(JSON.stringify(result)).not.toContain('.ordessa')
  })
})

describe('C-03 §5/§6 — the port is never absent, never throwing', () => {
  it('answers host-not-ready from a port that is not ready yet, and queues nothing', async () => {
    const pending: WirePort = new PendingWirePort()
    expect(pending.ready).toBe(false)
    const result = await pending.call('some.method', {})
    expect(result).toMatchObject({ kind: 'Unknown', reason: 'host-not-ready' })
  })

  it('answers port-absent forever from the absent port', async () => {
    const absent: WirePort = new AbsentWirePort()
    expect(absent.ready).toBe(false)
    for (const _attempt of [1, 2, 3]) {
      const result = await absent.call('some.method', {})
      expect(result).toMatchObject({ kind: 'Unknown', reason: 'port-absent' })
    }
  })

  it('never throws out of call(), whatever the transport does', async () => {
    const hostile = port({
      readToken: async () => {
        throw new Error('boom')
      },
      fetchImpl: (async () => {
        throw new Error('boom')
      }) as unknown as typeof fetch,
    })
    await expect(hostile.call('some.method', {})).resolves.toMatchObject({ kind: 'Unknown' })
  })

  it('exposes a scope but no credential on any port', () => {
    const ready = port()
    const absent = new AbsentWirePort('scope-value')
    for (const candidate of [ready, absent, new PendingWirePort()]) {
      expect(Object.keys(candidate)).not.toContain('token')
      expect(Object.keys(candidate)).not.toContain('tokenFile')
      expect(Object.keys(candidate)).not.toContain('origin')
    }
  })
})

describe('C-03 §2 — results are immutable', () => {
  it('freezes every result and its payload', async () => {
    const results: WireResult[] = [
      await port({
        fetchImpl: (async () => jsonResponse(200, { requestId: 'r', a: 1 })) as unknown as typeof fetch,
      }).call('some.method', {}),
      await port({ readToken: async () => null }).call('some.method', {}),
      await new AbsentWirePort().call(),
    ]
    for (const result of results) {
      expect(Object.isFrozen(result)).toBe(true)
      if (result.kind === 'Accepted') expect(Object.isFrozen(result.result)).toBe(true)
    }
  })
})

describe('the bearer is read once per call and never retained', () => {
  it('injects it into the header and stores it nowhere on the port', async () => {
    let seen: string | undefined
    const fetchImpl = vi.fn(async (_url: string, init: RequestInit) => {
      seen = (init.headers as Record<string, string>)['Authorization']
      return jsonResponse(200, { requestId: 'r', ok: true })
    })
    const subject = port({ fetchImpl: fetchImpl as unknown as typeof fetch })
    await subject.call('some.method', {})
    expect(seen).toBe(`Bearer ${CANARY}`)
    expect(JSON.stringify(Object.getOwnPropertyNames(subject))).not.toContain(CANARY)
  })
})

describe('C-03 §4 — THE CANARY: the token reaches no plugin-visible surface', () => {
  it('appears in no result, no port property and no error text', async () => {
    // The port is handed to a plugin; everything reachable from it is
    // plugin-visible. This walks the whole reachable graph.
    const subject = port({
      fetchImpl: (async () => {
        throw new Error(`upstream refused with ${CANARY}`)
      }) as unknown as typeof fetch,
    })
    const surfaces: string[] = [JSON.stringify(Object.getOwnPropertyNames(subject))]
    surfaces.push(JSON.stringify(await subject.call('some.method', {})))
    surfaces.push(JSON.stringify(await port({ readToken: async () => null }).call('some.method', {})))
    surfaces.push(JSON.stringify(await new AbsentWirePort().call()))
    surfaces.push(JSON.stringify(await new PendingWirePort().call()))
    surfaces.push(String(subject.ready))
    surfaces.push(String(subject.scope))
    for (const surface of surfaces) {
      expect(surface).not.toContain(CANARY)
    }
  })

  it('a token reader that fails yields null, never a partial token', async () => {
    const read = tokenReaderFor('/some/root', async () => {
      throw new Error('nope')
    })
    expect(await read()).toBeNull()
  })

  it('refuses a token file carrying control characters rather than cleaning it', async () => {
    const read = tokenReaderFor('/some/root', async () => `${CANARY}\u0000evil`)
    expect(await read()).toBeNull()
  })
})

describe('interpret — the shape decides, not the status code', () => {
  it('reads a 200 refusal as Refused', () => {
    expect(
      interpret('id', 200, { requestId: 'id', error: { message: 'nope', retryable: true } }),
    ).toMatchObject({ kind: 'Refused', reason: 'nope' })
  })

  it('reads a bare 4xx as Refused with a stable reason', () => {
    expect(interpret('id', 404, { requestId: 'id' })).toMatchObject({
      kind: 'Refused',
      reason: 'server-refused',
    })
  })
})
