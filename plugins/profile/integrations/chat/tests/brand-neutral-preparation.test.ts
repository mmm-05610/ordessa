import { expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createChatContributions, type ChatSubmissionSnapshot } from '@extensions/ordessa.chat-api/contract.js'
import { createProfileChatGlue } from '../src/glue'
import type {
  ProfileSelection, ProfileServiceClient, AppliedReceiptDto, SessionRef,
} from '@ordessa/plugin-profile-api'

const pick = (harnessId: string): ProfileSelection =>
  ({ profileId: 'profile', displayName: 'P', harnessId })

/** Every Harness the product ships, as data — never as a branch. The frontend
 * must not know which of them needs a pre-creation preparation: the backend
 * already answers `not-required` for the ones that do not
 * (`preparation_params(harness, …) is None`). */
const HARNESSES = ['pi', 'codex', 'claude'] as const

const snapshot: ChatSubmissionSnapshot = {
  submissionId: 'send', draftId: 'draft', draftRevision: 1,
  target: { kind: 'draft', draftId: 'draft', serverInstanceId: 'server', contextRevision: 1 },
  text: 'keep text', attachmentIds: [],
}

function ref(harnessId: string): SessionRef {
  return { realm: 'local', harnessId, nativeSessionKey: 'native', sessionUid: 'canonical' }
}

/** A Profile service WITHOUT the creation-preparation port — the honest shape
 * of a deployment whose native registration owner is absent. */
function withoutPreparationPort(harnessId: string) {
  const order: string[] = []
  const receipt: AppliedReceiptDto = { operationId: 'op', sessionRef: ref(harnessId), runtimeGeneration: '1',
    configDigest: 'digest', profileId: 'profile', profileRevision: 1, overlayRevision: null, policyRevision: 1,
    providerGenerations: {}, evidenceKind: 'controlled-fixture', confirmedAt: 'now' }
  const profiles = {
    async registerNativeSession() { order.push('register'); return { sessionRef: ref(harnessId) } },
    async selectForSession() { order.push('select'); return {} },
    async inspectSessionConfig() { return { sessionRef: ref(harnessId), switchState: 'settled',
      current: { profileId: 'profile', revision: 1 }, pending: null,
      evidence: { receipt, evidenceKind: receipt.evidenceKind, journal: { operationId: 'op', state: 'confirmed' } } } },
    async beginTurnApplication() { order.push('apply'); return { turnId: 'turn', appliedSwitch: false, receipt } },
    async reconcile() { order.push('reconcile'); return { state: 'confirmed-current', receipt } },
  } as unknown as ProfileServiceClient
  const chat = createChatContributions()
  const glue = createProfileChatGlue(new OwnedResources(), chat, {
    profiles,
    catalog: () => [],
    nativeSessions: {
      getSnapshot: () => ({ available: [], selectedConnectionId: 'client',
        draft: { active: true, canSend: true } }),
      subscribe: () => () => undefined,
      async prepareSubmission() { order.push('prepare'); return { sessionId: 'native',
        serverInstanceId: 'server', connectionId: 'channel', nativeSessionId: 'native',
        harnessId, workspaceId: 'project' } },
    },
  })
  return { order, glue, chat }
}

it.each(HARNESSES)(
  'a draft selection refuses before any native creation when the preparation port is absent — %s included',
  async harnessId => {
    const f = withoutPreparationPort(harnessId)
    try {
      f.glue.store.select('draft:draft', pick(harnessId))
      const result = await f.chat.submit(snapshot, { async submit() { return { status: 'accepted' as const } } })
      expect(result).toMatchObject({ status: 'refused' })
      // Nothing was prepared, no native session, no prompt — for ANY harness.
      expect(f.order).toEqual([])
      // The draft and its selection survive the refusal.
      expect(f.glue.store.peek('draft:draft')).toEqual(pick(harnessId))
      expect(snapshot.text).toBe('keep text')
    } finally { f.glue.dispose() }
  })

it('with the port present, EVERY draft harness routes through it — the frontend does not pre-empt the backend', async () => {
  for (const harnessId of HARNESSES) {
    const order: string[] = []
    const chat = createChatContributions()
    const harnessRef = ref(harnessId)
    const receipt: AppliedReceiptDto = { operationId: 'op', sessionRef: harnessRef, runtimeGeneration: '1',
      configDigest: 'digest', profileId: 'profile', profileRevision: 1, overlayRevision: null, policyRevision: 1,
      providerGenerations: {}, evidenceKind: 'controlled-fixture', confirmedAt: 'now' }
    const profiles = {
      async registerNativeSession() { order.push('register'); return { sessionRef: harnessRef } },
      async selectForSession() { order.push('select'); return {} },
      async inspectSessionConfig() { return { sessionRef: harnessRef, switchState: 'settled',
        current: { profileId: 'profile', revision: 1 }, pending: null,
        evidence: { receipt, evidenceKind: receipt.evidenceKind, journal: { operationId: 'op', state: 'confirmed' } } } },
      async beginTurnApplication() { order.push('apply'); return { turnId: 'turn', appliedSwitch: false, receipt } },
      async reconcile() { return { state: 'confirmed-current', receipt } },
      async prepareNativeCreation(input: { connectionId: string; profileId: string; operationId: string }) {
        order.push('prepare-provider')
        // `not-required` is the backend's own per-harness verdict (Pi applies
        // live). The frontend forwards the call either way.
        return { state: harnessId === 'pi' ? 'not-required' : 'prepared',
          operationId: input.operationId, connectionId: input.connectionId, profileId: input.profileId,
          harnessId, profileRevision: 1 }
      },
    } as unknown as ProfileServiceClient
    const glue = createProfileChatGlue(new OwnedResources(), chat, {
      profiles, catalog: () => [],
      nativeSessions: {
        getSnapshot: () => ({ available: [], selectedConnectionId: 'client', draft: { active: true, canSend: true } }),
        subscribe: () => () => undefined,
        async prepareSubmission(preparation) {
          order.push('prepare')
          await preparation?.beforeCreate(Object.freeze({ attemptId: 'attempt', serverInstanceId: 'server',
            connectionId: 'channel', harnessId, workspaceId: 'project' }))
          order.push('session/new')
          return { sessionId: 'native', serverInstanceId: 'server', connectionId: 'channel',
            nativeSessionId: 'native', harnessId, workspaceId: 'project' }
        },
      },
    })
    try {
      glue.store.select('draft:draft', pick(harnessId))
      const gateway = { async submit() { order.push('prompt'); return { status: 'accepted' as const } } }
      expect(await chat.submit(snapshot, gateway)).toEqual({ status: 'accepted' })
      // Identical order for every harness: the backend, not the renderer,
      // decides whether the preparation had native parameters to send.
      expect(order).toEqual(['prepare', 'prepare-provider', 'session/new', 'register', 'select', 'apply', 'prompt'])
    } finally { glue.dispose() }
  }
})
