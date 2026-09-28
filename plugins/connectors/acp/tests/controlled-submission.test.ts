import { expect, it } from 'vitest'
import { createHash } from 'node:crypto'
import { AcpClient } from '../src/client'
import type { AcpChannelHandle, AcpChannelSpec } from '../src/channel'
import type { AcpSubmissionAdmission } from '../src/submission'
import type { AcpAttachmentPreparePort, AcpAttachmentTarget, AcpPreparedAttachment } from '../src/attachments'
import { HarnessPeer } from '../../../../tests/acp-connector/fixtures/acp-peer'

const digest = 'a'.repeat(64)

it('next submission uses the same ACP owner and admits attachment/command before prompt', async () => {
  const peer = new HarnessPeer({ capabilities: { promptCapabilities: {} } })
  const decisions: string[] = []
  let outcome: AcpSubmissionAdmission = { kind: 'refused', code: 'AUTHORIZATION_REFUSED', reason: 'no permit' }
  const imageBytes = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64')
  let stored: { target: AcpAttachmentTarget; ref: AcpPreparedAttachment; bytes: Buffer } | undefined
  const attachmentPrepare: AcpAttachmentPreparePort = {
    capabilities: async () => ({ kind: 'available', mimeTypes: ['image/png'], uriSchemes: ['data:'], maxBytes: 1024, maxCount: 1 }),
    prepare: async (target, sourceId) => {
      if (sourceId !== 'picked-image') return { kind: 'refused', reason: 'source absent' }
      const ref = { preparedId: 'prepared-1', name: 'pixel.png', mimeType: 'image/png',
        uri: `data:image/png;base64,${imageBytes.toString('base64')}`,
        sha256: createHash('sha256').update(imageBytes).digest('hex'), byteLength: imageBytes.length }
      stored = { target, ref, bytes: imageBytes }
      return { kind: 'prepared', reference: ref }
    },
    verify: async (target, ref) => stored && JSON.stringify(target) === JSON.stringify(stored.target)
      && JSON.stringify(ref) === JSON.stringify(stored.ref)
      && createHash('sha256').update(stored.bytes).digest('hex') === ref.sha256
      ? { kind: 'verified', reference: stored.ref } : { kind: 'refused', reason: 'unowned or changed' },
    release: async () => { stored = undefined },
  }
  const handle: AcpChannelHandle = {
    connectionId: 'connection-1', binding: { id: 'project-1', normalizedPath: '/private/project' },
    stream: peer.stream, release: async () => { peer.close() },
    subscribeDown: () => () => undefined,
    attachmentPrepare,
    authorizeSubmission: async submission => { decisions.push(submission.submissionId); return outcome },
  }
  const spec: AcpChannelSpec = {
    serverInstanceId: 'server-1', harness: { id: 'pi', title: 'Pi' },
    listProjects: async () => [handle.binding], openProject: async () => handle.binding,
    acquireChannel: async () => handle,
  }
  const client = await AcpClient.connect(spec, 'acp:server-1')
  try {
    await client.openWorkspace('project-1')
    const sessionId = await client.newSession()
    const prepared = await client.prepareAttachment(sessionId, 'picked-image', 'prepare-1')
    const submission = { submissionId: 'submit-1', nativeSessionId: sessionId,
      text: '/literal message', configurationDigest: digest,
      commandId: 'catalog-command-1', attachments: [prepared] }
    await expect(client.sendControlled(sessionId, submission)).rejects.toThrow('AUTHORIZATION_REFUSED')
    expect(peer.recorded('session/prompt')).toHaveLength(0)
    outcome = { kind: 'unknown', operationId: 'operation-1', reason: 'reconcile' }
    await expect(client.sendControlled(sessionId, { ...submission, submissionId: 'submit-2' })).rejects.toThrow('outcome unknown')
    expect(peer.recorded('session/prompt')).toHaveLength(0)
    outcome = { kind: 'accepted', submissionId: 'other-submit' }
    await expect(client.sendControlled(sessionId, { ...submission, submissionId: 'submit-3' })).rejects.toThrow('identity changed')
    expect(peer.recorded('session/prompt')).toHaveLength(0)
    outcome = { kind: 'accepted', submissionId: 'submit-4' }
    await client.sendControlled(sessionId, { ...submission, submissionId: 'submit-4' })
    expect(decisions).toEqual(['submit-1', 'submit-2', 'submit-3', 'submit-4'])
    const prompt = peer.recorded('session/prompt')
    expect(prompt).toHaveLength(1)
    expect(prompt[0].params.prompt).toEqual([
      { type: 'text', text: '/literal message' },
      { type: 'resource_link', name: 'pixel.png', uri: prepared.uri, mimeType: 'image/png' },
    ])
    expect(Buffer.from(prepared.uri.split(',')[1], 'base64')).toEqual(imageBytes)
    await client.releasePreparedAttachment(sessionId, prepared.preparedId)
    expect(stored).toBeUndefined()
  } finally { client.dispose() }
})

