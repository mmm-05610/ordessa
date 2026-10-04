import { describe, expect, it } from 'vitest'
import type { WireCall } from '../src/owner-port'
import {
  createFrontendSubmissionJournal,
  type FrontendSubmissionCapture,
  type FrontendSubmissionJournalStoragePort,
  type FrontendSubmissionRecord,
} from '../src/frontend-submission-journal'
import { createDurableSubmissionClient } from '../src/durable-submission'

function conditions(overrides: Record<string, unknown> = {}) {
  return {
    binding: {
      ownerRef: 'native-owner:session-1', surfaceId: 'agent.native-submit',
      environment: 'environment-1', environmentContextRevision: 'context:8',
      providerActivation: 'provider:3',
    },
    baseRevision: 'native-base:11', sourceRevision: '7', configOwnerRef: 'config-owner:1',
    ...overrides,
  }
}

function capture(overrides: Partial<FrontendSubmissionCapture> = {}): FrontendSubmissionCapture {
  return {
    key: { namespace: 'environment-1', principalScope: 'local', requestId: 'request-conditions-1' },
    target: 'canonical:session-1', guarantee: 'reliable', generation: 7,
    binding: {
      target: 'canonical:session-1', generation: 7,
      expectedConditions: conditions(),
    },
    inputSchema: 'agent-input/v1', submissionMode: 'existing',
    draft: {
      draftId: 'draft-1', draftRevision: 4, text: 'captured prompt',
      attachmentIds: [], attachmentRefs: [],
    },
    configOperationIds: [],
    ...overrides,
  }
}

function fixture() {
  const records = new Map<string, FrontendSubmissionRecord>()
  const keyOf = (key: FrontendSubmissionCapture['key']) =>
    `${key.namespace}\u0000${key.principalScope}\u0000${key.requestId}`
  const storage: FrontendSubmissionJournalStoragePort = {
    async transact(options, operation) {
      const result = operation(records.get(options.key))
      if (options.mode === 'readwrite' && result.record) records.set(options.key, result.record)
      return result.value
    },
    async list(scope) {
      return [...records.values()].filter(record => record.key.namespace === scope.namespace
        && record.key.principalScope === scope.principalScope)
    },
    close() {},
  }
  const journal = createFrontendSubmissionJournal({ storage })
  const calls: Array<{ method: string; params: Readonly<Record<string, unknown>> }> = []
  const wire: WireCall = async (method, params) => {
    calls.push({ method, params })
    if (method === 'agent.submission.query') {
      return { kind: 'Accepted', result: {
        submissionId: String(params.submissionId), outcome: 'unknown', resend: false,
      } }
    }
    return { kind: 'Accepted', result: {
      submissionId: 'request-conditions-1', outcome: 'accepted',
    } }
  }
  const client = createDurableSubmissionClient({ wire, journal })
  return { client, journal, calls, keyOf }
}

describe('durable submission expected conditions guard', () => {
  it('refuses missing conditions before writing a journal mapping or calling the wire', async () => {
    const backend = fixture()
    const value = capture({ binding: undefined })

    const result = await backend.client.submit(value)

    expect(result).toMatchObject({ status: 'refused' })
    expect(await backend.journal.get(value.key)).toBeUndefined()
    expect(backend.calls).toEqual([])
    await backend.journal.dispose()
  })

  it.each([
    ['missing binding field', conditions({ binding: { ownerRef: 'native-owner:session-1' } })],
    ['missing base revision', conditions({ baseRevision: '' })],
    ['missing source revision', conditions({ sourceRevision: '' })],
    ['missing config owner', conditions({ configOwnerRef: '' })],
  ])('refuses a partial descriptor (%s) before journal or wire effects', async (_label, expectedConditions) => {
    const backend = fixture()
    const value = capture({ binding: {
      ...capture().binding,
      expectedConditions,
    } })

    const result = await backend.client.submit(value)

    expect(result).toMatchObject({ status: 'refused' })
    expect(await backend.journal.get(value.key)).toBeUndefined()
    expect(backend.calls).toEqual([])
    await backend.journal.dispose()
  })

  it.each([
    ['target', { target: 'canonical:other-session' }],
    ['generation', { generation: 8 }],
  ])('refuses conditions captured for a different %s before journaling', async (_label, mismatch) => {
    const backend = fixture()
    const value = capture({ binding: {
      ...capture().binding,
      ...mismatch,
    } })

    const result = await backend.client.submit(value)

    expect(result).toMatchObject({ status: 'refused' })
    expect(await backend.journal.get(value.key)).toBeUndefined()
    expect(backend.calls).toEqual([])
    await backend.journal.dispose()
  })

  it('requires the native conditions environment to match the durable key namespace', async () => {
    const backend = fixture()
    const value = capture({ binding: {
      ...capture().binding,
      expectedConditions: conditions({
        binding: { ...conditions().binding, environment: 'environment-other' },
      }),
    } })

    const result = await backend.client.submit(value)

    expect(result).toMatchObject({ status: 'refused' })
    expect(await backend.journal.get(value.key)).toBeUndefined()
    expect(backend.calls).toEqual([])
    await backend.journal.dispose()
  })

  it('forwards only the frozen journal conditions into the one wire submission', async () => {
    const backend = fixture()
    const original = capture()
    const pending = backend.client.submit(original)
    const expected = original.binding?.expectedConditions
    ;(original.binding as { target: string }).target = 'mutated-target'
    ;(expected as { baseRevision: string }).baseRevision = 'mutated-base'

    const result = await pending

    expect(result).toMatchObject({ status: 'accepted' })
    expect(backend.calls.map(call => call.method)).toEqual(['agent.submitInput'])
    expect(backend.calls[0].params.capture).toMatchObject({ expectedConditions: conditions() })
    await backend.journal.dispose()
  })

  it('continues querying a preconditions legacy record without adding a new dispatch', async () => {
    const backend = fixture()
    const legacy = capture({ binding: undefined })
    await backend.journal.capture(legacy)

    const result = await backend.client.reconcile(legacy.key)

    expect(result).toMatchObject({ status: 'unknown', queryHint: 'submission:request-conditions-1' })
    expect(backend.calls.map(call => call.method)).toEqual(['agent.submission.query'])
    await backend.journal.dispose()
  })
})
