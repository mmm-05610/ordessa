import { expect, it } from 'vitest'
import type { ChatContentReference } from '@extensions/ordessa.chat-api/contract.js'
import { createReliableChatSubmission } from '../src/adapters/reliable-agent'

it('captures the backend binding and complete draft before asynchronous guards can change them', async () => {
  const operations = ['operation-a', 'operation-b']
  const binding = { target: 'canonical-target', generation: 7, namespace: 'environment',
    principalScope: 'local', schema: 'agent-input/v1', mode: 'existing' as const, configOperationIds: operations }
  const received: unknown[] = []
  const adapter = createReliableChatSubmission({
    captureSubmissionBinding: () => binding,
    captureSubmissionConditions: () => Object.freeze({ binding: Object.freeze({ ownerRef: 'native-owner',
      surfaceId: 'native-submit', environment: 'environment', environmentContextRevision: 'revision-1',
      providerActivation: 'native-provider:1' }), baseRevision: 'native-base-1', sourceRevision: '1', configOwnerRef: 'config-owner' }),
    async forLocation() {},
  }, { async submit(capture) { received.push(capture); return { status: 'accepted' as const } } })
  const snapshot = { submissionId: 'original-request', target: { kind: 'session' as const,
    connectionId: 'connector', sessionId: 'route', contextRevision: 1 }, draftId: 'chat-draft',
    draftRevision: 2, text: 'original text', attachmentIds: ['local-item'], attachmentRefs: ['immutable-ref' as ChatContentReference] }
  const gateway = adapter.capture(snapshot)
  snapshot.text = 'later text'
  snapshot.attachmentRefs[0] = 'later ref' as ChatContentReference
  operations.push('later-operation')
  binding.target = 'later-target'
  expect(await gateway.submit(snapshot)).toEqual({ status: 'accepted' })
  expect(received).toEqual([expect.objectContaining({
    key: { namespace: 'environment', principalScope: 'local', requestId: 'original-request' },
    target: 'canonical-target', guarantee: 'reliable', generation: 7,
    inputSchema: 'agent-input/v1', submissionMode: 'existing',
    draft: { draftId: 'chat-draft', draftRevision: 2, text: 'original text',
      attachmentIds: ['local-item'], attachmentRefs: ['immutable-ref' as ChatContentReference] },
    configOperationIds: ['operation-a', 'operation-b'],
  })])
})

it('refuses an unresolved capability without dispatch or raw facade fallback', async () => {
  let calls = 0
  const adapter = createReliableChatSubmission({
    captureSubmissionBinding() { throw new Error('capability unavailable') },
    captureSubmissionConditions() { throw new Error('conditions unavailable') },
    async forLocation() {},
  }, { async submit() { calls++; return { status: 'accepted' as const } } })
  const snapshot = { submissionId: 'request', target: { kind: 'draft' as const, draftId: 'draft',
    contextRevision: 1 }, draftId: 'draft', draftRevision: 0, text: 'kept', attachmentIds: [] }
  expect(await adapter.capture(snapshot).submit(snapshot)).toEqual({ status: 'refused', reason: 'capability unavailable' })
  expect(calls).toBe(0)
})
