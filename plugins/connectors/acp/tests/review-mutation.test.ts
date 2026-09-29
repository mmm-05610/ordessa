import { expect, it } from 'vitest'
import { AcpClient } from '../src/client'
import { HarnessPeer } from '../../../../tests/integration/acp-connector/fixtures/acp-peer'
import type { AcpChannelHandle } from '../src/channel'
import type { AcpSubmissionAdmission } from '../src/submission'
import type { AcpPreparedAttachment } from '../src/attachments'

it('review: ACP prompt must match the payload admitted by backend', async () => {
  const peer = new HarnessPeer()
  let resolveAdmission!: (result: AcpSubmissionAdmission) => void
  let observedText = ''
  const handle: AcpChannelHandle = {
    connectionId: 'c', binding: { id: 'p', normalizedPath: '/private/p' }, stream: peer.stream,
    release: async () => { peer.close() },
    subscribeDown: () => () => undefined,
    authorizeSubmission: async input => {
      observedText = input.text
      return new Promise(resolve => { resolveAdmission = resolve })
    },
  }
  const client = await AcpClient.connect({ serverInstanceId: 's', harness: { id: 'pi', title: 'Pi' },
    listProjects: async () => [handle.binding], openProject: async () => handle.binding,
    acquireChannel: async () => handle }, 'acp:s')
  try {
    await client.openWorkspace('p')
    const sessionId = await client.newSession()
    const submission = { submissionId: 'one', nativeSessionId: sessionId, text: 'A',
      configurationDigest: 'a'.repeat(64), attachments: [] as AcpPreparedAttachment[] }
    const sent = client.sendControlled(sessionId, submission)
    expect(observedText).toBe('A')
    submission.text = 'B'
    resolveAdmission({ kind: 'accepted', submissionId: 'one' })
    await sent
    expect(peer.recorded('session/prompt')[0].params.prompt).toEqual([{ type: 'text', text: 'A' }])
  } finally { client.dispose() }
})

it('review: ACP permission choice must match the option admitted by backend', async () => {
  const peer = new HarnessPeer()
  let resolveAdmission!: (result: AcpSubmissionAdmission) => void
  let observedOption = ''
  const handle: AcpChannelHandle = {
    connectionId: 'c', binding: { id: 'p', normalizedPath: '/private/p' }, stream: peer.stream,
    release: async () => { peer.close() },
    authorizePermission: async decision => {
      observedOption = decision.optionId
      return new Promise(resolve => { resolveAdmission = resolve })
    },
  }
  const client = await AcpClient.connect({ serverInstanceId: 's', harness: { id: 'pi', title: 'Pi' },
    listProjects: async () => [handle.binding], openProject: async () => handle.binding,
    acquireChannel: async () => handle }, 'acp:s')
  try {
    await client.openWorkspace('p')
    const sessionId = await client.newSession()
    let wireAnswer: unknown
    peer.queueTurn(async api => {
      wireAnswer = await api.permission({ toolCallId: 't', title: 'tool', status: 'pending' },
        [{ optionId: 'allow', name: 'Allow', kind: 'allow_once' },
          { optionId: 'deny', name: 'Deny', kind: 'reject_once' }])
      return 'end_turn'
    })
    const turn = client.send(sessionId, 'prompt')
    await peer.waitFor('permission', () => client.getSnapshot().interactions.length === 1)
    const item = client.getSnapshot().interactions[0]
    const answer = { kind: 'choice' as const, choiceId: 'allow' }
    const responding = client.respondControlled(item.id, answer)
    expect(observedOption).toBe('allow')
    answer.choiceId = 'deny'
    resolveAdmission({ kind: 'accepted', submissionId: item.id })
    await responding; await turn
    expect(wireAnswer).toEqual({ outcome: { outcome: 'selected', optionId: 'allow' } })
  } finally { client.dispose() }
})
