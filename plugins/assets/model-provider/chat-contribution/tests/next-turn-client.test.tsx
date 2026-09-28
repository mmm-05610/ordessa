// @vitest-environment jsdom
// authored in this line (Z3 T05): consumer-side gates for the next-turn
// client. Red before src/next-turn-client.ts existed.
import { describe, expect, it, vi } from 'vitest'
import {
  CHOOSE_METHOD, TARGET_UNAVAILABLE, TRANSPORT_MISSING,
  createNextTurnClient,
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
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 3 })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    const outcome = await client.queue(CHOICE)
    expect(outcome).toEqual({ state: 'pending-next-turn', sequence: 3 })
    expect(client.pending).toEqual(CHOICE)
    expect(invoke).toHaveBeenCalledWith(CHOOSE_METHOD, {
      target: SESSION,
      choice: { providerConfigId: 'p-1', modelId: 'm1' },
      operationKey: expect.stringMatching(/^chat-queue-s-9-\d+$/),
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
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 5 })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    await client.queue(CHOICE)
    const resolution = { session: { ...SESSION, acpSessionId: 's-OTHER' },
                         sequence: 5, outcome: 'confirmed' }
    expect(client.applyResolution(resolution)).toEqual({ rejected: true })
    expect(client.pending).toEqual(CHOICE)
  })

  it('a late resolution with a stale sequence is rejected', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 5 })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    await client.queue(CHOICE)
    const resolution = { session: SESSION, sequence: 4, outcome: 'confirmed' }
    expect(client.applyResolution(resolution)).toEqual({ rejected: true })
    expect(client.pending).toEqual(CHOICE)
  })

  it('the matching resolution applies and clears the pending intent', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'pending-next-turn', sequence: 5 })
    const client = createNextTurnClient(invoke, SESSION_LOCATION)
    await client.queue(CHOICE)
    const outcome = client.applyResolution({ session: SESSION, sequence: 5, outcome: 'confirmed' })
    expect(outcome).toEqual({ state: 'pending-next-turn', sequence: 5 })
    expect(client.pending).toBeNull()
  })
})
