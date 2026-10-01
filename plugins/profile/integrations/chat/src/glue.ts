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
  const stopNative = input.nativeSessions?.subscribe?.(() => {
    const native = input.nativeSessions?.getSnapshot?.()
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
      if (selected && target.kind === 'draft' && selected.harnessId !== 'pi' && !input.profiles.prepareNativeCreation)
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
        if (!selected && !store.peek(key)) store.select(key, selection)
        // Selection changes while preparation waits belong to the next submit.
        const applyStore = store.peek(key) === selection ? store : new ProfileSelectionStore()
        if (applyStore !== store) applyStore.select(key, selection)
        const outcome = await applyStore.applyOnSubmit(key, binding.ref, input.profiles)
        if (!outcome.ok) {
          if (outcome.unknown) return { status: 'unknown' }
          // Wire/1 currently hides business error details. Query the domain's
          // explicit safety state instead of guessing uncertainty from text.
          const failed = await input.profiles.inspectSessionConfig?.(binding.ref)
          return failed?.switchState === 'needs_recovery' ? { status: 'unknown' }
            : { status: 'refused', reason: outcome.reason }
        }
        binding.selection = selection
        retainedSelections.delete(retainedKey)
        return { status: 'ready' }
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
          onRefresh: input.catalogState ? () => { void input.catalogState!.refresh() } : undefined,
          onOpenSelector: input.catalogState ? () => { void input.catalogState!.refresh() } : undefined,
          onOpenManager: input.onOpenManager,
          onSelect: (selection: ProfileSelection) => store.select(key, selection),
          onClearSelection: () => store.forget(key),
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
