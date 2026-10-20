import { expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { registerCanonicalModelSelector } from '../src/canonical-selector'

it('the Model Provider contribution adds no hidden configuration/apply guard to Chat send', async () => {
  const chat = createChatContributions()
  const scope = new OwnedResources()
  registerCanonicalModelSelector(chat, scope)
  const snapshot: ChatSubmissionSnapshot = {
    submissionId: 'sub-1', draftId: 'draft-1', draftRevision: 1,
    text: 'hello', attachmentIds: [],
    target: { kind: 'session', connectionId: 'conn', serverInstanceId: 'server',
      sessionId: 'session-uid', harnessId: 'pi', contextRevision: 0 },
  }
  const gateway = { submit: vi.fn().mockResolvedValue({ status: 'accepted' }) }
  expect(await chat.submit(snapshot, gateway, () => true)).toEqual({ status: 'accepted' })
  expect(gateway.submit).toHaveBeenCalledOnce()
  expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()).toHaveLength(1)
  scope.dispose()
})
