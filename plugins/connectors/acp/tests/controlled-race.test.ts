import { expect, it } from 'vitest'
import { AcpClient } from '../src/client'
import type { AcpChannelHandle } from '../src/channel'
import type { AcpControlledSubmission, AcpSubmissionAdmission } from '../src/submission'
import { deferred, HarnessPeer } from '../../../../tests/integration/acp-connector/fixtures/acp-peer'

const digest = 'a'.repeat(64)
const submission = (id: string, nativeSessionId: string): AcpControlledSubmission => ({
  submissionId: id, nativeSessionId, text: id, configurationDigest: digest, attachments: [],
})

async function setup(authorize: (input: AcpControlledSubmission) => Promise<AcpSubmissionAdmission>) {
  const peer = new HarnessPeer()
  let down!: (reason: string) => void
  const handle: AcpChannelHandle = {
    connectionId: 'connection-race', binding: { id: 'project', normalizedPath: '/private/project' },
    stream: peer.stream, authorizeSubmission: authorize,
    subscribeDown: listener => { down = listener; return () => { down = () => undefined } },
    release: async () => { peer.close() },
  }
  const client = await AcpClient.connect({ serverInstanceId: 'server-race',
    harness: { id: 'pi', title: 'Pi' }, listProjects: async () => [handle.binding],
    openProject: async () => handle.binding, acquireChannel: async () => handle }, 'acp:server-race')
  await client.openWorkspace('project')
  const nativeSessionId = await client.newSession()
  return { client, peer, down: (reason: string) => down(reason), nativeSessionId }
}

it('refuses a concurrent controlled submit before a second admission is requested', async () => {
  let settle!: (value: AcpSubmissionAdmission) => void
  let admissions = 0
  const { client, peer, nativeSessionId } = await setup(async input => {
    admissions += 1
    if (admissions > 1) return { kind: 'accepted', submissionId: input.submissionId }
    return new Promise(resolve => { settle = resolve })
  })
  try {
    const first = client.sendControlled(nativeSessionId, submission('first', nativeSessionId))
    await expect(client.sendControlled(nativeSessionId, submission('second', nativeSessionId)))
      .rejects.toThrow(/already pending|already outputting/)
    expect(admissions).toBe(1)
    settle({ kind: 'accepted', submissionId: 'first' })
    await first
    expect(peer.recorded('session/prompt')).toHaveLength(1)
  } finally { client.dispose() }
})

it('never authorizes or prompts twice for one submission identity', async () => {
  let admissions = 0
  const { client, peer, nativeSessionId } = await setup(async input => {
    admissions += 1
    return { kind: 'accepted', submissionId: input.submissionId }
  })
  try {
    await client.sendControlled(nativeSessionId, submission('once', nativeSessionId))
    await expect(client.sendControlled(nativeSessionId, submission('once', nativeSessionId)))
      .rejects.toThrow(/submission identity already used/)
    expect(admissions).toBe(1)
    expect(peer.recorded('session/prompt')).toHaveLength(1)
  } finally { client.dispose() }
})

it('does not reuse an identity after an uncertain backend admission', async () => {
  let admissions = 0
  const { client, peer, nativeSessionId } = await setup(async () => {
    admissions += 1
    return { kind: 'unknown', operationId: 'operation-uncertain', reason: 'reconcile' }
  })
  try {
    await expect(client.sendControlled(nativeSessionId, submission('uncertain', nativeSessionId)))
      .rejects.toThrow('outcome unknown')
    await expect(client.sendControlled(nativeSessionId, submission('uncertain', nativeSessionId)))
      .rejects.toThrow('submission identity already used')
    expect(admissions).toBe(1)
    expect(peer.recorded('session/prompt')).toHaveLength(0)
  } finally { client.dispose() }
})

it('late admission cannot prompt after native session selection changes', async () => {
  let settle!: (value: AcpSubmissionAdmission) => void
  const { client, peer, nativeSessionId } = await setup(async () => new Promise(resolve => { settle = resolve }))
  try {
    const waiting = client.sendControlled(nativeSessionId, submission('stale', nativeSessionId))
    await client.newSession()
    settle({ kind: 'accepted', submissionId: 'stale' })
    await expect(waiting).rejects.toThrow(/session changed/)
    expect(peer.recorded('session/prompt')).toHaveLength(0)
  } finally { client.dispose() }
})

it('late admission cannot prompt after the channel owner reports transport down', async () => {
  let settle!: (value: AcpSubmissionAdmission) => void
  const { client, peer, down, nativeSessionId } = await setup(async () => new Promise(resolve => { settle = resolve }))
  try {
    const waiting = client.sendControlled(nativeSessionId, submission('down', nativeSessionId))
    down('socket lost')
    settle({ kind: 'accepted', submissionId: 'down' })
    await expect(waiting).rejects.toThrow(/channel.*down|owner.*gone/)
    expect(peer.recorded('session/prompt')).toHaveLength(0)
  } finally { client.dispose() }
})

it('late admission cannot prompt over another run started while it awaited authority', async () => {
  let settle!: (value: AcpSubmissionAdmission) => void
  const turnGate = deferred()
  const { client, peer, nativeSessionId } = await setup(async () => new Promise(resolve => { settle = resolve }))
  try {
    const waiting = client.sendControlled(nativeSessionId, submission('old', nativeSessionId))
    peer.queueTurn(async () => { await turnGate.promise; return 'end_turn' })
    const running = client.send(nativeSessionId, 'legacy turn')
    settle({ kind: 'accepted', submissionId: 'old' })
    await expect(waiting).rejects.toThrow(/already outputting/)
    expect(peer.recorded('session/prompt')).toHaveLength(1)
    turnGate.resolve(); await running
  } finally { turnGate.resolve(); client.dispose() }
})
