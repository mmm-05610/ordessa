/**
 * Profile → Chat glue (PV-10).  Optional entry: without Chat (no
 * ChatContributionsToken) or without Profile (no ProfileServiceToken) this
 * glue is simply absent and both products keep working (contracts.md §4).
 *
 * The glue contributes one composer.toolbar picker.  It owns NO state of the
 * Chat, stores no draft text, and holds no session lifecycle: selections live
 * in {@link ProfileSelectionStore} and die with the UI scope (G18).
 */
import type { ResourceScope } from '@ordessa/extension-api'
import {
  chatContribution,
  defineChatComponentKey,
  type ChatContributionContext,
  type ChatContributionsService,
  type ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import type {
  ProfileCatalogGroup,
  ProfileSelection,
  ProfileServiceClient,
} from '@ordessa/plugin-profile-api'
import { ProfilePicker } from './picker'
import type { ProfilePickerProps } from './picker-model'
import { catalogForLocation, ProfileSelectionStore } from './selection'
import type { ApplyOutcome } from './selection'
import type { ProfileCatalog } from './catalog'
import type { AgentSessions } from '@extensions/ordessa.agent-contracts/contract.js'

export { ProfileSelectionStore, catalogForLocation } from './selection'
export type { ApplyOutcome, SelectionCounters } from './selection'
export { ProfilePicker } from './picker'
export { pickerOptionGroups, selectedOptionValue } from './picker-model'
export type { ProfilePickerProps } from './picker-model'

/** Chat-owned key factory: the glue never invents a second key identity. */
export const ProfilePickerKey =
  defineChatComponentKey<ProfilePickerProps>('ordessa.profile.picker', 1)

export interface ChatLocationLike {
  readonly kind?: string
  readonly draftId?: string
  readonly sessionId?: string
}

/** Extract the picker's store key + catalog scope from the chat location. */
export function pickerKeyFor(location: ChatLocation): {
  key: string
  scope: { readonly kind: 'draft' } | { readonly kind: 'session'; readonly harnessId: string }
} {
  if (location.kind === 'session') {
    return {
      key: `session:${location.sessionId}`,
      scope: { kind: 'session', harnessId: location.harnessId ?? '' },
    }
  }
  return { key: `draft:${location.draftId}`, scope: { kind: 'draft' } }
}

export interface ProfileChatGlueInput {
  readonly store?: ProfileSelectionStore
  readonly profiles: Pick<ProfileServiceClient, 'beginTurnApplication'> & Partial<Pick<ProfileServiceClient, 'selectForSession' | 'inspectSessionConfig' | 'registerNativeSession' | 'reconcile' | 'prepareNativeCreation'>>
  readonly catalog: () => readonly ProfileCatalogGroup[]
  readonly catalogState?: Pick<ProfileCatalog, 'message' | 'subscribe' | 'getSnapshot' | 'refresh'>
  readonly onOpenManager?: () => void
  readonly nativeSessions?: Pick<AgentSessions, 'prepareSubmission'> & Partial<Pick<AgentSessions, 'getSnapshot' | 'subscribe'>>
}

export function createProfileChatGlue(
  scope: ResourceScope,
  contributions: ChatContributionsService,
  input: ProfileChatGlueInput,
) {
  const store = input.store ?? new ProfileSelectionStore()
  const subscribe = (listener: () => void) => {
    const stopStore = store.subscribe(listener)
    const stopCatalog = input.catalogState?.subscribe(listener)
    return () => { stopStore(); stopCatalog?.() }
  }
  const getSnapshot = () => store.getSnapshot() + (input.catalogState?.getSnapshot() ?? 0)
  const scoped = contributions.forScope(scope)
  const bindings = new Map<string, { ref: import('@ordessa/plugin-profile-api').SessionRef; selection: ProfileSelection; uiSessionId: string; serverId: string }>()
  const retainedSelections = new Map<string, { selection: ProfileSelection; connectionId?: string }>()

  // -- click-order seam (021 appendix §6c F1.2): registration wire calls for
  //    one picker key (selectForSession here, chooseForSession on the model
  //    side via the projected `serializeRegistration` hook) run strictly one
  //    after another, so the backend's action_seq stamps CLICK order, never
  //    network race order. One failed task never poisons the queue.
  const clickQueues = new Map<string, Promise<unknown>>()
  const enqueueClick = <T>(key: string, task: () => Promise<T>): Promise<T> => {
    const tail = clickQueues.get(key) ?? Promise.resolve()
    const run = tail.then(task, task)
    const settled: Promise<unknown> = run.then(() => undefined, () => undefined)
    clickQueues.set(key, settled)
    void settled.then(() => {
      if (clickQueues.get(key) === settled) clickQueues.delete(key)
    })
    return run
  }

  /** Raw backend registration of one pick (click handler task and the submit
   * guard both use it — NEVER enqueue it from inside another queued task). */
  const registrationTask = async (key: string, ref: import('@ordessa/plugin-profile-api').SessionRef, selection: ProfileSelection): Promise<void> => {
    try {
      if (typeof input.profiles.selectForSession !== 'function')
        throw new Error('Profile selection registration is unavailable')
      if (selection.harnessId !== ref.harnessId)
        throw new Error(`所选预设属于另一 Harness（${selection.harnessId}），不能登记到此会话`)
      await input.profiles.selectForSession(
        `profile-chat.register:${ref.sessionUid}:${selection.profileId}:${++registrationSequence}`,
        { sessionRef: ref, profileId: selection.profileId })
      store.markRegistered(key, selection)
    } catch (error) {
      // surfaced in the picker (registrationError), pick kept for retry
      store.markRegistrationFailed(key, selection,
        error instanceof Error ? error.message : String(error))
    }
  }
  let registrationSequence = 0

  const stopNative = input.nativeSessions?.subscribe?.(() => {
    const native = input.nativeSessions?.getSnapshot?.()
    if (native?.draft?.active === false && native.draft.endedBy !== 'opened') store.clearDraftConfirmations()
    if (native?.draft?.endedBy !== 'discarded') return
    for (const [key, retained] of retainedSelections)
      if (retained.connectionId === native.selectedConnectionId) retainedSelections.delete(key)
  })
  const nativeLifetime = scope.add({ isDisposed: false as boolean, dispose() {
    if (this.isDisposed) return
    this.isDisposed = true
    stopNative?.(); retainedSelections.clear()
  } })
  const guard = scoped.addSubmissionGuard({ id: 'ordessa.profile-chat.application', order: 10,
    async prepare(snapshot) {
      const { key } = pickerKeyFor(snapshot.target)
      const target = snapshot.target
      const native = input.nativeSessions?.getSnapshot?.()
      const retainedKey = JSON.stringify([target.serverInstanceId, native?.selectedConnectionId ?? null, key])
      const selected = store.peek(key) ?? (target.kind === 'draft' ? retainedSelections.get(retainedKey)?.selection : undefined)
      const currentBinding = target.kind === 'session' ? [...bindings.values()].find(binding =>
        binding.uiSessionId === target.sessionId && binding.serverId === target.serverInstanceId) : undefined
      if (!selected && !currentBinding) return { status: 'ready' }
      if (!input.nativeSessions?.prepareSubmission || !input.profiles.registerNativeSession)
        return selected ? { status: 'refused', reason: 'Profile 会话应用尚未接入：缺少后端会话身份与生产应用端口。所选预设和草稿已保留。' } : { status: 'ready' }
      const offeredHarness = input.nativeSessions.getSnapshot?.().agent?.connection.harnessId
      if (selected && offeredHarness && offeredHarness !== selected.harnessId)
        return { status: 'refused', reason: '所选 Profile 属于另一 Harness，请先选择对应连接；没有创建会话。' }
      // Brand differences belong to the Harness, not to this frontend: whether a
      // given Harness needs pre-creation native parameters is the backend's own
      // per-harness verdict (`prepareNativeCreation` answers `not-required` for
      // the ones that apply live). The renderer therefore demands the port for
      // EVERY draft selection and forwards the call unchanged; it never encodes
      // which Harness may skip it.
      if (selected && target.kind === 'draft' && !input.profiles.prepareNativeCreation)
        return { status: 'refused', reason: '所选 Harness 缺少 Profile 创建前准备服务；草稿和选择已保留。' }
      try {
        if (selected && target.kind === 'draft') retainedSelections.set(retainedKey, { selection: selected, connectionId: native?.selectedConnectionId })
        const owner = await input.nativeSessions.prepareSubmission(selected && input.profiles.prepareNativeCreation ? {
          configurationProfileId: selected.profileId,
          beforeCreate: async context => {
            if (context.serverInstanceId !== target.serverInstanceId || context.harnessId !== selected.harnessId)
              throw new Error('Profile preparation context changed')
            const operationId = `create:${context.attemptId}`
            const result = await input.profiles.prepareNativeCreation!({ connectionId: context.connectionId,
              profileId: selected.profileId, operationId })
            if (!result || !['prepared', 'not-required'].includes(result.state)
                || result.operationId !== operationId || result.connectionId !== context.connectionId
                || result.profileId !== selected.profileId || result.harnessId !== context.harnessId
                || !Number.isSafeInteger(result.profileRevision) || result.profileRevision < 1
                || Object.keys(result).sort().join(',') !== 'connectionId,harnessId,operationId,profileId,profileRevision,state')
              throw new Error('Profile native preparation is unknown or malformed')
          },
        } : undefined)
        if (snapshot.target.serverInstanceId !== owner.serverInstanceId)
          return { status: 'refused', reason: 'Profile Server identity changed' }
        const identity = JSON.stringify([owner.serverInstanceId, owner.connectionId, owner.nativeSessionId])
        let binding = bindings.get(identity)
        const selection = selected ?? binding?.selection
        if (!selection) return { status: 'ready' }
        if (selection.harnessId !== owner.harnessId) return { status: 'refused', reason: 'Profile belongs to another Harness' }
        if (!binding) {
          const result = await input.profiles.registerNativeSession({ connectionId: owner.connectionId,
            nativeSessionId: owner.nativeSessionId, profileId: selection.profileId })
          if (result.sessionRef.harnessId !== owner.harnessId || result.sessionRef.nativeSessionKey !== owner.nativeSessionId
              || !result.sessionRef.sessionUid || !result.sessionRef.realm) return { status: 'unknown' }
          binding = { ref: result.sessionRef, selection, uiSessionId: owner.sessionId, serverId: owner.serverInstanceId }
          bindings.set(identity, binding)
        }
        const inspected = await input.profiles.inspectSessionConfig?.(binding.ref)
        if (inspected?.switchState === 'needs_recovery') {
          const recovered = await input.profiles.reconcile?.(`profile-reconcile:${snapshot.submissionId}`, binding.ref)
          if (!recovered || recovered.state === 'unknown') return { status: 'unknown' }
          if (recovered.state === 'confirmed-current') {
            // The next explicit send can apply a new selection. This call only reconciles.
            return { status: 'refused', reason: 'Profile 应用结果已核实，请再次点击发送；未自动重发。' }
          }
          return { status: 'refused', reason: 'Profile 已核实为未应用，请再次点击发送重试；未自动重发。' }
        }
        // Registration + application run as ONE serialized task per session
        // key (§6c F1.2): clicks queued around it keep their wire order, and
        // the apply never races a click registration.
        const capturedRegistered = !!selected && store.isRegistered(key, selected)
        return await enqueueClick(key, async (): Promise<
          { readonly status: 'ready' } | { readonly status: 'refused'; readonly reason: string }
          | { readonly status: 'unknown' }
        > => {
          const live = store.peek(key)
          let outcome: ApplyOutcome
          if (live && store.isRegistered(key, live)) {
            // the backend already holds the newest click's intent: apply it
            outcome = await store.applyOnSubmit(key, binding.ref, input.profiles)
          } else if (selected && capturedRegistered) {
            // the click-registered pick is the backend's pending even though a
            // store-level re-pick arrived meanwhile (it stays for next submit)
            outcome = await store.applyOnSubmit(key, binding.ref, input.profiles, selected)
          } else if (selected) {
            // never registered at click (draft flow / failed click): register
            // now, inside this serialized task, then apply the vouched pick
            await registrationTask(key, binding.ref, selected)
            if (store.peek(key) === selected && !store.isRegistered(key, selected))
              return { status: 'refused',
                reason: `所选预设未能登记到会话：${store.registrationError(key) ?? '未知原因'}；草稿与选择已保留，可重试。` }
            outcome = await store.applyOnSubmit(key, binding.ref, input.profiles, selected)
          } else {
            // ordinary bound turn: apply the effective configuration, no reselect
            outcome = await store.applyOnSubmit(key, binding.ref, input.profiles, binding.selection)
          }
          if (!outcome.ok) {
            if (outcome.unknown) return { status: 'unknown' }
            // Wire/1 currently hides business error details. Query the domain's
            // explicit safety state instead of guessing uncertainty from text.
            const failed = await input.profiles.inspectSessionConfig?.(binding.ref)
            return failed?.switchState === 'needs_recovery' ? { status: 'unknown' }
              : { status: 'refused', reason: outcome.reason }
          }
          binding.selection = outcome.applied
          retainedSelections.delete(retainedKey)
          return { status: 'ready' }
        })
      } catch (error) {
        // Transport loss cannot be turned into a safe retry or fallback send.
        return { status: 'unknown' }
      }
    },
  })
  const registration = chatContribution<ProfilePickerProps>({
    id: 'ordessa.profile-chat.picker',
    slot: 'composer.toolbar',
    order: 10,
    key: ProfilePickerKey,
    project: (context: ChatContributionContext) => {
      if (context.slot !== 'composer.toolbar') return { hidden: true }
      const { key, scope: pickerScope } = pickerKeyFor(context.location)
      const liveProps = (): ProfilePickerProps => {
        const location = context.location
        const bound = location.kind === 'session' ? [...bindings.values()].find(binding =>
          binding.uiSessionId === location.sessionId && binding.serverId === location.serverInstanceId) : undefined
        const scope = pickerScope.kind === 'session' && bound ? { ...pickerScope, harnessId: bound.ref.harnessId } : pickerScope
        const groups = catalogForLocation(input.catalog(), scope)
        return {
          label: store.currentLabel(key, bound?.selection.displayName), groups,
          statusMessage: input.catalogState?.message || (groups.length ? undefined : '当前 Harness 没有可用预设。'),
          // §6c F1.1: a click registration that failed is surfaced here, never
          // swallowed — the pick stays unregistered and the user can retry.
          registrationError: store.registrationError(key),
          onRefresh: input.catalogState ? () => { void input.catalogState!.refresh() } : undefined,
          onOpenSelector: input.catalogState ? () => { void input.catalogState!.refresh() } : undefined,
          onOpenManager: input.onOpenManager,
          // §6c F1.1: the explicit selection REGISTERS at click time for a
          // bound session (the backend stamps the click's action_seq); it
          // never applies or restarts anything (FR-04). A draft keeps its
          // pick in the store; registration happens at submit.
          onSelect: (selection: ProfileSelection) => {
            store.select(key, selection)
            if (location.kind !== 'session') return
            void enqueueClick(key, async () => {
              try {
                let registered = [...bindings.values()].find(binding =>
                  binding.uiSessionId === location.sessionId && binding.serverId === location.serverInstanceId)
                if (!registered) {
                  if (!input.nativeSessions?.prepareSubmission || !input.profiles.registerNativeSession)
                    throw new Error('原生会话登记端口不可用')
                  const owner = await input.nativeSessions.prepareSubmission()
                  if (owner.sessionId !== location.sessionId || owner.serverInstanceId !== location.serverInstanceId
                    || owner.harnessId !== selection.harnessId) throw new Error('原生会话身份已变化')
                  const result = await input.profiles.registerNativeSession({ connectionId: owner.connectionId,
                    nativeSessionId: owner.nativeSessionId, profileId: selection.profileId })
                  if (result.sessionRef.harnessId !== owner.harnessId
                    || result.sessionRef.nativeSessionKey !== owner.nativeSessionId
                    || !result.sessionRef.sessionUid || !result.sessionRef.realm) throw new Error('会话登记未确认')
                  registered = { ref: result.sessionRef, selection, uiSessionId: owner.sessionId, serverId: owner.serverInstanceId }
                  bindings.set(JSON.stringify([owner.serverInstanceId, owner.connectionId, owner.nativeSessionId]), registered)
                }
                await registrationTask(key, registered.ref, selection)
              } catch (error) {
                store.markRegistrationFailed(key, selection, error instanceof Error ? error.message : String(error))
              }
            })
          },
          onClearSelection: () => store.forget(key),
          // 021 T04: the registered binding fact of THIS chat session, for the
          // model route's bound/unbound dispatch (appendix §3.3). Purely a
          // read-side projection; the model guard never applies through it.
          boundNativeSession: bound
            ? { serverInstanceId: bound.serverId, sessionId: bound.uiSessionId }
            : null,
          // §6c F1.2: the per-session click-order seam. The model side runs its
          // chooseForSession call through this hook (absent → unbound → the
          // model side calls directly, semantics unchanged). Read-only
          // projection, same channel as `boundNativeSession`.
          serializeRegistration: location.kind === 'session'
            ? (task: () => Promise<void>) => enqueueClick(key, task)
            : null,
        }
      }
      return {
        hidden: false,
        props: {
          ...liveProps(), subscribe, getSnapshot, getLiveProps: liveProps,
        },
      }
    },
  })
  const disposeRegistration =
    scoped.addContribution(registration)
  return {
    store,
    dispose() {
      disposeRegistration.dispose()
      guard.dispose()
      bindings.clear()
      nativeLifetime.dispose()
    },
  }
}

/** Read-side convenience for the Chat host outlet. */
export function pickerComponent() {
  return ProfilePicker
}
