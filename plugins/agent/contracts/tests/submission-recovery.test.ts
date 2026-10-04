import { expect, it } from 'vitest'
import { createSubmissionRecoveryClient } from '../src/submission-recovery'
import type { FrontendSubmissionJournal, FrontendSubmissionRecord } from '../src/frontend-submission-journal'

it('lists only the current backend-authorized scope even without a live native binding', async () => {
  const seen: unknown[] = []
  const journal = { async list(scope: unknown) { seen.push(scope); return [] } } as unknown as FrontendSubmissionJournal
  const methods: string[] = []
  const recovery = createSubmissionRecoveryClient({ journal, wire: async method => {
    methods.push(method)
    return { kind: 'Accepted', result: { namespace: 'persisted-environment', principalScope: 'local' } }
  } })
  expect(await recovery.list()).toMatchObject({ status: 'available', records: [] })
  expect(seen).toEqual([{ namespace: 'persisted-environment', principalScope: 'local' }])
  expect(methods).toEqual(['agent.submission.scope'])
})

it('does not scan journal records when authorized scope cannot be obtained', async () => {
  let reads = 0
  const journal = { async list() { reads++; return [] } } as unknown as FrontendSubmissionJournal
  const recovery = createSubmissionRecoveryClient({ journal,
    wire: async () => ({ kind: 'Refused', reason: 'connection unavailable' }) })
  expect(await recovery.list()).toMatchObject({ status: 'unavailable' })
  expect(reads).toBe(0)
})

it('queries the exact original record and rejects a different authorized scope', async () => {
  const key = { namespace: 'persisted-environment', principalScope: 'local', requestId: 'original' }
  const record = { key, target: 'old-canonical-target', state: 'possibly-submitted', results: [] } as unknown as FrontendSubmissionRecord
  const methods: Array<{ method: string; params: unknown }> = []
  const journal = { async get() { return record }, async recordResult() { return { status: 'recorded', record } } } as unknown as FrontendSubmissionJournal
  const recovery = createSubmissionRecoveryClient({ journal, wire: async (method, params) => {
    methods.push({ method, params })
    return method === 'agent.submission.scope'
      ? { kind: 'Accepted', result: { namespace: key.namespace, principalScope: key.principalScope } }
      : { kind: 'Accepted', result: { submissionId: 'original', outcome: 'unknown', resend: false } }
  } })
  expect(await recovery.reconcile(key)).toMatchObject({ status: 'unknown' })
  expect(methods.at(-1)).toEqual({ method: 'agent.submission.query', params: { target: 'old-canonical-target', submissionId: 'original' } })
  methods.length = 0
  expect(await recovery.reconcile({ ...key, namespace: 'other-environment' })).toMatchObject({ status: 'unavailable' })
  expect(methods.map(item => item.method)).toEqual(['agent.submission.scope'])
})
