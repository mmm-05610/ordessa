import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  createFrontendSubmissionJournal,
  type FrontendSubmissionCapture,
  type FrontendSubmissionJournalStoragePort,
  type FrontendSubmissionRecord,
  type FrontendSubmissionTransactionOptions,
  type FrontendSubmissionTransactionResult,
} from '../src/frontend-submission-journal'

const capture = (overrides: Partial<FrontendSubmissionCapture> = {}): FrontendSubmissionCapture => ({
  key: { namespace: 'env-install-1', principalScope: 'principal-7', requestId: 'request-1' },
  target: 'agent-target-session-3',
  guarantee: 'reliable',
  generation: 12,
  binding: { ownerRef: 'owner-session-3', bindingRevision: 5 },
  inputSchema: 'agent-input/v1',
  submissionMode: 'existing',
  draft: {
    draftId: 'draft-4', draftRevision: 9, text: 'captured prompt',
    attachmentIds: ['item-1'],
    attachmentRefs: ['immutable-content-ref-1'],
  },
  configOperationIds: ['model-operation-2'],
  ...overrides,
})

/** The injected port exercises the domain protocol. IndexedDB durability and
 * process-kill survival are separate host-level evidence, not claimed here. */
function createControlledStorage() {
  const records = new Map<string, FrontendSubmissionRecord>()
  const transactions: Array<{ mode: string; durability: string }> = []
  let failNextWrite: Error | undefined
  let commitGate: Promise<void> | undefined
  let releaseCommit: (() => void) | undefined
  const port: FrontendSubmissionJournalStoragePort = {
    async transact<T>(options: FrontendSubmissionTransactionOptions, operation: (current: FrontendSubmissionRecord | undefined) => FrontendSubmissionTransactionResult<T>) {
      transactions.push(options)
      const key = options.key
      const current = records.get(key)
      const result = operation(current)
      if (options.mode === 'readwrite') {
        if (failNextWrite) {
          const failure = failNextWrite
          failNextWrite = undefined
          throw failure
        }
        if (commitGate) await commitGate
        if (result.record) records.set(key, result.record)
      }
      return result.value as T
    },
    async list(prefix) {
      return [...records.values()].filter(record => record.key.namespace === prefix.namespace
        && record.key.principalScope === prefix.principalScope)
    },
    close: vi.fn(),
  }
  return {
    port,
    records,
    transactions,
    failWrite(error = new Error('journal commit failed')) { failNextWrite = error },
    holdCommit() {
      commitGate = new Promise<void>(resolve => { releaseCommit = resolve })
    },
    releaseCommit() {
      releaseCommit?.()
      commitGate = undefined
    },
  }
}

function storageKey(value: FrontendSubmissionCapture['key']) {
  return `${value.namespace}\u0000${value.principalScope}\u0000${value.requestId}`
}

