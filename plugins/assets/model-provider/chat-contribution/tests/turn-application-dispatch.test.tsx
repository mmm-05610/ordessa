// @vitest-environment jsdom
// authored in this line (021 T04): the bound/unbound send dispatch and the
// appendix §2 client semantics, against the REAL chat contributions registry.
//
// Gates (zcode-profile-model-closeout §5, frontend side):
// - bound/unbound dispatch: a session whose Profile glue binding is projected
//   never triggers ``beginTurnApplication`` (the Profile guard owns the one
//   real application); an unbound session submits its queued intent (M06);
// - refused blocks the send with the draft and the intent kept; unknown
//   blocks without a fabricated outcome; no-intent passes (FR-06);
// - every explicit retry carries a NEW operation key (§6b.2);
// - a pick made while a submit is in flight still queues immediately (M11);
// - a submit from a stale session never reaches the wire (M12).
import { describe, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  chatContribution,
  createChatContributions,
  type ChatContributionsService,
  type ChatLocation,
  type ChatSubmissionSnapshot,
} from '@extensions/ordessa.chat-api/contract.js'
import {
  MODEL_SELECTOR_ID,
  ModelSelectorKey,
  PROFILE_BINDING_CONTRIBUTION_ID,
  TURN_APPLICATION_GUARD_ID,
  clientRegistryOf,
  registerModelSelector,
  targetIdentityOf,
} from '../src/chat-api-entry'
import { SUBMIT_METHOD, createNextTurnClient } from '../src/next-turn-client'
import type { ModelProviderService } from '../contracts/index'

const LOCATION: ChatLocation = {
  kind: 'session', connectionId: 'conn-1', serverInstanceId: 'srv-1',
  sessionId: 's-9', harnessId: 'pi', contextRevision: 0,
}
const TARGET = { serverInstanceId: 'srv-1', harnessId: 'pi', acpSessionId: 's-9' }

function snapshot(target: ChatLocation = LOCATION): ChatSubmissionSnapshot {
  return {
    submissionId: 'sub-1', target, draftId: 'd-1', draftRevision: 1,
    text: 'hello', attachmentIds: [],
  }
}

function evidence() {
  return {
    operationId: 'op-native-1',
    nativeTarget: { owner: 'connection:s-9', canonicalUid: 'profile-session-1', generation: 3 },
    appliedRevision: 'applied-1',
    evidenceRef: 'pi-independent-query:1',
  }
}

function makeService(): ModelProviderService {
  return {} as ModelProviderService
}

function bindProfileFact(chat: ChatContributionsService, bound: {
  serverInstanceId: string; sessionId: string
} | null) {
  const registration = chatContribution<{ location: ChatLocation }>({
    id: PROFILE_BINDING_CONTRIBUTION_ID,
    slot: 'composer.toolbar',
    order: 10,
    key: ModelSelectorKey,
    project: context => ({
      hidden: false as const,
      props: { label: null, groups: [], onSelect: () => undefined, boundNativeSession: bound },
    }),
  })
  chat.forScope(new OwnedResources()).addContribution(registration)
}

async function runGuard(chat: ChatContributionsService, target: ChatLocation = LOCATION) {
  const gateway = { submit: vi.fn().mockResolvedValue({ status: 'accepted' }) }
  const result = await chat.submit(snapshot(target), gateway, () => true)
  return { result, gateway }
}