it('controlled submission without backend admission refuses before prompt', async () => {
  const peer = new HarnessPeer()
  const handle: AcpChannelHandle = { connectionId: 'connection-2',
    binding: { id: 'project-2', normalizedPath: '/private/project' }, stream: peer.stream,
    release: async () => { peer.close() } }
  const client = await AcpClient.connect({ serverInstanceId: 'server-2',
    harness: { id: 'pi', title: 'Pi' }, listProjects: async () => [handle.binding],
    openProject: async () => handle.binding, acquireChannel: async () => handle }, 'acp:server-2')
  try {
    await client.openWorkspace('project-2')
    const sessionId = await client.newSession()
    await expect(client.sendControlled(sessionId, { submissionId: 'submit-2', nativeSessionId: sessionId,
      text: 'hello', configurationDigest: digest, attachments: [] })).rejects.toThrow('admission unavailable')
    expect(peer.recorded('session/prompt')).toHaveLength(0)
  } finally { client.dispose() }
})

it('execution-time permission answer waits for same-channel backend authorization', async () => {
  const peer = new HarnessPeer()
  let outcome: AcpSubmissionAdmission = { kind: 'refused', code: 'AUTHORIZATION_REFUSED', reason: 'not granted' }
  const seen: string[] = []
  const handle: AcpChannelHandle = { connectionId: 'connection-3',
    binding: { id: 'project-3', normalizedPath: '/private/project' }, stream: peer.stream,
    release: async () => { peer.close() },
    authorizePermission: async decision => { seen.push(decision.interactionId); return outcome },
  }
  const client = await AcpClient.connect({ serverInstanceId: 'server-3',
    harness: { id: 'pi', title: 'Pi' }, listProjects: async () => [handle.binding],
    openProject: async () => handle.binding, acquireChannel: async () => handle }, 'acp:server-3')
  try {
    await client.openWorkspace('project-3')
    const sessionId = await client.newSession()
    let answer: unknown
    peer.queueTurn(async api => {
      answer = await api.permission({ toolCallId: 'tool-1', title: 'run tool', status: 'pending' },
        [{ optionId: 'allow-once', name: 'Allow once', kind: 'allow_once' }])
      return 'end_turn'
    })
    const turn = client.send(sessionId, 'trigger request')
    await peer.waitFor('permission request', () => client.getSnapshot().interactions.length === 1)
    const item = client.getSnapshot().interactions[0]
    await expect(client.respondControlled(item.id, { kind: 'choice', choiceId: 'allow-once' }))
      .rejects.toThrow('AUTHORIZATION_REFUSED')
    expect(item.state).toBe('pending')
    outcome = { kind: 'unknown', operationId: 'pending-1', reason: 'verify' }
    await expect(client.respondControlled(item.id, { kind: 'choice', choiceId: 'allow-once' }))
      .rejects.toThrow('outcome unknown')
    expect(item.state).toBe('pending')
    outcome = { kind: 'accepted', submissionId: item.id }
    await client.respondControlled(item.id, { kind: 'choice', choiceId: 'allow-once' })
    await turn
    expect(seen).toEqual([item.id, item.id, item.id])
    expect(answer).toEqual({ outcome: { outcome: 'selected', optionId: 'allow-once' } })
  } finally { client.dispose() }
})