describe('Agent frontend persistent submission journal', () => {
  let storage: ReturnType<typeof createControlledStorage>

  beforeEach(() => {
    storage = createControlledStorage()
  })

  it('captures and freezes the exact request before returning from the durable mapping write', async () => {
    const journal = createFrontendSubmissionJournal({ storage: storage.port })
    storage.holdCommit()
    const submitted = capture()
    const pending = journal.capture(submitted)

    await Promise.resolve()
    expect(storage.records.size).toBe(0)
    ;(submitted.draft as { text: string }).text = 'late edit'
    ;(submitted.draft.attachmentRefs as string[])[0] = 'late-ref'
    ;(submitted.configOperationIds as string[])[0] = 'late-op'
    storage.releaseCommit()

    const result = await pending
    expect(result.status).toBe('created')
    expect(result.record.draft.text).toBe('captured prompt')
    expect(result.record.draft.attachmentRefs).toEqual(['immutable-content-ref-1'])
    expect(result.record.configOperationIds).toEqual(['model-operation-2'])
    expect(Object.isFrozen(result.record)).toBe(true)
    expect(Object.isFrozen(result.record.draft)).toBe(true)
    expect(storage.transactions[0]).toMatchObject({ mode: 'readwrite', durability: 'strict' })
    await journal.dispose()
  })

  it('treats identical capture as idempotent and refuses changed content under the same logical key', async () => {
    const journal = createFrontendSubmissionJournal({ storage: storage.port })
    const first = await journal.capture(capture())
    const duplicate = await journal.capture(capture())

    expect(first.status).toBe('created')
    expect(duplicate.status).toBe('existing')
    expect(duplicate.record).toEqual(first.record)
    for (const changed of [
      capture({ target: 'different-canonical-target' }),
      capture({ generation: 13 }),
      capture({ guarantee: 'raw' as 'reliable' }),
      capture({ binding: { ownerRef: 'different-owner', bindingRevision: 5 } }),
      capture({ inputSchema: 'agent-input/v2' }),
      capture({ submissionMode: 'createWithConfig' }),
      capture({ draft: { ...capture().draft, text: 'changed prompt' } }),
      capture({ configOperationIds: ['different-operation'] }),
      capture({ draft: { ...capture().draft, attachmentIds: ['different-item'] } }),
      capture({ draft: { ...capture().draft, attachmentRefs: ['different-immutable-ref'] } }),
    ]) {
      expect((await journal.capture(changed)).status).toBe('conflict')
    }
    expect(storage.records.size).toBe(1)
    await journal.dispose()
  })

  it('grants at most one dispatch claim and withholds it when the marker transaction fails', async () => {
    const journal = createFrontendSubmissionJournal({ storage: storage.port })
    const submitted = capture()
    await journal.capture(submitted)
    const [left, right] = await Promise.all([
      journal.markPossiblySubmitted(submitted.key),
      journal.markPossiblySubmitted(submitted.key),
    ])
    expect([left.status, right.status].filter(status => status === 'dispatch-authorized')).toHaveLength(1)
    expect([left.status, right.status].filter(status => status === 'already-possibly-submitted')).toHaveLength(1)

    const freshStorage = createControlledStorage()
    const other = createFrontendSubmissionJournal({ storage: freshStorage.port })
    await other.capture(capture({ key: { ...submitted.key, requestId: 'request-2' } }))
    freshStorage.failWrite()
    await expect(other.markPossiblySubmitted({ ...submitted.key, requestId: 'request-2' }))
      .rejects.toThrow('journal commit failed')
    expect(freshStorage.records.get(storageKey({ ...submitted.key, requestId: 'request-2' }))?.state).toBe('captured')
    await journal.dispose()
    await other.dispose()
  })

  it('keeps unknown/spent keys query-only across disposal and recovery, with no expiry or delete path', async () => {
    const journal = createFrontendSubmissionJournal({ storage: storage.port })
    const submitted = capture()
    await journal.capture(submitted)
    await journal.markPossiblySubmitted(submitted.key)
    const unknown = await journal.recordResult(submitted.key, {
      outcome: 'unknown', facts: { backend: { state: 'possibly-submitted' } },
    })
    expect(unknown.status).toBe('recorded')
    await journal.dispose()

    const recovered = createFrontendSubmissionJournal({ storage: storage.port })
    const persisted = await recovered.get(submitted.key)
    expect(persisted?.state).toBe('possibly-submitted')
    expect(persisted?.results).toHaveLength(1)
    expect(persisted?.results[0].outcome).toBe('unknown')
    const retry = await recovered.markPossiblySubmitted(submitted.key)
    expect(retry.status).toBe('already-possibly-submitted')
    expect('dispatch-authorized' === retry.status).toBe(false)
    expect(await recovered.list({ namespace: submitted.key.namespace, principalScope: submitted.key.principalScope }))
      .toHaveLength(1)
    expect(recovered).not.toHaveProperty('delete')
    expect(recovered).not.toHaveProperty('clear')
    expect(storage.records.has(storageKey(submitted.key))).toBe(true)
    await recovered.dispose()
  })

  it('appends definitive observations without erasing unknown evidence and never moves back to captured', async () => {
    const journal = createFrontendSubmissionJournal({ storage: storage.port })
    const submitted = capture()
    await journal.capture(submitted)
    await journal.markPossiblySubmitted(submitted.key)
    await journal.recordResult(submitted.key, { outcome: 'unknown', facts: { input: { outcome: 'unknown' } } })
    const accepted = await journal.recordResult(submitted.key, {
      outcome: 'accepted', facts: { input: { outcome: 'accepted', sessionId: 'native-session-1' } },
    })
    expect(accepted.record!.state).toBe('result-recorded')
    expect(accepted.record!.results.map(result => result.outcome)).toEqual(['unknown', 'accepted'])
    expect(Object.isFrozen(accepted.record!.results[1].facts)).toBe(true)
    expect(Object.isFrozen((accepted.record!.results[1].facts as { input: object }).input)).toBe(true)
    expect((await journal.markPossiblySubmitted(submitted.key)).status).toBe('result-recorded')
    await journal.dispose()
  })

  it('isolates namespace and principal while preserving a request ID within each scope', async () => {
    const journal = createFrontendSubmissionJournal({ storage: storage.port })
    const original = capture()
    await journal.capture(original)
    const otherPrincipal = capture({ key: { ...original.key, principalScope: 'principal-8' } })
    const otherNamespace = capture({ key: { ...original.key, namespace: 'env-install-2' } })
    expect((await journal.capture(otherPrincipal)).status).toBe('created')
    expect((await journal.capture(otherNamespace)).status).toBe('created')
    expect(storage.records.size).toBe(3)
    await journal.dispose()
  })

  it('rejects delimiter injection instead of allowing distinct logical keys to collide', async () => {
    const journal = createFrontendSubmissionJournal({ storage: storage.port })
    const firstCollision = capture({
      key: { namespace: 'env\u0000principal', principalScope: 'scope', requestId: 'request' },
    })
    const secondCollision = capture({
      key: { namespace: 'env', principalScope: 'principal\u0000scope', requestId: 'request' },
    })
    const literalSeparator = capture({
      key: { namespace: 'env\\u0000principal', principalScope: 'scope', requestId: 'request' },
    })
    await expect(journal.capture(firstCollision)).rejects.toThrow('reserved key separator')
    await expect(journal.capture(secondCollision)).rejects.toThrow('reserved key separator')
    await expect(journal.capture(literalSeparator)).rejects.toThrow('reserved key separator')
    expect(storage.records.size).toBe(0)
    await journal.dispose()
  })
})
