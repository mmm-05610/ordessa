import { expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { createProfileChatGlue } from '../src/glue'
import type { ProfileServiceClient, AppliedReceiptDto, SessionRef, NativeCreationPreparationDto } from '@ordessa/plugin-profile-api'

const selection = { profileId: 'profile', displayName: 'P', harnessId: 'pi', archived: false }
const ref: SessionRef = { realm: 'local', harnessId: 'pi', nativeSessionKey: 'native', sessionUid: 'canonical' }
const receipt: AppliedReceiptDto = { operationId: 'op', sessionRef: ref, runtimeGeneration: '1',
  configDigest: 'digest', profileId: 'profile', profileRevision: 1, overlayRevision: null, policyRevision: 1,
  providerGenerations: {}, evidenceKind: 'controlled-fixture', confirmedAt: 'now' }
const snapshot: ChatSubmissionSnapshot = { submissionId: 'send', draftId: 'draft', draftRevision: 1,
  target: { kind: 'draft', draftId: 'draft', serverInstanceId: 'server', contextRevision: 1 },
  text: 'keep text', attachmentIds: [] }

function setup(nativePreparation?: { response?: Record<string, unknown>; wait?: Promise<void>; harnessId?: string }) {
  const scope = new OwnedResources(), chat = createChatContributions(), order: string[] = []
  let state = 'settled', fail = false, unknown = false
  let nativePrepared = false, discarded = false
  const nativeListeners = new Set<() => void>()
  const applied: string[] = []
  const harnessId = nativePreparation?.harnessId ?? 'pi'
  const sessionRef = { ...ref, harnessId }
  const profiles = {
    async registerNativeSession() { order.push('register'); return { sessionRef } },
    async selectForSession(_operation: string, input: { profileId: string }) { order.push('select'); applied.push(input.profileId); return {} },
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
  if (nativePreparation) profiles.prepareNativeCreation = async input => {
    order.push('prepare-provider')
    expect(input).toEqual({ connectionId: 'channel', profileId: 'profile', operationId: 'create:attempt' })
    await nativePreparation.wait
    return { state: 'prepared', operationId: input.operationId, connectionId: input.connectionId,
      profileId: input.profileId, harnessId, profileRevision: 1, ...nativePreparation.response } as NativeCreationPreparationDto
  }
  const glue = createProfileChatGlue(scope, chat, { profiles, catalog: () => [], nativeSessions: {
    getSnapshot: () => ({ available: [], selectedConnectionId: 'client', draft: { active: !discarded, canSend: true,
      ...(discarded ? { endedBy: 'discarded' as const } : {}) } }),
    subscribe(listener) { nativeListeners.add(listener); return () => { nativeListeners.delete(listener) } },
    async prepareSubmission(preparation) {
      order.push('prepare')
      if (nativePreparation && !nativePrepared) {
        await preparation?.beforeCreate(Object.freeze({ attemptId: 'attempt', serverInstanceId: 'server', connectionId: 'channel', harnessId, workspaceId: 'project' }))
        order.push('session/new')
        nativePrepared = true
      }
      return { sessionId: 'native', serverInstanceId: 'server', connectionId: 'channel', nativeSessionId: 'native', harnessId, workspaceId: 'project' }
    },
  } })
  const gateway = { async submit() { order.push('prompt'); return { status: 'accepted' as const } } }
  return { scope, chat, glue, order, gateway, applied, fail: (value: boolean) => { fail = value }, unknown: (value: boolean) => { unknown = value },
    discard() { discarded = true; for (const listener of nativeListeners) listener(); discarded = false; nativePrepared = false },
  }
}

it('retains a failed initial preparation after clearing selection and only resets it on explicit discard', async () => {
  const response = { state: 'unknown' }
  const f = setup({ response })
  try {
    f.glue.store.select('draft:draft', selection)
    expect(await f.chat.submit(snapshot, f.gateway)).toEqual({ status: 'unknown' })
    f.glue.store.forget('draft:draft')
    expect(await f.chat.submit({ ...snapshot, submissionId: 'cleared' }, f.gateway)).toEqual({ status: 'unknown' })
    expect(f.order.filter(item => item === 'prepare-provider')).toHaveLength(2)
    expect(f.order).not.toContain('session/new')
    expect(f.order).not.toContain('prompt')
    f.discard()
    f.order.length = 0
    expect(await f.chat.submit({ ...snapshot, submissionId: 'after-discard' }, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order).toEqual(['prompt'])
  } finally { f.scope.dispose() }
})

it('retains the required C4 application after native creation when selection is cleared', async () => {
  const f = setup({})
  try {
    f.glue.store.select('draft:draft', selection)
    f.fail(true)
    expect(await f.chat.submit(snapshot, f.gateway)).toMatchObject({ status: 'refused' })
    f.glue.store.forget('draft:draft')
    expect(await f.chat.submit({ ...snapshot, submissionId: 'cleared' }, f.gateway)).toMatchObject({ status: 'refused' })
    expect(f.order.filter(item => item === 'prepare-provider')).toHaveLength(1)
    expect(f.order.filter(item => item === 'session/new')).toHaveLength(1)
    expect(f.order).not.toContain('prompt')
    f.fail(false)
    expect(await f.chat.submit({ ...snapshot, submissionId: 'confirmed' }, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order.filter(item => item === 'session/new')).toHaveLength(1)
    expect(f.order.filter(item => item === 'prompt')).toHaveLength(1)
    expect(f.applied).toEqual(['profile', 'profile', 'profile'])
  } finally { f.scope.dispose() }
})

it('queries an unknown C4 outcome after clearing selection without automatically reapplying or sending', async () => {
  const f = setup({})
  try {
    f.glue.store.select('draft:draft', selection)
    f.unknown(true)
    expect(await f.chat.submit(snapshot, f.gateway)).toEqual({ status: 'unknown' })
    f.glue.store.forget('draft:draft')
    f.unknown(false)
    expect(await f.chat.submit({ ...snapshot, submissionId: 'cleared-reconcile' }, f.gateway)).toMatchObject({ status: 'refused' })
    expect(f.order.filter(item => item === 'apply')).toHaveLength(1)
    expect(f.order.filter(item => item === 'reconcile')).toHaveLength(1)
    expect(f.order.filter(item => item === 'session/new')).toHaveLength(1)
    expect(f.order).not.toContain('prompt')
  } finally { f.scope.dispose() }
})

it('prepares the selected provider on the actual channel before new, register, apply and prompt', async () => {
  const f = setup({})
  try {
    f.glue.store.select('draft:draft', selection)
    expect(await f.chat.submit(snapshot, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order).toEqual(['prepare', 'prepare-provider', 'session/new', 'register', 'select', 'apply', 'prompt'])
  } finally { f.scope.dispose() }
})

it.each([
  { state: 'unknown' }, { state: 'unexpected' }, { operationId: 'wrong' }, { connectionId: 'wrong' },
  { profileId: 'wrong' }, { harnessId: 'wrong' }, { profileRevision: 0 }, { profileRevision: 1.5 },
  { privateTransport: {} },
])('blocks new and prompt for malformed or unknown provider preparation: %j', async response => {
  const f = setup({ response })
  try {
    f.glue.store.select('draft:draft', selection)
    expect(await f.chat.submit(snapshot, f.gateway)).toEqual({ status: 'unknown' })
    expect(f.order).toEqual(['prepare', 'prepare-provider'])
    expect(f.glue.store.peek('draft:draft')).toEqual(selection)
  } finally { f.scope.dispose() }
})

it.each(['codex', 'claude'])('refuses %s before creation if the provider preparation service is missing', async harnessId => {
  const f = setup()
  try {
    f.glue.store.select('draft:draft', { ...selection, harnessId })
    expect(await f.chat.submit(snapshot, f.gateway)).toMatchObject({ status: 'refused' })
    expect(f.order).toEqual([])
  } finally { f.scope.dispose() }
})

it('keeps a changed selection during preparation for the next explicit submission', async () => {
  let release!: () => void
  const f = setup({ wait: new Promise<void>(resolve => { release = resolve }) })
  try {
    f.glue.store.select('draft:draft', selection)
    const pending = f.chat.submit(snapshot, f.gateway)
    await Promise.resolve()
    const next = { ...selection, profileId: 'next', displayName: 'Next' }
    f.glue.store.select('draft:draft', next)
    release()
    expect(await pending).toEqual({ status: 'accepted' })
    expect(f.applied).toEqual(['profile'])
    expect(f.glue.store.peek('draft:draft')).toEqual(next)
  } finally { release(); f.scope.dispose() }
})

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
