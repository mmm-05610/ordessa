import { describe, expect, it } from 'vitest'
import type { WireCall } from '../src/owner-port'
import {
  createFrontendSubmissionJournal,
  type FrontendSubmissionCapture,
  type FrontendSubmissionJournal,
  type FrontendSubmissionJournalStoragePort,
  type FrontendSubmissionRecord,
  type FrontendSubmissionTransactionOptions,
  type FrontendSubmissionTransactionResult,
} from '../src/frontend-submission-journal'
import { createDurableSubmissionClient } from '../src/durable-submission'

function storage() {
  const records = new Map<string, FrontendSubmissionRecord>()
  let writes = 0
  let failWriteNumber: number | undefined
  const keyOf = (key: FrontendSubmissionCapture['key']) =>
    `${key.namespace}\u0000${key.principalScope}\u0000${key.requestId}`
  const port: FrontendSubmissionJournalStoragePort = {
    async transact<T>(options: FrontendSubmissionTransactionOptions, operation: (current: FrontendSubmissionRecord | undefined) => FrontendSubmissionTransactionResult<T>) {
      const current = records.get(options.key)
      const result = operation(current)
      if (options.mode === 'readwrite') {
        writes += 1
        if (writes === failWriteNumber) throw new Error('controlled durable commit failure')
        if (result.record) records.set(options.key, result.record)
      }
      return result.value
    },
    async list(scope) {
      return [...records.values()].filter(record => record.key.namespace === scope.namespace
        && record.key.principalScope === scope.principalScope)
    },
    close() {},
  }
  return {
    port, records, keyOf,
    failWrite(number: number) { failWriteNumber = number },
  }
}

function capture(overrides: Partial<FrontendSubmissionCapture> = {}): FrontendSubmissionCapture {
  return {
    key: { namespace: 'environment-1', principalScope: 'local', requestId: 'request-1' },
    target: 'backend-canonical:session-1', guarantee: 'reliable', generation: 7,
    binding: {
      target: 'backend-canonical:session-1', generation: 7,
      expectedConditions: {
        binding: {
          ownerRef: 'native-owner:session-1', surfaceId: 'agent.native-submit',
          environment: 'environment-1', environmentContextRevision: 'context:8',
          providerActivation: 'provider:3',
        },
        baseRevision: 'native-base:11', sourceRevision: '7', configOwnerRef: 'config-owner:1',
      },
    },
    inputSchema: 'agent-input/v1', submissionMode: 'existing',
    draft: {
      draftId: 'draft-1', draftRevision: 4, text: 'captured prompt',
      attachmentIds: ['item-1'], attachmentRefs: ['immutable-ref-1'],
    },
    configOperationIds: ['operation-model-2'],
    ...overrides,
  }
}

function harness(options: {
  submit?: (params: Readonly<Record<string, unknown>>) => Awaited<ReturnType<WireCall>> | Promise<Awaited<ReturnType<WireCall>>>
  query?: (params: Readonly<Record<string, unknown>>) => Awaited<ReturnType<WireCall>> | Promise<Awaited<ReturnType<WireCall>>>
  failResultWrite?: boolean
} = {}) {
  const db = storage()
  const base = createFrontendSubmissionJournal({ storage: db.port })
  const events: string[] = []
  const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
  const journal: FrontendSubmissionJournal = {
    async capture(value) { events.push('capture'); return base.capture(value) },
    async markPossiblySubmitted(key) { events.push('marker'); return base.markPossiblySubmitted(key) },
    async recordResult(key, result) {
      events.push('result')
      if (options.failResultWrite) throw new Error('result commit failed after native effect')
      return base.recordResult(key, result)
    },
    get: key => base.get(key),
    list: scope => base.list(scope),
    dispose: () => base.dispose(),
  }
  const wire: WireCall = async (method, params) => {
    events.push(`wire:${method}`)
    calls.push({ method, params })
    if (method === 'agent.submitInput') {
      return options.submit ? options.submit(params) : {
        kind: 'Accepted', result: { submissionId: 'request-1', outcome: 'accepted' },
      }
    }
    if (method === 'agent.submission.query') {
      return options.query ? options.query(params) : {
        kind: 'Accepted', result: {
          submissionId: String(params.submissionId), outcome: 'accepted',
          configApply: { outcome: 'applied', operationIds: ['operation-model-2'] },
          inputAcceptance: { outcome: 'accepted', session: { sessionId: 'native-session-1' } },
          runResult: { outcome: 'running', runId: 'run-1' },
        },
      }
    }
    return { kind: 'Refused', reason: `unexpected wire method: ${method}` }
  }
  return {
    client: createDurableSubmissionClient({ wire, journal }),
    journal, base, db, calls, events,
  }
}

