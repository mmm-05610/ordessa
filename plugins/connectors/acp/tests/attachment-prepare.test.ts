import { createHash } from 'node:crypto'
import { expect, it } from 'vitest'
import { AcpClient } from '../src/client'
import type { AcpChannelHandle, AcpChannelSpec } from '../src/channel'
import type { AcpAttachmentCapabilities, AcpAttachmentPreparePort, AcpAttachmentTarget,
  AcpPreparedAttachment } from '../src/attachments'
import { HarnessPeer } from '../../../../tests/integration/acp-connector/fixtures/acp-peer'

const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64')
const digest = createHash('sha256').update(image).digest('hex')

async function fixture(withPort = true, connectionId = 'connection-1', injectedPort?: AcpAttachmentPreparePort) {
  const peer = new HarnessPeer()
  let caps: AcpAttachmentCapabilities = { kind: 'available', mimeTypes: ['image/png'], uriSchemes: ['data:'], maxBytes: 1024, maxCount: 1 }
  let now = 0, expiry = 10
  let stored: { target: AcpAttachmentTarget; ref: AcpPreparedAttachment } | undefined
  let admissionCalls = 0
  const port: AcpAttachmentPreparePort = {
    capabilities: async () => caps,
    prepare: async (target, sourceId) => {
      if (sourceId === 'unknown') return { kind: 'unknown', operationId: 'prepare-unknown' }
      if (sourceId !== 'owned-image') return { kind: 'refused', reason: 'source not owned' }
      const ref: AcpPreparedAttachment = { preparedId: 'prepared-image', name: 'pixel.png',
        uri: `data:image/png;base64,${image.toString('base64')}`, mimeType: 'image/png',
        sha256: digest, byteLength: image.length }
      stored = { target, ref }
      return { kind: 'prepared', reference: ref }
    },
    verify: async (target, reference) => stored && now < expiry
      && JSON.stringify(target) === JSON.stringify(stored.target)
      && JSON.stringify(reference) === JSON.stringify(stored.ref)
      && createHash('sha256').update(image).digest('hex') === reference.sha256
      ? { kind: 'verified', reference: stored.ref } : { kind: 'refused', reason: 'unowned, expired or changed' },
    release: async () => { stored = undefined },
  }
  const handle: AcpChannelHandle = { connectionId,
    binding: { id: 'project-1', normalizedPath: '/project' }, stream: peer.stream,
    subscribeDown: () => () => undefined,
    ...(withPort ? { attachmentPrepare: injectedPort ?? port } : {}),
    authorizeSubmission: async submission => { admissionCalls++; return { kind: 'accepted', submissionId: submission.submissionId } },
    release: async () => { peer.close() } }
  const spec: AcpChannelSpec = { serverInstanceId: 'server-1', harness: { id: 'pi', title: 'Pi' },
    listProjects: async () => [handle.binding], openProject: async () => handle.binding,
    acquireChannel: async () => handle }
  const client = await AcpClient.connect(spec, 'acp:server-1')
  await client.openWorkspace('project-1')
  const sessionId = await client.newSession()
  const send = (reference: AcpPreparedAttachment, submissionId: string) => client.sendControlled(sessionId,
    { submissionId, nativeSessionId: sessionId, text: 'image', configurationDigest: 'a'.repeat(64), attachments: [reference] })
  return { peer, client, sessionId, send, port, handle, setCaps: (value: AcpAttachmentCapabilities) => { caps = value },
    expire: () => { now = expiry }, getAdmissionCalls: () => admissionCalls }
}

it('requires an owner preparation port and known capability before any attachment admission', async () => {
  const absent = await fixture(false)
  const forged: AcpPreparedAttachment = { preparedId: 'forged', name: 'pixel.png', uri: 'data:image/png;base64,AA==',
    mimeType: 'image/png', sha256: digest, byteLength: 1 }
  await expect(absent.send(forged, 'submit-absent')).rejects.toThrow(/preparation owner unavailable/)
  expect(absent.peer.recorded('session/prompt')).toEqual([])
  expect(absent.getAdmissionCalls()).toBe(0)
  absent.client.dispose()

  const unknown = await fixture()
  unknown.setCaps({ kind: 'unknown', reason: 'owner unavailable' })
  await expect(unknown.client.prepareAttachment(unknown.sessionId, 'owned-image', 'prepare-1')).rejects.toThrow(/capability unknown/)
  await expect(unknown.send(forged, 'submit-unknown')).rejects.toThrow(/capability unavailable/)
  expect(unknown.peer.recorded('session/prompt')).toEqual([])
  expect(unknown.getAdmissionCalls()).toBe(0)
  unknown.client.dispose()
})

it('rejects a data URI when the owner capability allows only https', async () => {
  const owner = await fixture()
  const ref = await owner.client.prepareAttachment(owner.sessionId, 'owned-image', 'prepare-data')
  owner.setCaps({ kind: 'available', mimeTypes: ['image/png'], uriSchemes: ['https:'], maxBytes: 1024, maxCount: 1 })
  await expect(owner.send(ref, 'submit-wrong-scheme')).rejects.toThrow(/reference invalid or unsupported/)
  expect(owner.getAdmissionCalls()).toBe(0)
  expect(owner.peer.recorded('session/prompt')).toEqual([])
  owner.client.dispose()
})

