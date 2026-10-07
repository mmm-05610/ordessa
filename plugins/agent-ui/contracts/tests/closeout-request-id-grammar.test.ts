import { describe, expect, it } from 'vitest'
import type { WireCall } from '../src/owner-port'
import {
  createFrontendSubmissionJournal,
  type FrontendSubmissionCapture,
  type FrontendSubmissionJournalStoragePort,
  type FrontendSubmissionRecord,
} from '../src/frontend-submission-journal'
import { createDurableSubmissionClient } from '../src/durable-submission'

function capture(requestId: string): FrontendSubmissionCapture {
  return {
    key: { namespace: 'environment-1', principalScope: 'local', requestId },
    target: 'canonical:session-1', guarantee: 'reliable', generation: 1,
    binding: { target: 'canonical:session-1', generation: 1, expectedConditions: {
      binding: { ownerRef: 'native-owner:1', surfaceId: 'native-submit',
        environment: 'environment-1', environmentContextRevision: 'context:1',
        providerActivation: 'provider:1' },
      baseRevision: 'native:1', sourceRevision: '1', configOwnerRef: 'config:1',
    } },
    inputSchema: 'agent-input/v1', submissionMode: 'existing',
    draft: { draftId: 'draft-1', draftRevision: 0, text: 'prompt', attachmentIds: [], attachmentRefs: [] },
    configOperationIds: [],
  }
}

describe('durable request ID grammar', () => {
  it.each(['Uppercase-1', '1starts-with-digit', 'has:colon', 'x'.repeat(65)])(
    'refuses a request ID outside the Environment local-ID grammar before journal or wire work',
    async requestId => {
      let transactions = 0
      let wireCalls = 0
      const records = new Map<string, FrontendSubmissionRecord>()
      const storage: FrontendSubmissionJournalStoragePort = {
        async transact(options, operation) {
          transactions += 1
          const result = operation(records.get(options.key))
          if (options.mode === 'readwrite' && result.record) records.set(options.key, result.record)
          return result.value
        },
        async list() { return [...records.values()] },
        close() {},
      }
      const journal = createFrontendSubmissionJournal({ storage })
      const wire: WireCall = async () => {
        wireCalls += 1
        return { kind: 'Accepted', result: { submissionId: requestId, outcome: 'accepted' } }
      }
      const client = createDurableSubmissionClient({ wire, journal })

      const result = await client.submit(capture(requestId))

      expect(result).toMatchObject({ status: 'refused' })
      expect(transactions).toBe(0)
      expect(wireCalls).toBe(0)
      expect(records.size).toBe(0)
      await journal.dispose()
    },
  )

  it('reconciles a legacy key by its original ID without normalizing or redispatching it', async () => {
    const records = new Map<string, FrontendSubmissionRecord>()
    const storage: FrontendSubmissionJournalStoragePort = {
      async transact(options, operation) {
        const result = operation(records.get(options.key))
        if (options.mode === 'readwrite' && result.record) records.set(options.key, result.record)
        return result.value
      },
      async list() { return [...records.values()] },
      close() {},
    }
    const journal = createFrontendSubmissionJournal({ storage })
    const legacy = capture('Legacy-UPPER-1')
    await journal.capture(legacy)
    // Simulate an existing persisted request whose marker committed before
    // interruption; an unmarked captured record is correctly not dispatched.
    await journal.markPossiblySubmitted(legacy.key)
    const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
    const wire: WireCall = async (method, params) => {
      calls.push({ method, params })
      return { kind: 'Accepted', result: {
        submissionId: String(params.submissionId), outcome: 'accepted', resend: false,
      } }
    }
    const client = createDurableSubmissionClient({ wire, journal })

    const result = await client.reconcile(legacy.key)

    expect(result).toMatchObject({ status: 'accepted' })
    expect(calls).toEqual([{
      method: 'agent.submission.query',
      params: { target: legacy.target, submissionId: 'Legacy-UPPER-1' },
    }])
    await journal.dispose()
  })
})