describe('Agent durable submission client', () => {
  it('dispatches the committed journal capture once, after the possibly-submitted marker', async () => {
    const backend = harness()
    const original = capture()
    const pending = backend.client.submit(original)
    ;(original.draft as { text: string }).text = 'late caller mutation'
    ;(original.draft.attachmentRefs as string[])[0] = 'late-ref'
    ;(original.configOperationIds as string[])[0] = 'late-operation'

    const result = await pending

    expect(backend.events).toEqual([
      'capture', 'marker', 'wire:agent.submitInput', 'result',
    ])
    expect(backend.calls.filter(call => call.method === 'agent.submitInput')).toHaveLength(1)
    expect(backend.calls[0].params).toMatchObject({
      target: 'backend-canonical:session-1', draftRevision: 4,
      capture: {
        submissionId: 'request-1',
        draft: { draftId: 'draft-1', text: 'captured prompt', attachmentIds: ['immutable-ref-1'] },
        configOperationIds: ['operation-model-2'], schema: 'agent-input/v1', mode: 'existing',
      },
    })
    expect(result).toMatchObject({ status: 'accepted' })
    expect((await backend.base.get(original.key))?.state).toBe('result-recorded')
    await backend.journal.dispose()
  })

  it('does not dispatch a conflicting same-key capture', async () => {
    const backend = harness()
    await backend.client.submit(capture())

    const conflict = await backend.client.submit(capture({
      draft: { ...capture().draft, text: 'different request content' },
    }))

    expect(conflict).toMatchObject({ status: 'refused' })
    expect(backend.calls.filter(call => call.method === 'agent.submitInput')).toHaveLength(1)
    expect(backend.calls.filter(call => call.method === 'agent.submission.query')).toHaveLength(0)
    await backend.journal.dispose()
  })

  it('refuses incomplete production schema or mode before creating a mapping or calling the wire', async () => {
    const backend = harness()

    const result = await backend.client.submit(capture({ inputSchema: undefined, submissionMode: undefined }))

    expect(result).toMatchObject({ status: 'refused' })
    expect(await backend.base.get(capture().key)).toBeUndefined()
    expect(backend.calls).toEqual([])
    await backend.journal.dispose()
  })

  it('sends no wire request when the possibly-submitted marker cannot commit', async () => {
    const backend = harness()
    backend.db.failWrite(2) // capture commits first; the marker is the second durable write.

    const result = await backend.client.submit(capture())

    expect(result).toMatchObject({ status: 'unknown' })
    expect(backend.calls).toEqual([])
    expect((await backend.base.get(capture().key))?.state).toBe('captured')
    await backend.journal.dispose()
  })

  it('reconciles existing or spent keys by query only and records backend facts', async () => {
    const backend = harness({ submit: async () => ({
      kind: 'Accepted', result: { submissionId: 'request-1', outcome: 'unknown', resend: false },
    }) })
    await backend.client.submit(capture())

    const recovered = await backend.client.submit(capture())

    expect(backend.calls.map(call => call.method)).toEqual([
      'agent.submitInput', 'agent.submission.query',
    ])
    expect(recovered).toMatchObject({ status: 'accepted' })
    const record = await backend.base.get(capture().key)
    expect(record?.state).toBe('result-recorded')
    expect(record?.results[record.results.length - 1]).toMatchObject({ outcome: 'accepted', facts: {
      configApply: { outcome: 'applied', operationIds: ['operation-model-2'] },
      inputAcceptance: { outcome: 'accepted', session: { sessionId: 'native-session-1' } },
      runResult: { outcome: 'running', runId: 'run-1' },
    } })
    await backend.journal.dispose()
  })

  it('returns unavailable for a missing original key without inventing a query identity', async () => {
    const backend = harness()

    const result = await backend.client.reconcile({
      namespace: 'environment-1', principalScope: 'local', requestId: 'missing-request',
    })

    expect(result).toMatchObject({ status: 'unavailable' })
    expect(backend.calls).toEqual([])
    await backend.journal.dispose()
  })

  it('keeps post-effect result-write failure unknown under the original query hint', async () => {
    const backend = harness({ failResultWrite: true })

    const result = await backend.client.submit(capture())

    expect(result).toMatchObject({ status: 'unknown', queryHint: 'submission:request-1' })
    expect(backend.calls.filter(call => call.method === 'agent.submitInput')).toHaveLength(1)
    expect((await backend.base.get(capture().key))?.state).toBe('possibly-submitted')
    await backend.journal.dispose()
  })

  it('does not label an unreceipted wire refusal as known-rejected', async () => {
    const backend = harness({ submit: async () => ({ kind: 'Refused', reason: 'transport refused' }) })

    const result = await backend.client.submit(capture())

    expect(result).toMatchObject({ status: 'unknown', queryHint: 'submission:request-1' })
    const record = await backend.base.get(capture().key)
    expect(record?.results[record.results.length - 1]).toMatchObject({ outcome: 'unknown' })
    await backend.journal.dispose()
  })

  it('lists only the journal scope and never creates an alternate local submission store', async () => {
    const backend = harness()
    await backend.base.capture(capture())
    await backend.base.capture(capture({
      key: { namespace: 'environment-1', principalScope: 'other-principal', requestId: 'request-2' },
    }))

    const rows = await backend.client.list({ namespace: 'environment-1', principalScope: 'local' })

    expect(rows).toHaveLength(1)
    expect(rows[0].key).toEqual({ namespace: 'environment-1', principalScope: 'local', requestId: 'request-1' })
    await backend.journal.dispose()
  })
})
