import { describe, expect, it, vi } from 'vitest'
import { AcpNextSubmitCoordinator, type AcpNextSubmission, type BackendAdmissionState } from '../src/acp-next-submit'
import { WireError } from '../src/wire'

const submission = (): AcpNextSubmission => ({
  submissionId: 'submission-1', nativeSessionId: 'native-1', text: '/literal user text',
  attachments: [{ name: 'brief', uri: 'content://brief', sha256: 'a'.repeat(64) }],
  configurationDigest: 'b'.repeat(64), commandId: 'catalog-command-1',
})
const ready = (): BackendAdmissionState => ({
  connectionId: 'connection-1', nativeSessionId: 'native-1', runtimeGeneration: 7,
  admissionSupported: true, q5Ready: true, chatApiReady: true, outputInProgress: false,
})

describe('backend ACP next-submit request seam', () => {
  it('refuses missing authority and output in progress without calling Server', async () => {
    const call = vi.fn().mockResolvedValue({ kind: 'accepted', submissionId: 'submission-1' })
    const missing = new AcpNextSubmitCoordinator({ call }, () => undefined)
    expect(await missing.submit(submission())).toMatchObject({ kind: 'refused', code: 'CAPABILITY_UNSUPPORTED' })
    for (const state of [
      { ...ready(), admissionSupported: false }, { ...ready(), q5Ready: false },
      { ...ready(), chatApiReady: false }, { ...ready(), outputInProgress: true },
      { ...ready(), nativeSessionId: 'other' },
    ]) {
      const result = await new AcpNextSubmitCoordinator({ call }, () => state).submit(submission())
      expect(result.kind).toBe('refused')
    }
    expect(call).not.toHaveBeenCalled()
  })

  it('sends one frozen snapshot to the exact Server method and keeps slash literal', async () => {
    const calls: { method: string; params: Record<string, unknown> }[] = []
    const wire = { call: async <T>(method: string, params: Record<string, unknown>): Promise<T> => {
      calls.push({ method, params })
      return { kind: 'accepted', submissionId: 'submission-1' } as T
    } }
    const coordinator = new AcpNextSubmitCoordinator(wire, ready)
    const input = submission()
    expect(await coordinator.submit(input)).toEqual({ kind: 'accepted', submissionId: 'submission-1' })
    expect(calls).toHaveLength(1)
    expect(calls[0].method).toBe('acp.submission.authorize')
    expect(calls[0].params.connectionId).toBe('connection-1')
    const sent = calls[0].params.submission as AcpNextSubmission
    expect(sent.text).toBe('/literal user text')
    expect(sent.commandId).toBe('catalog-command-1')
    expect(Object.isFrozen(sent)).toBe(true)
    expect(Object.isFrozen(sent.attachments)).toBe(true)
    expect(Object.isFrozen(sent.attachments[0])).toBe(true)
    ;(input.attachments as unknown as { name: string }[])[0].name = 'changed-after-submit'
    expect(sent.attachments[0].name).toBe('brief')
  })

  it('keeps Unknown after lost answer and reconnect without another wire call', async () => {
    const call = vi.fn().mockRejectedValue(new WireError('UNAVAILABLE', 'connection lost'))
    let state = ready()
    const coordinator = new AcpNextSubmitCoordinator({ call }, () => state)
    expect(await coordinator.submit(submission())).toMatchObject({ kind: 'unknown', operationId: 'submission-1' })
    state = { ...ready(), connectionId: 'connection-after-reconnect' }
    expect(await coordinator.submit(submission())).toMatchObject({ kind: 'unknown', operationId: 'submission-1' })
    expect(call).toHaveBeenCalledTimes(1)
  })

  it('keeps a direct Server refusal typed and never retries the same ID', async () => {
    const call = vi.fn().mockResolvedValue({ kind: 'refused', code: 'AUTHORIZATION_REFUSED', reason: 'denied' })
    const coordinator = new AcpNextSubmitCoordinator({ call }, ready)
    expect(await coordinator.submit(submission())).toEqual({ kind: 'refused', code: 'AUTHORIZATION_REFUSED', reason: 'denied' })
    expect(await coordinator.submit(submission())).toMatchObject({ kind: 'unknown', operationId: 'submission-1' })
    expect(call).toHaveBeenCalledTimes(1)
  })

  it('does not accept a reply for another submission identity', async () => {
    const call = vi.fn().mockResolvedValue({ kind: 'accepted', submissionId: 'somebody-else' })
    const coordinator = new AcpNextSubmitCoordinator({ call }, ready)
    expect(await coordinator.submit(submission())).toMatchObject({ kind: 'unknown', operationId: 'submission-1' })
    expect(await coordinator.submit(submission())).toMatchObject({ kind: 'unknown', operationId: 'submission-1' })
    expect(call).toHaveBeenCalledTimes(1)
  })

  it('preserves the Server operation ID of a real Unknown result', async () => {
    const call = vi.fn().mockResolvedValue({ kind: 'unknown', operationId: 'journal-operation-1',
      reason: 'effect needs reconciliation' })
    const coordinator = new AcpNextSubmitCoordinator({ call }, ready)
    expect(await coordinator.submit(submission())).toEqual({ kind: 'unknown',
      operationId: 'journal-operation-1', reason: 'effect needs reconciliation' })
    expect(call).toHaveBeenCalledTimes(1)
  })

  it('does not turn a mixed refusal and Unknown response into a settled refusal', async () => {
    const call = vi.fn().mockResolvedValue({ kind: 'refused', code: 'AUTHORIZATION_REFUSED',
      reason: 'denied', operationId: 'effect-may-exist' })
    const coordinator = new AcpNextSubmitCoordinator({ call }, ready)
    expect(await coordinator.submit(submission())).toMatchObject({ kind: 'unknown', operationId: 'submission-1' })
    expect(call).toHaveBeenCalledTimes(1)
  })
})