describe('turn-application client (appendix §2 consumer)', () => {
  it('submits the queued intent and consumes it on an evidenced ready', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 7, intentRoute: 'independent' })
      .mockResolvedValueOnce({ outcome: 'ready', sequence: 7, application: evidence() })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    const outcome = await client.submitTurn()
    expect(outcome).toEqual({ state: 'ready', sequence: 7, application: evidence() })
    expect(client.pending).toBeNull() // the ready answer consumed the intent
    expect(invoke).toHaveBeenLastCalledWith(SUBMIT_METHOD, {
      target: TARGET, operationKey: expect.stringMatching(/^chat-submit-s-9-\d+-/),
      expectedSequence: 7,
    })
  })

  it('keeps the intent on a refusal and blocks on an unknown', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 2, intentRoute: 'independent' })
      .mockResolvedValueOnce({ outcome: 'refused', reason: 'TARGET_STALE' })
      .mockResolvedValueOnce({ outcome: 'unknown', reason: 'OPERATION_UNKNOWN' })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    expect(await client.submitTurn()).toEqual({ state: 'refused', code: 'TARGET_STALE' })
    expect(client.pending).not.toBeNull() // the intent stays for an explicit retry
    expect(await client.submitTurn()).toEqual({ state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' })
    expect(client.pending).not.toBeNull()
  })

  it('answers no-intent without touching the queue bookkeeping', async () => {
    const invoke = vi.fn().mockResolvedValue({ outcome: 'no-intent' })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    expect(await client.submitTurn()).toEqual({ state: 'no-intent' })
    expect(client.pending).toBeNull()
  })

  it('never believes a ready answer without real evidence references', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 3, intentRoute: 'independent' })
      .mockResolvedValue({ outcome: 'ready', sequence: 3,
        application: { operationId: '', nativeTarget: {}, evidenceRef: ' ' } })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    expect(await client.submitTurn()).toEqual({ state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' })
    expect(client.pending).not.toBeNull() // an unevidenced ready is not a confirmation
  })

  it('gives every explicit retry a fresh operation key (§6b.2)', async () => {
    const invoke = vi.fn()
      .mockResolvedValue({ outcome: 'refused', reason: 'TARGET_STALE' })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.submitTurn()
    await client.submitTurn()
    const keys = invoke.mock.calls
      .filter(([method]) => method === SUBMIT_METHOD)
      .map(([, params]) => (params as { operationKey: string }).operationKey)
    expect(keys).toHaveLength(2)
    expect(new Set(keys).size).toBe(2)
  })

  it('a submit from a stale session never reaches the wire (M12)', async () => {
    const invoke = vi.fn()
    let current = true
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET },
      () => current)
    current = false
    expect(await client.submitTurn()).toEqual({ state: 'refused', code: 'TARGET_STALE' })
    expect(invoke).not.toHaveBeenCalled()
  })

  it('a pick made while a submit is in flight still queues immediately (M11)', async () => {
    let releaseSubmit: (() => void) | undefined
    const submitInFlight = new Promise<void>(resolve => { releaseSubmit = resolve })
    const invoke = vi.fn()
      .mockImplementation((method: string) => {
        if (method === SUBMIT_METHOD) return submitInFlight.then(() => ({
          outcome: 'ready', sequence: 5, application: evidence() }))
        return Promise.resolve({ outcome: 'pending-next-turn', sequence: 6, intentRoute: 'independent' })
      })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    const submitting = client.submitTurn()
    const queued = await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm2' })
    expect(queued).toEqual({ state: 'pending-next-turn', sequence: 6 })
    releaseSubmit!()
    await submitting
    expect(client.pending).not.toBeNull() // the newer pick was not consumed (FR-04)
  })

  it('reconciles read-only: a confirmed observation clears, others keep', async () => {
    const invoke = vi.fn()
      .mockResolvedValueOnce({ outcome: 'pending-next-turn', sequence: 9, intentRoute: 'independent' })
      .mockResolvedValueOnce({ outcome: 'confirmed', turnFact: {
        harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1',
        providerConfigVersion: 1, evidence: { applied: 'reconcile-verified' } } })
    const client = createNextTurnClient(invoke, { kind: 'session', session: TARGET })
    await client.queue({ harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' })
    expect(await client.reconcile()).toEqual({
      state: 'confirmed', turnFact: {
        harnessId: 'pi', providerConfigId: 'p-1', modelId: 'm1' } })
    expect(client.pending).toBeNull()
  })
})

