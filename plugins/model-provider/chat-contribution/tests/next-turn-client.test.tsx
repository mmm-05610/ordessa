// @vitest-environment jsdom
// authored in this line (Z3 T05): consumer-side gates for the next-turn
// client. Red before src/next-turn-client.ts existed.
import { describe, expect, it, vi } from 'vitest'
import {
  CHOOSE_METHOD, TARGET_UNAVAILABLE, TRANSPORT_MISSING,
  createNextTurnClient,
  QUERY_METHOD,
} from '../src/next-turn-client'

const SESSION = { serverInstanceId: 'srv-1', harnessId: 'pi', acpSessionId: 's-9' }
const SESSION_LOCATION = { kind: 'session', session: SESSION } as const
const CHOICE = { harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' }

describe('next-turn client (consumer side)', () => {
  it('refuses without a transport instead of silently no-oping', async () => {
    const client = createNextTurnClient(undefined, SESSION_LOCATION)
    const outcome = await client.queue(CHOICE)
    expect(outcome).toEqual({ state: 'refused', code: TRANSPORT_MISSING })
  })

  it('refuses to queue a draft: there is no native session yet', async () => {
    const invoke = vi.fn()
    const client = createNextTurnClient(invoke, { kind: 'draft', target: undefined })
    const outcome = await client.queue(CHOICE)
    expect(outcome).toEqual({ state: 'refused', code: TARGET_UNAVAILABLE })
    expect(invoke).not.toHaveBeenCalled()
  })

  it('queues through the frozen wire method with the native target', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 3, intentRoute: 'independent' })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    const outcome = await client.queue(CHOICE)
    expect(outcome).toEqual({ state: 'pending-next-turn', sequence: 3 })
    expect(client.pending).toEqual(CHOICE)
    expect(invoke).toHaveBeenCalledWith(CHOOSE_METHOD, {
      target: SESSION,
      choice: { providerConfigId: 'p-1', modelId: 'm1' },
      operationKey: expect.stringMatching(/^chat-queue-s-9-\d+-[a-f0-9-]+$/),
    })
  })

  it('a wire error keeps the draft semantics: refused with the typed code, state untouched', async () => {
    const invoke = vi.fn().mockRejectedValue({
      details: { internalCode: 'SELECTION_UNSUPPORTED' },
    })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    const outcome = await client.queue(CHOICE)
    expect(outcome).toEqual({ state: 'refused', code: 'SELECTION_UNSUPPORTED' })
    expect(client.pending).toBeNull()
  })

  it('an unverifiable answer is unknown-outcome, never applied', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'applied' })  // forged shape
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    const outcome = await client.queue(CHOICE)
    expect(outcome).toEqual({ state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' })
    expect(client.pending).toBeNull()
  })

  it('a late resolution from another session is rejected, state untouched', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 5, intentRoute: 'independent' })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    await client.queue(CHOICE)
    const resolution = { session: { ...SESSION, acpSessionId: 's-OTHER' },
                         sequence: 5, outcome: 'confirmed' }
    expect(client.applyResolution(resolution)).toEqual({ rejected: true })
    expect(client.pending).toEqual(CHOICE)
  })

  it('a late resolution with a stale sequence is rejected', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 5, intentRoute: 'independent' })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    await client.queue(CHOICE)
    const resolution = { session: SESSION, sequence: 4, outcome: 'confirmed' }
    expect(client.applyResolution(resolution)).toEqual({ rejected: true })
    expect(client.pending).toEqual(CHOICE)
  })

  it('the matching resolution applies and clears the pending intent', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 5, intentRoute: 'independent' })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    await client.queue(CHOICE)
    const outcome = client.applyResolution({ session: SESSION, sequence: 5, outcome: 'confirmed' })
    expect(outcome).toEqual({ state: 'pending-next-turn', sequence: 5 })
    expect(client.pending).toBeNull()
  })

  it('rejects missing native identity and foreign harness before making a request', async () => {
    const invoke = vi.fn()
    expect(await createNextTurnClient(invoke, { kind: 'session', session: { ...SESSION, acpSessionId: '' } }).queue(CHOICE))
      .toEqual({ state: 'refused', code: TARGET_UNAVAILABLE })
    expect(await createNextTurnClient(invoke, SESSION_LOCATION).queue({ ...CHOICE, harnessId: 'other' }))
      .toEqual({ state: 'refused', code: 'TARGET_STALE' })
    expect(invoke).not.toHaveBeenCalled()
  })

  it('network uncertainty preserves an already queued choice', async () => {
    const invoke = vi.fn().mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 5, intentRoute: 'independent' })
      .mockRejectedValueOnce(new Error('network offline'))
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    await client.queue(CHOICE)
    expect(await client.queue({ ...CHOICE, modelId: 'other' })).toEqual({ state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' })
    expect(client.pending).toEqual(CHOICE)
  })

  it('discards a late queue acknowledgement after the selected session changes', async () => {
    let current = true, resolve!: (value: unknown) => void
    const invoke = vi.fn(() => new Promise(r => { resolve = r }))
    const client = createNextTurnClient(invoke, SESSION_LOCATION, () => current)
    const outcome = client.queue(CHOICE)
    current = false; resolve({ outcome: 'pending-next-turn', sequence: 5, intentRoute: 'independent' })
    expect(await outcome).toEqual({ state: 'refused', code: 'TARGET_STALE' })
    expect(client.pending).toBeNull()
    expect(client.applyResolution({ session: SESSION, sequence: 5, outcome: 'confirmed' })).toEqual({ rejected: true })
  })

  it('a late acknowledgement of an older click never overrides a newer recorded sequence', async () => {
    // exact-sequence fencing (M12/§6c F2.3): the responses of two clicks may
    // cross on the wire, but the older acknowledgement must not land
    let first: (value: unknown) => void = () => undefined
    const invoke = vi.fn((method: string, params: object) => {
      if (method !== CHOOSE_METHOD) return Promise.resolve()
      const key = (params as { operationKey: string }).operationKey
      return key.includes('-2-') ? Promise.resolve({ outcome: 'pending-next-turn', sequence: 7, intentRoute: 'independent' })
        : new Promise(resolve => { first = resolve })
    })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    const slowQueue = client.queue(CHOICE) // click 1: the response is held
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(await client.queue({ ...CHOICE, modelId: 'other' })).toEqual({ state: 'pending-next-turn', sequence: 7 })
    first({ outcome: 'pending-next-turn', sequence: 5, intentRoute: 'independent' })
    expect(await slowQueue).toEqual({ state: 'unknown-outcome', code: 'OBSERVATION_STALE' })
    expect(client.pending).toEqual({ ...CHOICE, modelId: 'other' }) // the newer pick owns the state
  })

  it('remounted clients do not reuse an idempotency operation key for another choice', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 5, intentRoute: 'independent' })
    await createNextTurnClient(invoke, SESSION_LOCATION).queue(CHOICE)
    await createNextTurnClient(invoke, SESSION_LOCATION).queue({ ...CHOICE, modelId: 'other' })
    expect((invoke.mock.calls[0][1] as { operationKey: string }).operationKey)
      .not.toBe((invoke.mock.calls[1][1] as { operationKey: string }).operationKey)
  })

  it('queries a native target without applying or retrying and ignores unverified confirmation', async () => {
    const invoke = vi.fn().mockResolvedValue({ desired: { providerConfigId: 'p-1', modelId: 'm1' },
      lastConfirmed: { harnessId: 'pi', providerConfigId: 'p-old', modelId: 'm-old', providerConfigVersion: 1 }, revision: 5, intentRoute: 'profile-overlay' })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    expect(await client.query()).toEqual({ state: 'observed', desired: CHOICE, lastConfirmed: null })
    expect(invoke).toHaveBeenCalledExactlyOnceWith(QUERY_METHOD, { target: SESSION })
  })

  it('keeps malformed or late query responses unknown', async () => {
    const invoke = vi.fn().mockResolvedValue({ desired: null })
    expect(await createNextTurnClient(invoke, SESSION_LOCATION).query()).toEqual({ state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' })
    let current = true, resolve!: (value: unknown) => void
    const client = createNextTurnClient(() => new Promise(r => { resolve = r }), SESSION_LOCATION, () => current)
    const query = client.query()
    current = false; resolve({ desired: CHOICE, lastConfirmed: null, revision: 5 })
    expect(await query).toEqual({ state: 'unknown-outcome', code: 'TARGET_STALE' })
    expect(client.pending).toBeNull()
  })
})
