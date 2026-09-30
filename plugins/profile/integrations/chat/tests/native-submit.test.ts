import { expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { createProfileChatGlue } from '../src/glue'
import type { ProfileServiceClient, AppliedReceiptDto, SessionRef } from '@ordessa/plugin-profile-api'

const selection = { profileId: 'profile', displayName: 'P', harnessId: 'pi', archived: false }
const ref: SessionRef = { realm: 'local', harnessId: 'pi', nativeSessionKey: 'native', sessionUid: 'canonical' }
const receipt: AppliedReceiptDto = { operationId: 'op', sessionRef: ref, runtimeGeneration: '1',
  configDigest: 'digest', profileId: 'profile', profileRevision: 1, overlayRevision: null, policyRevision: 1,
  providerGenerations: {}, evidenceKind: 'controlled-fixture', confirmedAt: 'now' }
const snapshot: ChatSubmissionSnapshot = { submissionId: 'send', draftId: 'draft', draftRevision: 1,
  target: { kind: 'draft', draftId: 'draft', serverInstanceId: 'server', contextRevision: 1 },
  text: 'keep text', attachmentIds: [] }

function setup() {
  const scope = new OwnedResources(), chat = createChatContributions(), order: string[] = []
  let state = 'settled', fail = false, unknown = false
  const profiles = {
    async registerNativeSession() { order.push('register'); return { sessionRef: ref } },
    async selectForSession() { order.push('select'); return {} },
    async inspectSessionConfig() { return { sessionRef: ref, switchState: state, current: { profileId: 'profile', revision: 1 }, pending: null,
      evidence: { receipt, evidenceKind: receipt.evidenceKind, journal: { operationId: 'op', state: 'confirmed' } } } },
    async beginTurnApplication() {
      order.push('apply')
      if (unknown) { state = 'needs_recovery'; throw new Error('typed business refusal') }
      if (fail) throw new Error('configuration unsupported')
      return { turnId: 'turn', appliedSwitch: false, receipt }
    },
    async reconcile() { order.push('reconcile'); state = 'settled'; return { state: 'confirmed-current', receipt } },
  } as unknown as ProfileServiceClient
  const glue = createProfileChatGlue(scope, chat, { profiles, catalog: () => [], nativeSessions: {
    async prepareSubmission() { order.push('prepare'); return { sessionId: 'native', serverInstanceId: 'server', connectionId: 'channel', nativeSessionId: 'native', harnessId: 'pi', workspaceId: 'project' } },
  } })
  const gateway = { async submit() { order.push('prompt'); return { status: 'accepted' as const } } }
  return { scope, chat, glue, order, gateway, fail: (value: boolean) => { fail = value }, unknown: (value: boolean) => { unknown = value } }
}

it('applies between native preparation and first prompt, then reapplies at the next explicit submit', async () => {
  const f = setup()
  try {
    f.glue.store.select('draft:draft', selection)
    expect(await f.chat.submit(snapshot, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order).toEqual(['prepare', 'register', 'select', 'apply', 'prompt'])
    const next = { ...snapshot, submissionId: 'next', target: { kind: 'session' as const, sessionId: 'native', connectionId: 'client', harnessId: 'pi', serverInstanceId: 'server', contextRevision: 2 } }
    expect(await f.chat.submit(next, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order.filter(item => item === 'register')).toHaveLength(1)
    expect(f.order.filter(item => item === 'apply')).toHaveLength(2)
    expect(f.order.filter(item => item === 'prompt')).toHaveLength(2)
  } finally { f.scope.dispose() }
})

it('configuration refusal keeps choice/text and retries without a second registration or prompt before confirmation', async () => {
  const f = setup()
  try {
    f.glue.store.select('draft:draft', selection)
    f.fail(true)
    expect(await f.chat.submit(snapshot, f.gateway)).toMatchObject({ status: 'refused' })
    expect(f.glue.store.peek('draft:draft')).toEqual(selection)
    expect(f.order).not.toContain('prompt')
    expect(snapshot.text).toBe('keep text')
    f.fail(false)
    expect(await f.chat.submit({ ...snapshot, submissionId: 'retry' }, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order.filter(item => item === 'register')).toHaveLength(1)
    expect(f.order.filter(item => item === 'prompt')).toHaveLength(1)
  } finally { f.scope.dispose() }
})

it('unknown configuration is only reconciled on the next click, never automatically applied or sent', async () => {
  const f = setup()
  try {
    f.glue.store.select('draft:draft', selection)
    f.unknown(true)
    expect(await f.chat.submit(snapshot, f.gateway)).toEqual({ status: 'unknown' })
    f.unknown(false)
    expect(await f.chat.submit({ ...snapshot, submissionId: 'reconcile' }, f.gateway)).toMatchObject({ status: 'refused' })
    expect(f.order.filter(item => item === 'apply')).toHaveLength(1)
    expect(f.order.filter(item => item === 'reconcile')).toHaveLength(1)
    expect(f.order).not.toContain('prompt')
    expect(f.glue.store.peek('draft:draft')).toEqual(selection)
  } finally { f.scope.dispose() }
})

it('does not prepare an unrelated draft just because another session has a Profile binding', async () => {
  const f = setup()
  try {
    f.glue.store.select('draft:draft', selection)
    await f.chat.submit(snapshot, f.gateway)
    f.order.length = 0
    const other = { ...snapshot, submissionId: 'other', draftId: 'other',
      target: { ...snapshot.target, kind: 'draft' as const, draftId: 'other' } }
    expect(await f.chat.submit(other, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order).toEqual(['prompt'])
  } finally { f.scope.dispose() }
})
