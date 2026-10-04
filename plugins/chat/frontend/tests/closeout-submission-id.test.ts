import { expect, it } from 'vitest'
import type { ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { createReliableChatSubmission } from '../src/adapters/reliable-agent'
import { createChatSubmissionId } from '../src/views/chat-page'

it('routes Chat generated request IDs through the real Agent adapter in Environment grammar', async () => {
  const submissionId = createChatSubmissionId()
  let dispatchedRequestId: string | undefined
  const adapter = createReliableChatSubmission({
    captureSubmissionBinding: () => ({ target: 'canonical:session-1', generation: 1,
      namespace: 'environment-1', principalScope: 'local', schema: 'agent-input/v1',
      mode: 'existing', configOperationIds: [] }),
    captureSubmissionConditions: () => ({ binding: {
      ownerRef: 'native-owner:1', surfaceId: 'native-submit', environment: 'environment-1',
      environmentContextRevision: 'context:1', providerActivation: 'provider:1',
    }, baseRevision: 'native:1', sourceRevision: '1', configOwnerRef: 'config:1' }),
    async forLocation() {},
  }, {
    async submit(capture) {
      dispatchedRequestId = capture.key.requestId
      return { status: 'accepted' }
    },
  })
  const snapshot: ChatSubmissionSnapshot = {
    submissionId,
    target: { kind: 'session', connectionId: 'connection-1', sessionId: 'session-1', contextRevision: 1 },
    draftId: 'draft-1', draftRevision: 2, text: 'prompt', attachmentIds: [], attachmentRefs: [],
  }

  expect(await adapter.capture(snapshot).submit(snapshot)).toEqual({ status: 'accepted' })
  expect(dispatchedRequestId).toBe(submissionId)
  expect(dispatchedRequestId).toMatch(/^[a-z][a-z0-9._-]{0,63}$/)
})
