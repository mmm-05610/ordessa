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

/** The production Profile client always exposes `prepareNativeCreation`; the
 * per-harness verdict (`prepared` vs `not-required`) belongs to the backend, so
 * the default fixture answers `not-required` and the harness id is data. */
function setup(nativePreparation: { response?: Record<string, unknown>; wait?: Promise<void>; harnessId?: string } = {}) {
  const scope = new OwnedResources(), chat = createChatContributions(), order: string[] = []
  let state = 'settled', fail = false, unknown = false
  let nativePrepared = false, discarded = false
  let temporaryOverride: string | null = null
  let applicationWait: Promise<void> | undefined
  let currentProfileId = 'profile'
  const currentReceipt = () => ({ ...receipt, profileId: currentProfileId })
  const nativeListeners = new Set<() => void>()
  const applied: string[] = []
  const harnessId = nativePreparation.harnessId ?? 'pi'
  const sessionRef = { ...ref, harnessId }
  const profiles = {
    async registerNativeSession() { order.push('register'); return { sessionRef } },
    async selectForSession(_operation: string, input: { profileId: string }) { order.push('select'); applied.push(input.profileId); currentProfileId = input.profileId; temporaryOverride = null; return {} },
    async inspectSessionConfig() { return { sessionRef: ref, switchState: state, current: { profileId: currentProfileId, revision: 1 }, pending: null,
      evidence: { receipt: currentReceipt(), evidenceKind: receipt.evidenceKind, journal: { operationId: 'op', state: 'confirmed' } } } },
    async beginTurnApplication() {
      order.push('apply')
      await applicationWait
      if (unknown) { state = 'needs_recovery'; throw new Error('typed business refusal') }
      if (fail) throw new Error('configuration unsupported')
      return { turnId: 'turn', appliedSwitch: false, receipt: currentReceipt() }
    },
    async reconcile() { order.push('reconcile'); state = 'settled'; return { state: 'confirmed-current', receipt } },
  } as unknown as ProfileServiceClient
  if (nativePreparation) profiles.prepareNativeCreation = async input => {
    order.push('prepare-provider')
    expect(input).toEqual({ connectionId: 'channel', profileId: 'profile', operationId: 'create:attempt' })
    await nativePreparation.wait
    return { state: 'not-required', operationId: input.operationId, connectionId: input.connectionId,
      profileId: input.profileId, harnessId, profileRevision: 1, ...nativePreparation.response } as NativeCreationPreparationDto
  }
  const glue = createProfileChatGlue(scope, chat, { profiles, catalog: () => [], nativeSessions: {
    getSnapshot: () => ({ available: [], selectedConnectionId: 'client', draft: { active: !discarded, canSend: true,
      ...(discarded ? { endedBy: 'discarded' as const } : {}) } }),
    subscribe(listener) { nativeListeners.add(listener); return () => { nativeListeners.delete(listener) } },
    async prepareSubmission(preparation) {
      order.push('prepare')
      if (!nativePrepared) {
        await preparation?.beforeCreate(Object.freeze({ attemptId: 'attempt', serverInstanceId: 'server', connectionId: 'channel', harnessId, workspaceId: 'project' }))
        order.push('session/new')
        nativePrepared = true
      }
      return { sessionId: 'native', serverInstanceId: 'server', connectionId: 'channel', nativeSessionId: 'native', harnessId, workspaceId: 'project' }
    },
  } })
  const gateway = { async submit() { order.push('prompt'); return { status: 'accepted' as const } } }
  return { scope, chat, glue, order, gateway, applied, fail: (value: boolean) => { fail = value }, unknown: (value: boolean) => { unknown = value },
    override: (value: string) => { temporaryOverride = value }, currentOverride: () => temporaryOverride,
    waitForApplication: (wait: Promise<void> | undefined) => { applicationWait = wait },
    discard() { discarded = true; for (const listener of nativeListeners) listener(); discarded = false; nativePrepared = false },
  }
}

