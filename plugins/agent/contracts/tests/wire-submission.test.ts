import { describe, expect, it } from 'vitest'
import type { ChatContentReference, ChatSubmissionSnapshot } from '../../../chat/api/src/contract'
import type { WireCall } from '../src/owner-port'
import { createWireSubmissionClient } from '../src/wire-submission'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(done => { resolve = done })
  return { promise, resolve }
}

const target = 'backend-canonical:session-7'
const location = { kind: 'session' as const, connectionId: 'connection-1', sessionId: 'session-7', contextRevision: 4 }

function chatSnapshot(overrides: Partial<ChatSubmissionSnapshot> = {}): ChatSubmissionSnapshot {
  return {
    submissionId: 'submission-1',
    target: location,
    draftId: 'draft-1',
    draftRevision: 8,
    text: 'captured text',
    attachmentIds: ['item-1'],
    attachmentRefs: ['immutable-content-ref-1' as ChatContentReference],
    ...overrides,
  }
}

describe('Agent wire submission client', () => {
  it('freezes Chat capture and operation IDs before the wire await', async () => {
    const gate = deferred<Awaited<ReturnType<WireCall>>>()
    const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
    const wire: WireCall = async (method, params) => {
      calls.push({ method, params })
      return gate.promise
    }
    const client = createWireSubmissionClient(wire)
    const snapshot = chatSnapshot() as ChatSubmissionSnapshot
    const operationIds = ['operation-model-2']
    const request = {
      target,
      snapshot,
      configOperationIds: operationIds,
      schema: 'agent-input/v1',
      mode: 'existing' as const,
    }

    const pending = client.submit(request)
    ;(snapshot as unknown as { text: string }).text = 'late edit'
    ;(snapshot as unknown as { attachmentRefs: string[] }).attachmentRefs[0] = 'late-reference'
    operationIds[0] = 'late-operation'

    expect(calls).toHaveLength(1)
    expect(calls[0].method).toBe('agent.submitInput')
    expect(calls[0].params).toMatchObject({
      target,
      draftRevision: 8,
      capture: {
        submissionId: 'submission-1',
        draft: {
          draftId: 'draft-1',
          draftRevision: 8,
          text: 'captured text',
          attachmentIds: ['immutable-content-ref-1'],
        },
        configOperationIds: ['operation-model-2'],
        schema: 'agent-input/v1',
        mode: 'existing',
      },
    })
    gate.resolve({ kind: 'Accepted', result: { submissionId: 'submission-1', outcome: 'accepted' } })
    await expect(pending).resolves.toEqual({ status: 'accepted', receipt: {
      submissionId: 'submission-1', outcome: 'accepted',
    } })
  })

  it('keeps unknown on the original ID and exposes query without resubmitting', async () => {
    const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
    const queryFacts = {
      submissionId: 'submission-1', outcome: 'accepted',
      inputAcceptance: { outcome: 'accepted', session: { sessionId: 'native-1' } },
      runResult: { outcome: 'running', runId: 'run-1' },
    }
    const wire: WireCall = async (method, params) => {
      calls.push({ method, params })
      if (method === 'agent.submitInput') {
        return { kind: 'Accepted', result: { submissionId: 'submission-1', outcome: 'unknown', resend: false } }
      }
      if (method === 'agent.submission.query') {
        return { kind: 'Accepted', result: queryFacts }
      }
      return { kind: 'Refused', reason: `unexpected method: ${method}` }
    }
    const client = createWireSubmissionClient(wire)
    const result = await client.submit({
      target, snapshot: chatSnapshot({ attachmentIds: [], attachmentRefs: [] }),
      configOperationIds: ['operation-model-2'], schema: 'agent-input/v1', mode: 'existing',
    })
    expect(result).toEqual({ status: 'unknown', queryHint: 'submission:submission-1', receipt: {
      submissionId: 'submission-1', outcome: 'unknown', resend: false,
    } })

    const query = await client.query(target, 'submission-1')
    expect(query).toMatchObject({ kind: 'ok', value: {
      submissionId: 'submission-1', outcome: 'accepted',
      inputAcceptance: { outcome: 'accepted', session: { sessionId: 'native-1' } },
      runResult: { outcome: 'running', runId: 'run-1' },
    } })
    if (query.kind === 'ok') {
      expect(Object.isFrozen(query.value.inputAcceptance)).toBe(true)
      expect(Object.isFrozen((query.value.inputAcceptance as Record<string, unknown>).session)).toBe(true)
      queryFacts.inputAcceptance.session.sessionId = 'late mutation'
      expect((query.value.inputAcceptance as { session: { sessionId: string } }).session.sessionId).toBe('native-1')
    }
    expect(calls.map(call => call.method)).toEqual(['agent.submitInput', 'agent.submission.query'])
    expect(calls[1].params).toEqual({ target, submissionId: 'submission-1' })
  })

  it('refuses incomplete reliable attachment capture and unsupported mode without raw fallback', async () => {
    const calls: string[] = []
    const wire: WireCall = async method => {
      calls.push(method)
      return { kind: 'Accepted', result: { submissionId: 'submission-1', outcome: 'accepted' } }
    }
    const client = createWireSubmissionClient(wire)
    const attachmentResult = await client.submit({
      target,
      snapshot: chatSnapshot({ attachmentRefs: undefined }),
      configOperationIds: [], schema: 'agent-input/v1', mode: 'existing',
    })
    const modeResult = await client.submit({
      target,
      snapshot: chatSnapshot({ attachmentIds: [], attachmentRefs: [] }),
      configOperationIds: [], schema: 'agent-input/v1', mode: 'raw' as never,
    })

    expect(attachmentResult.status).toBe('refused')
    expect(modeResult.status).toBe('refused')
    expect(calls).toEqual([])
  })

  it('does not convert transport loss or a moved receipt identity into acceptance', async () => {
    const methods: string[] = []
    const wire: WireCall = async (method, params) => {
      methods.push(method)
      if (method !== 'agent.submitInput') return { kind: 'Unknown', reason: 'unavailable' }
      if (params.capture && (params.capture as Record<string, unknown>).submissionId === 'submission-1') {
        throw new Error('reply lost after dispatch')
      }
      return { kind: 'Accepted', result: { submissionId: 'different-submission', outcome: 'accepted' } }
    }
    const client = createWireSubmissionClient(wire)
    const request = {
      target, snapshot: chatSnapshot({ attachmentIds: [], attachmentRefs: [] }),
      configOperationIds: [], schema: 'agent-input/v1', mode: 'existing' as const,
    }

    expect((await client.submit(request)).status).toBe('unknown')
    const moved = await client.submit({ ...request, snapshot: chatSnapshot({
      submissionId: 'submission-2', attachmentIds: [], attachmentRefs: [],
    }) })
    expect(moved.status).toBe('unknown')
    expect(methods).toEqual(['agent.submitInput', 'agent.submitInput'])
  })

  it('treats an unknown query and mismatched queried identity as unknown', async () => {
    let moved = false
    const unknownFacts = {
      submissionId: 'submission-1', outcome: 'unknown', resend: false,
      backend: { state: 'possibly-submitted' }, configApply: { outcome: 'applied', operationIds: ['op-1'] },
    }
    const wire: WireCall = async (_method, params) => ({
      kind: 'Accepted', result: moved
        ? { submissionId: 'another-id', outcome: 'accepted' }
        : unknownFacts,
    })
    const client = createWireSubmissionClient(wire)
    const unknown = await client.query(target, 'submission-1')
    expect(unknown).toMatchObject({ kind: 'unknown', queryHint: 'submission:submission-1',
      observed: { submissionId: 'submission-1', outcome: 'unknown', resend: false,
        backend: { state: 'possibly-submitted' }, configApply: { outcome: 'applied', operationIds: ['op-1'] } } })
    if (unknown.kind === 'unknown' && unknown.observed) {
      expect(Object.isFrozen(unknown.observed.configApply)).toBe(true)
      unknownFacts.configApply.operationIds[0] = 'late mutation'
      expect((unknown.observed.configApply as { operationIds: string[] }).operationIds).toEqual(['op-1'])
    }
    moved = true
    expect(await client.query(target, 'submission-1')).toMatchObject({ kind: 'unknown', queryHint: 'submission:submission-1',
      observed: { submissionId: 'another-id', outcome: 'accepted' } })
  })
})