describe('bound/unbound send dispatch (appendix §3.3)', () => {
  it('names a target only from complete native identity facts', () => {
    expect(targetIdentityOf(LOCATION)).toEqual(TARGET)
    expect(targetIdentityOf({ ...LOCATION, serverInstanceId: undefined })).toBeUndefined()
    expect(targetIdentityOf({ kind: 'draft', draftId: 'd', contextRevision: 0 })).toBeUndefined()
  })

  it('a bound session never submits: the Profile guard owns the one apply (M06)', async () => {
    const chat = createChatContributions()
    const invoke = vi.fn().mockResolvedValue({ desired: null, lastConfirmed: null, revision: null, intentRoute: null })
    const scope = new OwnedResources()
    registerModelSelector(chat, scope, { service: makeService(), invoke })
    bindProfileFact(chat, { serverInstanceId: 'srv-1', sessionId: 's-9' })
    const { result, gateway } = await runGuard(chat)
    expect(result).toEqual({ status: 'accepted' })
    expect(gateway.submit).toHaveBeenCalled() // the send proceeds
    expect(invoke).toHaveBeenCalledWith('modelProvider.queryChoice', { target: TARGET })
    expect(invoke.mock.calls.some(([method]) => method === SUBMIT_METHOD)).toBe(false)
  })

  it('a binding projected for another session does not read as bound', async () => {
    const chat = createChatContributions()
    const invoke = vi.fn().mockResolvedValue({ outcome: 'no-intent' })
    const scope = new OwnedResources()
    registerModelSelector(chat, scope, { service: makeService(), invoke })
    bindProfileFact(chat, { serverInstanceId: 'srv-1', sessionId: 'OTHER' })
    const { result, gateway } = await runGuard(chat)
    expect(result).toEqual({ status: 'accepted' })
    expect(gateway.submit).toHaveBeenCalled()
    expect(invoke).toHaveBeenCalledWith(SUBMIT_METHOD, expect.objectContaining({ target: TARGET }))
  })

  it('without the Profile extension every session dispatches unbound', async () => {
    const chat = createChatContributions()
    const invoke = vi.fn().mockResolvedValue({ outcome: 'ready', sequence: 1, application: evidence() })
    const scope = new OwnedResources()
    registerModelSelector(chat, scope, { service: makeService(), invoke })
    const { result } = await runGuard(chat)
    expect(result).toEqual({ status: 'accepted' })
    expect(invoke).toHaveBeenCalledWith(SUBMIT_METHOD, expect.objectContaining({ target: TARGET }))
  })

  it('a refused model application blocks the send and preserves the draft path', async () => {
    const chat = createChatContributions()
    const invoke = vi.fn().mockResolvedValue({ outcome: 'refused', reason: 'CATALOGUE_STALE' })
    const scope = new OwnedResources()
    registerModelSelector(chat, scope, { service: makeService(), invoke })
    const { result, gateway } = await runGuard(chat)
    expect(result).toEqual({
      status: 'refused',
      reason: expect.stringContaining('CATALOGUE_STALE'),
    })
    expect(gateway.submit).not.toHaveBeenCalled() // zero prompt (FR-06)
  })

  it('an undecided model application blocks the send without a fabricated outcome', async () => {
    const chat = createChatContributions()
    const invoke = vi.fn().mockResolvedValue({ outcome: 'unknown', reason: 'OPERATION_UNKNOWN' })
    const scope = new OwnedResources()
    registerModelSelector(chat, scope, { service: makeService(), invoke })
    const { result, gateway } = await runGuard(chat)
    expect(result).toEqual({ status: 'unknown' })
    expect(gateway.submit).not.toHaveBeenCalled()
  })

  it('the guard reads the composer client bookkeeping when one registered', async () => {
    const chat = createChatContributions()
    const invoke = vi.fn()
    const scope = new OwnedResources()
    const wiring = { service: makeService(), invoke }
    registerModelSelector(chat, scope, wiring)
    const clients = clientRegistryOf(wiring)
    const submitTurn = vi.fn().mockResolvedValue({ state: 'no-intent' })
    clients.set(JSON.stringify(TARGET), { client: { submitTurn } as never, isCurrent: () => true })
    const gateway = { submit: vi.fn().mockResolvedValue({ status: 'accepted' }) }
    const result = await chat.submit(snapshot(), gateway, () => true)
    expect(result).toEqual({ status: 'accepted' })
    expect(submitTurn).toHaveBeenCalledTimes(1)
    expect(invoke).not.toHaveBeenCalled() // the registered client owns the call
  })

  it('disposing the registration removes exactly this route and its guard', async () => {
    const chat = createChatContributions()
    const scope = new OwnedResources()
    const handle = registerModelSelector(chat, scope, { service: makeService() })
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()
      .map(view => view.id)).toEqual([MODEL_SELECTOR_ID])
    handle.dispose()
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()).toHaveLength(0)
    // the guard is gone with it: a submit runs no model-side preparation
    const gateway = { submit: vi.fn().mockResolvedValue({ status: 'accepted' }) }
    const result = await chat.submit(snapshot(), gateway, () => true)
    expect(result).toEqual({ status: 'accepted' })
    expect(chat.contributionsBySlot('composer.toolbar').getSnapshot()).toHaveLength(0)
    void TURN_APPLICATION_GUARD_ID
  })
})