it('keeps an applied Profile visible after an unknown first prompt, but not in a discarded new draft', async () => {
  const f = setup({})
  try {
    f.glue.store.select('draft:draft', selection)
    expect(await f.chat.submit(snapshot, { async submit() { return { status: 'unknown' as const } } }))
      .toEqual({ status: 'unknown' })
    expect(f.glue.store.peek('draft:draft')).toBeNull()
    expect(f.glue.store.currentLabel('draft:draft')).toBe(selection.displayName)
    expect(f.order).toContain('apply')
    f.discard()
    expect(f.glue.store.currentLabel('draft:draft')).toBeNull()
  } finally { f.scope.dispose() }
})

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

it.each(['pi', 'codex', 'claude'])(
  'refuses before creation for ANY harness when the provider preparation service is missing: %s',
  async harnessId => {
    // A deployment without the native-registration owner: the port is absent
    // for every Harness equally, and the frontend must not name one.
    const scope = new OwnedResources(), chat = createChatContributions()
    const profiles = { async registerNativeSession() { throw new Error('never reached') } } as unknown as ProfileServiceClient
    const glue = createProfileChatGlue(scope, chat, { profiles, catalog: () => [], nativeSessions: {
      getSnapshot: () => ({ available: [], selectedConnectionId: 'client', draft: { active: true, canSend: true } }),
      subscribe: () => () => undefined,
      async prepareSubmission() { throw new Error('no native creation may be attempted') },
    } })
    try {
      glue.store.select('draft:draft', { ...selection, harnessId })
      expect(await chat.submit(snapshot, { async submit() { throw new Error('never reached') } }))
        .toMatchObject({ status: 'refused' })
      expect(glue.store.peek('draft:draft')).toEqual({ ...selection, harnessId })
    } finally { glue.dispose() }
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

it('applies each turn without reselecting the bound Profile or clearing a temporary override on ordinary next submit', async () => {
  const f = setup()
  try {
    f.glue.store.select('draft:draft', selection)
    expect(await f.chat.submit(snapshot, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order).toEqual(['prepare', 'prepare-provider', 'session/new', 'register', 'select', 'apply', 'prompt'])
    const next = { ...snapshot, submissionId: 'next', target: { kind: 'session' as const, sessionId: 'native', connectionId: 'client', harnessId: 'pi', serverInstanceId: 'server', contextRevision: 2 } }
    f.override('temporary-model')
    expect(await f.chat.submit(next, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order.filter(item => item === 'select')).toHaveLength(1)
    expect(f.currentOverride()).toBe('temporary-model')
    expect(f.glue.store.peek('session:native')).toBeNull()
    expect(f.order.filter(item => item === 'register')).toHaveLength(1)
    expect(f.order.filter(item => item === 'apply')).toHaveLength(2)
    expect(f.order.filter(item => item === 'prompt')).toHaveLength(2)
  } finally { f.scope.dispose() }
})

it('explicitly reselects even the same Profile on next submit and clears temporary overrides', async () => {
  const f = setup()
  try {
    f.glue.store.select('draft:draft', selection)
    await f.chat.submit(snapshot, f.gateway)
    f.override('temporary-model')
    f.glue.store.select('session:native', selection)
    const next = { ...snapshot, submissionId: 'reselect', target: { kind: 'session' as const, sessionId: 'native', connectionId: 'client', harnessId: 'pi', serverInstanceId: 'server', contextRevision: 2 } }
    expect(await f.chat.submit(next, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order.filter(item => item === 'select')).toHaveLength(2)
    expect(f.order.filter(item => item === 'apply')).toHaveLength(2)
    expect(f.currentOverride()).toBeNull()
    expect(f.glue.store.peek('session:native')).toBeNull()
  } finally { f.scope.dispose() }
})

it.each(['confirmed', 'refused', 'unknown'] as const)('keeps a new pick during ordinary application (%s) for the next turn without prompting on failure', async verdict => {
  const f = setup()
  let release!: () => void
  try {
    f.glue.store.select('draft:draft', selection)
    await f.chat.submit(snapshot, f.gateway)
    f.order.length = 0
    f.waitForApplication(new Promise<void>(resolve => { release = resolve }))
    f.fail(verdict === 'refused')
    f.unknown(verdict === 'unknown')
    const next = { ...snapshot, submissionId: 'ordinary', target: { kind: 'session' as const, sessionId: 'native', connectionId: 'client', harnessId: 'pi', serverInstanceId: 'server', contextRevision: 2 } }
    const submitting = f.chat.submit(next, f.gateway)
    // Wait for the actual application gate rather than racing preparation.
    for (let tick = 0; tick < 20 && !f.order.includes('apply'); tick += 1) await Promise.resolve()
    expect(f.order).toContain('apply')
    const newPick = { ...selection, profileId: 'next', displayName: 'Next' }
    f.glue.store.select('session:native', newPick)
    release()
    expect(await submitting).toMatchObject({ status: verdict === 'confirmed' ? 'accepted' : verdict })
    expect(f.glue.store.peek('session:native')).toEqual(newPick)
    expect(f.applied).toEqual(['profile'])
    expect(f.order.filter(item => item === 'prompt')).toHaveLength(verdict === 'confirmed' ? 1 : 0)
    if (verdict === 'confirmed') {
      f.waitForApplication(undefined)
      expect(await f.chat.submit({ ...next, submissionId: 'new-pick' }, f.gateway)).toEqual({ status: 'accepted' })
      expect(f.applied).toEqual(['profile', 'next'])
      expect(f.glue.store.peek('session:native')).toBeNull()
    }
  } finally { release?.(); f.scope.dispose() }
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

it('ordinary submission without a Profile pick or binding makes zero Profile or preparation calls', async () => {
  const f = setup()
  try {
    expect(await f.chat.submit(snapshot, f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order).toEqual(['prompt'])
    expect(f.applied).toEqual([])
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

it('projects the registered binding fact for the model route bound dispatch (021 T04)', async () => {
  const f = setup({})
  try {
    const sessionTarget = { kind: 'session' as const, connectionId: 'client',
      serverInstanceId: 'server', sessionId: 'native', harnessId: 'pi', contextRevision: 1 }
    const boundFact = () => {
      const [view] = f.chat.contributionsBySlot('composer.toolbar').getSnapshot()
        .filter(item => item.id === 'ordessa.profile-chat.picker')
      const projected = view?.project?.({
        slot: 'composer.toolbar' as const, location: sessionTarget,
        connection: { status: 'connected' },
      })
      if (!projected || projected.hidden) return undefined
      return (projected.props as { boundNativeSession?: { serverInstanceId: string; sessionId: string } | null })
        .boundNativeSession
    }
    // no binding yet: absence reads as unbound (never a guessed fact)
    expect(boundFact()).toBeNull()
    f.glue.store.select('session:native', selection)
    expect(await f.chat.submit({ ...snapshot, target: sessionTarget, submissionId: 'bind' },
      f.gateway)).toEqual({ status: 'accepted' })
    expect(f.order).toContain('register')
    // the registered binding of THIS chat session travels to the model guard
    expect(boundFact()).toEqual({ serverInstanceId: 'server', sessionId: 'native' })
    // a different chat session does not read as bound
    const [view] = f.chat.contributionsBySlot('composer.toolbar').getSnapshot()
      .filter(item => item.id === 'ordessa.profile-chat.picker')
    const other = view?.project?.({
      slot: 'composer.toolbar' as const,
      location: { ...sessionTarget, sessionId: 'other' },
      connection: { status: 'connected' },
    })
    expect(other && !other.hidden && (other.props as { boundNativeSession?: unknown }).boundNativeSession)
      .toBeNull()
  } finally { f.scope.dispose() }
})