it('refuses forged, expired, cross-connection and file URI references before admission', async () => {
  const one = await fixture()
  const ref = await one.client.prepareAttachment(one.sessionId, 'owned-image', 'prepare-1')
  await expect(one.send({ ...ref, sha256: 'b'.repeat(64) }, 'submit-forged')).rejects.toThrow(/ownership or content changed/)
  await expect(one.send({ ...ref, uri: 'file:///remote/secret.png' }, 'submit-path')).rejects.toThrow(/reference invalid/)
  one.expire()
  await expect(one.send(ref, 'submit-expired')).rejects.toThrow(/ownership or content changed/)
  expect(one.peer.recorded('session/prompt')).toEqual([])
  expect(one.getAdmissionCalls()).toBe(0)
  one.client.dispose()

  const two = await fixture(true, 'connection-2', one.port)
  await expect(two.send(ref, 'submit-cross-connection')).rejects.toThrow(/ownership or content changed/)
  expect(two.peer.recorded('session/prompt')).toEqual([])
  expect(two.getAdmissionCalls()).toBe(0)
  two.client.dispose()
})

it('treats malformed owner capabilities and down-during-prepare as unavailable', async () => {
  const malformed = await fixture()
  for (const bad of [
    { kind: 'available', mimeTypes: ['image/png'], uriSchemes: ['data:'], maxBytes: true, maxCount: 1 },
    { kind: 'available', mimeTypes: [], uriSchemes: ['data:'], maxBytes: 1024, maxCount: 1 },
    { kind: 'available', mimeTypes: ['image/png'], uriSchemes: ['data:'], maxBytes: 1024, maxCount: 0 },
    { kind: 'available', mimeTypes: ['image/png'], uriSchemes: ['file:'], maxBytes: 1024, maxCount: 1 },
  ]) {
    malformed.setCaps(bad as unknown as AcpAttachmentCapabilities)
    expect(await malformed.client.attachmentCapabilities(malformed.sessionId)).toMatchObject({ kind: 'unknown' })
    await expect(malformed.client.prepareAttachment(malformed.sessionId, 'owned-image', 'bad-cap'))
      .rejects.toThrow(/capability unknown/)
  }
  expect(malformed.getAdmissionCalls()).toBe(0)
  malformed.client.dispose()

  const pending = await fixture()
  let released = false
  pending.port.release = async () => { released = true }
  let finish!: (value: Awaited<ReturnType<AcpAttachmentPreparePort['prepare']>>) => void
  pending.port.prepare = async () => await new Promise(resolve => { finish = resolve })
  const underway = pending.client.prepareAttachment(pending.sessionId, 'owned-image', 'prepare-down')
  // Let the capability read finish and the prepare call begin, then drop the owner.
  await new Promise(resolve => setTimeout(resolve, 0))
  pending.client.dispose()
  finish({ kind: 'prepared', reference: { preparedId: 'late', name: 'pixel.png',
    uri: 'data:image/png;base64,AA==', mimeType: 'image/png', sha256: digest, byteLength: 1 } })
  await expect(underway).rejects.toThrow(/owner changed/)
  expect(released).toBe(true)
  expect(pending.peer.recorded('session/prompt')).toEqual([])
  expect(pending.getAdmissionCalls()).toBe(0)
})

it('does not spend admission when the channel closes during attachment verification', async () => {
  const pending = await fixture()
  const ref = await pending.client.prepareAttachment(pending.sessionId, 'owned-image', 'prepare-verify-race')
  let finish!: (value: Awaited<ReturnType<AcpAttachmentPreparePort['verify']>>) => void
  pending.port.verify = async () => await new Promise(resolve => { finish = resolve })
  const send = pending.send(ref, 'submit-verify-race')
  await new Promise(resolve => setTimeout(resolve, 0))
  pending.client.dispose()
  finish({ kind: 'verified', reference: ref })
  await expect(send).rejects.toThrow(/owner changed/)
  expect(pending.getAdmissionCalls()).toBe(0)
  expect(pending.peer.recorded('session/prompt')).toEqual([])
})

it('does not spend admission after session selection changes during verification', async () => {
  const pending = await fixture()
  const ref = await pending.client.prepareAttachment(pending.sessionId, 'owned-image', 'prepare-switch')
  let finish!: (value: Awaited<ReturnType<AcpAttachmentPreparePort['verify']>>) => void
  pending.port.verify = async () => await new Promise(resolve => { finish = resolve })
  const send = pending.send(ref, 'submit-switch')
  await new Promise(resolve => setTimeout(resolve, 0))
  const otherSession = await pending.client.newSession()
  expect(otherSession).not.toBe(pending.sessionId)
  finish({ kind: 'verified', reference: ref })
  await expect(send).rejects.toThrow(/owner changed/)
  expect(pending.getAdmissionCalls()).toBe(0)
  expect(pending.peer.recorded('session/prompt')).toEqual([])
  pending.client.dispose()
})

it('keeps an uncertain prepare out of admission and releases owned content', async () => {
  const owned = await fixture()
  await expect(owned.client.prepareAttachment(owned.sessionId, 'unknown', 'prepare-unknown')).rejects.toThrow(/preparation unknown/)
  expect(owned.getAdmissionCalls()).toBe(0)
  const ref = await owned.client.prepareAttachment(owned.sessionId, 'owned-image', 'prepare-owned')
  await owned.client.releasePreparedAttachment(owned.sessionId, ref.preparedId)
  await expect(owned.send(ref, 'submit-released')).rejects.toThrow(/ownership or content changed/)
  expect(owned.peer.recorded('session/prompt')).toEqual([])
  owned.client.dispose()
})
